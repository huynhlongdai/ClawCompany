import json
from sqlalchemy.orm import Session
from app.models import Company, Project, Approval, InboxItem, Agent, Member, NinaCommandLog

def executive_brief(db: Session, organization_id: int):
    company_count = db.query(Company).filter(Company.organization_id == organization_id).count()
    company_ids = [x[0] for x in db.query(Company.id).filter(Company.organization_id == organization_id).all()]
    projects = db.query(Project).filter(Project.company_id.in_(company_ids)).count() if company_ids else 0
    pending = db.query(Approval).filter(Approval.organization_id == organization_id, Approval.status == "pending").count()
    unread = db.query(InboxItem).filter(InboxItem.organization_id == organization_id, InboxItem.status == "unread").count()
    agents = db.query(Agent).join(Member, Member.id == Agent.member_id).filter(Member.organization_id == organization_id).count()
    return {
        "headline": f"{company_count} companies, {projects} projects, {agents} AI employees.",
        "needs_attention": [f"{pending} approvals pending", f"{unread} unread inbox items"],
        "companies": company_count, "projects": projects, "agents": agents,
        "approvals": pending, "unread": unread,
    }

def handle_command(db: Session, organization_id: int, user_id: int | None, message: str):
    m = message.lower()
    intent = "brief"
    if "approval" in m or "phê duyệt" in m:
        intent = "approvals"
    elif "project" in m or "dự án" in m:
        intent = "projects"
    elif "agent" in m or "nhân sự ai" in m:
        intent = "agents"
    brief = executive_brief(db, organization_id)
    if intent == "approvals":
        result = {"intent": intent, "message": f"Có {brief['approvals']} phê duyệt đang chờ.", "data": brief}
    elif intent == "projects":
        result = {"intent": intent, "message": f"Hiện có {brief['projects']} dự án trong tổ chức.", "data": brief}
    elif intent == "agents":
        result = {"intent": intent, "message": f"Hiện có {brief['agents']} AI employees.", "data": brief}
    else:
        result = {"intent": "brief", "message": brief["headline"], "data": brief}
    log = NinaCommandLog(
        organization_id=organization_id, user_id=user_id, message=message,
        intent=result["intent"], result_json=json.dumps(result, ensure_ascii=False),
    )
    db.add(log); db.commit()
    return result
