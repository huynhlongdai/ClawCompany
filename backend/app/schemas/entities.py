from pydantic import BaseModel, Field
from app.schemas.common import ORMModel

class OrganizationCreate(BaseModel):
    name: str
    slug: str

class OrganizationOut(ORMModel):
    id: int
    name: str
    slug: str

class CompanyCreate(BaseModel):
    organization_id: int
    name: str
    industry: str = ""
    status: str = "active"

class CompanyOut(ORMModel):
    id: int
    organization_id: int
    name: str
    industry: str
    status: str

class DepartmentCreate(BaseModel):
    company_id: int
    name: str
    head_member_id: int | None = None
    access_level: str = "restricted"

class DepartmentOut(ORMModel):
    id: int
    company_id: int
    name: str
    head_member_id: int | None
    access_level: str

class MemberCreate(BaseModel):
    organization_id: int
    company_id: int | None = None
    department_id: int | None = None
    name: str
    member_type: str = Field(pattern="^(human|agent)$")
    role: str = ""
    manager_id: int | None = None
    status: str = "active"

class MemberOut(ORMModel):
    id: int
    organization_id: int
    company_id: int | None
    department_id: int | None
    name: str
    member_type: str
    role: str
    manager_id: int | None
    status: str

class AgentCreate(BaseModel):
    member_id: int
    runtime_agent_id: str
    runtime_provider: str = "openclaw"
    lifecycle: str = "active"
    model: str = ""
    success_rate: float = 0
    cost_30d: float = 0
    risk: str = "low"

class AgentOut(ORMModel):
    id: int
    member_id: int
    runtime_provider: str
    runtime_agent_id: str
    lifecycle: str
    model: str
    success_rate: float
    cost_30d: float
    risk: str

class ProjectCreate(BaseModel):
    company_id: int
    name: str
    description: str = ""
    owner_member_id: int | None = None
    status: str = "planning"
    progress: int = Field(default=0, ge=0, le=100)

class ProjectOut(ORMModel):
    id: int
    company_id: int
    name: str
    description: str
    owner_member_id: int | None
    status: str
    progress: int

class TaskCreate(BaseModel):
    project_id: int
    title: str
    description: str = ""
    assignee_member_id: int | None = None
    status: str = "backlog"
    priority: str = "medium"

class TaskOut(ORMModel):
    id: int
    project_id: int
    title: str
    description: str
    assignee_member_id: int | None
    status: str
    priority: str
    runtime_task_id: str | None
    runtime_run_id: str | None
    runtime_session_key: str | None

class KnowledgeCreate(BaseModel):
    organization_id: int
    company_id: int | None = None
    department_id: int | None = None
    project_id: int | None = None
    title: str
    source_type: str = "upload"
    access_level: str = "restricted"
    content: str = ""

class KnowledgeOut(ORMModel):
    id: int
    organization_id: int
    company_id: int | None
    department_id: int | None
    project_id: int | None
    title: str
    source_type: str
    access_level: str
    indexed: bool

class ApprovalCreate(BaseModel):
    organization_id: int
    company_id: int | None = None
    requester_member_id: int | None = None
    approver_member_id: int | None = None
    action: str
    risk: str = "medium"
    policy_key: str = ""
    evidence: str = ""

class ApprovalResolve(BaseModel):
    status: str = Field(pattern="^(approved|rejected)$")
    resolution_note: str = ""

class ApprovalOut(ORMModel):
    id: int
    organization_id: int
    company_id: int | None
    requester_member_id: int | None
    approver_member_id: int | None
    action: str
    risk: str
    policy_key: str
    status: str
    evidence: str
    resolution_note: str