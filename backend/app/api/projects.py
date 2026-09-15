from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.models import Project, Company
from app.schemas import ProjectCreate, ProjectOut
from app.core.authz import Principal, get_principal, require_role, require_human
from app.core.tenancy import active_org, ensure_company, ensure_member

router = APIRouter(prefix="/projects", tags=["projects"])

@router.get("", response_model=list[ProjectOut])
def list_projects(company_id: int | None = None, principal: Principal = Depends(require_human()), db: Session = Depends(get_db)):
    org_id = active_org(principal)
    q = db.query(Project).join(Company, Company.id == Project.company_id).filter(Company.organization_id == org_id)
    if company_id is not None:
        ensure_company(db, company_id, principal); q = q.filter(Project.company_id == company_id)
    return q.order_by(Project.id.desc()).all()

@router.post("", response_model=ProjectOut)
def create_project(payload: ProjectCreate, principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    ensure_company(db, payload.company_id, principal)
    if payload.owner_member_id is not None: ensure_member(db, payload.owner_member_id, principal)
    obj = Project(**payload.model_dump())
    db.add(obj); db.commit(); db.refresh(obj)
    return obj
