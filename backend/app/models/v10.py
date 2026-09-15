from datetime import datetime
from sqlalchemy import String, Integer, DateTime, ForeignKey, Text, Float, Boolean
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base


class CompanyEvent(Base):
    __tablename__ = "company_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"), nullable=True, index=True)
    event_type: Mapped[str] = mapped_column(String(180), index=True)
    source: Mapped[str] = mapped_column(String(120), default="company")
    aggregate_type: Mapped[str] = mapped_column(String(80), default="")
    aggregate_id: Mapped[str] = mapped_column(String(160), default="")
    correlation_id: Mapped[str] = mapped_column(String(160), default="", index=True)
    causation_id: Mapped[str] = mapped_column(String(160), default="")
    actor_member_id: Mapped[int | None] = mapped_column(ForeignKey("members.id"), nullable=True)
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    error: Mapped[str] = mapped_column(Text, default="")
    occurred_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class EventTrigger(Base):
    __tablename__ = "event_triggers"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(180))
    event_pattern: Mapped[str] = mapped_column(String(180), default="*")
    condition_json: Mapped[str] = mapped_column(Text, default="{}")
    action_type: Mapped[str] = mapped_column(String(80), default="message")
    action_json: Mapped[str] = mapped_column(Text, default="{}")
    cooldown_seconds: Mapped[int] = mapped_column(Integer, default=0)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_fired_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class TriggerExecution(Base):
    __tablename__ = "trigger_executions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    trigger_id: Mapped[int] = mapped_column(ForeignKey("event_triggers.id"), index=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("company_events.id"), index=True)
    status: Mapped[str] = mapped_column(String(32), default="completed", index=True)
    result_type: Mapped[str] = mapped_column(String(80), default="")
    result_id: Mapped[str] = mapped_column(String(160), default="")
    result_json: Mapped[str] = mapped_column(Text, default="{}")
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class AgentMessage(Base):
    __tablename__ = "agent_messages"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"), nullable=True, index=True)
    thread_key: Mapped[str] = mapped_column(String(180), default="", index=True)
    sender_member_id: Mapped[int | None] = mapped_column(ForeignKey("members.id"), nullable=True, index=True)
    recipient_member_id: Mapped[int | None] = mapped_column(ForeignKey("members.id"), nullable=True, index=True)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id"), nullable=True, index=True)
    artifact_id: Mapped[int | None] = mapped_column(ForeignKey("artifacts.id"), nullable=True, index=True)
    message_type: Mapped[str] = mapped_column(String(48), default="message")
    subject: Mapped[str] = mapped_column(String(220), default="")
    content: Mapped[str] = mapped_column(Text)
    context_json: Mapped[str] = mapped_column(Text, default="{}")
    priority: Mapped[str] = mapped_column(String(24), default="normal")
    status: Mapped[str] = mapped_column(String(32), default="sent", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Artifact(Base):
    __tablename__ = "artifacts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"), nullable=True, index=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), nullable=True, index=True)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id"), nullable=True, index=True)
    created_by_member_id: Mapped[int | None] = mapped_column(ForeignKey("members.id"), nullable=True)
    created_by_agent_id: Mapped[int | None] = mapped_column(ForeignKey("agents.id"), nullable=True)
    runtime_run_id: Mapped[str] = mapped_column(String(180), default="", index=True)
    bundle_key: Mapped[str] = mapped_column(String(180), default="", index=True)
    logical_path: Mapped[str] = mapped_column(String(500), default="")
    name: Mapped[str] = mapped_column(String(220))
    artifact_type: Mapped[str] = mapped_column(String(64), default="deliverable")
    mime_type: Mapped[str] = mapped_column(String(120), default="text/plain")
    storage_backend: Mapped[str] = mapped_column(String(48), default="inline")
    uri: Mapped[str] = mapped_column(String(1000), default="")
    content_text: Mapped[str] = mapped_column(Text, default="")
    content_sha256: Mapped[str] = mapped_column(String(64), default="", index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    parent_artifact_id: Mapped[int | None] = mapped_column(ForeignKey("artifacts.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="ready", index=True)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ArtifactHandoff(Base):
    __tablename__ = "artifact_handoffs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    artifact_id: Mapped[int] = mapped_column(ForeignKey("artifacts.id"), index=True)
    from_member_id: Mapped[int | None] = mapped_column(ForeignKey("members.id"), nullable=True)
    to_member_id: Mapped[int] = mapped_column(ForeignKey("members.id"), index=True)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id"), nullable=True, index=True)
    purpose: Mapped[str] = mapped_column(String(80), default="continue_work")
    instructions: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ArtifactEvaluation(Base):
    __tablename__ = "artifact_evaluations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    artifact_id: Mapped[int] = mapped_column(ForeignKey("artifacts.id"), index=True)
    evaluator_member_id: Mapped[int | None] = mapped_column(ForeignKey("members.id"), nullable=True)
    evaluator_agent_id: Mapped[int | None] = mapped_column(ForeignKey("agents.id"), nullable=True)
    rubric_json: Mapped[str] = mapped_column(Text, default="{}")
    score: Mapped[float] = mapped_column(Float, default=0)
    verdict: Mapped[str] = mapped_column(String(32), default="review", index=True)
    findings_json: Mapped[str] = mapped_column(Text, default="[]")
    status: Mapped[str] = mapped_column(String(32), default="completed")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class SLAProfile(Base):
    __tablename__ = "sla_profiles"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(180))
    resource_type: Mapped[str] = mapped_column(String(64), default="task")
    priority: Mapped[str] = mapped_column(String(24), default="*")
    response_minutes: Mapped[int] = mapped_column(Integer, default=60)
    completion_minutes: Mapped[int] = mapped_column(Integer, default=1440)
    escalation_after_minutes: Mapped[int] = mapped_column(Integer, default=30)
    escalation_target_member_id: Mapped[int | None] = mapped_column(ForeignKey("members.id"), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class SLAIncident(Base):
    __tablename__ = "sla_incidents"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("sla_profiles.id"), index=True)
    resource_type: Mapped[str] = mapped_column(String(64), index=True)
    resource_id: Mapped[str] = mapped_column(String(160), index=True)
    breach_type: Mapped[str] = mapped_column(String(48), default="completion")
    severity: Mapped[str] = mapped_column(String(24), default="medium")
    status: Mapped[str] = mapped_column(String(32), default="open", index=True)
    summary: Mapped[str] = mapped_column(Text, default="")
    breached_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    escalated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class DecisionLoop(Base):
    __tablename__ = "decision_loops"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(180), default="Nina Continuous Loop")
    mode: Mapped[str] = mapped_column(String(32), default="supervised")
    interval_seconds: Mapped[int] = mapped_column(Integer, default=60)
    policy_json: Mapped[str] = mapped_column(Text, default="{}")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_tick_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    next_tick_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class DecisionLoopRun(Base):
    __tablename__ = "decision_loop_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    loop_id: Mapped[int] = mapped_column(ForeignKey("decision_loops.id"), index=True)
    status: Mapped[str] = mapped_column(String(32), default="completed", index=True)
    snapshot_json: Mapped[str] = mapped_column(Text, default="{}")
    decisions_json: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class SimulationScenario(Base):
    __tablename__ = "simulation_scenarios"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(180))
    description: Mapped[str] = mapped_column(Text, default="")
    assumptions_json: Mapped[str] = mapped_column(Text, default="{}")
    status: Mapped[str] = mapped_column(String(32), default="draft")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class SimulationRun(Base):
    __tablename__ = "simulation_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    scenario_id: Mapped[int] = mapped_column(ForeignKey("simulation_scenarios.id"), index=True)
    status: Mapped[str] = mapped_column(String(32), default="completed", index=True)
    input_snapshot_json: Mapped[str] = mapped_column(Text, default="{}")
    result_json: Mapped[str] = mapped_column(Text, default="{}")
    score: Mapped[float] = mapped_column(Float, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
