from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import or_
from app.db.session import get_db
from app.models import KnowledgeDocument
from app.schemas import KnowledgeCreate, KnowledgeOut
from app.core.authz import Principal, get_principal, require_role, enforce_org, require_human
from app.core.tenancy import active_org, ensure_company, ensure_department, ensure_project

router = APIRouter(prefix="/knowledge", tags=["knowledge"])

@router.get("", response_model=list[KnowledgeOut])
def list_documents(company_id: int | None = None, department_id: int | None = None, project_id: int | None = None, principal: Principal = Depends(require_human()), db: Session = Depends(get_db)):
    org_id = active_org(principal)
    q = db.query(KnowledgeDocument).filter(KnowledgeDocument.organization_id == org_id)
    if company_id is not None: ensure_company(db, company_id, principal); q = q.filter(KnowledgeDocument.company_id == company_id)
    if department_id is not None: ensure_department(db, department_id, principal); q = q.filter(KnowledgeDocument.department_id == department_id)
    if project_id is not None: ensure_project(db, project_id, principal); q = q.filter(KnowledgeDocument.project_id == project_id)
    return q.order_by(KnowledgeDocument.id.desc()).all()

@router.post("", response_model=KnowledgeOut)
def create_document(payload: KnowledgeCreate, principal: Principal = Depends(require_role("member")), db: Session = Depends(get_db)):
    enforce_org(payload.organization_id, principal)
    if payload.company_id is not None: ensure_company(db, payload.company_id, principal)
    if payload.department_id is not None: ensure_department(db, payload.department_id, principal)
    if payload.project_id is not None: ensure_project(db, payload.project_id, principal)
    obj = KnowledgeDocument(**payload.model_dump(), indexed=bool(payload.content))
    db.add(obj); db.commit(); db.refresh(obj)
    return obj

@router.get("/search", response_model=list[KnowledgeOut])
def search(q: str, principal: Principal = Depends(require_human()), db: Session = Depends(get_db)):
    org_id = active_org(principal); like = f"%{q}%"
    return db.query(KnowledgeDocument).filter(
        KnowledgeDocument.organization_id == org_id,
        or_(KnowledgeDocument.title.ilike(like), KnowledgeDocument.content.ilike(like))
    ).limit(50).all()
