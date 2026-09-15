from pydantic import BaseModel, Field
from app.schemas.common import ORMModel

class ResourceCreate(BaseModel):
    organization_id: int | None = None
    company_id: int | None = None
    name: str | None = None
    title: str | None = None
    status: str = "active"
    data: dict = {}

class GenericOut(ORMModel):
    id: int

class InboxCreate(BaseModel):
    organization_id: int
    recipient_member_id: int | None = None
    source: str
    title: str
    item_type: str = "notification"
    priority: str = "normal"
    status: str = "unread"
    related_type: str = ""
    related_id: str = ""

class MissionCreate(BaseModel):
    company_id: int
    name: str
    outcome: str = ""
    owner_member_id: int | None = None
    status: str = "planning"
    progress: int = Field(default=0, ge=0, le=100)
    target_date: str = ""

class WorkflowCreate(BaseModel):
    organization_id: int
    company_id: int | None = None
    name: str
    trigger_type: str = "manual"
    definition_json: str = "{}"
    owner_member_id: int | None = None
    status: str = "active"

class AutomationCreate(BaseModel):
    organization_id: int
    company_id: int | None = None
    name: str
    automation_type: str = "scheduled"
    schedule: str = ""
    condition_json: str = "{}"
    owner_member_id: int | None = None
    status: str = "active"

class SOPCreate(BaseModel):
    organization_id: int
    department_id: int | None = None
    title: str
    version: str = "v1.0"
    owner_member_id: int | None = None
    content: str = ""
    status: str = "draft"

class DecisionCreate(BaseModel):
    organization_id: int
    company_id: int | None = None
    title: str
    context: str = ""
    alternatives: str = ""
    recommendation: str = ""
    owner_member_id: int | None = None
    status: str = "pending"
    impact: str = "medium"

class ConversationCreate(BaseModel):
    organization_id: int
    company_id: int | None = None
    conversation_type: str = "internal"
    title: str
    session_key: str = ""
    channel: str = "web"
    related_type: str = ""
    related_id: str = ""

class MessageCreate(BaseModel):
    sender_member_id: int | None = None
    sender_name: str = ""
    content: str
    message_type: str = "text"

class CustomerCreate(BaseModel):
    organization_id: int
    name: str
    plan: str = "AI Employee"
    tenant_key: str
    status: str = "active"
    portal_enabled: bool = True
    usage_percent: int = 0
    mrr: float = 0

class CustomerAssignmentCreate(BaseModel):
    customer_id: int
    agent_id: int
    role_label: str = ""
    knowledge_scope: str = ""
    status: str = "active"

class ReportCreate(BaseModel):
    organization_id: int
    company_id: int | None = None
    report_type: str = "executive"
    title: str
    period: str = ""
    owner_member_id: int | None = None
    content: str = ""
    audience: str = ""
    status: str = "ready"

class MetricCreate(BaseModel):
    organization_id: int
    scope_type: str = "organization"
    scope_id: str = ""
    metric_key: str
    current_value: float = 0
    previous_value: float = 0
    target_value: float = 0
    unit: str = ""

class IntegrationCreate(BaseModel):
    organization_id: int
    company_id: int | None = None
    name: str
    category: str = "app"
    provider: str = ""
    status: str = "connected"
    config_json: str = "{}"
    last_sync: str = ""

class SkillCreate(BaseModel):
    organization_id: int
    name: str
    version: str = "1.0"
    scope: str = "organization"
    description: str = ""
    status: str = "enabled"

class ToolCreate(BaseModel):
    organization_id: int
    name: str
    tool_type: str = "tool"
    scope: str = "organization"
    policy: str = "scoped"
    status: str = "enabled"
    config_json: str = "{}"

class MarketplaceCreate(BaseModel):
    organization_id: int
    name: str
    template_type: str = "employee"
    publisher: str = "Nova"
    version: str = "1.0"
    manifest_json: str = "{}"
    price_monthly: float = 0
    status: str = "draft"

class SubscriptionCreate(BaseModel):
    customer_id: int
    plan: str
    status: str = "active"
    mrr: float = 0
    ai_cost: float = 0
    usage_percent: int = 0
    renewal_date: str = ""

class SettingUpsert(BaseModel):
    organization_id: int
    key: str
    value: str
    category: str = "general"

class RoleBindingCreate(BaseModel):
    organization_id: int
    member_id: int
    role: str = "member"
    scope_type: str = "organization"
    scope_id: str = ""

class PolicyCreate(BaseModel):
    organization_id: int
    key: str
    action: str
    minimum_role: str = "member"
    requires_approval: bool = False
    enabled: bool = True