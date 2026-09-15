"""v18 workspace operations API — the write half of the cockpit.

Every endpoint resolves its target through the tenancy helpers first, so a token
from another organization gets 403/404 instead of touching a neighbour's data.
Writes require the `company.workspace:write` scope for API keys and at least the
`member` human role; structural changes (company, department, seats) require
`manager`.
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.authz import Principal, require_role, require_scope
from app.core.tenancy import (active_org, ensure_company, ensure_member, ensure_project,
                             ensure_task)
from app.db.session import get_db
from app.services import workspace_ops as ops

router = APIRouter(prefix="/v18", tags=["v18-workspace-ops"])

WRITE = "company.workspace:write"


def writer(minimum_role: str = "member"):
    """Human role gate and API-key scope gate in one dependency.

    require_role rejects API keys outright and require_scope waves through JWTs,
    so the two together mean: humans are checked by role, agents by scope.
    """
    def dep(principal: Principal = Depends(require_scope(WRITE))) -> Principal:
        if principal.auth_type != "api_key":
            return require_role(minimum_role)(principal)
        return principal
    return dep


# --------------------------------------------------------------------------- models

class CompanyIn(BaseModel):
    name: str
    industry: str = ""
    status: str = "active"


class CompanyPatch(BaseModel):
    name: str | None = None
    industry: str | None = None
    status: str | None = None


class DepartmentIn(BaseModel):
    company_id: int
    name: str
    head_member_id: int | None = None
    access_level: str = "restricted"


class MemberIn(BaseModel):
    name: str
    member_type: str = Field(pattern="^(human|agent)$")
    company_id: int | None = None
    department_id: int | None = None
    role: str = ""
    manager_id: int | None = None
    status: str = "active"
    runtime_agent_id: str | None = None
    model: str = ""
    risk: str = "low"


class MemberPatch(BaseModel):
    company_id: int | None = None
    department_id: int | None = None
    role: str | None = None
    manager_id: int | None = None
    status: str | None = None


class ProjectIn(BaseModel):
    company_id: int
    name: str
    description: str = ""
    owner_member_id: int | None = None
    status: str = "planning"


class ProjectPatch(BaseModel):
    status: str | None = None
    progress: int | None = None
    owner_member_id: int | None = None
    description: str | None = None


class TaskIn(BaseModel):
    project_id: int
    title: str
    description: str = ""
    assignee_member_id: int | None = None
    priority: str = "medium"


class TaskMove(BaseModel):
    status: str


class TaskAssign(BaseModel):
    assignee_member_id: int | None = None


class KnowledgeIn(BaseModel):
    title: str
    content: str = ""
    company_id: int | None = None
    department_id: int | None = None
    project_id: int | None = None
    access_level: str = "restricted"
    source_type: str = "manual"


# ------------------------------------------------------------------------ endpoints

@router.post("/workspace/companies")
def create_company(payload: CompanyIn, principal: Principal = Depends(writer("manager")),
                   db: Session = Depends(get_db)):
    company = ops.create_company(db, active_org(principal), name=payload.name, industry=payload.industry,
                                 status=payload.status, actor_member_id=principal.member_id)
    return {"id": company.id, "name": company.name, "industry": company.industry, "status": company.status}


@router.patch("/workspace/companies/{company_id}")
def update_company(company_id: int, payload: CompanyPatch,
                   principal: Principal = Depends(writer("manager")), db: Session = Depends(get_db)):
    company = ensure_company(db, company_id, principal)
    company = ops.update_company(db, company, name=payload.name, industry=payload.industry,
                                 status=payload.status, actor_member_id=principal.member_id)
    return {"id": company.id, "name": company.name, "industry": company.industry, "status": company.status}


@router.post("/workspace/departments")
def create_department(payload: DepartmentIn, principal: Principal = Depends(writer("manager")),
                      db: Session = Depends(get_db)):
    company = ensure_company(db, payload.company_id, principal)
    dept = ops.create_department(db, company, name=payload.name, head_member_id=payload.head_member_id,
                                 access_level=payload.access_level, actor_member_id=principal.member_id)
    return {"id": dept.id, "company_id": dept.company_id, "name": dept.name,
            "head_member_id": dept.head_member_id, "access_level": dept.access_level}


@router.post("/workspace/members")
def create_member(payload: MemberIn, principal: Principal = Depends(writer("manager")),
                  db: Session = Depends(get_db)):
    org_id = active_org(principal)
    if payload.company_id is not None:
        ensure_company(db, payload.company_id, principal)
    member, agent = ops.create_member(
        db, org_id, name=payload.name, member_type=payload.member_type, company_id=payload.company_id,
        department_id=payload.department_id, role=payload.role, manager_id=payload.manager_id,
        status=payload.status, runtime_agent_id=payload.runtime_agent_id, model=payload.model,
        risk=payload.risk, actor_member_id=principal.member_id)
    return {"id": member.id, "name": member.name, "member_type": member.member_type,
            "company_id": member.company_id, "department_id": member.department_id,
            "role": member.role, "status": member.status,
            "agent": ({"id": agent.id, "runtime_agent_id": agent.runtime_agent_id,
                       "lifecycle": agent.lifecycle} if agent else None)}


@router.patch("/workspace/members/{member_id}")
def update_member(member_id: int, payload: MemberPatch, principal: Principal = Depends(writer("manager")),
                  db: Session = Depends(get_db)):
    member = ensure_member(db, member_id, principal)
    if payload.company_id is not None:
        ensure_company(db, payload.company_id, principal)
    member = ops.move_member(db, member, company_id=payload.company_id, department_id=payload.department_id,
                             role=payload.role, manager_id=payload.manager_id, status=payload.status,
                             actor_member_id=principal.member_id)
    return {"id": member.id, "name": member.name, "company_id": member.company_id,
            "department_id": member.department_id, "manager_id": member.manager_id,
            "role": member.role, "status": member.status}


@router.post("/workspace/projects")
def create_project(payload: ProjectIn, principal: Principal = Depends(writer("member")),
                   db: Session = Depends(get_db)):
    company = ensure_company(db, payload.company_id, principal)
    project = ops.create_project(db, company, name=payload.name, description=payload.description,
                                 owner_member_id=payload.owner_member_id, status=payload.status,
                                 actor_member_id=principal.member_id)
    return {"id": project.id, "company_id": project.company_id, "name": project.name,
            "status": project.status, "progress": project.progress,
            "owner_member_id": project.owner_member_id}


@router.patch("/workspace/projects/{project_id}")
def update_project(project_id: int, payload: ProjectPatch,
                   principal: Principal = Depends(writer("member")), db: Session = Depends(get_db)):
    project = ensure_project(db, project_id, principal)
    project = ops.update_project(db, project, active_org(principal), status=payload.status,
                                 progress=payload.progress, owner_member_id=payload.owner_member_id,
                                 description=payload.description, actor_member_id=principal.member_id)
    return {"id": project.id, "name": project.name, "status": project.status,
            "progress": project.progress, "owner_member_id": project.owner_member_id}


@router.post("/workspace/tasks")
def create_task(payload: TaskIn, principal: Principal = Depends(writer("member")),
                db: Session = Depends(get_db)):
    project = ensure_project(db, payload.project_id, principal)
    task = ops.create_task(db, project, active_org(principal), title=payload.title,
                           description=payload.description, assignee_member_id=payload.assignee_member_id,
                           priority=payload.priority, actor_member_id=principal.member_id)
    return _task_out(task)


@router.post("/workspace/tasks/{task_id}/move")
def move_task(task_id: int, payload: TaskMove, principal: Principal = Depends(writer("member")),
              db: Session = Depends(get_db)):
    task = ensure_task(db, task_id, principal)
    project = ensure_project(db, task.project_id, principal)
    task = ops.move_task(db, task, project, active_org(principal), status=payload.status,
                         actor_member_id=principal.member_id)
    return _task_out(task)


@router.post("/workspace/tasks/{task_id}/assign")
def assign_task(task_id: int, payload: TaskAssign, principal: Principal = Depends(writer("member")),
                db: Session = Depends(get_db)):
    task = ensure_task(db, task_id, principal)
    project = ensure_project(db, task.project_id, principal)
    task = ops.assign_task(db, task, project, active_org(principal),
                           assignee_member_id=payload.assignee_member_id,
                           actor_member_id=principal.member_id)
    return _task_out(task)


@router.post("/workspace/knowledge")
def create_knowledge(payload: KnowledgeIn, principal: Principal = Depends(writer("member")),
                     db: Session = Depends(get_db)):
    if payload.company_id is not None:
        ensure_company(db, payload.company_id, principal)
    if payload.project_id is not None:
        ensure_project(db, payload.project_id, principal)
    doc = ops.create_knowledge_document(db, active_org(principal), title=payload.title,
                                        content=payload.content, company_id=payload.company_id,
                                        department_id=payload.department_id,
                                        project_id=payload.project_id,
                                        access_level=payload.access_level,
                                        source_type=payload.source_type,
                                        actor_member_id=principal.member_id)
    return {"id": doc.id, "title": doc.title, "access_level": doc.access_level,
            "company_id": doc.company_id, "indexed": doc.indexed}


@router.get("/workspace/vocabulary")
def vocabulary(principal: Principal = Depends(require_scope("company.context:read"))):
    """Let the UI build dropdowns and disable illegal moves without hardcoding."""
    return {
        "company_statuses": list(ops.COMPANY_STATUSES),
        "member_statuses": list(ops.MEMBER_STATUSES),
        "project_statuses": list(ops.PROJECT_STATUSES),
        "task_statuses": list(ops.TASK_STATUSES),
        "task_priorities": list(ops.TASK_PRIORITIES),
        "task_transitions": {key: list(value) for key, value in ops.TASK_TRANSITIONS.items()},
        "access_levels": list(ops.ACCESS_LEVELS),
    }


def _task_out(task) -> dict:
    return {"id": task.id, "project_id": task.project_id, "title": task.title,
            "status": task.status, "priority": task.priority,
            "assignee_member_id": task.assignee_member_id}
