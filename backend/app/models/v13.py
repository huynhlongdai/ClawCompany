from datetime import datetime
from sqlalchemy import String, Integer, DateTime, ForeignKey, Text, Float, Boolean, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base


class WorkspaceGatewaySession(Base):
    __tablename__ = "workspace_gateway_sessions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("dev_workspaces.id"), index=True)
    member_id: Mapped[int | None] = mapped_column(ForeignKey("members.id"), nullable=True, index=True)
    agent_id: Mapped[int | None] = mapped_column(ForeignKey("agents.id"), nullable=True, index=True)
    provider: Mapped[str] = mapped_column(String(64), default="openclaw", index=True)
    provider_session_id: Mapped[str] = mapped_column(String(240), default="", index=True)
    session_key: Mapped[str] = mapped_column(String(180), unique=True, index=True)
    capabilities_json: Mapped[str] = mapped_column(Text, default="[]")
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class WorkspaceGatewayOperation(Base):
    __tablename__ = "workspace_gateway_operations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("workspace_gateway_sessions.id"), index=True)
    operation_type: Mapped[str] = mapped_column(String(48), index=True)
    logical_path: Mapped[str] = mapped_column(String(700), default="")
    artifact_id: Mapped[int | None] = mapped_column(ForeignKey("artifacts.id"), nullable=True, index=True)
    request_json: Mapped[str] = mapped_column(Text, default="{}")
    response_json: Mapped[str] = mapped_column(Text, default="{}")
    status: Mapped[str] = mapped_column(String(32), default="completed", index=True)
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class CICDPipelineGraph(Base):
    __tablename__ = "cicd_pipeline_graphs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"), nullable=True, index=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), nullable=True, index=True)
    repository_id: Mapped[int] = mapped_column(ForeignKey("repositories.id"), index=True)
    name: Mapped[str] = mapped_column(String(180))
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(32), default="draft", index=True)
    trigger_json: Mapped[str] = mapped_column(Text, default="{}")
    created_by_member_id: Mapped[int | None] = mapped_column(ForeignKey("members.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class CICDNode(Base):
    __tablename__ = "cicd_nodes"
    __table_args__ = (UniqueConstraint("graph_id", "node_key", name="uq_cicd_node_graph_key"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    graph_id: Mapped[int] = mapped_column(ForeignKey("cicd_pipeline_graphs.id"), index=True)
    node_key: Mapped[str] = mapped_column(String(120), index=True)
    node_type: Mapped[str] = mapped_column(String(48), default="noop", index=True)
    name: Mapped[str] = mapped_column(String(180))
    config_json: Mapped[str] = mapped_column(Text, default="{}")
    required: Mapped[bool] = mapped_column(Boolean, default=True)
    order_hint: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class CICDEdge(Base):
    __tablename__ = "cicd_edges"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    graph_id: Mapped[int] = mapped_column(ForeignKey("cicd_pipeline_graphs.id"), index=True)
    from_node_id: Mapped[int] = mapped_column(ForeignKey("cicd_nodes.id"), index=True)
    to_node_id: Mapped[int] = mapped_column(ForeignKey("cicd_nodes.id"), index=True)
    condition_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class CICDRun(Base):
    __tablename__ = "cicd_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    graph_id: Mapped[int] = mapped_column(ForeignKey("cicd_pipeline_graphs.id"), index=True)
    repository_id: Mapped[int] = mapped_column(ForeignKey("repositories.id"), index=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), nullable=True, index=True)
    release_id: Mapped[int | None] = mapped_column(ForeignKey("releases.id"), nullable=True, index=True)
    initiated_by_member_id: Mapped[int | None] = mapped_column(ForeignKey("members.id"), nullable=True)
    initiated_by_agent_id: Mapped[int | None] = mapped_column(ForeignKey("agents.id"), nullable=True)
    ref: Mapped[str] = mapped_column(String(180), default="main")
    commit_sha: Mapped[str] = mapped_column(String(80), default="", index=True)
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    correlation_id: Mapped[str] = mapped_column(String(80), default="", index=True)
    summary_json: Mapped[str] = mapped_column(Text, default="{}")
    error: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class CICDNodeRun(Base):
    __tablename__ = "cicd_node_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    ci_run_id: Mapped[int] = mapped_column(ForeignKey("cicd_runs.id"), index=True)
    node_id: Mapped[int] = mapped_column(ForeignKey("cicd_nodes.id"), index=True)
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    sandbox_run_id: Mapped[int | None] = mapped_column(ForeignKey("sandbox_runs.id"), nullable=True, index=True)
    output_json: Mapped[str] = mapped_column(Text, default="{}")
    error: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class BuildRecord(Base):
    __tablename__ = "build_records"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    repository_id: Mapped[int] = mapped_column(ForeignKey("repositories.id"), index=True)
    ci_run_id: Mapped[int | None] = mapped_column(ForeignKey("cicd_runs.id"), nullable=True, index=True)
    release_id: Mapped[int | None] = mapped_column(ForeignKey("releases.id"), nullable=True, index=True)
    commit_sha: Mapped[str] = mapped_column(String(80), index=True)
    status: Mapped[str] = mapped_column(String(32), default="building", index=True)
    source_digest: Mapped[str] = mapped_column(String(64), default="", index=True)
    manifest_artifact_id: Mapped[int | None] = mapped_column(ForeignKey("artifacts.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class SBOMDocument(Base):
    __tablename__ = "sbom_documents"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    build_id: Mapped[int] = mapped_column(ForeignKey("build_records.id"), index=True)
    format: Mapped[str] = mapped_column(String(32), default="spdx-json")
    spec_version: Mapped[str] = mapped_column(String(32), default="SPDX-2.3")
    artifact_id: Mapped[int] = mapped_column(ForeignKey("artifacts.id"), index=True)
    file_count: Mapped[int] = mapped_column(Integer, default=0)
    package_count: Mapped[int] = mapped_column(Integer, default=0)
    digest: Mapped[str] = mapped_column(String(64), default="", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class BuildProvenance(Base):
    __tablename__ = "build_provenance"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    build_id: Mapped[int] = mapped_column(ForeignKey("build_records.id"), index=True)
    artifact_id: Mapped[int] = mapped_column(ForeignKey("artifacts.id"), index=True)
    builder_id: Mapped[str] = mapped_column(String(240), default="clawcompany://builder/v13")
    predicate_type: Mapped[str] = mapped_column(String(240), default="https://slsa.dev/provenance/v1")
    invocation_json: Mapped[str] = mapped_column(Text, default="{}")
    materials_json: Mapped[str] = mapped_column(Text, default="[]")
    subject_json: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class SecurityReview(Base):
    __tablename__ = "security_reviews"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    repository_id: Mapped[int] = mapped_column(ForeignKey("repositories.id"), index=True)
    ci_run_id: Mapped[int | None] = mapped_column(ForeignKey("cicd_runs.id"), nullable=True, index=True)
    build_id: Mapped[int | None] = mapped_column(ForeignKey("build_records.id"), nullable=True, index=True)
    reviewer_member_id: Mapped[int | None] = mapped_column(ForeignKey("members.id"), nullable=True)
    reviewer_agent_id: Mapped[int | None] = mapped_column(ForeignKey("agents.id"), nullable=True)
    commit_sha: Mapped[str] = mapped_column(String(80), default="", index=True)
    status: Mapped[str] = mapped_column(String(32), default="running", index=True)
    verdict: Mapped[str] = mapped_column(String(32), default="review", index=True)
    score: Mapped[float] = mapped_column(Float, default=100)
    summary: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class SecurityFinding(Base):
    __tablename__ = "security_findings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    review_id: Mapped[int] = mapped_column(ForeignKey("security_reviews.id"), index=True)
    severity: Mapped[str] = mapped_column(String(24), default="medium", index=True)
    category: Mapped[str] = mapped_column(String(64), default="code_security")
    rule_id: Mapped[str] = mapped_column(String(120), index=True)
    path: Mapped[str] = mapped_column(String(700), default="")
    line: Mapped[int | None] = mapped_column(Integer, nullable=True)
    title: Mapped[str] = mapped_column(String(240))
    evidence: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="open", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class PreviewRoute(Base):
    __tablename__ = "preview_routes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    preview_environment_id: Mapped[int] = mapped_column(ForeignKey("preview_environments.id"), index=True)
    hostname: Mapped[str] = mapped_column(String(300), default="", index=True)
    slug: Mapped[str] = mapped_column(String(180), index=True)
    path_prefix: Mapped[str] = mapped_column(String(500), default="/")
    target_url: Mapped[str] = mapped_column(String(1000))
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class DeploymentHealthPolicy(Base):
    __tablename__ = "deployment_health_policies"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    environment_id: Mapped[int] = mapped_column(ForeignKey("deployment_environments.id"), index=True)
    name: Mapped[str] = mapped_column(String(180))
    check_type: Mapped[str] = mapped_column(String(48), default="filesystem_marker")
    target: Mapped[str] = mapped_column(String(1000), default="")
    expected_status: Mapped[int] = mapped_column(Integer, default=200)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=5)
    success_threshold: Mapped[int] = mapped_column(Integer, default=1)
    failure_threshold: Mapped[int] = mapped_column(Integer, default=1)
    auto_rollback: Mapped[bool] = mapped_column(Boolean, default=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class DeploymentHealthRun(Base):
    __tablename__ = "deployment_health_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    policy_id: Mapped[int] = mapped_column(ForeignKey("deployment_health_policies.id"), index=True)
    deployment_id: Mapped[int] = mapped_column(ForeignKey("deployments.id"), index=True)
    status: Mapped[str] = mapped_column(String(32), default="running", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    successes: Mapped[int] = mapped_column(Integer, default=0)
    failures: Mapped[int] = mapped_column(Integer, default=0)
    detail_json: Mapped[str] = mapped_column(Text, default="{}")
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class DeploymentStrategyRun(Base):
    __tablename__ = "deployment_strategy_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    environment_id: Mapped[int] = mapped_column(ForeignKey("deployment_environments.id"), index=True)
    release_id: Mapped[int] = mapped_column(ForeignKey("releases.id"), index=True)
    deployment_id: Mapped[int | None] = mapped_column(ForeignKey("deployments.id"), nullable=True, index=True)
    health_run_id: Mapped[int | None] = mapped_column(ForeignKey("deployment_health_runs.id"), nullable=True)
    rollback_id: Mapped[int | None] = mapped_column(ForeignKey("deployment_rollbacks.id"), nullable=True)
    requested_by_member_id: Mapped[int | None] = mapped_column(ForeignKey("members.id"), nullable=True)
    strategy: Mapped[str] = mapped_column(String(32), default="rolling", index=True)
    traffic_percent: Mapped[int] = mapped_column(Integer, default=100)
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    phase_json: Mapped[str] = mapped_column(Text, default="{}")
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ReleaseManagerRun(Base):
    __tablename__ = "release_manager_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    release_id: Mapped[int] = mapped_column(ForeignKey("releases.id"), index=True)
    ci_run_id: Mapped[int | None] = mapped_column(ForeignKey("cicd_runs.id"), nullable=True, index=True)
    security_review_id: Mapped[int | None] = mapped_column(ForeignKey("security_reviews.id"), nullable=True)
    strategy_run_id: Mapped[int | None] = mapped_column(ForeignKey("deployment_strategy_runs.id"), nullable=True)
    requested_by_member_id: Mapped[int | None] = mapped_column(ForeignKey("members.id"), nullable=True)
    requested_by_agent_id: Mapped[int | None] = mapped_column(ForeignKey("agents.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="completed", index=True)
    decision: Mapped[str] = mapped_column(String(32), default="hold", index=True)
    reason: Mapped[str] = mapped_column(Text, default="")
    evidence_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class EngineeringInitiative(Base):
    __tablename__ = "engineering_initiatives"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"), nullable=True, index=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), nullable=True, index=True)
    repository_id: Mapped[int] = mapped_column(ForeignKey("repositories.id"), index=True)
    executive_goal_id: Mapped[int | None] = mapped_column(ForeignKey("executive_goals.id"), nullable=True, index=True)
    pipeline_graph_id: Mapped[int] = mapped_column(ForeignKey("cicd_pipeline_graphs.id"), index=True)
    desired_environment_id: Mapped[int | None] = mapped_column(ForeignKey("deployment_environments.id"), nullable=True, index=True)
    nina_member_id: Mapped[int | None] = mapped_column(ForeignKey("members.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(220))
    objective: Mapped[str] = mapped_column(Text, default="")
    ref: Mapped[str] = mapped_column(String(180), default="main")
    release_version: Mapped[str] = mapped_column(String(120), default="")
    deployment_strategy: Mapped[str] = mapped_column(String(32), default="rolling")
    status: Mapped[str] = mapped_column(String(32), default="planned", index=True)
    current_ci_run_id: Mapped[int | None] = mapped_column(ForeignKey("cicd_runs.id"), nullable=True)
    current_release_id: Mapped[int | None] = mapped_column(ForeignKey("releases.id"), nullable=True)
    release_manager_run_id: Mapped[int | None] = mapped_column(ForeignKey("release_manager_runs.id"), nullable=True)
    result_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
