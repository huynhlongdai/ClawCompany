from datetime import datetime
from sqlalchemy import String, Integer, DateTime, ForeignKey, Text, Float, Boolean
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base

class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class InboxItem(Base, TimestampMixin):
    __tablename__ = "inbox_items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    recipient_member_id: Mapped[int | None] = mapped_column(ForeignKey("members.id"), nullable=True, index=True)
    source: Mapped[str] = mapped_column(String(160))
    title: Mapped[str] = mapped_column(String(220))
    item_type: Mapped[str] = mapped_column(String(64), default="notification")
    priority: Mapped[str] = mapped_column(String(32), default="normal")
    status: Mapped[str] = mapped_column(String(32), default="unread")
    related_type: Mapped[str] = mapped_column(String(64), default="")
    related_id: Mapped[str] = mapped_column(String(120), default="")

class Mission(Base, TimestampMixin):
    __tablename__ = "missions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    name: Mapped[str] = mapped_column(String(220))
    outcome: Mapped[str] = mapped_column(Text, default="")
    owner_member_id: Mapped[int | None] = mapped_column(ForeignKey("members.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="planning")
    progress: Mapped[int] = mapped_column(Integer, default=0)
    target_date: Mapped[str] = mapped_column(String(40), default="")

class Workflow(Base, TimestampMixin):
    __tablename__ = "workflows"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(220))
    trigger_type: Mapped[str] = mapped_column(String(80), default="manual")
    definition_json: Mapped[str] = mapped_column(Text, default="{}")
    owner_member_id: Mapped[int | None] = mapped_column(ForeignKey("members.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="active")
    success_rate: Mapped[float] = mapped_column(Float, default=0)

class WorkflowRun(Base, TimestampMixin):
    __tablename__ = "workflow_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workflow_id: Mapped[int] = mapped_column(ForeignKey("workflows.id"), index=True)
    status: Mapped[str] = mapped_column(String(32), default="queued")
    current_step: Mapped[int] = mapped_column(Integer, default=0)
    input_json: Mapped[str] = mapped_column(Text, default="{}")
    output_json: Mapped[str] = mapped_column(Text, default="{}")
    error: Mapped[str] = mapped_column(Text, default="")

class Automation(Base, TimestampMixin):
    __tablename__ = "automations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(220))
    automation_type: Mapped[str] = mapped_column(String(64), default="scheduled")
    schedule: Mapped[str] = mapped_column(String(180), default="")
    condition_json: Mapped[str] = mapped_column(Text, default="{}")
    owner_member_id: Mapped[int | None] = mapped_column(ForeignKey("members.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="active")
    last_result: Mapped[str] = mapped_column(String(64), default="")

class SOP(Base, TimestampMixin):
    __tablename__ = "sops"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(220))
    version: Mapped[str] = mapped_column(String(40), default="v1.0")
    owner_member_id: Mapped[int | None] = mapped_column(ForeignKey("members.id"), nullable=True)
    content: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="draft")
    compliance_score: Mapped[float] = mapped_column(Float, default=0)

class Decision(Base, TimestampMixin):
    __tablename__ = "decisions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(220))
    context: Mapped[str] = mapped_column(Text, default="")
    alternatives: Mapped[str] = mapped_column(Text, default="")
    recommendation: Mapped[str] = mapped_column(Text, default="")
    owner_member_id: Mapped[int | None] = mapped_column(ForeignKey("members.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    impact: Mapped[str] = mapped_column(String(32), default="medium")

class Conversation(Base, TimestampMixin):
    __tablename__ = "conversations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"), nullable=True)
    conversation_type: Mapped[str] = mapped_column(String(48), default="internal")
    title: Mapped[str] = mapped_column(String(220))
    session_key: Mapped[str] = mapped_column(String(220), default="")
    channel: Mapped[str] = mapped_column(String(80), default="web")
    related_type: Mapped[str] = mapped_column(String(64), default="")
    related_id: Mapped[str] = mapped_column(String(120), default="")
    status: Mapped[str] = mapped_column(String(32), default="active")

class ConversationMessage(Base, TimestampMixin):
    __tablename__ = "conversation_messages"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id"), index=True)
    sender_member_id: Mapped[int | None] = mapped_column(ForeignKey("members.id"), nullable=True)
    sender_name: Mapped[str] = mapped_column(String(160), default="")
    content: Mapped[str] = mapped_column(Text)
    message_type: Mapped[str] = mapped_column(String(32), default="text")

class Customer(Base, TimestampMixin):
    __tablename__ = "customers"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    plan: Mapped[str] = mapped_column(String(120), default="AI Employee")
    tenant_key: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(32), default="active")
    portal_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    usage_percent: Mapped[int] = mapped_column(Integer, default=0)
    mrr: Mapped[float] = mapped_column(Float, default=0)

class CustomerAgentAssignment(Base, TimestampMixin):
    __tablename__ = "customer_agent_assignments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id"), index=True)
    role_label: Mapped[str] = mapped_column(String(160), default="")
    knowledge_scope: Mapped[str] = mapped_column(String(220), default="")
    status: Mapped[str] = mapped_column(String(32), default="active")

