"""v31: field-level audit values, department status, and clearable columns.

Section 21.6 listed five debts. This router closes four of them:

* guarded writes recorded field *names* only, so the audit could not say
  what a value used to be (``field_diff`` plus a patched ``row_guard``),
* departments had no status column and archiving overloaded
  ``access_level`` (migration ``0014``),
* two departments in one company could share a name (unique index in the
  same migration, plus a 409 that names the clash),
* ``owner_member_id`` could not be cleared, because JSON null already meant
  "leave alone" (the ``__clear__`` sentinel).

The fifth -- restoring agent and session runtime state when a member is
un-archived -- stays open on purpose. It needs a live gateway to verify and
this sandbox has no network, so shipping it untested would be worse than
leaving it written down.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.authz import Principal, require_role, require_scope
from app.core.tenancy import active_org, ensure_company, ensure_department, ensure_project
from app.db.session import get_db
from app.services import field_diff, row_guard, workspace_ops, write_audit

router = APIRouter(prefix="/v31", tags=["v31-field-audit"])

READ = "company.context:read"
WRITE = "company.workspace:write"  # same scope as v18 and v27-v30


def writer(minimum_role: str = "member"):
    def dep(principal: Principal = Depends(require_scope(WRITE))) -> Principal:
        if principal.auth_type != "api_key":
            return require_role(minimum_role)(principal)
        return principal
    return dep


class DepartmentUpdateIn(BaseModel):
    name: str | None = Field(default=None, max_length=160)
    head_member_id: int | None = None
    access_level: str | None = None
    status: str | None = None
    # Explicit, for the same reason the guarded write needs a sentinel:
    # omitting head_member_id must not unassign the head.
    clear_head: bool = False


class ProjectOwnerIn(BaseModel):
    owner_member_id: int | None = None
    clear_owner: bool = False


@router.get("/vocabulary")
def vocabulary(principal: Principal = Depends(require_scope(READ))):
    """What v31 added to the write vocabulary.

    Clients read this instead of hardcoding the clearable-field list, the
    same reasoning as v18's ``/vocabulary`` and v28's ``/guards``.
    """
    return {
        "department_statuses": list(workspace_ops.DEPARTMENT_STATUSES),
        "clearable": {k: list(v) for k, v in row_guard.CLEARABLE.items()},
        "clear_sentinel": field_diff.CLEAR,
        "null_means": "leave the column unchanged",
        "department_name_unique_per_company": True,
        "name_conflict_status": 409,
        "value_truncated_at": field_diff.MAX_VALUE_CHARS,
        "redacted_fields": list(field_diff.REDACTED_FIELDS),
    }


@router.get("/history/{entity_type}/{entity_id}")
def field_history(entity_type: str, entity_id: str,
                  limit: int = Query(default=write_audit.DEFAULT_LIMIT, ge=1,
                                     le=write_audit.MAX_LIMIT),
                  cursor: int | None = Query(default=None, ge=1),
                  principal: Principal = Depends(require_scope(READ)),
                  db: Session = Depends(get_db)):
    """One row's history, rebuilt per field from the recorded before-values.

    ``writes_without_values`` counts guarded writes that predate v31. Those
    are reported rather than hidden: a partially reconstructable history is
    useful, a silently incomplete one is misleading.
    """
    feed = write_audit.entity_history(db, active_org(principal), entity_type, entity_id,
                                      limit=limit, cursor=cursor)
    rebuilt = field_diff.reconstruct(feed.get("rows") or [])
    return {
        "entity_type": entity_type,
        "entity_id": entity_id,
        "rows": feed.get("rows") or [],
        "timeline": rebuilt["fields"],
        "field_names": rebuilt["field_names"],
        "writes_without_values": rebuilt["writes_without_values"],
        "note": rebuilt["note"],
        "cursor": feed.get("cursor"),
        "next_cursor": feed.get("next_cursor"),
        "has_more": feed.get("has_more", False),
    }


@router.patch("/departments/{department_id}")
def update_department(department_id: int, payload: DepartmentUpdateIn,
                      principal: Principal = Depends(writer("manager")),
                      db: Session = Depends(get_db)):
    """Edit a department: name, head, access level, status.

    Departments were creatable and cascade-archivable but never editable,
    so a renamed team had to go through v28's generic guarded write, which
    bypassed the uniqueness check this endpoint enforces.
    """
    dept = ensure_department(db, department_id, principal)
    updated = workspace_ops.update_department(
        db, dept, active_org(principal),
        name=payload.name, head_member_id=payload.head_member_id,
        access_level=payload.access_level, status=payload.status,
        clear_head=payload.clear_head, actor_member_id=principal.member_id,
    )
    return {"id": updated.id, "company_id": updated.company_id, "name": updated.name,
            "head_member_id": updated.head_member_id,
            "access_level": updated.access_level, "status": updated.status}


@router.get("/companies/{company_id}/departments/name-conflicts")
def name_conflicts(company_id: int, principal: Principal = Depends(require_scope(READ)),
                   db: Session = Depends(get_db)):
    """Duplicate department names, which block migration ``0014``.

    The migration refuses to run rather than auto-renaming rows nobody has
    reviewed, so this is the endpoint that tells an operator what to fix
    first.
    """
    company = ensure_company(db, company_id, principal)
    conflicts = workspace_ops.duplicate_department_names(db, company.id)
    return {
        "company_id": company.id,
        "conflicts": conflicts,
        "blocks_migration": bool(conflicts),
        "migration": "0014_v31_department_status_and_unique_name",
    }


@router.post("/projects/{project_id}/owner")
def set_project_owner(project_id: int, payload: ProjectOwnerIn,
                      principal: Principal = Depends(writer("member")),
                      db: Session = Depends(get_db)):
    """Assign or unassign a project owner.

    Unassigning needs ``clear_owner: true``. Treating a null
    ``owner_member_id`` as "remove the owner" would have cleared owners for
    every client that simply omits the field.
    """
    if payload.owner_member_id is None and not payload.clear_owner:
        raise HTTPException(400, detail="Pass owner_member_id, or clear_owner: true to unassign")
    project = ensure_project(db, project_id, principal)
    updated = workspace_ops.update_project(
        db, project, active_org(principal),
        owner_member_id=payload.owner_member_id,
        clear_owner=payload.clear_owner,
        actor_member_id=principal.member_id,
    )
    return {"id": updated.id, "owner_member_id": updated.owner_member_id,
            "cleared": payload.clear_owner}
