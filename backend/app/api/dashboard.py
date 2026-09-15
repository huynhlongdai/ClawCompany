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
