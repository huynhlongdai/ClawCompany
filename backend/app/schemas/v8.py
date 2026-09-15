from pydantic import BaseModel, Field


class AgentHireRequest(BaseModel):
    organization_id: int
    company_id: int | None = None
    department_id: int | None = None
    template_id: int | None = None
    name: str
    role: str
    model: str = ""
    runtime_agent_id: str = ""
    manager_member_id: int | None = None
    manifest: dict = Field(default_factory=dict)


class CompanyFactoryRequest(BaseModel):
    organization_id: int
    template_id: int | None = None
    company_name: str
    industry: str = ""
    manifest: dict = Field(default_factory=dict)


class NinaPlanRequest(BaseModel):
    organization_id: int
    objective: str
    company_id: int | None = None
    project_id: int | None = None
    auto_create_tasks: bool = True
    max_steps: int = Field(default=6, ge=1, le=20)


class NinaDelegateRequest(BaseModel):
    execute_unassigned: bool = False


class WorkflowGraphSave(BaseModel):
    graph: dict
    publish: bool = False


class CustomerChatStart(BaseModel):
    agent_id: int
    title: str = "AI Employee Chat"


class CustomerChatMessage(BaseModel):
    content: str = Field(min_length=1, max_length=20000)


class RuntimeEventQuery(BaseModel):
    run_id: str


class UsageMeterRuleCreate(BaseModel):
    organization_id: int
    event_type: str
    unit: str = "event"
    unit_cost: float = 0
    customer_billable: bool = False
    customer_unit_price: float = 0
    enabled: bool = True
