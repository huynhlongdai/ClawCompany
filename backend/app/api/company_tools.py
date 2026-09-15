from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session
from app.core.authz import Principal, get_principal, enforce_org, require_scope
from app.db.session import get_db
from app.models import Agent, Member, Company, Department, Task, Project, Approval, InboxItem
from app.services.vector_search import search_vectors
from app.services.policy import authorize

router = APIRouter(prefix="/company-tools", tags=["company-tools"])

def resolve_agent(db: Session, runtime_agent_id: str, principal: Principal):
    agent = db.query(Agent).filter(Agent.runtime_agent_id == runtime_agent_id).first()
    if not agent:
        raise HTTPException(404, "Agent binding not found")
    member = db.get(Member, agent.member_id)
    if not member:
        raise HTTPException(404, "Member not found")
    enforce_org(member.organization_id, principal)
    return agent, member

@router.get("/context")
def company_context(runtime_agent_id: str, principal: Principal = Depends(require_scope("company.context:read")), db: Session = Depends(get_db)):
    agent, member = resolve_agent(db, runtime_agent_id, principal)
    company = db.get(Company, member.company_id) if member.company_id else None
    department = db.get(Department, member.department_id) if member.department_id else None
    manager = db.get(Member, member.manager_id) if member.manager_id else None
    return {
        "agent": {"id": agent.id, "runtime_agent_id": agent.runtime_agent_id, "lifecycle": agent.lifecycle, "model": agent.model},
        "member": {"id": member.id, "name": member.name, "role": member.role, "status": member.status},
        "organization_id": member.organization_id,
        "company": {"id": company.id, "name": company.name} if company else None,
        "department": {"id": department.id, "name": department.name} if department else None,
        "manager": {"id": manager.id, "name": manager.name, "role": manager.role} if manager else None,
    }

@router.get("/tasks")
def company_tasks(runtime_agent_id: str, status: str | None = None, principal: Principal = Depends(require_scope("company.tasks:read")), db: Session = Depends(get_db)):
    agent, member = resolve_agent(db, runtime_agent_id, principal)
    q = db.query(Task).filter(Task.assignee_member_id == member.id)
    if status:
        q = q.filter(Task.status == status)
    rows = q.order_by(Task.id.desc()).limit(100).all()
    return [{"id": t.id, "project_id": t.project_id, "title": t.title, "description": t.description, "status": t.status, "priority": t.priority} for t in rows]

@router.post("/tasks/{task_id}/status")
def update_task_status(task_id: int, runtime_agent_id: str, payload: dict = Body(...), principal: Principal = Depends(require_scope("company.tasks:write")), db: Session = Depends(get_db)):
    agent, member = resolve_agent(db, runtime_agent_id, principal)
    task = db.get(Task, task_id)
    if not task or task.assignee_member_id != member.id:
        raise HTTPException(404, "Assigned task not found")
    task.status = str(payload.get("status", task.status))
    db.add(task); db.commit(); db.refresh(task)
    return {"id": task.id, "status": task.status}

@router.post("/knowledge/search")
def company_knowledge_search(runtime_agent_id: str, payload: dict = Body(...), principal: Principal = Depends(require_scope("company.knowledge:read")), db: Session = Depends(get_db)):
    agent, member = resolve_agent(db, runtime_agent_id, principal)
    query = str(payload.get("query", "")).strip()
    if not query:
        raise HTTPException(400, "query is required")
    return search_vectors(
        db, member.organization_id, query,
        company_id=member.company_id, department_id=member.department_id,
        project_id=payload.get("project_id"), limit=int(payload.get("limit", 8)),
    )

@router.post("/approval/request")
def company_approval_request(runtime_agent_id: str, payload: dict = Body(...), principal: Principal = Depends(require_scope("company.approvals:write")), db: Session = Depends(get_db)):
    agent, member = resolve_agent(db, runtime_agent_id, principal)
    action = str(payload.get("action", "")).strip()
    if not action:
        raise HTTPException(400, "action is required")
    decision = authorize(
        db, member.organization_id, action, actor_member_id=member.id,
        fallback_role="member", company_id=member.company_id,
        evidence=str(payload.get("evidence", "")),
    )
    return {"decision": decision.decision, "reason": decision.reason, "policy_key": decision.policy_key, "approval_id": decision.approval_id}

@router.post("/message/owner")
def company_message_owner(runtime_agent_id: str, payload: dict = Body(...), principal: Principal = Depends(require_scope("company.messages:write")), db: Session = Depends(get_db)):
    agent, member = resolve_agent(db, runtime_agent_id, principal)
    manager = db.get(Member, member.manager_id) if member.manager_id else None
    recipient = manager.id if manager else None
    item = InboxItem(
        organization_id=member.organization_id, recipient_member_id=recipient,
        source=member.name, title=str(payload.get("message", "Agent message")),
        item_type="agent_message", priority=str(payload.get("priority", "normal")),
        related_type="agent", related_id=str(agent.id),
    )
    db.add(item); db.commit(); db.refresh(item)
    return {"inbox_id": item.id, "recipient_member_id": recipient}
