from datetime import datetime
from sqlalchemy import String, Integer, DateTime, ForeignKey, Text, Float, Boolean
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base


class AutonomyPolicy(Base):
    __tablename__ = "autonomy_policies"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"), nullable=True, index=True)
    mode: Mapped[str] = mapped_column(String(32), default="supervised")  # manual | supervised | autonomous
    max_concurrent_runs: Mapped[int] = mapped_column(Integer, default=5)
    retry_limit: Mapped[int] = mapped_column(Integer, default=2)
    max_auto_risk: Mapped[str] = mapped_column(String(24), default="low")
    daily_budget_limit: Mapped[float] = mapped_column(Float, default=100.0)
    per_action_limit: Mapped[float] = mapped_column(Float, default=25.0)
    pause_on_high_incident: Mapped[bool] = mapped_column(Boolean, default=True)
    require_approval_for_external_publish: Mapped[bool] = mapped_column(Boolean, default=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ExecutiveGoal(Base):
    __tablename__ = "executive_goals"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"), nullable=True, index=True)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(220))
    objective: Mapped[str] = mapped_column(Text)
    expected_outcome: Mapped[str] = mapped_column(Text, default="")
    priority: Mapped[str] = mapped_column(String(24), default="high")
    risk: Mapped[str] = mapped_column(String(24), default="medium")
    autonomy_mode: Mapped[str] = mapped_column(String(32), default="inherit")
    status: Mapped[str] = mapped_column(String(32), default="draft", index=True)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    execution_plan_id: Mapped[int | None] = mapped_column(ForeignKey("nina_execution_plans.id"), nullable=True, index=True)
    deadline: Mapped[str] = mapped_column(String(48), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class BudgetEnvelope(Base):
    __tablename__ = "budget_envelopes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"), nullable=True, index=True)
    goal_id: Mapped[int | None] = mapped_column(ForeignKey("executive_goals.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(180))
    currency: Mapped[str] = mapped_column(String(12), default="USD")
    amount_limit: Mapped[float] = mapped_column(Float, default=0)
    amount_reserved: Mapped[float] = mapped_column(Float, default=0)
    amount_spent: Mapped[float] = mapped_column(Float, default=0)
    status: Mapped[str] = mapped_column(String(32), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class BudgetLedgerEntry(Base):
    __tablename__ = "budget_ledger_entries"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    budget_id: Mapped[int] = mapped_column(ForeignKey("budget_envelopes.id"), index=True)
    entry_type: Mapped[str] = mapped_column(String(32), default="spend")  # reserve|spend|release|credit
    amount: Mapped[float] = mapped_column(Float)
    source_type: Mapped[str] = mapped_column(String(64), default="")
    source_id: Mapped[str] = mapped_column(String(120), default="")
    memo: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class OperatingCycle(Base):
    __tablename__ = "operating_cycles"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    goal_id: Mapped[int] = mapped_column(ForeignKey("executive_goals.id"), index=True)
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    mode: Mapped[str] = mapped_column(String(32), default="supervised")
    snapshot_json: Mapped[str] = mapped_column(Text, default="{}")
    decisions_json: Mapped[str] = mapped_column(Text, default="[]")
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class DelegationAssignment(Base):
    __tablename__ = "delegation_assignments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    cycle_id: Mapped[int] = mapped_column(ForeignKey("operating_cycles.id"), index=True)
    goal_id: Mapped[int] = mapped_column(ForeignKey("executive_goals.id"), index=True)
    plan_step_id: Mapped[int | None] = mapped_column(ForeignKey("nina_plan_steps.id"), nullable=True, index=True)
    parent_member_id: Mapped[int | None] = mapped_column(ForeignKey("members.id"), nullable=True)
    assignee_member_id: Mapped[int | None] = mapped_column(ForeignKey("members.id"), nullable=True, index=True)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id"), nullable=True, index=True)
    depth: Mapped[int] = mapped_column(Integer, default=0)
    instruction: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    runtime_run_id: Mapped[str] = mapped_column(String(180), default="", index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=2)
    estimated_cost: Mapped[float] = mapped_column(Float, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class RecoveryIncident(Base):
    __tablename__ = "recovery_incidents"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    goal_id: Mapped[int | None] = mapped_column(ForeignKey("executive_goals.id"), nullable=True, index=True)
    cycle_id: Mapped[int | None] = mapped_column(ForeignKey("operating_cycles.id"), nullable=True, index=True)
    assignment_id: Mapped[int | None] = mapped_column(ForeignKey("delegation_assignments.id"), nullable=True, index=True)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id"), nullable=True)
    agent_id: Mapped[int | None] = mapped_column(ForeignKey("agents.id"), nullable=True)
    runtime_run_id: Mapped[str] = mapped_column(String(180), default="", index=True)
    incident_type: Mapped[str] = mapped_column(String(80), default="runtime_failure")
    severity: Mapped[str] = mapped_column(String(24), default="medium")
    status: Mapped[str] = mapped_column(String(32), default="open", index=True)
    error: Mapped[str] = mapped_column(Text, default="")
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, default=2)
    resolution: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class OrganizationMemory(Base):
    __tablename__ = "organization_memories"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"), nullable=True, index=True)
    department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id"), nullable=True, index=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), nullable=True, index=True)
    agent_id: Mapped[int | None] = mapped_column(ForeignKey("agents.id"), nullable=True, index=True)
    memory_type: Mapped[str] = mapped_column(String(48), default="fact")
    content: Mapped[str] = mapped_column(Text)
    source_type: Mapped[str] = mapped_column(String(64), default="manual")
    source_id: Mapped[str] = mapped_column(String(120), default="")
    importance: Mapped[int] = mapped_column(Integer, default=3)
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    tags_json: Mapped[str] = mapped_column(Text, default="[]")
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class RecurringOperation(Base):
    __tablename__ = "recurring_operations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    schedule: Mapped[str] = mapped_column(String(120), default="0 8 * * *")
    timezone: Mapped[str] = mapped_column(String(80), default="UTC")
    operation_type: Mapped[str] = mapped_column(String(64), default="nina_goal")
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_status: Mapped[str] = mapped_column(String(32), default="never")
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
