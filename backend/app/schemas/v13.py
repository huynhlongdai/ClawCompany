from datetime import datetime
from pydantic import BaseModel, Field


class WorkspaceGatewaySessionCreate(BaseModel):
    workspace_id: int
    member_id: int | None = None
    agent_id: int | None = None
    provider: str = Field(default="openclaw", max_length=64)
    provider_session_id: str = Field(default="", max_length=240)
    capabilities: list[str] = Field(default_factory=lambda: ["read", "write", "snapshot"])
    ttl_minutes: int = Field(default=120, ge=5, le=10080)


class WorkspaceGatewayWrite(BaseModel):
    logical_path: str = Field(min_length=1, max_length=700)
    content: str


class WorkspaceGatewaySnapshot(BaseModel):
    bundle_key: str = Field(min_length=1, max_length=180)
    artifact_type: str = Field(default="source_code", max_length=64)
    include_globs: list[str] = Field(default_factory=list)
    max_files: int = Field(default=250, ge=1, le=2000)


class CICDNodeInput(BaseModel):
    key: str = Field(min_length=1, max_length=120)
    type: str = Field(default="noop", pattern="^(noop|gate|sandbox|security|evidence|release)$")
    name: str = Field(min_length=1, max_length=180)
    config: dict = Field(default_factory=dict)
    required: bool = True
    order_hint: int = 0


class CICDEdgeInput(BaseModel):
    source: str = Field(min_length=1, max_length=120)
    target: str = Field(min_length=1, max_length=120)
    condition: dict = Field(default_factory=dict)


class CICDGraphCreate(BaseModel):
    organization_id: int
    company_id: int | None = None
    project_id: int | None = None
    repository_id: int
    name: str = Field(min_length=1, max_length=180)
    trigger: dict = Field(default_factory=dict)
    status: str = Field(default="active", pattern="^(draft|active|paused)$")
    nodes: list[CICDNodeInput] = Field(min_length=1)
    edges: list[CICDEdgeInput] = Field(default_factory=list)


class CICDRunCreate(BaseModel):
    graph_id: int
    ref: str = Field(default="main", max_length=180)
    commit_sha: str = Field(default="", max_length=80)
    initiated_by_member_id: int | None = None
    initiated_by_agent_id: int | None = None
    execute: bool = True


class BuildEvidenceCreate(BaseModel):
    repository_id: int
    commit_sha: str = Field(min_length=1, max_length=80)
    ci_run_id: int | None = None
    release_id: int | None = None
    producer_member_id: int | None = None
    producer_agent_id: int | None = None


class SecurityReviewCreate(BaseModel):
    repository_id: int
    commit_sha: str = Field(min_length=1, max_length=80)
    ci_run_id: int | None = None
    build_id: int | None = None
    reviewer_member_id: int | None = None
    reviewer_agent_id: int | None = None
    block_on: list[str] = Field(default_factory=lambda: ["critical", "high"])


class PreviewRouteCreate(BaseModel):
    preview_environment_id: int
    hostname: str = Field(default="", max_length=300)
    slug: str = Field(min_length=1, max_length=180)
    path_prefix: str = Field(default="/", max_length=500)
    target_url: str = Field(min_length=1, max_length=1000)
    expires_at: datetime | None = None


class HealthPolicyCreate(BaseModel):
    environment_id: int
    name: str = Field(min_length=1, max_length=180)
    check_type: str = Field(default="filesystem_marker", pattern="^(filesystem_marker|http)$")
    target: str = Field(default="", max_length=1000)
    expected_status: int = Field(default=200, ge=100, le=599)
    timeout_seconds: int = Field(default=5, ge=1, le=60)
    success_threshold: int = Field(default=1, ge=1, le=20)
    failure_threshold: int = Field(default=1, ge=1, le=20)
    auto_rollback: bool = True


class ProgressiveDeployRequest(BaseModel):
    release_id: int
    environment_id: int
    strategy: str = Field(default="rolling", pattern="^(rolling|blue_green|canary)$")
    health_policy_id: int | None = None
    traffic_percent: int = Field(default=10, ge=1, le=100)
    requested_by_member_id: int | None = None


class ReleaseManagerAssessRequest(BaseModel):
    release_id: int
    ci_run_id: int | None = None
    security_review_id: int | None = None
    strategy_run_id: int | None = None
    requested_by_member_id: int | None = None
    requested_by_agent_id: int | None = None


class EngineeringInitiativeCreate(BaseModel):
    organization_id: int
    company_id: int | None = None
    project_id: int | None = None
    repository_id: int
    executive_goal_id: int | None = None
    pipeline_graph_id: int
    desired_environment_id: int | None = None
    nina_member_id: int | None = None
    title: str = Field(min_length=1, max_length=220)
    objective: str = ""
    ref: str = Field(default="main", max_length=180)
    release_version: str = Field(default="", max_length=120)
    deployment_strategy: str = Field(default="rolling", pattern="^(rolling|blue_green|canary)$")


class EngineeringInitiativeRun(BaseModel):
    execute_deployment: bool = True
    health_policy_id: int | None = None
