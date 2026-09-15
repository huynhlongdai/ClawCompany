from pydantic import BaseModel, Field


class CompanyEventCreate(BaseModel):
    organization_id: int
    company_id: int | None = None
    event_type: str = Field(min_length=2, max_length=180)
    source: str = "manual"
    aggregate_type: str = ""
    aggregate_id: str = ""
    correlation_id: str = ""
    causation_id: str = ""
    payload: dict = Field(default_factory=dict)


class EventTriggerCreate(BaseModel):
    organization_id: int
    company_id: int | None = None
    name: str = Field(min_length=2, max_length=180)
    event_pattern: str = "*"
    condition: dict = Field(default_factory=dict)
    action_type: str = "message"
    action: dict = Field(default_factory=dict)
    cooldown_seconds: int = Field(default=0, ge=0, le=604800)
    enabled: bool = True


class AgentMessageCreate(BaseModel):
    organization_id: int
    company_id: int | None = None
    thread_key: str = ""
    sender_member_id: int | None = None
    recipient_member_id: int | None = None
    task_id: int | None = None
    artifact_id: int | None = None
    message_type: str = "message"
    subject: str = ""
    content: str = Field(min_length=1, max_length=50000)
    priority: str = "normal"
    context: dict = Field(default_factory=dict)


class ArtifactCreate(BaseModel):
    organization_id: int
    company_id: int | None = None
    project_id: int | None = None
    task_id: int | None = None
    created_by_member_id: int | None = None
    created_by_agent_id: int | None = None
    runtime_run_id: str = ""
    bundle_key: str = ""
    logical_path: str = ""
    name: str = Field(min_length=1, max_length=220)
    artifact_type: str = "deliverable"
    mime_type: str = "text/plain"
    uri: str = ""
    content_text: str = Field(default="", max_length=2_000_000)
    metadata: dict = Field(default_factory=dict)


class ArtifactHandoffCreate(BaseModel):
    to_member_id: int
    from_member_id: int | None = None
    task_id: int | None = None
    purpose: str = "continue_work"
    instructions: str = Field(default="", max_length=30000)


class ArtifactEvaluationCreate(BaseModel):
    evaluator_member_id: int | None = None
    evaluator_agent_id: int | None = None
    rubric: dict = Field(default_factory=dict)


class SLAProfileCreate(BaseModel):
    organization_id: int
    company_id: int | None = None
    name: str
    resource_type: str = "task"
    priority: str = "*"
    response_minutes: int = Field(default=60, ge=1)
    completion_minutes: int = Field(default=1440, ge=1)
    escalation_after_minutes: int = Field(default=30, ge=0)
    escalation_target_member_id: int | None = None
    enabled: bool = True


class DecisionLoopCreate(BaseModel):
    organization_id: int
    company_id: int | None = None
    name: str = "Nina Continuous Loop"
    mode: str = "supervised"
    interval_seconds: int = Field(default=60, ge=10, le=86400)
    policy: dict = Field(default_factory=dict)
    enabled: bool = True


class SimulationScenarioCreate(BaseModel):
    organization_id: int
    company_id: int | None = None
    name: str
    description: str = ""
    assumptions: dict = Field(default_factory=dict)
