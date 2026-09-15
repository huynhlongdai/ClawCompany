"""v15 production trust, telemetry federation and autonomous SRE

Revision ID: 0011_v15_production_trust_sre
Revises: 0010_v14_distributed_secure_execution
"""
from alembic import op
import sqlalchemy as sa

revision = "0011_v15_production_trust_sre"
down_revision = "0010_v14_distributed_secure_execution"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("runner_trust_authorities",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("name", sa.String(180), nullable=False), sa.Column("issuer_cn", sa.String(240), nullable=False), sa.Column("ca_cert_pem", sa.Text(), nullable=False),
        sa.Column("private_key_ref", sa.String(700), nullable=False), sa.Column("status", sa.String(32), nullable=False), sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False), sa.Column("rotated_at", sa.DateTime(), nullable=True))
    op.create_index("ix_runner_trust_authorities_organization_id", "runner_trust_authorities", ["organization_id"])
    op.create_table("runner_certificates",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("runner_node_id", sa.Integer(), sa.ForeignKey("runner_nodes.id"), nullable=False), sa.Column("trust_authority_id", sa.Integer(), sa.ForeignKey("runner_trust_authorities.id"), nullable=False),
        sa.Column("previous_certificate_id", sa.Integer(), sa.ForeignKey("runner_certificates.id"), nullable=True), sa.Column("serial_number", sa.String(160), nullable=False),
        sa.Column("subject_dn", sa.String(700), nullable=False), sa.Column("certificate_pem", sa.Text(), nullable=False), sa.Column("fingerprint_sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False), sa.Column("not_before", sa.DateTime(), nullable=False), sa.Column("not_after", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False), sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("organization_id", "fingerprint_sha256", name="uq_runner_cert_org_fp"))
    op.create_index("ix_runner_certificates_organization_id", "runner_certificates", ["organization_id"]); op.create_index("ix_runner_certificates_runner_node_id", "runner_certificates", ["runner_node_id"])
    op.create_table("workload_signing_keys",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("kid", sa.String(180), nullable=False), sa.Column("algorithm", sa.String(24), nullable=False), sa.Column("public_key_pem", sa.Text(), nullable=False),
        sa.Column("private_key_ref", sa.String(700), nullable=False), sa.Column("status", sa.String(32), nullable=False), sa.Column("not_before", sa.DateTime(), nullable=False),
        sa.Column("not_after", sa.DateTime(), nullable=True), sa.Column("created_at", sa.DateTime(), nullable=False), sa.Column("retired_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("organization_id", "kid", name="uq_workload_key_org_kid"))
    op.create_index("ix_workload_signing_keys_organization_id", "workload_signing_keys", ["organization_id"])
    op.create_table("evidence_trust_policies",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("name", sa.String(180), nullable=False), sa.Column("signature_type", sa.String(48), nullable=False), sa.Column("key_ref", sa.String(700), nullable=False),
        sa.Column("expected_signer", sa.String(700), nullable=False), sa.Column("expected_issuer", sa.String(700), nullable=False), sa.Column("config_json", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False), sa.Column("created_at", sa.DateTime(), nullable=False))
    op.create_index("ix_evidence_trust_policies_organization_id", "evidence_trust_policies", ["organization_id"])
    op.create_table("evidence_verifications",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("signature_id", sa.Integer(), sa.ForeignKey("evidence_signatures.id"), nullable=False), sa.Column("policy_id", sa.Integer(), sa.ForeignKey("evidence_trust_policies.id"), nullable=True),
        sa.Column("status", sa.String(32), nullable=False), sa.Column("reason", sa.Text(), nullable=False), sa.Column("detail_json", sa.Text(), nullable=False),
        sa.Column("verified_at", sa.DateTime(), nullable=True), sa.Column("created_at", sa.DateTime(), nullable=False))
    op.create_index("ix_evidence_verifications_organization_id", "evidence_verifications", ["organization_id"])
    op.create_table("telemetry_exporters",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("name", sa.String(180), nullable=False), sa.Column("provider", sa.String(64), nullable=False), sa.Column("endpoint", sa.String(1000), nullable=False),
        sa.Column("auth_secret_ref", sa.String(700), nullable=False), sa.Column("config_json", sa.Text(), nullable=False), sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("last_success_at", sa.DateTime(), nullable=True), sa.Column("last_error", sa.Text(), nullable=False), sa.Column("created_at", sa.DateTime(), nullable=False))
    op.create_index("ix_telemetry_exporters_organization_id", "telemetry_exporters", ["organization_id"])
    op.create_table("telemetry_export_attempts",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("exporter_id", sa.Integer(), sa.ForeignKey("telemetry_exporters.id"), nullable=False), sa.Column("status", sa.String(32), nullable=False),
        sa.Column("batch_size", sa.Integer(), nullable=False), sa.Column("response_code", sa.Integer(), nullable=True), sa.Column("error", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False), sa.Column("completed_at", sa.DateTime(), nullable=True))
    op.create_index("ix_telemetry_export_attempts_organization_id", "telemetry_export_attempts", ["organization_id"])
    op.create_table("secret_provider_connections",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=True), sa.Column("name", sa.String(180), nullable=False), sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("endpoint", sa.String(1000), nullable=False), sa.Column("auth_ref", sa.String(700), nullable=False), sa.Column("config_json", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False), sa.Column("last_verified_at", sa.DateTime(), nullable=True), sa.Column("created_at", sa.DateTime(), nullable=False))
    op.create_index("ix_secret_provider_connections_organization_id", "secret_provider_connections", ["organization_id"])
    op.create_table("secret_access_leases",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("secret_reference_id", sa.Integer(), sa.ForeignKey("secret_references.id"), nullable=False), sa.Column("provider_connection_id", sa.Integer(), sa.ForeignKey("secret_provider_connections.id"), nullable=True),
        sa.Column("runner_lease_id", sa.Integer(), sa.ForeignKey("runner_leases.id"), nullable=True), sa.Column("member_id", sa.Integer(), sa.ForeignKey("members.id"), nullable=True),
        sa.Column("agent_id", sa.Integer(), sa.ForeignKey("agents.id"), nullable=True), sa.Column("mount_name", sa.String(180), nullable=False), sa.Column("status", sa.String(32), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False), sa.Column("created_at", sa.DateTime(), nullable=False), sa.Column("revoked_at", sa.DateTime(), nullable=True))
    op.create_index("ix_secret_access_leases_organization_id", "secret_access_leases", ["organization_id"])
    op.create_table("incident_paging_routes",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=True), sa.Column("name", sa.String(180), nullable=False), sa.Column("provider", sa.String(48), nullable=False),
        sa.Column("endpoint", sa.String(1000), nullable=False), sa.Column("secret_ref", sa.String(700), nullable=False), sa.Column("severities_json", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False), sa.Column("created_at", sa.DateTime(), nullable=False))
    op.create_index("ix_incident_paging_routes_organization_id", "incident_paging_routes", ["organization_id"])
    op.create_table("incident_notifications",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("incident_id", sa.Integer(), sa.ForeignKey("incidents.id"), nullable=False), sa.Column("route_id", sa.Integer(), sa.ForeignKey("incident_paging_routes.id"), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False), sa.Column("status", sa.String(32), nullable=False), sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("response_code", sa.Integer(), nullable=True), sa.Column("response_excerpt", sa.Text(), nullable=False), sa.Column("error", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False), sa.Column("sent_at", sa.DateTime(), nullable=True))
    op.create_index("ix_incident_notifications_organization_id", "incident_notifications", ["organization_id"])
    op.create_table("scheduler_nodes",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("node_key", sa.String(180), nullable=False), sa.Column("status", sa.String(32), nullable=False), sa.Column("capacity", sa.Integer(), nullable=False),
        sa.Column("labels_json", sa.Text(), nullable=False), sa.Column("last_heartbeat_at", sa.DateTime(), nullable=True), sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("organization_id", "node_key", name="uq_scheduler_node_org_key"))
    op.create_index("ix_scheduler_nodes_organization_id", "scheduler_nodes", ["organization_id"])
    op.create_table("scheduler_leadership_leases",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("lease_name", sa.String(180), nullable=False), sa.Column("holder_node_id", sa.Integer(), sa.ForeignKey("scheduler_nodes.id"), nullable=False),
        sa.Column("fencing_token", sa.Integer(), nullable=False), sa.Column("expires_at", sa.DateTime(), nullable=False), sa.Column("acquired_at", sa.DateTime(), nullable=False),
        sa.Column("renewed_at", sa.DateTime(), nullable=False), sa.UniqueConstraint("organization_id", "lease_name", name="uq_scheduler_lease_org_name"))
    op.create_index("ix_scheduler_leadership_leases_organization_id", "scheduler_leadership_leases", ["organization_id"])
    op.create_table("sre_recovery_policies",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=True), sa.Column("name", sa.String(180), nullable=False),
        sa.Column("severities_json", sa.Text(), nullable=False), sa.Column("actions_json", sa.Text(), nullable=False), sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("approval_required_for_json", sa.Text(), nullable=False), sa.Column("enabled", sa.Boolean(), nullable=False), sa.Column("created_at", sa.DateTime(), nullable=False))
    op.create_index("ix_sre_recovery_policies_organization_id", "sre_recovery_policies", ["organization_id"])
    op.create_table("sre_recovery_runs",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("policy_id", sa.Integer(), sa.ForeignKey("sre_recovery_policies.id"), nullable=False), sa.Column("incident_id", sa.Integer(), sa.ForeignKey("incidents.id"), nullable=False),
        sa.Column("approval_id", sa.Integer(), sa.ForeignKey("approvals.id"), nullable=True), sa.Column("status", sa.String(32), nullable=False), sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("plan_json", sa.Text(), nullable=False), sa.Column("result_json", sa.Text(), nullable=False), sa.Column("error", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True), sa.Column("completed_at", sa.DateTime(), nullable=True), sa.Column("created_at", sa.DateTime(), nullable=False))
    op.create_index("ix_sre_recovery_runs_organization_id", "sre_recovery_runs", ["organization_id"])
    op.create_table("sre_decisions",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("incident_id", sa.Integer(), sa.ForeignKey("incidents.id"), nullable=True), sa.Column("recovery_run_id", sa.Integer(), sa.ForeignKey("sre_recovery_runs.id"), nullable=True),
        sa.Column("nina_member_id", sa.Integer(), sa.ForeignKey("members.id"), nullable=True), sa.Column("risk", sa.String(24), nullable=False),
        sa.Column("decision", sa.String(64), nullable=False), sa.Column("rationale", sa.Text(), nullable=False), sa.Column("evidence_json", sa.Text(), nullable=False),
        sa.Column("action_json", sa.Text(), nullable=False), sa.Column("status", sa.String(32), nullable=False), sa.Column("created_at", sa.DateTime(), nullable=False))
    op.create_index("ix_sre_decisions_organization_id", "sre_decisions", ["organization_id"])


def downgrade():
    for name in ["sre_decisions", "sre_recovery_runs", "sre_recovery_policies", "scheduler_leadership_leases", "scheduler_nodes",
                 "incident_notifications", "incident_paging_routes", "secret_access_leases", "secret_provider_connections",
                 "telemetry_export_attempts", "telemetry_exporters", "evidence_verifications", "evidence_trust_policies",
                 "workload_signing_keys", "runner_certificates", "runner_trust_authorities"]:
        op.drop_table(name)
