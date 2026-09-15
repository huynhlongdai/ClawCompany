"""v29: cascade archive for the org tree, and an audit feed that reads the
events v28 was only writing.

Section 19.6 named both debts. Archiving a company, department or member
needed a cascade design, and the guard events had no consumer. Neither adds
a table: the cascade uses existing status vocabularies and the audit feed
reads ``CompanyEvent``.
"""
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.authz import Principal, require_role, require_scope
from app.core.tenancy import active_org, ensure_company, ensure_department, ensure_member
from app.db.session import get_db
from app.services import entity_archive, write_audit

router = APIRouter(prefix="/v29", tags=["v29-cascade-archive"])

READ = "company.context:read"
WRITE = "company.workspace:write"  # same scope as v18/v27/v28: cockpit writing


def writer(minimum_role: str = "manager"):
    def dep(principal: Principal = Depends(require_scope(WRITE))) -> Principal:
        if principal.auth_type != "api_key":
            return require_role(minimum_role)(principal)
        return principal
    return dep


class ArchiveIn(BaseModel):
    # Forcing is an explicit act. It does not stop anything inside OpenClaw;
    # it archives anyway and the response lists what was left running.
    force: bool = False


_LOADERS = {
    "company": ensure_company,
    "department": ensure_department,
    "member": ensure_member,
}


@router.get("/vocabulary")
def vocabulary(principal: Principal = Depends(require_scope(READ))):
    """What the cascade can archive and which words it writes.

    Same reasoning as v18's vocabulary endpoint: clients should read the
    state machine rather than hardcode a copy that drifts.
    """
    return {
        "kinds": list(entity_archive.KINDS),
        "company_archived_status": entity_archive.COMPANY_ARCHIVED,
        "member_archived_status": entity_archive.MEMBER_ARCHIVED,
        "department_locked_access_level": entity_archive.DEPARTMENT_LOCKED,
        "default_restore": {
            "company": entity_archive.COMPANY_DEFAULT_RESTORE,
            "member": entity_archive.MEMBER_DEFAULT_RESTORE,
            "department": entity_archive.DEPARTMENT_DEFAULT_RESTORE,
        },
        "archive_events": entity_archive.ARCHIVE_EVENTS,
        "restore_events": entity_archive.RESTORE_EVENTS,
        "audit_event_types": list(write_audit.event_types(include_runtime=True)),
        "audit_categories": sorted(set(write_audit.CATEGORIES.values())),
        "deletes_rows": False,
        "notes": [
            "Departments have no status column, so a department archive locks "
            "access_level to 'confidential' instead of inventing one.",
            "Agent rows are never touched: their lifecycle belongs to the runtime.",
            "Projects cancelled by a company archive are reopened one at a time "
            "via /api/v28/projects/{id}/restore.",
        ],
    }


# --- cascade preview / archive / restore -------------------------------------


@router.get("/companies/{company_id}/archive/preview")
def company_archive_preview(company_id: int, db: Session = Depends(get_db),
                            principal: Principal = Depends(require_scope(READ))):
    company = ensure_company(db, company_id, principal)
    return entity_archive.cascade_preview(db, company, active_org(principal))


@router.post("/companies/{company_id}/archive")
def company_archive(company_id: int, payload: ArchiveIn | None = None,
                    db: Session = Depends(get_db),
                    principal: Principal = Depends(writer("admin"))):
    """Archiving a whole company is an admin act, not a manager's."""
    company = ensure_company(db, company_id, principal)
    body = payload or ArchiveIn()
    return entity_archive.archive_entity(db, company, active_org(principal),
                                         force=body.force,
                                         actor_member_id=principal.member_id)


@router.get("/companies/{company_id}/restore/preview")
def company_restore_preview(company_id: int, db: Session = Depends(get_db),
                            principal: Principal = Depends(require_scope(READ))):
    company = ensure_company(db, company_id, principal)
    return entity_archive.restore_preview(db, company, active_org(principal))


@router.post("/companies/{company_id}/restore")
def company_restore(company_id: int, db: Session = Depends(get_db),
                    principal: Principal = Depends(writer("admin"))):
    company = ensure_company(db, company_id, principal)
    return entity_archive.restore_entity(db, company, active_org(principal),
                                         actor_member_id=principal.member_id)