class Report(Base, TimestampMixin):
    __tablename__ = "reports"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"), nullable=True)
    report_type: Mapped[str] = mapped_column(String(64), default="executive")
    title: Mapped[str] = mapped_column(String(220))
    period: Mapped[str] = mapped_column(String(80), default="")
    owner_member_id: Mapped[int | None] = mapped_column(ForeignKey("members.id"), nullable=True)
    content: Mapped[str] = mapped_column(Text, default="")
    audience: Mapped[str] = mapped_column(String(120), default="")
    status: Mapped[str] = mapped_column(String(32), default="ready")

class AnalyticsMetric(Base, TimestampMixin):
    __tablename__ = "analytics_metrics"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    scope_type: Mapped[str] = mapped_column(String(64), default="organization")
    scope_id: Mapped[str] = mapped_column(String(120), default="")
    metric_key: Mapped[str] = mapped_column(String(120), index=True)
    current_value: Mapped[float] = mapped_column(Float, default=0)
    previous_value: Mapped[float] = mapped_column(Float, default=0)
    target_value: Mapped[float] = mapped_column(Float, default=0)
    unit: Mapped[str] = mapped_column(String(40), default="")

class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    actor_member_id: Mapped[int | None] = mapped_column(ForeignKey("members.id"), nullable=True)
    actor_name: Mapped[str] = mapped_column(String(160), default="")
    action: Mapped[str] = mapped_column(String(180), index=True)
    object_type: Mapped[str] = mapped_column(String(80), default="")
    object_id: Mapped[str] = mapped_column(String(120), default="")
    result: Mapped[str] = mapped_column(String(48), default="success")
    risk: Mapped[str] = mapped_column(String(32), default="low")
    trace_id: Mapped[str] = mapped_column(String(120), index=True)
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

class Integration(Base, TimestampMixin):
    __tablename__ = "integrations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(160))
    category: Mapped[str] = mapped_column(String(64), default="app")
    provider: Mapped[str] = mapped_column(String(120), default="")
    status: Mapped[str] = mapped_column(String(32), default="connected")
    config_json: Mapped[str] = mapped_column(Text, default="{}")
    last_sync: Mapped[str] = mapped_column(String(80), default="")

class Skill(Base, TimestampMixin):
    __tablename__ = "skills"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(160), index=True)
    version: Mapped[str] = mapped_column(String(40), default="1.0")
    scope: Mapped[str] = mapped_column(String(120), default="organization")
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="enabled")

class Tool(Base, TimestampMixin):
    __tablename__ = "tools"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(160), index=True)
    tool_type: Mapped[str] = mapped_column(String(64), default="tool")
    scope: Mapped[str] = mapped_column(String(120), default="organization")
    policy: Mapped[str] = mapped_column(String(80), default="scoped")
    status: Mapped[str] = mapped_column(String(32), default="enabled")
    config_json: Mapped[str] = mapped_column(Text, default="{}")

class MarketplaceTemplate(Base, TimestampMixin):
    __tablename__ = "marketplace_templates"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(220))
    template_type: Mapped[str] = mapped_column(String(64), default="employee")
    publisher: Mapped[str] = mapped_column(String(160), default="Nova")
    version: Mapped[str] = mapped_column(String(40), default="1.0")
    manifest_json: Mapped[str] = mapped_column(Text, default="{}")
    price_monthly: Mapped[float] = mapped_column(Float, default=0)
    status: Mapped[str] = mapped_column(String(32), default="draft")
    installs: Mapped[int] = mapped_column(Integer, default=0)

class Subscription(Base, TimestampMixin):
    __tablename__ = "subscriptions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    plan: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(32), default="active")
    mrr: Mapped[float] = mapped_column(Float, default=0)
    ai_cost: Mapped[float] = mapped_column(Float, default=0)
    usage_percent: Mapped[int] = mapped_column(Integer, default=0)
    renewal_date: Mapped[str] = mapped_column(String(40), default="")

class OrganizationSetting(Base, TimestampMixin):
    __tablename__ = "organization_settings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    key: Mapped[str] = mapped_column(String(160), index=True)
    value: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(80), default="general")

class RoleBinding(Base, TimestampMixin):
    __tablename__ = "role_bindings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id"), index=True)
    role: Mapped[str] = mapped_column(String(80), default="member")
    scope_type: Mapped[str] = mapped_column(String(64), default="organization")
    scope_id: Mapped[str] = mapped_column(String(120), default="")

class PermissionPolicy(Base, TimestampMixin):
    __tablename__ = "permission_policies"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    key: Mapped[str] = mapped_column(String(120), index=True)
    action: Mapped[str] = mapped_column(String(180))
    minimum_role: Mapped[str] = mapped_column(String(80), default="member")
    requires_approval: Mapped[bool] = mapped_column(Boolean, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)