from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.models import Approval
from app.schemas import ApprovalCreate, ApprovalResolve, ApprovalOut
from app.core.authz import Principal, get_principal, require_role, enforce_org, require_human
from app.core.tenancy import active_org, ensure_company, ensure_member

router = APIRouter(prefix="/approvals", tags=["approvals"])

@router.get("", response_model=list[ApprovalOut])
def list_approvals(status: str | None = None, principal: Principal = Depends(require_human()), db: Session = Depends(get_db)):
    org_id = active_org(principal)
    q = db.query(Approval).filter(Approval.organization_id == org_id)
    if status: q = q.filter(Approval.status == status)
    return q.order_by(Approval.id.desc()).all()

@router.post("", response_model=ApprovalOut)
def create_approval(payload: ApprovalCreate, principal: Principal = Depends(require_role("member")), db: Session = Depends(get_db)):
    enforce_org(payload.organization_id, principal)
    if payload.company_id is not None: ensure_company(db, payload.company_id, principal)
    if payload.requester_member_id is not None: ensure_member(db, payload.requester_member_id, principal)
    if payload.approver_member_id is not None: ensure_member(db, payload.approver_member_id, principal)
    obj = Approval(**payload.model_dump())
    db.add(obj); db.commit(); db.refresh(obj)
    return obj

@router.post("/{approval_id}/resolve", response_model=ApprovalOut)
def resolve_approval(approval_id: int, payload: ApprovalResolve, principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    obj = db.get(Approval, approval_id)
    if not obj: from fastapi import HTTPException; raise HTTPException(404, "Approval not found")
    enforce_org(obj.organization_id, principal)
    obj.status = payload.status; obj.resolution_note = payload.resolution_note
    db.add(obj); db.commit(); db.refresh(obj)
    return obj