@router.get("/departments/{department_id}/archive/preview")
def department_archive_preview(department_id: int, db: Session = Depends(get_db),
                               principal: Principal = Depends(require_scope(READ))):
    dept = ensure_department(db, department_id, principal)
    return entity_archive.cascade_preview(db, dept, active_org(principal))


@router.post("/departments/{department_id}/archive")
def department_archive(department_id: int, payload: ArchiveIn | None = None,
                       db: Session = Depends(get_db),
                       principal: Principal = Depends(writer("manager"))):
    dept = ensure_department(db, department_id, principal)
    body = payload or ArchiveIn()
    return entity_archive.archive_entity(db, dept, active_org(principal),
                                         force=body.force,
                                         actor_member_id=principal.member_id)


@router.get("/departments/{department_id}/restore/preview")
def department_restore_preview(department_id: int, db: Session = Depends(get_db),
                              principal: Principal = Depends(require_scope(READ))):
    dept = ensure_department(db, department_id, principal)
    return entity_archive.restore_preview(db, dept, active_org(principal))


@router.post("/departments/{department_id}/restore")
def department_restore(department_id: int, db: Session = Depends(get_db),
                       principal: Principal = Depends(writer("manager"))):
    dept = ensure_department(db, department_id, principal)
    return entity_archive.restore_entity(db, dept, active_org(principal),
                                         actor_member_id=principal.member_id)


@router.get("/members/{member_id}/archive/preview")
def member_archive_preview(member_id: int, db: Session = Depends(get_db),
                           principal: Principal = Depends(require_scope(READ))):
    member = ensure_member(db, member_id, principal)
    return entity_archive.cascade_preview(db, member, active_org(principal))


@router.post("/members/{member_id}/archive")
def member_archive(member_id: int, payload: ArchiveIn | None = None,
                   db: Session = Depends(get_db),
                   principal: Principal = Depends(writer("manager"))):
    member = ensure_member(db, member_id, principal)
    body = payload or ArchiveIn()
    return entity_archive.archive_entity(db, member, active_org(principal),
                                         force=body.force,
                                         actor_member_id=principal.member_id)


@router.get("/members/{member_id}/restore/preview")
def member_restore_preview(member_id: int, db: Session = Depends(get_db),
                           principal: Principal = Depends(require_scope(READ))):
    member = ensure_member(db, member_id, principal)
    return entity_archive.restore_preview(db, member, active_org(principal))


@router.post("/members/{member_id}/restore")
def member_restore(member_id: int, db: Session = Depends(get_db),
                   principal: Principal = Depends(writer("manager"))):
    member = ensure_member(db, member_id, principal)
    return entity_archive.restore_entity(db, member, active_org(principal),
                                         actor_member_id=principal.member_id)


# --- write audit -------------------------------------------------------------


@router.get("/audit")
def audit(company_id: int | None = None,
          entity_type: str | None = None,
          entity_id: str | None = None,
          category: list[str] | None = Query(default=None),
          include_runtime: bool = False,
          since_hours: int | None = Query(default=None, ge=1, le=8760),
          limit: int = Query(default=write_audit.DEFAULT_LIMIT, ge=1,
                             le=write_audit.MAX_LIMIT),
          db: Session = Depends(get_db),
          principal: Principal = Depends(require_scope(READ))):
    """The feed v28's guard events were missing.

    Newest-first, organization-scoped, and truncated rather than paginated:
    the response says ``truncated`` when there is more, instead of implying
    completeness it cannot offer.
    """
    return write_audit.feed(db, active_org(principal), company_id=company_id,
                            entity_type=entity_type, entity_id=entity_id,
                            categories=tuple(category) if category else None,
                            include_runtime=include_runtime,
                            since_hours=since_hours, limit=limit)


@router.get("/audit/{entity_type}/{entity_id}")
def audit_entity(entity_type: str, entity_id: str,
                 limit: int = Query(default=write_audit.DEFAULT_LIMIT, ge=1,
                                    le=write_audit.MAX_LIMIT),
                 db: Session = Depends(get_db),
                 principal: Principal = Depends(require_scope(READ))):
    """The audit trail for one row: who changed it, when, and which fields."""
    return write_audit.entity_history(db, active_org(principal), entity_type,
                                      entity_id, limit=limit)
