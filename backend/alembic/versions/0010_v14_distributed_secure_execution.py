"""v14 distributed secure execution and observability

Revision ID: 0010_v14_distributed_secure_execution
Revises: 0009_v13_ai_engineering_org
"""
from alembic import op
import sqlalchemy as sa

revision = "0010_v14_distributed_secure_execution"
down_revision = "0009_v13_ai_engineering_org"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("runner_pools",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=True), sa.Column("name", sa.String(180), nullable=False),
        sa.Column("provider", sa.String(48), nullable=False), sa.Column("capabilities_json", sa.Text(), nullable=False), sa.Column("selectors_json", sa.Text(), nullable=False),
        sa.Column("max_concurrency", sa.Integer(), nullable=False), sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False), sa.Column("updated_at", sa.DateTime(), nullable=False))
    op.create_index("ix_runner_pools_organization_id", "runner_pools", ["organization_id"])
    op.create_table("runner_nodes",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("pool_id", sa.Integer(), sa.ForeignKey("runner_pools.id"), nullable=False), sa.Column("node_key", sa.String(180), nullable=False),
        sa.Column("provider", sa.String(48), nullable=False), sa.Column("endpoint", sa.String(1000), nullable=False), sa.Column("capabilities_json", sa.Text(), nullable=False),
        sa.Column("labels_json", sa.Text(), nullable=False), sa.Column("status", sa.String(32), nullable=False), sa.Column("active_leases", sa.Integer(), nullable=False),
        sa.Column("capacity", sa.Integer(), nullable=False), sa.Column("last_heartbeat_at", sa.DateTime(), nullable=True), sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("organization_id", "node_key", name="uq_runner_node_org_key"))
    op.create_index("ix_runner_nodes_organization_id", "runner_nodes", ["organization_id"]); op.create_index("ix_runner_nodes_pool_id", "runner_nodes", ["pool_id"])
    op.create_table("runner_leases",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("pool_id", sa.Integer(), sa.ForeignKey("runner_pools.id"), nullable=False), sa.Column("runner_node_id", sa.Integer(), sa.ForeignKey("runner_nodes.id"), nullable=False),
        sa.Column("member_id", sa.Integer(), sa.ForeignKey("members.id"), nullable=True), sa.Column("agent_id", sa.Integer(), sa.ForeignKey("agents.id"), nullable=True),
        sa.Column("workload_type", sa.String(64), nullable=False), sa.Column("workload_ref", sa.String(180), nullable=False), sa.Column("requested_capabilities_json", sa.Text(), nullable=False),
        sa.Column("scopes_json", sa.Text(), nullable=False), sa.Column("status", sa.String(32), nullable=False), sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("released_at", sa.DateTime(), nullable=True), sa.Column("created_at", sa.DateTime(), nullable=False))
    op.create_index("ix_runner_leases_organization_id", "runner_leases", ["organization_id"]); op.create_index("ix_runner_leases_runner_node_id", "runner_leases", ["runner_node_id"])
    op.create_table("runner_jobs",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("lease_id", sa.Integer(), sa.ForeignKey("runner_leases.id"), nullable=False), sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("dev_workspaces.id"), nullable=True),
        sa.Column("sandbox_run_id", sa.Integer(), sa.ForeignKey("sandbox_runs.id"), nullable=True), sa.Column("job_type", sa.String(64), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False), sa.Column("status", sa.String(32), nullable=False), sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("result_json", sa.Text(), nullable=False), sa.Column("error", sa.Text(), nullable=False), sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True), sa.Column("created_at", sa.DateTime(), nullable=False))
    op.create_index("ix_runner_jobs_organization_id", "runner_jobs", ["organization_id"]); op.create_index("ix_runner_jobs_lease_id", "runner_jobs", ["lease_id"])
    op.create_table("workload_identity_tokens",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("lease_id", sa.Integer(), sa.ForeignKey("runner_leases.id"), nullable=False), sa.Column("member_id", sa.Integer(), sa.ForeignKey("members.id"), nullable=True),
        sa.Column("agent_id", sa.Integer(), sa.ForeignKey("agents.id"), nullable=True), sa.Column("jti", sa.String(96), nullable=False, unique=True),
        sa.Column("issuer", sa.String(500), nullable=False), sa.Column("audience", sa.String(300), nullable=False), sa.Column("scopes_json", sa.Text(), nullable=False),
        sa.Column("signing_alg", sa.String(24), nullable=False), sa.Column("status", sa.String(32), nullable=False), sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False))
    op.create_index("ix_workload_identity_tokens_organization_id", "workload_identity_tokens", ["organization_id"]); op.create_index("ix_workload_identity_tokens_jti", "workload_identity_tokens", ["jti"], unique=True)
    op.create_table("evidence_signatures",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("artifact_id", sa.Integer(), sa.ForeignKey("artifacts.id"), nullable=False), sa.Column("build_id", sa.Integer(), sa.ForeignKey("build_records.id"), nullable=True),
        sa.Column("signature_type", sa.String(48), nullable=False), sa.Column("signer", sa.String(300), nullable=False), sa.Column("key_ref", sa.String(700), nullable=False),
        sa.Column("subject_digest", sa.String(64), nullable=False), sa.Column("signature", sa.Text(), nullable=False), sa.Column("certificate_json", sa.Text(), nullable=False),
        sa.Column("verified", sa.Boolean(), nullable=False), sa.Column("created_at", sa.DateTime(), nullable=False), sa.Column("verified_at", sa.DateTime(), nullable=True))
    op.create_index("ix_evidence_signatures_organization_id", "evidence_signatures", ["organization_id"]); op.create_index("ix_evidence_signatures_artifact_id", "evidence_signatures", ["artifact_id"])
    op.create_table("scanner_providers",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("name", sa.String(180), nullable=False), sa.Column("provider_type", sa.String(64), nullable=False), sa.Column("executable", sa.String(300), nullable=False),
        sa.Column("config_json", sa.Text(), nullable=False), sa.Column("block_on", sa.String(24), nullable=False), sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False))
    op.create_index("ix_scanner_providers_organization_id", "scanner_providers", ["organization_id"])
    op.create_table("external_scan_runs",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("provider_id", sa.Integer(), sa.ForeignKey("scanner_providers.id"), nullable=False), sa.Column("repository_id", sa.Integer(), sa.ForeignKey("repositories.id"), nullable=False),
        sa.Column("ci_run_id", sa.Integer(), sa.ForeignKey("cicd_runs.id"), nullable=True), sa.Column("commit_sha", sa.String(80), nullable=False),
        sa.Column("status", sa.String(32), nullable=False), sa.Column("verdict", sa.String(32), nullable=False), sa.Column("findings_json", sa.Text(), nullable=False),
        sa.Column("summary_json", sa.Text(), nullable=False), sa.Column("exit_code", sa.Integer(), nullable=True), sa.Column("error", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False), sa.Column("completed_at", sa.DateTime(), nullable=True))
    op.create_index("ix_external_scan_runs_organization_id", "external_scan_runs", ["organization_id"]); op.create_index("ix_external_scan_runs_repository_id", "external_scan_runs", ["repository_id"])
    op.create_table("traffic_routers",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("environment_id", sa.Integer(), sa.ForeignKey("deployment_environments.id"), nullable=False), sa.Column("name", sa.String(180), nullable=False),
        sa.Column("provider", sa.String(64), nullable=False), sa.Column("config_json", sa.Text(), nullable=False), sa.Column("current_weights_json", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False), sa.Column("created_at", sa.DateTime(), nullable=False), sa.Column("updated_at", sa.DateTime(), nullable=False))
    op.create_index("ix_traffic_routers_organization_id", "traffic_routers", ["organization_id"]); op.create_index("ix_traffic_routers_environment_id", "traffic_routers", ["environment_id"])
    op.create_table("traffic_shifts",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("router_id", sa.Integer(), sa.ForeignKey("traffic_routers.id"), nullable=False), sa.Column("strategy_run_id", sa.Integer(), sa.ForeignKey("deployment_strategy_runs.id"), nullable=True),
        sa.Column("release_id", sa.Integer(), sa.ForeignKey("releases.id"), nullable=False), sa.Column("from_release_id", sa.Integer(), sa.ForeignKey("releases.id"), nullable=True),
        sa.Column("from_weight", sa.Integer(), nullable=False), sa.Column("to_weight", sa.Integer(), nullable=False), sa.Column("status", sa.String(32), nullable=False),
        sa.Column("provider_ref", sa.String(1000), nullable=False), sa.Column("detail_json", sa.Text(), nullable=False), sa.Column("created_at", sa.DateTime(), nullable=False))
    op.create_index("ix_traffic_shifts_organization_id", "traffic_shifts", ["organization_id"]); op.create_index("ix_traffic_shifts_router_id", "traffic_shifts", ["router_id"])
    op.create_table("telemetry_metric_samples",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("environment_id", sa.Integer(), sa.ForeignKey("deployment_environments.id"), nullable=True), sa.Column("deployment_id", sa.Integer(), sa.ForeignKey("deployments.id"), nullable=True),
        sa.Column("release_id", sa.Integer(), sa.ForeignKey("releases.id"), nullable=True), sa.Column("metric_name", sa.String(180), nullable=False),
        sa.Column("value", sa.Float(), nullable=False), sa.Column("unit", sa.String(48), nullable=False), sa.Column("labels_json", sa.Text(), nullable=False),
        sa.Column("observed_at", sa.DateTime(), nullable=False))
    op.create_index("ix_telemetry_metric_samples_organization_id", "telemetry_metric_samples", ["organization_id"]); op.create_index("ix_telemetry_metric_samples_metric_name", "telemetry_metric_samples", ["metric_name"])
    op.create_table("slo_definitions",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("environment_id", sa.Integer(), sa.ForeignKey("deployment_environments.id"), nullable=False), sa.Column("name", sa.String(180), nullable=False),
        sa.Column("metric_name", sa.String(180), nullable=False), sa.Column("comparator", sa.String(8), nullable=False), sa.Column("threshold", sa.Float(), nullable=False),
        sa.Column("window_minutes", sa.Integer(), nullable=False), sa.Column("min_samples", sa.Integer(), nullable=False), sa.Column("auto_incident", sa.Boolean(), nullable=False),
        sa.Column("auto_rollback", sa.Boolean(), nullable=False), sa.Column("severity", sa.String(24), nullable=False), sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False))
    op.create_index("ix_slo_definitions_organization_id", "slo_definitions", ["organization_id"]); op.create_index("ix_slo_definitions_environment_id", "slo_definitions", ["environment_id"])
    op.create_table("slo_evaluations",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("slo_id", sa.Integer(), sa.ForeignKey("slo_definitions.id"), nullable=False), sa.Column("deployment_id", sa.Integer(), sa.ForeignKey("deployments.id"), nullable=True),
        sa.Column("release_id", sa.Integer(), sa.ForeignKey("releases.id"), nullable=True), sa.Column("status", sa.String(32), nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=False), sa.Column("aggregate_value", sa.Float(), nullable=True), sa.Column("threshold", sa.Float(), nullable=False),
        sa.Column("detail_json", sa.Text(), nullable=False), sa.Column("evaluated_at", sa.DateTime(), nullable=False))
    op.create_index("ix_slo_evaluations_organization_id", "slo_evaluations", ["organization_id"]); op.create_index("ix_slo_evaluations_slo_id", "slo_evaluations", ["slo_id"])
    op.create_table("incidents",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=True), sa.Column("environment_id", sa.Integer(), sa.ForeignKey("deployment_environments.id"), nullable=True),
        sa.Column("deployment_id", sa.Integer(), sa.ForeignKey("deployments.id"), nullable=True), sa.Column("release_id", sa.Integer(), sa.ForeignKey("releases.id"), nullable=True),
        sa.Column("slo_evaluation_id", sa.Integer(), sa.ForeignKey("slo_evaluations.id"), nullable=True), sa.Column("owner_member_id", sa.Integer(), sa.ForeignKey("members.id"), nullable=True),
        sa.Column("title", sa.String(240), nullable=False), sa.Column("severity", sa.String(24), nullable=False), sa.Column("status", sa.String(32), nullable=False),
        sa.Column("source", sa.String(64), nullable=False), sa.Column("summary", sa.Text(), nullable=False), sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("acknowledged_at", sa.DateTime(), nullable=True), sa.Column("resolved_at", sa.DateTime(), nullable=True))
    op.create_index("ix_incidents_organization_id", "incidents", ["organization_id"]); op.create_index("ix_incidents_status", "incidents", ["status"])
    op.create_table("incident_events",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("incident_id", sa.Integer(), sa.ForeignKey("incidents.id"), nullable=False), sa.Column("actor_member_id", sa.Integer(), sa.ForeignKey("members.id"), nullable=True),
        sa.Column("actor_agent_id", sa.Integer(), sa.ForeignKey("agents.id"), nullable=True), sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("message", sa.Text(), nullable=False), sa.Column("data_json", sa.Text(), nullable=False), sa.Column("created_at", sa.DateTime(), nullable=False))
    op.create_index("ix_incident_events_organization_id", "incident_events", ["organization_id"]); op.create_index("ix_incident_events_incident_id", "incident_events", ["incident_id"])
    op.create_table("portfolio_objectives",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=True), sa.Column("owner_member_id", sa.Integer(), sa.ForeignKey("members.id"), nullable=True),
        sa.Column("title", sa.String(220), nullable=False), sa.Column("objective", sa.Text(), nullable=False), sa.Column("priority", sa.String(24), nullable=False),
        sa.Column("status", sa.String(32), nullable=False), sa.Column("target_json", sa.Text(), nullable=False), sa.Column("created_at", sa.DateTime(), nullable=False))
    op.create_index("ix_portfolio_objectives_organization_id", "portfolio_objectives", ["organization_id"])
    op.create_table("portfolio_reviews",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("objective_id", sa.Integer(), sa.ForeignKey("portfolio_objectives.id"), nullable=True), sa.Column("nina_member_id", sa.Integer(), sa.ForeignKey("members.id"), nullable=True),
        sa.Column("status", sa.String(32), nullable=False), sa.Column("health", sa.String(32), nullable=False), sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("metrics_json", sa.Text(), nullable=False), sa.Column("recommendations_json", sa.Text(), nullable=False), sa.Column("created_at", sa.DateTime(), nullable=False))
    op.create_index("ix_portfolio_reviews_organization_id", "portfolio_reviews", ["organization_id"])


def downgrade():
    for name in ["portfolio_reviews", "portfolio_objectives", "incident_events", "incidents", "slo_evaluations", "slo_definitions",
                 "telemetry_metric_samples", "traffic_shifts", "traffic_routers", "external_scan_runs", "scanner_providers", "evidence_signatures",
                 "workload_identity_tokens", "runner_jobs", "runner_leases", "runner_nodes", "runner_pools"]:
        op.drop_table(name)
