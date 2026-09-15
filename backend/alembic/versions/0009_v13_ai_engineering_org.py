"""v13 AI engineering organization

Revision ID: 0009_v13_ai_engineering_org
Revises: 0008_v12_secure_dev_cloud
"""
from alembic import op
import sqlalchemy as sa

revision = "0009_v13_ai_engineering_org"
down_revision = "0008_v12_secure_dev_cloud"
branch_labels = None
depends_on = None


def ts(name="created_at"):
    return sa.Column(name, sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP"))


def idx(table, *columns, unique=False):
    op.create_index(f"ix_{table}_{'_'.join(columns)}", table, list(columns), unique=unique)


def upgrade():
    op.create_table(
        "workspace_gateway_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("dev_workspaces.id"), nullable=False),
        sa.Column("member_id", sa.Integer(), sa.ForeignKey("members.id"), nullable=True),
        sa.Column("agent_id", sa.Integer(), sa.ForeignKey("agents.id"), nullable=True),
        sa.Column("provider", sa.String(64), nullable=False, server_default="openclaw"),
        sa.Column("provider_session_id", sa.String(240), nullable=False, server_default=""),
        sa.Column("session_key", sa.String(180), nullable=False, unique=True),
        sa.Column("capabilities_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("expires_at", sa.DateTime(), nullable=True), ts(), sa.Column("closed_at", sa.DateTime(), nullable=True),
    )
    for c in ["organization_id","workspace_id","member_id","agent_id","provider","provider_session_id","session_key","status","expires_at","created_at"]: idx("workspace_gateway_sessions", c, unique=(c=="session_key"))

    op.create_table(
        "workspace_gateway_operations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("session_id", sa.Integer(), sa.ForeignKey("workspace_gateway_sessions.id"), nullable=False),
        sa.Column("operation_type", sa.String(48), nullable=False),
        sa.Column("logical_path", sa.String(700), nullable=False, server_default=""),
        sa.Column("artifact_id", sa.Integer(), sa.ForeignKey("artifacts.id"), nullable=True),
        sa.Column("request_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("response_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("status", sa.String(32), nullable=False, server_default="completed"),
        sa.Column("error", sa.Text(), nullable=False, server_default=""), ts(),
    )
    for c in ["organization_id","session_id","operation_type","artifact_id","status","created_at"]: idx("workspace_gateway_operations", c)

    op.create_table(
        "cicd_pipeline_graphs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=True),
        sa.Column("repository_id", sa.Integer(), sa.ForeignKey("repositories.id"), nullable=False),
        sa.Column("name", sa.String(180), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
        sa.Column("trigger_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_by_member_id", sa.Integer(), sa.ForeignKey("members.id"), nullable=True),
        ts(), sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    for c in ["organization_id","company_id","project_id","repository_id","status","created_at"]: idx("cicd_pipeline_graphs", c)

    op.create_table(
        "cicd_nodes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("graph_id", sa.Integer(), sa.ForeignKey("cicd_pipeline_graphs.id"), nullable=False),
        sa.Column("node_key", sa.String(120), nullable=False),
        sa.Column("node_type", sa.String(48), nullable=False, server_default="noop"),
        sa.Column("name", sa.String(180), nullable=False),
        sa.Column("config_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("required", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("order_hint", sa.Integer(), nullable=False, server_default="0"), ts(),
        sa.UniqueConstraint("graph_id","node_key", name="uq_cicd_node_graph_key"),
    )
    for c in ["organization_id","graph_id","node_key","node_type"]: idx("cicd_nodes", c)

    op.create_table(
        "cicd_edges",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("graph_id", sa.Integer(), sa.ForeignKey("cicd_pipeline_graphs.id"), nullable=False),
        sa.Column("from_node_id", sa.Integer(), sa.ForeignKey("cicd_nodes.id"), nullable=False),
        sa.Column("to_node_id", sa.Integer(), sa.ForeignKey("cicd_nodes.id"), nullable=False),
        sa.Column("condition_json", sa.Text(), nullable=False, server_default="{}"), ts(),
    )
    for c in ["organization_id","graph_id","from_node_id","to_node_id"]: idx("cicd_edges", c)

    op.create_table(
        "cicd_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("graph_id", sa.Integer(), sa.ForeignKey("cicd_pipeline_graphs.id"), nullable=False),
        sa.Column("repository_id", sa.Integer(), sa.ForeignKey("repositories.id"), nullable=False),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=True),
        sa.Column("release_id", sa.Integer(), sa.ForeignKey("releases.id"), nullable=True),
        sa.Column("initiated_by_member_id", sa.Integer(), sa.ForeignKey("members.id"), nullable=True),
        sa.Column("initiated_by_agent_id", sa.Integer(), sa.ForeignKey("agents.id"), nullable=True),
        sa.Column("ref", sa.String(180), nullable=False, server_default="main"),
        sa.Column("commit_sha", sa.String(80), nullable=False, server_default=""),
        sa.Column("status", sa.String(32), nullable=False, server_default="queued"),
        sa.Column("correlation_id", sa.String(80), nullable=False, server_default=""),
        sa.Column("summary_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("error", sa.Text(), nullable=False, server_default=""),
        sa.Column("started_at", sa.DateTime(), nullable=True), sa.Column("completed_at", sa.DateTime(), nullable=True), ts(),
    )
    for c in ["organization_id","graph_id","repository_id","project_id","release_id","commit_sha","status","correlation_id","created_at"]: idx("cicd_runs", c)

    op.create_table(
        "cicd_node_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("ci_run_id", sa.Integer(), sa.ForeignKey("cicd_runs.id"), nullable=False),
        sa.Column("node_id", sa.Integer(), sa.ForeignKey("cicd_nodes.id"), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="queued"),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("sandbox_run_id", sa.Integer(), sa.ForeignKey("sandbox_runs.id"), nullable=True),
        sa.Column("output_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("error", sa.Text(), nullable=False, server_default=""),
        sa.Column("started_at", sa.DateTime(), nullable=True), sa.Column("completed_at", sa.DateTime(), nullable=True), ts(),
    )
    for c in ["organization_id","ci_run_id","node_id","status","sandbox_run_id"]: idx("cicd_node_runs", c)

    op.create_table(
        "build_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("repository_id", sa.Integer(), sa.ForeignKey("repositories.id"), nullable=False),
        sa.Column("ci_run_id", sa.Integer(), sa.ForeignKey("cicd_runs.id"), nullable=True),
        sa.Column("release_id", sa.Integer(), sa.ForeignKey("releases.id"), nullable=True),
        sa.Column("commit_sha", sa.String(80), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="building"),
        sa.Column("source_digest", sa.String(64), nullable=False, server_default=""),
        sa.Column("manifest_artifact_id", sa.Integer(), sa.ForeignKey("artifacts.id"), nullable=True),
        ts(), sa.Column("completed_at", sa.DateTime(), nullable=True),
    )
    for c in ["organization_id","repository_id","ci_run_id","release_id","commit_sha","status","source_digest","created_at"]: idx("build_records", c)

    op.create_table(
        "sbom_documents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("build_id", sa.Integer(), sa.ForeignKey("build_records.id"), nullable=False),
        sa.Column("format", sa.String(32), nullable=False, server_default="spdx-json"),
        sa.Column("spec_version", sa.String(32), nullable=False, server_default="SPDX-2.3"),
        sa.Column("artifact_id", sa.Integer(), sa.ForeignKey("artifacts.id"), nullable=False),
        sa.Column("file_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("package_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("digest", sa.String(64), nullable=False, server_default=""), ts(),
    )
    for c in ["organization_id","build_id","artifact_id","digest"]: idx("sbom_documents", c)

    op.create_table(
        "build_provenance",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("build_id", sa.Integer(), sa.ForeignKey("build_records.id"), nullable=False),
        sa.Column("artifact_id", sa.Integer(), sa.ForeignKey("artifacts.id"), nullable=False),
        sa.Column("builder_id", sa.String(240), nullable=False, server_default="clawcompany://builder/v13"),
        sa.Column("predicate_type", sa.String(240), nullable=False, server_default="https://slsa.dev/provenance/v1"),
        sa.Column("invocation_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("materials_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("subject_json", sa.Text(), nullable=False, server_default="[]"), ts(),
    )
    for c in ["organization_id","build_id","artifact_id"]: idx("build_provenance", c)

    op.create_table(
        "security_reviews",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("repository_id", sa.Integer(), sa.ForeignKey("repositories.id"), nullable=False),
        sa.Column("ci_run_id", sa.Integer(), sa.ForeignKey("cicd_runs.id"), nullable=True),
        sa.Column("build_id", sa.Integer(), sa.ForeignKey("build_records.id"), nullable=True),
        sa.Column("reviewer_member_id", sa.Integer(), sa.ForeignKey("members.id"), nullable=True),
        sa.Column("reviewer_agent_id", sa.Integer(), sa.ForeignKey("agents.id"), nullable=True),
        sa.Column("commit_sha", sa.String(80), nullable=False, server_default=""),
        sa.Column("status", sa.String(32), nullable=False, server_default="running"),
        sa.Column("verdict", sa.String(32), nullable=False, server_default="review"),
        sa.Column("score", sa.Float(), nullable=False, server_default="100"),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""), ts(), sa.Column("completed_at", sa.DateTime(), nullable=True),
    )
    for c in ["organization_id","repository_id","ci_run_id","build_id","commit_sha","status","verdict","created_at"]: idx("security_reviews", c)

    op.create_table(
        "security_findings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("review_id", sa.Integer(), sa.ForeignKey("security_reviews.id"), nullable=False),
        sa.Column("severity", sa.String(24), nullable=False, server_default="medium"),
        sa.Column("category", sa.String(64), nullable=False, server_default="code_security"),
        sa.Column("rule_id", sa.String(120), nullable=False),
        sa.Column("path", sa.String(700), nullable=False, server_default=""),
        sa.Column("line", sa.Integer(), nullable=True),
        sa.Column("title", sa.String(240), nullable=False),
        sa.Column("evidence", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(32), nullable=False, server_default="open"), ts(),
    )
    for c in ["organization_id","review_id","severity","rule_id","status"]: idx("security_findings", c)

    op.create_table(
        "preview_routes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("preview_environment_id", sa.Integer(), sa.ForeignKey("preview_environments.id"), nullable=False),
        sa.Column("hostname", sa.String(300), nullable=False, server_default=""),
        sa.Column("slug", sa.String(180), nullable=False),
        sa.Column("path_prefix", sa.String(500), nullable=False, server_default="/"),
        sa.Column("target_url", sa.String(1000), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("expires_at", sa.DateTime(), nullable=True), ts(),
    )
    for c in ["organization_id","preview_environment_id","hostname","slug","status","expires_at"]: idx("preview_routes", c)

    op.create_table(
        "deployment_health_policies",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("environment_id", sa.Integer(), sa.ForeignKey("deployment_environments.id"), nullable=False),
        sa.Column("name", sa.String(180), nullable=False),
        sa.Column("check_type", sa.String(48), nullable=False, server_default="filesystem_marker"),
        sa.Column("target", sa.String(1000), nullable=False, server_default=""),
        sa.Column("expected_status", sa.Integer(), nullable=False, server_default="200"),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("success_threshold", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("failure_threshold", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("auto_rollback", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()), ts(),
    )
    idx("deployment_health_policies","organization_id"); idx("deployment_health_policies","environment_id")

    op.create_table(
        "deployment_health_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("policy_id", sa.Integer(), sa.ForeignKey("deployment_health_policies.id"), nullable=False),
        sa.Column("deployment_id", sa.Integer(), sa.ForeignKey("deployments.id"), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="running"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("successes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failures", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("detail_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("started_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
    )
    for c in ["organization_id","policy_id","deployment_id","status"]: idx("deployment_health_runs", c)

    op.create_table(
        "deployment_strategy_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("environment_id", sa.Integer(), sa.ForeignKey("deployment_environments.id"), nullable=False),
        sa.Column("release_id", sa.Integer(), sa.ForeignKey("releases.id"), nullable=False),
        sa.Column("deployment_id", sa.Integer(), sa.ForeignKey("deployments.id"), nullable=True),
        sa.Column("health_run_id", sa.Integer(), sa.ForeignKey("deployment_health_runs.id"), nullable=True),
        sa.Column("rollback_id", sa.Integer(), sa.ForeignKey("deployment_rollbacks.id"), nullable=True),
        sa.Column("requested_by_member_id", sa.Integer(), sa.ForeignKey("members.id"), nullable=True),
        sa.Column("strategy", sa.String(32), nullable=False, server_default="rolling"),
        sa.Column("traffic_percent", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("status", sa.String(32), nullable=False, server_default="queued"),
        sa.Column("phase_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("error", sa.Text(), nullable=False, server_default=""), ts(), sa.Column("completed_at", sa.DateTime(), nullable=True),
    )
    for c in ["organization_id","environment_id","release_id","deployment_id","strategy","status","created_at"]: idx("deployment_strategy_runs", c)

    op.create_table(
        "release_manager_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("release_id", sa.Integer(), sa.ForeignKey("releases.id"), nullable=False),
        sa.Column("ci_run_id", sa.Integer(), sa.ForeignKey("cicd_runs.id"), nullable=True),
        sa.Column("security_review_id", sa.Integer(), sa.ForeignKey("security_reviews.id"), nullable=True),
        sa.Column("strategy_run_id", sa.Integer(), sa.ForeignKey("deployment_strategy_runs.id"), nullable=True),
        sa.Column("requested_by_member_id", sa.Integer(), sa.ForeignKey("members.id"), nullable=True),
        sa.Column("requested_by_agent_id", sa.Integer(), sa.ForeignKey("agents.id"), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="completed"),
        sa.Column("decision", sa.String(32), nullable=False, server_default="hold"),
        sa.Column("reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("evidence_json", sa.Text(), nullable=False, server_default="{}"), ts(),
    )
    for c in ["organization_id","release_id","ci_run_id","status","decision","created_at"]: idx("release_manager_runs", c)

    op.create_table(
        "engineering_initiatives",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=True),
        sa.Column("repository_id", sa.Integer(), sa.ForeignKey("repositories.id"), nullable=False),
        sa.Column("executive_goal_id", sa.Integer(), sa.ForeignKey("executive_goals.id"), nullable=True),
        sa.Column("pipeline_graph_id", sa.Integer(), sa.ForeignKey("cicd_pipeline_graphs.id"), nullable=False),
        sa.Column("desired_environment_id", sa.Integer(), sa.ForeignKey("deployment_environments.id"), nullable=True),
        sa.Column("nina_member_id", sa.Integer(), sa.ForeignKey("members.id"), nullable=True),
        sa.Column("title", sa.String(220), nullable=False),
        sa.Column("objective", sa.Text(), nullable=False, server_default=""),
        sa.Column("ref", sa.String(180), nullable=False, server_default="main"),
        sa.Column("release_version", sa.String(120), nullable=False, server_default=""),
        sa.Column("deployment_strategy", sa.String(32), nullable=False, server_default="rolling"),
        sa.Column("status", sa.String(32), nullable=False, server_default="planned"),
        sa.Column("current_ci_run_id", sa.Integer(), sa.ForeignKey("cicd_runs.id"), nullable=True),
        sa.Column("current_release_id", sa.Integer(), sa.ForeignKey("releases.id"), nullable=True),
        sa.Column("release_manager_run_id", sa.Integer(), sa.ForeignKey("release_manager_runs.id"), nullable=True),
        sa.Column("result_json", sa.Text(), nullable=False, server_default="{}"), ts(),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    for c in ["organization_id","company_id","project_id","repository_id","executive_goal_id","pipeline_graph_id","desired_environment_id","status","created_at"]: idx("engineering_initiatives", c)


def downgrade():
    for table in [
        "engineering_initiatives", "release_manager_runs", "deployment_strategy_runs", "deployment_health_runs",
        "deployment_health_policies", "preview_routes", "security_findings", "security_reviews", "build_provenance",
        "sbom_documents", "build_records", "cicd_node_runs", "cicd_runs", "cicd_edges", "cicd_nodes",
        "cicd_pipeline_graphs", "workspace_gateway_operations", "workspace_gateway_sessions",
    ]:
        op.drop_table(table)
