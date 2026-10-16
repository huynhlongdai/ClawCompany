from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.models import Company, Member, Project, Customer, Approval, InboxItem
from app.core.authz import Principal, get_principal, enforce_org, require_human

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

@router.get("/summary")
def summary(organization_id: int, principal: Principal = Depends(require_human()), db: Session = Depends(get_db)):
    enforce_org(organization_id, principal)
    company_ids = [x[0] for x in db.query(Company.id).filter(Company.organization_id == organization_id).all()]
    from app.core import company_scope  # P0: người bị giới hạn công ty → số của công ty mình, không phải cả org
    allowed = company_scope.allowed_company_ids(principal)
    if allowed is not None:
        cids = [c for c in company_ids if c in allowed] or [-1]
        mem = db.query(Member).filter(Member.organization_id == organization_id, Member.company_id.in_(cids))
        return {
            "companies": len([c for c in cids if c != -1]),
            "members": mem.count(),
            "ai_agents": mem.filter(Member.member_type == "agent").count(),
            "humans": mem.filter(Member.member_type == "human").count(),
            "projects_active": db.query(Project).filter(Project.company_id.in_(cids), Project.status.in_(["active", "running"])).count(),
            "customers": 0,  # khách hàng hiện ở cấp tổ chức (chưa có company_id) — không đếm cho người bị giới hạn
            "approvals_pending": db.query(Approval).filter(Approval.company_id.in_(cids), Approval.status == "pending").count(),
            "inbox_unread": db.query(InboxItem).filter(InboxItem.company_id.in_(cids), InboxItem.status == "unread").count(),
        }
    return {
        "companies": db.query(Company).filter(Company.organization_id == organization_id).count(),
        "members": db.query(Member).filter(Member.organization_id == organization_id).count(),
        "ai_agents": db.query(Member).filter(Member.organization_id == organization_id, Member.member_type == "agent").count(),
        "humans": db.query(Member).filter(Member.organization_id == organization_id, Member.member_type == "human").count(),
        "projects_active": db.query(Project).filter(Project.company_id.in_(company_ids), Project.status.in_(["active", "running"])).count() if company_ids else 0,
        "customers": db.query(Customer).filter(Customer.organization_id == organization_id).count(),
        "approvals_pending": db.query(Approval).filter(Approval.organization_id == organization_id, Approval.status == "pending").count(),
        "inbox_unread": db.query(InboxItem).filter(InboxItem.organization_id == organization_id, InboxItem.status == "unread").count(),
    }
