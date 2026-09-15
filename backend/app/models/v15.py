from datetime import datetime, timezone
from sqlalchemy import String, Integer, DateTime, ForeignKey, Text, Float, Boolean, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class RunnerTrustAuthority(Base):
    __tablename__ = "runner_trust_authorities"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(180))
    issuer_cn: Mapped[str] = mapped_column(String(240))
    ca_cert_pem: Mapped[str] = mapped_column(Text)
    private_key_ref: Mapped[str] = mapped_column(String(700), default="")
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    rotated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class RunnerCertificate(Base):
    __tablename__ = "runner_certificates"
    __table_args__ = (UniqueConstraint("organization_id", "fingerprint_sha256", name="uq_runner_cert_org_fp"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    runner_node_id: Mapped[int] = mapped_column(ForeignKey("runner_nodes.id"), index=True)
    trust_authority_id: Mapped[int] = mapped_column(ForeignKey("runner_trust_authorities.id"), index=True)
    previous_certificate_id: Mapped[int | None] = mapped_column(ForeignKey("runner_certificates.id"), nullable=True)
    serial_number: Mapped[str] = mapped_column(String(160), index=True)
    subject_dn: Mapped[str] = mapped_column(String(700), default="")
    certificate_pem: Mapped[str] = mapped_column(Text)
    fingerprint_sha256: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    not_before: Mapped[datetime] = mapped_column(DateTime, index=True)
    not_after: Mapped[datetime] = mapped_column(DateTime, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class WorkloadSigningKey(Base):
    __tablename__ = "workload_signing_keys"
    __table_args__ = (UniqueConstraint("organization_id", "kid", name="uq_workload_key_org_kid"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    kid: Mapped[str] = mapped_column(String(180), index=True)
    algorithm: Mapped[str] = mapped_column(String(24), default="RS256")
    public_key_pem: Mapped[str] = mapped_column(Text, default="")
    private_key_ref: Mapped[str] = mapped_column(String(700), default="")
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)  # active|retiring|revoked
    not_before: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    not_after: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    retired_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class EvidenceTrustPolicy(Base):
    __tablename__ = "evidence_trust_policies"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(180))
    signature_type: Mapped[str] = mapped_column(String(48), default="cosign")
    key_ref: Mapped[str] = mapped_column(String(700), default="")
    expected_signer: Mapped[str] = mapped_column(String(700), default="")
    expected_issuer: Mapped[str] = mapped_column(String(700), default="")
    config_json: Mapped[str] = mapped_column(Text, default="{}")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class EvidenceVerification(Base):
    __tablename__ = "evidence_verifications"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    signature_id: Mapped[int] = mapped_column(ForeignKey("evidence_signatures.id"), index=True)
    policy_id: Mapped[int | None] = mapped_column(ForeignKey("evidence_trust_policies.id"), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    reason: Mapped[str] = mapped_column(Text, default="")
    detail_json: Mapped[str] = mapped_column(Text, default="{}")
    verified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class TelemetryExporter(Base):
    __tablename__ = "telemetry_exporters"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(180))
    provider: Mapped[str] = mapped_column(String(64), default="prometheus_pull", index=True)
    endpoint: Mapped[str] = mapped_column(String(1000), default="")
    auth_secret_ref: Mapped[str] = mapped_column(String(700), default="")
    config_json: Mapped[str] = mapped_column(Text, default="{}")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class TelemetryExportAttempt(Base):
    __tablename__ = "telemetry_export_attempts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    exporter_id: Mapped[int] = mapped_column(ForeignKey("telemetry_exporters.id"), index=True)
    status: Mapped[str] = mapped_column(String(32), default="running", index=True)
    batch_size: Mapped[int] = mapped_column(Integer, default=0)
    response_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class SecretProviderConnection(Base):
    __tablename__ = "secret_provider_connections"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(180))
    provider: Mapped[str] = mapped_column(String(64), index=True)  # env|vault_http|aws_sm_cli|gcp_sm_cli|azure_kv_cli
    endpoint: Mapped[str] = mapped_column(String(1000), default="")
    auth_ref: Mapped[str] = mapped_column(String(700), default="")
    config_json: Mapped[str] = mapped_column(Text, default="{}")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class SecretAccessLease(Base):
    __tablename__ = "secret_access_leases"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    secret_reference_id: Mapped[int] = mapped_column(ForeignKey("secret_references.id"), index=True)
    provider_connection_id: Mapped[int | None] = mapped_column(ForeignKey("secret_provider_connections.id"), nullable=True, index=True)
    runner_lease_id: Mapped[int | None] = mapped_column(ForeignKey("runner_leases.id"), nullable=True, index=True)
    member_id: Mapped[int | None] = mapped_column(ForeignKey("members.id"), nullable=True, index=True)
    agent_id: Mapped[int | None] = mapped_column(ForeignKey("agents.id"), nullable=True, index=True)
    mount_name: Mapped[str] = mapped_column(String(180), default="")
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class IncidentPagingRoute(Base):
    __tablename__ = "incident_paging_routes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(180))
    provider: Mapped[str] = mapped_column(String(48), default="console", index=True)  # console|webhook
    endpoint: Mapped[str] = mapped_column(String(1000), default="")
    secret_ref: Mapped[str] = mapped_column(String(700), default="")
    severities_json: Mapped[str] = mapped_column(Text, default='["critical","high"]')
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class IncidentNotification(Base):
    __tablename__ = "incident_notifications"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    incident_id: Mapped[int] = mapped_column(ForeignKey("incidents.id"), index=True)
    route_id: Mapped[int] = mapped_column(ForeignKey("incident_paging_routes.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(64), default="opened")
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    attempt: Mapped[int] = mapped_column(Integer, default=0)
    response_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_excerpt: Mapped[str] = mapped_column(Text, default="")
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class SchedulerNode(Base):
    __tablename__ = "scheduler_nodes"
    __table_args__ = (UniqueConstraint("organization_id", "node_key", name="uq_scheduler_node_org_key"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    node_key: Mapped[str] = mapped_column(String(180), index=True)
    status: Mapped[str] = mapped_column(String(32), default="online", index=True)
    capacity: Mapped[int] = mapped_column(Integer, default=1)
    labels_json: Mapped[str] = mapped_column(Text, default="{}")
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class SchedulerLeadershipLease(Base):
    __tablename__ = "scheduler_leadership_leases"
    __table_args__ = (UniqueConstraint("organization_id", "lease_name", name="uq_scheduler_lease_org_name"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    lease_name: Mapped[str] = mapped_column(String(180), index=True)
    holder_node_id: Mapped[int] = mapped_column(ForeignKey("scheduler_nodes.id"), index=True)
    fencing_token: Mapped[int] = mapped_column(Integer, default=1)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    acquired_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    renewed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class SRERecoveryPolicy(Base):
    __tablename__ = "sre_recovery_policies"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(180))
    severities_json: Mapped[str] = mapped_column(Text, default='["critical","high"]')
    actions_json: Mapped[str] = mapped_column(Text, default='["page","mark_mitigating"]')
    max_attempts: Mapped[int] = mapped_column(Integer, default=2)
    approval_required_for_json: Mapped[str] = mapped_column(Text, default='["critical"]')
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class SRERecoveryRun(Base):
    __tablename__ = "sre_recovery_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    policy_id: Mapped[int] = mapped_column(ForeignKey("sre_recovery_policies.id"), index=True)
    incident_id: Mapped[int] = mapped_column(ForeignKey("incidents.id"), index=True)
    approval_id: Mapped[int | None] = mapped_column(ForeignKey("approvals.id"), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(32), default="planned", index=True)
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    plan_json: Mapped[str] = mapped_column(Text, default="{}")
    result_json: Mapped[str] = mapped_column(Text, default="{}")
    error: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class SREDecision(Base):
    __tablename__ = "sre_decisions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    incident_id: Mapped[int | None] = mapped_column(ForeignKey("incidents.id"), nullable=True, index=True)
    recovery_run_id: Mapped[int | None] = mapped_column(ForeignKey("sre_recovery_runs.id"), nullable=True, index=True)
    nina_member_id: Mapped[int | None] = mapped_column(ForeignKey("members.id"), nullable=True, index=True)
    risk: Mapped[str] = mapped_column(String(24), default="medium")
    decision: Mapped[str] = mapped_column(String(64), default="observe")
    rationale: Mapped[str] = mapped_column(Text, default="")
    evidence_json: Mapped[str] = mapped_column(Text, default="{}")
    action_json: Mapped[str] = mapped_column(Text, default="{}")
    status: Mapped[str] = mapped_column(String(32), default="recorded", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
