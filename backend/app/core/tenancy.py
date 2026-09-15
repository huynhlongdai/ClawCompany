from fastapi import HTTPException
from sqlalchemy.orm import Session
from app.core.authz import Principal, enforce_org
from app.models import Company, Department, Member, Agent, Project, Task, KnowledgeDocument, Approval, Customer, Workflow


def active_org(principal: Principal) -> int:
    if principal.organization_id is None:
        raise HTTPException(400, "No active organization selected")
    return int(principal.organization_id)


def ensure_company(db: Session, company_id: int, principal: Principal) -> Company:
    item = db.get(Company, company_id)
    if not item:
        raise HTTPException(404, "Company not found")
    enforce_org(item.organization_id, principal)
    return item


def ensure_department(db: Session, department_id: int, principal: Principal) -> Department:
    item = db.get(Department, department_id)
    if not item:
        raise HTTPException(404, "Department not found")
    ensure_company(db, item.company_id, principal)
    return item


def ensure_member(db: Session, member_id: int, principal: Principal) -> Member:
    item = db.get(Member, member_id)
    if not item:
        raise HTTPException(404, "Member not found")
    enforce_org(item.organization_id, principal)
    return item


def ensure_agent(db: Session, agent_id: int, principal: Principal) -> Agent:
    item = db.get(Agent, agent_id)
    if not item:
        raise HTTPException(404, "Agent not found")
    ensure_member(db, item.member_id, principal)
    return item


def ensure_project(db: Session, project_id: int, principal: Principal) -> Project:
    item = db.get(Project, project_id)
    if not item:
        raise HTTPException(404, "Project not found")
    ensure_company(db, item.company_id, principal)
    return item


def ensure_task(db: Session, task_id: int, principal: Principal) -> Task:
    item = db.get(Task, task_id)
    if not item:
        raise HTTPException(404, "Task not found")
    ensure_project(db, item.project_id, principal)
    return item


def ensure_customer(db: Session, customer_id: int, principal: Principal) -> Customer:
    item = db.get(Customer, customer_id)
    if not item:
        raise HTTPException(404, "Customer not found")
    enforce_org(item.organization_id, principal)
    return item


def ensure_workflow(db: Session, workflow_id: int, principal: Principal) -> Workflow:
    item = db.get(Workflow, workflow_id)
    if not item:
        raise HTTPException(404, "Workflow not found")
    enforce_org(item.organization_id, principal)
    return item
