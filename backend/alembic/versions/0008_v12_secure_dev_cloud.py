"""v12 secure AI development cloud

Revision ID: 0008_v12_secure_dev_cloud
Revises: 0007_v11_event_webhooks
"""
from alembic import op
import sqlalchemy as sa

revision = "0008_v12_secure_dev_cloud"
down_revision = "0007_v11_event_webhooks"
branch_labels = None
depends_on = None


def ts(name="created_at"):
    return sa.Column(name, sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP"))


def idx(table, *columns, unique=False):
    op.create_index(f"ix_{table}_{'_'.join(columns)}", table, list(columns), unique=unique)


def upgrade():
    op.create_table(
        "dev_workspaces",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=True),
        sa.Column("repository_id", sa.Integer(), sa.ForeignKey("repositories.id"), nullable=True),
        sa.Column("owner_member_id", sa.Integer(), sa.ForeignKey("members.id"), nullable=True),
        sa.Column("owner_agent_id", sa.Integer(), sa.ForeignKey("agents.id"), nullable=True),
        sa.Column("name", sa.String(180), nullable=False),
        sa.Column("workspace_key", sa.String(180), nullable=False),
        sa.Column("root_path", sa.String(1000), nullable=False, server_default=""),
        sa.Column("base_ref", sa.String(180), nullable=False, server_default=""),
        sa.Column("status", sa.String(32), nullable=False, server_default="ready"),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        ts(),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    for col in ["organization_id","company_id","project_id","repository_id","owner_member_id","owner_agent_id","workspace_key","status","expires_at","created_at"]: idx("dev_workspaces", col)

    op.create_table(
        "sandbox_profiles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=True),
        sa.Column("name", sa.String(180), nullable=False),
        sa.Column("image", sa.String(300), nullable=False, server_default="python:3.12-slim"),
        sa.Column("provider", sa.String(40), nullable=False, server_default="mock"),
        sa.Column("cpu_limit", sa.Float(), nullable=False, server_default="1"),
        sa.Column("memory_mb", sa.Integer(), nullable=False, server_default="1024"),
        sa.Column("pids_limit", sa.Integer(), nullable=False, server_default="256"),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False, server_default="900"),
        sa.Column("network_mode", sa.String(32), nullable=False, server_default="none"),
        sa.Column("read_only_root", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("allowed_commands_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        ts(),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    idx("sandbox_profiles","organization_id"); idx("sandbox_profiles","company_id")

    op.create_table(
        "deployment_environments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=True),
        sa.Column("repository_id", sa.Integer(), sa.ForeignKey("repositories.id"), nullable=False),
        sa.Column("name", sa.String(180), nullable=False),
        sa.Column("slug", sa.String(120), nullable=False),
        sa.Column("environment_type", sa.String(32), nullable=False, server_default="preview"),
        sa.Column("provider", sa.String(48), nullable=False, server_default="filesystem"),
        sa.Column("target_ref", sa.String(700), nullable=False, server_default=""),
        sa.Column("base_url", sa.String(1000), nullable=False, server_default=""),
        sa.Column("require_approval", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("approval_risk", sa.String(24), nullable=False, server_default="high"),
        sa.Column("auto_deploy", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        ts(),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    for col in ["organization_id","company_id","project_id","repository_id","slug","environment_type"]: idx("deployment_environments", col)

    op.create_table(
        "secret_references",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=True),
        sa.Column("name", sa.String(180), nullable=False),
        sa.Column("provider", sa.String(48), nullable=False, server_default="env"),
        sa.Column("external_ref", sa.String(700), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("classification", sa.String(32), nullable=False, server_default="confidential"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        ts(),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    idx("secret_references","organization_id"); idx("secret_references","company_id")

    op.create_table(
        "secret_grants",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("secret_reference_id", sa.Integer(), sa.ForeignKey("secret_references.id"), nullable=False),
        sa.Column("member_id", sa.Integer(), sa.ForeignKey("members.id"), nullable=True),
        sa.Column("agent_id", sa.Integer(), sa.ForeignKey("agents.id"), nullable=True),
        sa.Column("sandbox_profile_id", sa.Integer(), sa.ForeignKey("sandbox_profiles.id"), nullable=True),
        sa.Column("environment_id", sa.Integer(), sa.ForeignKey("deployment_environments.id"), nullable=True),
        sa.Column("mount_name", sa.String(180), nullable=False, server_default=""),
        sa.Column("permissions_json", sa.Text(), nullable=False, server_default='["read"]'),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        ts(),
    )
    for col in ["organization_id","secret_reference_id","member_id","agent_id","sandbox_profile_id","environment_id","expires_at"]: idx("secret_grants", col)

    op.create_table(
        "sandbox_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("dev_workspaces.id"), nullable=False),
        sa.Column("profile_id", sa.Integer(), sa.ForeignKey("sandbox_profiles.id"), nullable=False),
        sa.Column("delivery_run_id", sa.Integer(), sa.ForeignKey("delivery_runs.id"), nullable=True),
        sa.Column("initiated_by_member_id", sa.Integer(), sa.ForeignKey("members.id"), nullable=True),
        sa.Column("initiated_by_agent_id", sa.Integer(), sa.ForeignKey("agents.id"), nullable=True),
        sa.Column("purpose", sa.String(64), nullable=False, server_default="test"),
        sa.Column("command_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("secret_grant_ids_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("status", sa.String(32), nullable=False, server_default="queued"),
        sa.Column("provider_run_id", sa.String(240), nullable=False, server_default=""),
        sa.Column("exit_code", sa.Integer(), nullable=True),
        sa.Column("stdout_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("stderr_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("error", sa.Text(), nullable=False, server_default=""),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        ts(),
    )
    for col in ["organization_id","workspace_id","profile_id","delivery_run_id","purpose","status","created_at"]: idx("sandbox_runs", col)

    op.create_table(
        "releases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("repository_id", sa.Integer(), sa.ForeignKey("repositories.id"), nullable=False),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=True),
        sa.Column("delivery_run_id", sa.Integer(), sa.ForeignKey("delivery_runs.id"), nullable=True),
        sa.Column("merge_request_id", sa.Integer(), sa.ForeignKey("repository_merge_requests.id"), nullable=True),
        sa.Column("created_by_member_id", sa.Integer(), sa.ForeignKey("members.id"), nullable=True),
        sa.Column("version", sa.String(120), nullable=False),
        sa.Column("commit_sha", sa.String(80), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
        sa.Column("release_notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("manifest_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("approval_id", sa.Integer(), sa.ForeignKey("approvals.id"), nullable=True),
        ts(),
        sa.Column("released_at", sa.DateTime(), nullable=True),
    )
    for col in ["organization_id","repository_id","project_id","delivery_run_id","merge_request_id","version","commit_sha","status","approval_id","created_at"]: idx("releases", col)

    op.create_table(
        "release_artifacts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("release_id", sa.Integer(), sa.ForeignKey("releases.id"), nullable=False),
        sa.Column("artifact_id", sa.Integer(), sa.ForeignKey("artifacts.id"), nullable=False),
        sa.Column("purpose", sa.String(48), nullable=False, server_default="source"),
        ts(),
    )
    idx("release_artifacts","organization_id");idx("release_artifacts","release_id");idx("release_artifacts","artifact_id")

    op.create_table(
        "preview_environments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("environment_id", sa.Integer(), sa.ForeignKey("deployment_environments.id"), nullable=False),
        sa.Column("release_id", sa.Integer(), sa.ForeignKey("releases.id"), nullable=False),
        sa.Column("delivery_run_id", sa.Integer(), sa.ForeignKey("delivery_runs.id"), nullable=True),
        sa.Column("name", sa.String(180), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="provisioning"),
        sa.Column("url", sa.String(1000), nullable=False, server_default=""),
        sa.Column("provider_ref", sa.String(700), nullable=False, server_default=""),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        ts(),
        sa.Column("destroyed_at", sa.DateTime(), nullable=True),
    )
    for col in ["organization_id","environment_id","release_id","delivery_run_id","status","expires_at"]:idx("preview_environments",col)

    op.create_table(
        "deployments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("environment_id", sa.Integer(), sa.ForeignKey("deployment_environments.id"), nullable=False),
        sa.Column("release_id", sa.Integer(), sa.ForeignKey("releases.id"), nullable=False),
        sa.Column("requested_by_member_id", sa.Integer(), sa.ForeignKey("members.id"), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="queued"),
        sa.Column("provider_ref", sa.String(700), nullable=False, server_default=""),
        sa.Column("deployed_path", sa.String(1000), nullable=False, server_default=""),
        sa.Column("previous_deployment_id", sa.Integer(), sa.ForeignKey("deployments.id"), nullable=True),
        sa.Column("error", sa.Text(), nullable=False, server_default=""),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        ts(),
    )
    for col in ["organization_id","environment_id","release_id","status","created_at"]:idx("deployments",col)

    op.create_table(
        "deployment_rollbacks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("environment_id", sa.Integer(), sa.ForeignKey("deployment_environments.id"), nullable=False),
        sa.Column("from_deployment_id", sa.Integer(), sa.ForeignKey("deployments.id"), nullable=False),
        sa.Column("to_deployment_id", sa.Integer(), sa.ForeignKey("deployments.id"), nullable=False),
        sa.Column("requested_by_member_id", sa.Integer(), sa.ForeignKey("members.id"), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="queued"),
        sa.Column("reason", sa.Text(), nullable=False, server_default=""),
        ts(),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
    )
    for col in ["organization_id","environment_id","from_deployment_id","to_deployment_id","status"]:idx("deployment_rollbacks",col)

    op.create_table(
        "delivery_automation_rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("repository_id", sa.Integer(), sa.ForeignKey("repositories.id"), nullable=False),
        sa.Column("pipeline_id", sa.Integer(), sa.ForeignKey("delivery_pipelines.id"), nullable=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=True),
        sa.Column("name", sa.String(180), nullable=False),
        sa.Column("handoff_purpose", sa.String(80), nullable=False, server_default="commit"),
        sa.Column("target_member_id", sa.Integer(), sa.ForeignKey("members.id"), nullable=True),
        sa.Column("target_branch", sa.String(180), nullable=False, server_default="main"),
        sa.Column("auto_prepare", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("auto_test", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        ts(),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    for col in ["organization_id","repository_id","pipeline_id","project_id","target_member_id"]:idx("delivery_automation_rules",col)


def downgrade():
    for table in [
        "delivery_automation_rules","deployment_rollbacks","deployments","preview_environments",
        "release_artifacts","releases","sandbox_runs","secret_grants","secret_references",
        "deployment_environments","sandbox_profiles","dev_workspaces",
    ]:
        op.drop_table(table)
