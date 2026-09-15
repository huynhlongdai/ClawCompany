from datetime import datetime
from sqlalchemy import String, Integer, DateTime, ForeignKey, Text, Float, Boolean, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base


class RunnerPool(Base):
    __tablename__ = "runner_pools"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(180))
    provider: Mapped[str] = mapped_column(String(48), default="remote")  # remote|kubernetes|firecracker|local
    capabilities_json: Mapped[str] = mapped_column(Text, default="[]")
    selectors_json: Mapped[str] = mapped_column(Text, default="{}")
    max_concurrency: Mapped[int] = mapped_column(Integer, default=4)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class RunnerNode(Base):
    __tablename__ = "runner_nodes"
    __table_args__ = (UniqueConstraint("organization_id", "node_key", name="uq_runner_node_org_key"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    pool_id: Mapped[int] = mapped_column(ForeignKey("runner_pools.id"), index=True)
    node_key: Mapped[str] = mapped_column(String(180), index=True)
    provider: Mapped[str] = mapped_column(String(48), default="remote")
    endpoint: Mapped[str] = mapped_column(String(1000), default="")
    capabilities_json: Mapped[str] = mapped_column(Text, default="[]")
    labels_json: Mapped[str] = mapped_column(Text, default="{}")
    status: Mapped[str] = mapped_column(String(32), default="online", index=True)
    active_leases: Mapped[int] = mapped_column(Integer, default=0)
    capacity: Mapped[int] = mapped_column(Integer, default=1)
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class RunnerLease(Base):
    __tablename__ = "runner_leases"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    pool_id: Mapped[int] = mapped_column(ForeignKey("runner_pools.id"), index=True)
    runner_node_id: Mapped[int] = mapped_column(ForeignKey("runner_nodes.id"), index=True)
    member_id: Mapped[int | None] = mapped_column(ForeignKey("members.id"), nullable=True, index=True)
    agent_id: Mapped[int | None] = mapped_column(ForeignKey("agents.id"), nullable=True, index=True)
    workload_type: Mapped[str] = mapped_column(String(64), default="sandbox", index=True)
    workload_ref: Mapped[str] = mapped_column(String(180), default="", index=True)
    requested_capabilities_json: Mapped[str] = mapped_column(Text, default="[]")
    scopes_json: Mapped[str] = mapped_column(Text, default="[]")
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    released_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class RunnerJob(Base):
    __tablename__ = "runner_jobs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    lease_id: Mapped[int] = mapped_column(ForeignKey("runner_leases.id"), index=True)
    workspace_id: Mapped[int | None] = mapped_column(ForeignKey("dev_workspaces.id"), nullable=True, index=True)
    sandbox_run_id: Mapped[int | None] = mapped_column(ForeignKey("sandbox_runs.id"), nullable=True, index=True)
    job_type: Mapped[str] = mapped_column(String(64), default="command", index=True)
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    attempt: Mapped[int] = mapped_column(Integer, default=0)
    result_json: Mapped[str] = mapped_column(Text, default="{}")
    error: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class WorkloadIdentityToken(Base):
    __tablename__ = "workload_identity_tokens"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    lease_id: Mapped[int] = mapped_column(ForeignKey("runner_leases.id"), index=True)
    member_id: Mapped[int | None] = mapped_column(ForeignKey("members.id"), nullable=True, index=True)
    agent_id: Mapped[int | None] = mapped_column(ForeignKey("agents.id"), nullable=True, index=True)
    jti: Mapped[str] = mapped_column(String(96), unique=True, index=True)
    issuer: Mapped[str] = mapped_column(String(500))
    audience: Mapped[str] = mapped_column(String(300))
    scopes_json: Mapped[str] = mapped_column(Text, default="[]")
    signing_alg: Mapped[str] = mapped_column(String(24), default="HS256")
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class EvidenceSignature(Base):
    __tablename__ = "evidence_signatures"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    artifact_id: Mapped[int] = mapped_column(ForeignKey("artifacts.id"), index=True)
    build_id: Mapped[int | None] = mapped_column(ForeignKey("build_records.id"), nullable=True, index=True)
    signature_type: Mapped[str] = mapped_column(String(48), default="hmac-sha256", index=True)
    signer: Mapped[str] = mapped_column(String(300), default="clawcompany://signer/local")
    key_ref: Mapped[str] = mapped_column(String(700), default="")
    subject_digest: Mapped[str] = mapped_column(String(64), index=True)
    signature: Mapped[str] = mapped_column(Text, default="")
    certificate_json: Mapped[str] = mapped_column(Text, default="{}")
    verified: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ScannerProvider(Base):
    __tablename__ = "scanner_providers"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(180))
    provider_type: Mapped[str] = mapped_column(String(64), default="builtin", index=True)  # builtin|semgrep|trivy|osv
    executable: Mapped[str] = mapped_column(String(300), default="")
    config_json: Mapped[str] = mapped_column(Text, default="{}")
    block_on: Mapped[str] = mapped_column(String(24), default="high")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ExternalScanRun(Base):
    __tablename__ = "external_scan_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    provider_id: Mapped[int] = mapped_column(ForeignKey("scanner_providers.id"), index=True)
    repository_id: Mapped[int] = mapped_column(ForeignKey("repositories.id"), index=True)
    ci_run_id: Mapped[int | None] = mapped_column(ForeignKey("cicd_runs.id"), nullable=True, index=True)
    commit_sha: Mapped[str] = mapped_column(String(80), index=True)
    status: Mapped[str] = mapped_column(String(32), default="running", index=True)
    verdict: Mapped[str] = mapped_column(String(32), default="review", index=True)
    findings_json: Mapped[str] = mapped_column(Text, default="[]")
    summary_json: Mapped[str] = mapped_column(Text, default="{}")
    exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class TrafficRouter(Base):
    __tablename__ = "traffic_routers"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    environment_id: Mapped[int] = mapped_column(ForeignKey("deployment_environments.id"), index=True)
    name: Mapped[str] = mapped_column(String(180))
    provider: Mapped[str] = mapped_column(String(64), default="database", index=True)  # database|file|kubernetes
    config_json: Mapped[str] = mapped_column(Text, default="{}")
    current_weights_json: Mapped[str] = mapped_column(Text, default="{}")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class TrafficShift(Base):
    __tablename__ = "traffic_shifts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    router_id: Mapped[int] = mapped_column(ForeignKey("traffic_routers.id"), index=True)
    strategy_run_id: Mapped[int | None] = mapped_column(ForeignKey("deployment_strategy_runs.id"), nullable=True, index=True)
    release_id: Mapped[int] = mapped_column(ForeignKey("releases.id"), index=True)
    from_release_id: Mapped[int | None] = mapped_column(ForeignKey("releases.id"), nullable=True)
    from_weight: Mapped[int] = mapped_column(Integer, default=100)
    to_weight: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(32), default="applied", index=True)
    provider_ref: Mapped[str] = mapped_column(String(1000), default="")
    detail_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class TelemetryMetricSample(Base):
    __tablename__ = "telemetry_metric_samples"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    environment_id: Mapped[int | None] = mapped_column(ForeignKey("deployment_environments.id"), nullable=True, index=True)
    deployment_id: Mapped[int | None] = mapped_column(ForeignKey("deployments.id"), nullable=True, index=True)
    release_id: Mapped[int | None] = mapped_column(ForeignKey("releases.id"), nullable=True, index=True)
    metric_name: Mapped[str] = mapped_column(String(180), index=True)
    value: Mapped[float] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(48), default="")
    labels_json: Mapped[str] = mapped_column(Text, default="{}")
    observed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class SLODefinition(Base):
    __tablename__ = "slo_definitions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    environment_id: Mapped[int] = mapped_column(ForeignKey("deployment_environments.id"), index=True)
    name: Mapped[str] = mapped_column(String(180))
    metric_name: Mapped[str] = mapped_column(String(180), index=True)
    comparator: Mapped[str] = mapped_column(String(8), default="lte")  # lte|gte
    threshold: Mapped[float] = mapped_column(Float)
    window_minutes: Mapped[int] = mapped_column(Integer, default=5)
    min_samples: Mapped[int] = mapped_column(Integer, default=1)
    auto_incident: Mapped[bool] = mapped_column(Boolean, default=True)
    auto_rollback: Mapped[bool] = mapped_column(Boolean, default=True)
    severity: Mapped[str] = mapped_column(String(24), default="high")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class SLOEvaluation(Base):
    __tablename__ = "slo_evaluations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    slo_id: Mapped[int] = mapped_column(ForeignKey("slo_definitions.id"), index=True)
    deployment_id: Mapped[int | None] = mapped_column(ForeignKey("deployments.id"), nullable=True, index=True)
    release_id: Mapped[int | None] = mapped_column(ForeignKey("releases.id"), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(32), default="insufficient_data", index=True)
    sample_count: Mapped[int] = mapped_column(Integer, default=0)
    aggregate_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    threshold: Mapped[float] = mapped_column(Float)
    detail_json: Mapped[str] = mapped_column(Text, default="{}")
    evaluated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class Incident(Base):
    __tablename__ = "incidents"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"), nullable=True, index=True)
    environment_id: Mapped[int | None] = mapped_column(ForeignKey("deployment_environments.id"), nullable=True, index=True)
    deployment_id: Mapped[int | None] = mapped_column(ForeignKey("deployments.id"), nullable=True, index=True)
    release_id: Mapped[int | None] = mapped_column(ForeignKey("releases.id"), nullable=True, index=True)
    slo_evaluation_id: Mapped[int | None] = mapped_column(ForeignKey("slo_evaluations.id"), nullable=True, index=True)
    owner_member_id: Mapped[int | None] = mapped_column(ForeignKey("members.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(240))
    severity: Mapped[str] = mapped_column(String(24), default="high", index=True)
    status: Mapped[str] = mapped_column(String(32), default="open", index=True)
    source: Mapped[str] = mapped_column(String(64), default="slo")
    summary: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class IncidentEvent(Base):
    __tablename__ = "incident_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    incident_id: Mapped[int] = mapped_column(ForeignKey("incidents.id"), index=True)
    actor_member_id: Mapped[int | None] = mapped_column(ForeignKey("members.id"), nullable=True)
    actor_agent_id: Mapped[int | None] = mapped_column(ForeignKey("agents.id"), nullable=True)
    event_type: Mapped[str] = mapped_column(String(64), default="note", index=True)
    message: Mapped[str] = mapped_column(Text, default="")
    data_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class PortfolioObjective(Base):
    __tablename__ = "portfolio_objectives"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"), nullable=True, index=True)
    owner_member_id: Mapped[int | None] = mapped_column(ForeignKey("members.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(220))
    objective: Mapped[str] = mapped_column(Text, default="")
    priority: Mapped[str] = mapped_column(String(24), default="medium", index=True)
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    target_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class PortfolioReview(Base):
    __tablename__ = "portfolio_reviews"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    objective_id: Mapped[int | None] = mapped_column(ForeignKey("portfolio_objectives.id"), nullable=True, index=True)
    nina_member_id: Mapped[int | None] = mapped_column(ForeignKey("members.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="completed", index=True)
    health: Mapped[str] = mapped_column(String(32), default="green", index=True)
    summary: Mapped[str] = mapped_column(Text, default="")
    metrics_json: Mapped[str] = mapped_column(Text, default="{}")
    recommendations_json: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
