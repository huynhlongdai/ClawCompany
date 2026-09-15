"""v28: binding write guards and a reversible archive.

v27 closed v18's three debts and then declared two of its own (section
18.7): the revision check was advisory, and un-archiving did not restore
the tasks the archive cancelled. These endpoints close both.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.authz import Principal, require_role, require_scope
from app.core.tenancy import (active_org, ensure_company, ensure_department, ensure_member,
                             ensure_project, ensure_task)
from app.db.session import get_db
from app.services import board_restore, board_truth, row_guard

router = APIRouter(prefix="/v28", tags=["v28-write-guards"])

READ = "company.context:read"
WRITE = "company.workspace:write"  # same scope as v18 and v27: cockpit writing


def writer(minimum_role: str = "member"):
    def dep(principal: Principal = Depends(require_scope(WRITE))) -> Principal:
        if principal.auth_type != "api_key":
            return require_role(minimum_role)(principal)
        return principal
    return dep


class GuardedUpdateIn(BaseModel):
    # Required, not optional. A compare-and-set with nothing to compare
    # against is just an UPDATE, and an endpoint that quietly degrades into
    # an unguarded write is worse than one that refuses.
    expected_revision: str = Field(min_length=3, max_length=200)
    values: dict[str, str | int | None] = Field(default_factory=dict)


def _guard(db: Session, entity, payload: GuardedUpdateIn, principal: Principal) -> dict:
    try:
        return row_guard.compare_and_set(
            db, entity, dict(payload.values),
            expected_revision=payload.expected_revision,
            organization_id=active_org(principal),
            actor_member_id=principal.member_id,
        )
    except row_guard.GuardError as exc:
        raise HTTPException(400, detail=str(exc)) from exc


@router.get("/guards")
def guards(principal: Principal = Depends(require_scope(READ))):
    """Which entities accept a guarded write, and which fields they expose.

    Clients build their forms from this instead of hardcoding a field list
    that drifts out of step with the server -- the same reasoning as v18's
    ``/vocabulary`` endpoint.
    """
    return {
        "writable": {k: list(v) for k, v in row_guard.WRITABLE.items()},
        "expected_revision_required": True,
        "binding": True,
        "advisory_endpoints": "/api/v27 (revision checked before the write)",
        "conflict_status": 409,
    }


@router.post("/guarded/projects/{project_id}")
def guarded_project(project_id: int, payload: GuardedUpdateIn,
                    principal: Principal = Depends(writer("member")),
                    db: Session = Depends(get_db)):
    return _guard(db, ensure_project(db, project_id, principal), payload, principal)


@router.post("/guarded/tasks/{task_id}")
def guarded_task(task_id: int, payload: GuardedUpdateIn,
                 principal: Principal = Depends(writer("member")),
                 db: Session = Depends(get_db)):
    """A guarded field write on a task.

    Note this is *not* the way to move a task between statuses: v18's
    transition rules live in ``workspace_ops.move_task`` and v27's
    ``/api/v27/tasks/{id}/move`` applies them with a revision check. A
    guarded write here sets the column directly, so status changes made this
    way skip the state machine -- which is why the UI only offers it for
    text and assignment fields.
    """
    return _guard(db, ensure_task(db, task_id, principal), payload, principal)


@router.post("/guarded/companies/{company_id}")
def guarded_company(company_id: int, payload: GuardedUpdateIn,
                    principal: Principal = Depends(writer("manager")),
                    db: Session = Depends(get_db)):
    return _guard(db, ensure_company(db, company_id, principal), payload, principal)


@router.post("/guarded/departments/{department_id}")
def guarded_department(department_id: int, payload: GuardedUpdateIn,
                       principal: Principal = Depends(writer("manager")),
                       db: Session = Depends(get_db)):
    return _guard(db, ensure_department(db, department_id, principal), payload, principal)


@router.post("/guarded/members/{member_id}")
def guarded_member(member_id: int, payload: GuardedUpdateIn,
                   principal: Principal = Depends(writer("manager")),
                   db: Session = Depends(get_db)):
    return _guard(db, ensure_member(db, member_id, principal), payload, principal)


@router.get("/projects/{project_id}/restore/preview")
def restore_preview(project_id: int, principal: Principal = Depends(require_scope(READ)),
                    db: Session = Depends(get_db)):
    """What un-archiving would restore, and what it would leave alone."""
    project = ensure_project(db, project_id, principal)
    return board_restore.restore_preview(db, project, active_org(principal))


@router.post("/projects/{project_id}/restore")
def restore(project_id: int, principal: Principal = Depends(writer("manager")),
            db: Session = Depends(get_db)):
    """Reverse an archive, including the tasks it cancelled."""
    project = ensure_project(db, project_id, principal)
    return board_restore.restore_project(db, project, active_org(principal),
                                         actor_member_id=principal.member_id)


@router.get("/projects/{project_id}/history")
def history(project_id: int, principal: Principal = Depends(require_scope(READ)),
            db: Session = Depends(get_db)):
    """Archive/restore state for one project, in one call."""
    project = ensure_project(db, project_id, principal)
    org = active_org(principal)
    return {
        "truth": board_truth.derive(db, project),
        "archive": board_truth.archive_preview(db, project),
        "restore": board_restore.restore_preview(db, project, org),
    }
