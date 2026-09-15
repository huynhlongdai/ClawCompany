"""v30: exact revisions, a paged audit log, and batch board restore.

Section 20.6 of the handover listed three debts and this router closes all
three:

1. The guard token was built from ``updated_at``, so two writes inside one
   clock tick were indistinguishable. Migration ``0013`` adds a counter and
   ``row_revision`` exposes both token shapes.
2. The v29 audit feed had no cursor, so a busy org could not be read past
   the first page.
3. Un-archiving a company left its cascaded projects cancelled; they had to
   be reopened one at a time.

Nothing here is a new subsystem: the guarded write is v28's conditional
UPDATE with a better token, and the batch restore walks v28's per-project
restore path so v29's task-status fidelity is inherited rather than copied.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.authz import Principal, require_role, require_scope
from app.core.tenancy import (active_org, ensure_company, ensure_department,
                              ensure_member, ensure_project, ensure_task)
from app.db.session import get_db
from app.services import cascade_restore, row_guard, row_revision as rev, write_audit

router = APIRouter(prefix="/v30", tags=["v30-exact-revisions"])

READ = "company.context:read"
WRITE = "company.workspace:write"  # same scope as v18/v27/v28/v29


def writer(minimum_role: str = "member"):
    def dep(principal: Principal = Depends(require_scope(WRITE))) -> Principal:
        if principal.auth_type != "api_key":
            return require_role(minimum_role)(principal)
        return principal
    return dep


# One generic guarded endpoint instead of v28's five, because the only thing
# that differed between those five was the loader.
_LOADERS = {
    "company": ensure_company,
    "department": ensure_department,
    "member": ensure_member,
    "project": ensure_project,
    "task": ensure_task,
}


class GuardedUpdateIn(BaseModel):
    expected_revision: str = Field(min_length=3, max_length=200)
    values: dict[str, str | int | None] = Field(default_factory=dict)


def _load(db: Session, kind: str, entity_id: int, principal: Principal):
    loader = _LOADERS.get(kind)
    if loader is None:
        raise HTTPException(404, detail=f"Unknown entity kind: {kind}")
    return loader(db, entity_id, principal)


@router.get("/revisions")
def modes(principal: Principal = Depends(require_scope(READ))):
    """Which kinds carry a counter, and what each token shape means.

    Clients read this rather than assume every row is exact: rows written
    before migration ``0013`` still guard by timestamp, and the difference
    is a real difference in the guarantee.
    """
    return {
        "counted_kinds": list(rev.COUNTED_KINDS),
        "modes": {
            rev.COUNTER_MODE: {
                "token": "project:12:r7",
                "exact": True,
                "note": "Monotonic per-row counter; two writes can never share a token.",
            },
            rev.TIMESTAMP_MODE: {
                "token": "project:12:2026-09-14T10:00:00",
                "exact": False,
                "note": ("v27 semantics, still accepted. Resolution depends on the "
                         "database, so a same-tick race can pass the guard."),
            },
        },
        "uncounted_rows": ("Rows that predate the migration report counter=null and "
                           "adopt 1 on their first guarded write. There is no backfill "
                           "pass, because inventing revisions would invalidate tokens "
                           "clients are already holding."),
        "conflict_status": 409,
    }


@router.get("/revisions/{kind}/{entity_id}")
def revision(kind: str, entity_id: int, principal: Principal = Depends(require_scope(READ)),
             db: Session = Depends(get_db)):
    """Both token shapes for one row, plus which mode a write would use."""
    return rev.describe(_load(db, kind, entity_id, principal))


@router.post("/guarded/{kind}/{entity_id}")
def guarded_update(kind: str, entity_id: int, payload: GuardedUpdateIn,
                   principal: Principal = Depends(writer("member")),
                   db: Session = Depends(get_db)):
    """v28's binding compare-and-set, now counter-aware.

    A counter token on an uncounted row is refused rather than quietly
    downgraded to a timestamp compare: the caller asked for the exact guard
    and should be told it is not available for that row yet.
    """
    entity = _load(db, kind, entity_id, principal)
    try:
        return row_guard.compare_and_set(
            db, entity, dict(payload.values),
            expected_revision=payload.expected_revision,
            organization_id=active_org(principal),
            actor_member_id=principal.member_id,
        )
    except row_guard.GuardError as exc:
        raise HTTPException(400, detail=str(exc)) from exc


@router.get("/audit")
def audit(company_id: int | None = None,
          entity_type: str | None = None,
          entity_id: str | None = None,
          include_runtime: bool = False,
          since_hours: int | None = Query(default=None, ge=1, le=24 * 90),
          limit: int = Query(default=write_audit.DEFAULT_LIMIT, ge=1,
                            le=write_audit.MAX_LIMIT),
          cursor: int | None = Query(default=None, ge=1),
          principal: Principal = Depends(require_scope(READ)),
          db: Session = Depends(get_db)):
    """The v29 feed with the cursor it was missing.

    Pass ``next_cursor`` back to get the following page. The cursor is the
    id of the last event *scanned*, not the last row returned, because
    category filtering happens after the SQL page -- paging on the last
    returned row would skip everything the filter dropped at the tail.
    """
    return write_audit.feed(db, active_org(principal), company_id=company_id,
                            entity_type=entity_type, entity_id=entity_id,
                            include_runtime=include_runtime,
                            since_hours=since_hours, limit=limit, cursor=cursor)


@router.get("/companies/{company_id}/projects/restore/preview")
def batch_restore_preview(company_id: int,
                          principal: Principal = Depends(require_scope(READ)),
                          db: Session = Depends(get_db)):
    """Which projects a company-level un-archive would reopen."""
    company = ensure_company(db, company_id, principal)
    return cascade_restore.preview(db, company, active_org(principal))


@router.post("/companies/{company_id}/projects/restore")
def batch_restore(company_id: int, principal: Principal = Depends(writer("manager")),
                  db: Session = Depends(get_db)):
    """Reopen every project the company archive cancelled.

    Each project goes through v28's restore path, so one failure is scoped
    to that project instead of poisoning the batch. Reopening projects does
    not un-archive the company itself -- that stays an explicit v29 call.
    """
    company = ensure_company(db, company_id, principal)
    return cascade_restore.restore_projects(db, company, active_org(principal),
                                            actor_member_id=principal.member_id)
