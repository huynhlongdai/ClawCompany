from datetime import datetime
from typing import Any
from pydantic import BaseModel, Field


class RunnerPoolCreate(BaseModel):
    organization_id: int
    company_id: int | None = None
    name: str
    provider: str = "remote"
    capabilities: list[str] = Field(default_factory=list)
    selectors: dict[str, Any] = Field(default_factory=dict)
    max_concurrency: int = 4


class RunnerNodeRegister(BaseModel):
    organization_id: int
    pool_id: int
    node_key: str
    provider: str = "remote"
    endpoint: str = ""
    capabilities: list[str] = Field(default_factory=list)
    labels: dict[str, Any] = Field(default_factory=dict)
    capacity: int = 1


class RunnerHeartbeat(BaseModel):
    status: str = "online"
    active_leases: int | None = None
    capabilities: list[str] | None = None


class RunnerLeaseRequest(BaseModel):
    organization_id: int
    pool_id: int
    member_id: int | None = None
    agent_id: int | None = None
    workload_type: str = "sandbox"
    workload_ref: str = ""
    required_capabilities: list[str] = Field(default_factory=list)
    scopes: list[str] = Field(default_factory=lambda: ["workspace:read", "workspace:write"])
    ttl_seconds: int = Field(default=600, ge=60, le=3600)


class RunnerJobCreate(BaseModel):
    lease_id: int
    workspace_id: int | None = None
    sandbox_run_id: int | None = None
    job_type: str = "command"
    payload: dict[str, Any] = Field(default_factory=dict)


class WorkloadTokenRequest(BaseModel):
    lease_id: int
    audience: str = "clawcompany-runner"
    ttl_seconds: int = Field(default=300, ge=60, le=900)


class EvidenceSignRequest(BaseModel):
    artifact_id: int
    build_id: int | None = None
    provider: str = "local_hmac"
    key_ref: str = "env:SUPPLY_CHAIN_SIGNING_KEY"


class EvidenceVerifyRequest(BaseModel):
    signature_id: int


class ScannerProviderCreate(BaseModel):
    organization_id: int
    name: str
    provider_type: str = "builtin"
    executable: str = ""
    config: dict[str, Any] = Field(default_factory=dict)
    block_on: str = "high"


class ScanRunCreate(BaseModel):
    provider_id: int
    repository_id: int
    commit_sha: str
    ci_run_id: int | None = None


class TrafficRouterCreate(BaseModel):
    organization_id: int
    environment_id: int
    name: str
    provider: str = "database"
    config: dict[str, Any] = Field(default_factory=dict)


class TrafficShiftRequest(BaseModel):
    router_id: int
    release_id: int
    from_release_id: int | None = None
    to_weight: int = Field(ge=0, le=100)
    strategy_run_id: int | None = None


class TelemetryIngest(BaseModel):
    organization_id: int
    environment_id: int | None = None
    deployment_id: int | None = None
    release_id: int | None = None
    metric_name: str
    value: float
    unit: str = ""
    labels: dict[str, Any] = Field(default_factory=dict)
    observed_at: datetime | None = None


class SLOCreate(BaseModel):
    organization_id: int
    environment_id: int
    name: str
    metric_name: str
    comparator: str = "lte"
    threshold: float
    window_minutes: int = Field(default=5, ge=1, le=1440)
    min_samples: int = Field(default=1, ge=1, le=100000)
    auto_incident: bool = True
    auto_rollback: bool = True
    severity: str = "high"


class SLOEvaluateRequest(BaseModel):
    deployment_id: int | None = None
    release_id: int | None = None


class IncidentCreate(BaseModel):
    organization_id: int
    company_id: int | None = None
    environment_id: int | None = None
    deployment_id: int | None = None
    release_id: int | None = None
    owner_member_id: int | None = None
    title: str
    severity: str = "high"
    source: str = "manual"
    summary: str = ""


class IncidentEventCreate(BaseModel):
    event_type: str = "note"
    message: str = ""
    data: dict[str, Any] = Field(default_factory=dict)


class IncidentStatusUpdate(BaseModel):
    status: str
    message: str = ""


class CanaryRunRequest(BaseModel):
    release_id: int
    environment_id: int
    router_id: int
    slo_ids: list[int] = Field(default_factory=list)
    steps: list[int] = Field(default_factory=lambda: [10, 25, 50, 100])
    requested_by_member_id: int | None = None


class PortfolioObjectiveCreate(BaseModel):
    organization_id: int
    company_id: int | None = None
    owner_member_id: int | None = None
    title: str
    objective: str = ""
    priority: str = "medium"
    targets: dict[str, Any] = Field(default_factory=dict)


class PortfolioReviewRequest(BaseModel):
    objective_id: int | None = None
    nina_member_id: int | None = None

class RunnerJobComplete(BaseModel):
    result: dict[str, Any] = Field(default_factory=dict)
    error: str = ""


class WorkloadTokenVerify(BaseModel):
    token: str
    audience: str = "clawcompany-runner"
