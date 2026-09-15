from datetime import datetime
from pydantic import BaseModel, Field


class RunnerTrustAuthorityCreate(BaseModel):
    organization_id: int
    name: str
    issuer_cn: str
    ca_cert_pem: str
    private_key_ref: str
    expires_at: datetime | None = None


class RunnerCSRSignRequest(BaseModel):
    runner_node_id: int
    csr_pem: str
    ttl_hours: int = Field(default=24, ge=1, le=168)
    previous_certificate_id: int | None = None


class RunnerCertificateRevokeRequest(BaseModel):
    reason: str = ""


class WorkloadSigningKeyCreate(BaseModel):
    organization_id: int
    kid: str
    algorithm: str = "RS256"
    public_key_pem: str = ""
    private_key_ref: str = ""
    not_before: datetime | None = None
    not_after: datetime | None = None
    activate: bool = True


class WorkloadSigningKeyStatus(BaseModel):
    status: str


class EvidenceTrustPolicyCreate(BaseModel):
    organization_id: int
    name: str
    signature_type: str = "cosign"
    key_ref: str = ""
    expected_signer: str = ""
    expected_issuer: str = ""
    config: dict = Field(default_factory=dict)
    enabled: bool = True


class EvidenceVerifyRequest(BaseModel):
    signature_id: int
    policy_id: int | None = None


class TelemetryExporterCreate(BaseModel):
    organization_id: int
    name: str
    provider: str = "prometheus_pull"
    endpoint: str = ""
    auth_secret_ref: str = ""
    config: dict = Field(default_factory=dict)
    enabled: bool = True


class TelemetryExportRequest(BaseModel):
    limit: int = Field(default=500, ge=1, le=5000)


class OTLPMetricsIngest(BaseModel):
    organization_id: int
    payload: dict
    environment_id: int | None = None
    deployment_id: int | None = None
    release_id: int | None = None


class SecretProviderConnectionCreate(BaseModel):
    organization_id: int
    company_id: int | None = None
    name: str
    provider: str
    endpoint: str = ""
    auth_ref: str = ""
    config: dict = Field(default_factory=dict)
    enabled: bool = True


class SecretProviderVerifyRequest(BaseModel):
    secret_reference_id: int | None = None


class SecretAccessLeaseCreate(BaseModel):
    organization_id: int
    secret_reference_id: int
    provider_connection_id: int | None = None
    runner_lease_id: int | None = None
    member_id: int | None = None
    agent_id: int | None = None
    mount_name: str = ""
    ttl_seconds: int = Field(default=300, ge=30, le=3600)


class IncidentPagingRouteCreate(BaseModel):
    organization_id: int
    company_id: int | None = None
    name: str
    provider: str = "console"
    endpoint: str = ""
    secret_ref: str = ""
    severities: list[str] = Field(default_factory=lambda: ["critical", "high"])
    enabled: bool = True


class IncidentPageRequest(BaseModel):
    event_type: str = "opened"


class SchedulerNodeRegister(BaseModel):
    organization_id: int
    node_key: str
    capacity: int = Field(default=1, ge=1, le=256)
    labels: dict = Field(default_factory=dict)


class SchedulerLeadershipRequest(BaseModel):
    lease_name: str = "sre-control-loop"
    ttl_seconds: int = Field(default=30, ge=5, le=300)


class SRERecoveryPolicyCreate(BaseModel):
    organization_id: int
    company_id: int | None = None
    name: str
    severities: list[str] = Field(default_factory=lambda: ["critical", "high"])
    actions: list[str] = Field(default_factory=lambda: ["page", "mark_mitigating"])
    max_attempts: int = Field(default=2, ge=1, le=10)
    approval_required_for: list[str] = Field(default_factory=lambda: ["critical"])
    enabled: bool = True


class SREPlanRequest(BaseModel):
    incident_id: int
    nina_member_id: int | None = None


class SREExecuteRequest(BaseModel):
    force: bool = False
