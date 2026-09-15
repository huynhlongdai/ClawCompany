from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.models import Member
from app.schemas import MemberCreate, MemberOut
from app.core.authz import Principal, get_principal, require_role, enforce_org, require_human
from app.core.tenancy import active_org, ensure_company, ensure_department, ensure_member

router = APIRouter(prefix="/members", tags=["members"])

@router.get("", response_model=list[MemberOut])
def list_members(company_id: int | None = None, member_type: str | None = None, principal: Principal = Depends(require_human()), db: Session = Depends(get_db)):
    org_id = active_org(principal)
    q = db.query(Member).filter(Member.organization_id == org_id)
    if company_id is not None:
        ensure_company(db, company_id, principal); q = q.filter(Member.company_id == company_id)
    if member_type:
        q = q.filter(Member.member_type == member_type)
    return q.order_by(Member.id).all()

@router.post("", response_model=MemberOut)
def create_member(payload: MemberCreate, principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    enforce_org(payload.organization_id, principal)
    if payload.company_id is not None: ensure_company(db, payload.company_id, principal)
    if payload.department_id is not None: ensure_department(db, payload.department_id, principal)
    if payload.manager_id is not None: ensure_member(db, payload.manager_id, principal)
    obj = Member(**payload.model_dump())
    db.add(obj); db.commit(); db.refresh(obj)
    return obj
