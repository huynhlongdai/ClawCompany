from pydantic import BaseModel, Field


class AutonomyPolicyUpsert(BaseModel):
    organization_id: int
    company_id: int | None = None
    mode: str = "supervised"
    max_concurrent_runs: int = Field(default=5, ge=1, le=100)
    retry_limit: int = Field(default=2, ge=0, le=10)
    max_auto_risk: str = "low"
    daily_budget_limit: float = Field(default=100.0, ge=0)
    per_action_limit: float = Field(default=25.0, ge=0)
    pause_on_high_incident: bool = True
    require_approval_for_external_publish: bool = True
    enabled: bool = True


class ExecutiveGoalCreate(BaseModel):
    organization_id: int
    company_id: int | None = None
    title: str = Field(min_length=2, max_length=220)
    objective: str = Field(min_length=4, max_length=12000)
    expected_outcome: str = ""
    priority: str = "high"
    risk: str = "medium"
    autonomy_mode: str = "inherit"
    deadline: str = ""
    budget_limit: float | None = Field(default=None, ge=0)
    currency: str = "USD"


class GoalPlanRequest(BaseModel):
    max_steps: int = Field(default=5, ge=1, le=20)
    project_id: int | None = None
    auto_create_tasks: bool = True


class GoalRunRequest(BaseModel):
    estimated_cost_per_assignment: float = Field(default=0.25, ge=0)
    execute_unassigned: bool = False


class BudgetEnvelopeCreate(BaseModel):
    organization_id: int
    company_id: int | None = None
    goal_id: int | None = None
    name: str
    currency: str = "USD"
    amount_limit: float = Field(ge=0)


class BudgetEntryCreate(BaseModel):
    entry_type: str = "spend"
    amount: float = Field(gt=0)
    source_type: str = "manual"
    source_id: str = ""
    memo: str = ""


class MemoryCreate(BaseModel):
    organization_id: int
    company_id: int | None = None
    department_id: int | None = None
    project_id: int | None = None
    agent_id: int | None = None
    memory_type: str = "fact"
    content: str = Field(min_length=1, max_length=30000)
    source_type: str = "manual"
    source_id: str = ""
    importance: int = Field(default=3, ge=1, le=5)
    confidence: float = Field(default=1.0, ge=0, le=1)
    tags: list[str] = Field(default_factory=list)


class RecurringOperationCreate(BaseModel):
    organization_id: int
    company_id: int | None = None
    name: str
    schedule: str = "0 8 * * *"
    timezone: str = "UTC"
    operation_type: str = "nina_goal"
    payload: dict = Field(default_factory=dict)
    enabled: bool = True


class IncidentRetryRequest(BaseModel):
    force: bool = False
