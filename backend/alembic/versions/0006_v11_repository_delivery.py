"""v11 repository delivery pipeline

Revision ID: 0006_v11_repository_delivery
Revises: 0005_v10_event_driven_company
"""
from alembic import op
import sqlalchemy as sa

revision = "0006_v11_repository_delivery"
down_revision = "0005_v10_event_driven_company"
branch_labels = None
depends_on = None


def _ts():
    return sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP"))


def upgrade():
    # The oldest baseline migrations are metadata-backed for compatibility.
    # On a fresh install that metadata may already contain the v11 member_id
    # column.  Make this historical evolution idempotent instead of failing on
    # duplicate columns / constraints. Existing pre-v11 databases still get
    # the column, FK and index here.
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    api_key_columns = {c["name"] for c in inspector.get_columns("api_keys")}
    if "member_id" not in api_key_columns:
        op.add_column("api_keys", sa.Column("member_id", sa.Integer(), nullable=True))

    inspector = sa.inspect(bind)
    member_fk_exists = any(
        fk.get("referred_table") == "members" and fk.get("constrained_columns") == ["member_id"]
        for fk in inspector.get_foreign_keys("api_keys")
    )
    if not member_fk_exists:
        if bind.dialect.name == "sqlite":
            with op.batch_alter_table("api_keys") as batch:
                batch.create_foreign_key(
                    "fk_api_keys_member_id_members", "members", ["member_id"], ["id"]
                )
        else:
            op.create_foreign_key(
                "fk_api_keys_member_id_members", "api_keys", "members", ["member_id"], ["id"]
            )

    inspector = sa.inspect(bind)
    index_names = {idx.get("name") for idx in inspector.get_indexes("api_keys")}
    if "ix_api_keys_member_id" not in index_names:
        op.create_index("ix_api_keys_member_id", "api_keys", ["member_id"])

    op.create_table(
        "repositories",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=True),
        sa.Column("name", sa.String(180), nullable=False),
        sa.Column("provider", sa.String(40), nullable=False, server_default="local"),
        sa.Column("remote_url", sa.String(1000), nullable=False, server_default=""),
        sa.Column("default_branch", sa.String(180), nullable=False, server_default="main"),
        sa.Column("local_path", sa.String(1000), nullable=False, server_default=""),
        sa.Column("external_repo_id", sa.String(240), nullable=False, server_default=""),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        _ts(), sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_repositories_organization_id", "repositories", ["organization_id"])
    op.create_index("ix_repositories_company_id", "repositories", ["company_id"])
    op.create_index("ix_repositories_project_id", "repositories", ["project_id"])
    op.create_index("ix_repositories_status", "repositories", ["status"])

    op.create_table(
        "repository_identity_credentials",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("repository_id", sa.Integer(), sa.ForeignKey("repositories.id"), nullable=False),
        sa.Column("member_id", sa.Integer(), sa.ForeignKey("members.id"), nullable=True),
        sa.Column("agent_id", sa.Integer(), sa.ForeignKey("agents.id"), nullable=True),
        sa.Column("provider_subject", sa.String(240), nullable=False, server_default=""),
        sa.Column("secret_ref", sa.String(500), nullable=False, server_default=""),
        sa.Column("permissions_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("branch_pattern", sa.String(240), nullable=False, server_default="*"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        _ts(), sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    for name, cols in [
        ("ix_repository_identity_credentials_organization_id", ["organization_id"]),
        ("ix_repository_identity_credentials_repository_id", ["repository_id"]),
        ("ix_repository_identity_credentials_member_id", ["member_id"]),
        ("ix_repository_identity_credentials_agent_id", ["agent_id"]),
    ]:
        op.create_index(name, "repository_identity_credentials", cols)

    op.create_table(
        "repository_test_profiles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("repository_id", sa.Integer(), sa.ForeignKey("repositories.id"), nullable=False),
        sa.Column("name", sa.String(180), nullable=False),
        sa.Column("commands_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False, server_default="300"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        _ts(), sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_repository_test_profiles_organization_id", "repository_test_profiles", ["organization_id"])
    op.create_index("ix_repository_test_profiles_repository_id", "repository_test_profiles", ["repository_id"])

    op.create_table(
        "delivery_pipelines",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("repository_id", sa.Integer(), sa.ForeignKey("repositories.id"), nullable=False),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=True),
        sa.Column("name", sa.String(180), nullable=False),
        sa.Column("target_branch", sa.String(180), nullable=False, server_default="main"),
        sa.Column("test_profile_id", sa.Integer(), sa.ForeignKey("repository_test_profiles.id"), nullable=True),
        sa.Column("require_tests", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("require_review", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("required_approvals", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("merge_strategy", sa.String(32), nullable=False, server_default="merge"),
        sa.Column("auto_merge", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        _ts(), sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_delivery_pipelines_organization_id", "delivery_pipelines", ["organization_id"])
    op.create_index("ix_delivery_pipelines_repository_id", "delivery_pipelines", ["repository_id"])
    op.create_index("ix_delivery_pipelines_project_id", "delivery_pipelines", ["project_id"])

    op.create_table(
        "delivery_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("pipeline_id", sa.Integer(), sa.ForeignKey("delivery_pipelines.id"), nullable=True),
        sa.Column("repository_id", sa.Integer(), sa.ForeignKey("repositories.id"), nullable=False),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=True),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("tasks.id"), nullable=True),
        sa.Column("initiated_by_member_id", sa.Integer(), sa.ForeignKey("members.id"), nullable=True),
        sa.Column("initiated_by_agent_id", sa.Integer(), sa.ForeignKey("agents.id"), nullable=True),
        sa.Column("artifact_bundle_key", sa.String(180), nullable=False, server_default=""),
        sa.Column("source_branch", sa.String(180), nullable=False, server_default=""),
        sa.Column("target_branch", sa.String(180), nullable=False, server_default="main"),
        sa.Column("status", sa.String(40), nullable=False, server_default="queued"),
        sa.Column("worktree_path", sa.String(1000), nullable=False, server_default=""),
        sa.Column("base_commit_sha", sa.String(80), nullable=False, server_default=""),
        sa.Column("head_commit_sha", sa.String(80), nullable=False, server_default=""),
        sa.Column("patch_artifact_id", sa.Integer(), sa.ForeignKey("artifacts.id"), nullable=True),
        sa.Column("merge_request_id", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=False, server_default=""),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        _ts(),
    )
    for name, cols in [
        ("ix_delivery_runs_organization_id", ["organization_id"]),
        ("ix_delivery_runs_pipeline_id", ["pipeline_id"]),
        ("ix_delivery_runs_repository_id", ["repository_id"]),
        ("ix_delivery_runs_project_id", ["project_id"]),
        ("ix_delivery_runs_task_id", ["task_id"]),
        ("ix_delivery_runs_artifact_bundle_key", ["artifact_bundle_key"]),
        ("ix_delivery_runs_status", ["status"]),
        ("ix_delivery_runs_created_at", ["created_at"]),
    ]:
        op.create_index(name, "delivery_runs", cols)

    op.create_table(
        "delivery_artifacts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("delivery_run_id", sa.Integer(), sa.ForeignKey("delivery_runs.id"), nullable=False),
        sa.Column("artifact_id", sa.Integer(), sa.ForeignKey("artifacts.id"), nullable=False),
        sa.Column("logical_path", sa.String(500), nullable=False, server_default=""),
        sa.Column("status", sa.String(32), nullable=False, server_default="materialized"),
        _ts(),
    )
    op.create_index("ix_delivery_artifacts_organization_id", "delivery_artifacts", ["organization_id"])
    op.create_index("ix_delivery_artifacts_delivery_run_id", "delivery_artifacts", ["delivery_run_id"])
    op.create_index("ix_delivery_artifacts_artifact_id", "delivery_artifacts", ["artifact_id"])

    op.create_table(
        "repository_test_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("delivery_run_id", sa.Integer(), sa.ForeignKey("delivery_runs.id"), nullable=False),
        sa.Column("profile_id", sa.Integer(), sa.ForeignKey("repository_test_profiles.id"), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="queued"),
        sa.Column("summary_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("log_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        _ts(),
    )
    op.create_index("ix_repository_test_runs_organization_id", "repository_test_runs", ["organization_id"])
    op.create_index("ix_repository_test_runs_delivery_run_id", "repository_test_runs", ["delivery_run_id"])
    op.create_index("ix_repository_test_runs_status", "repository_test_runs", ["status"])

    op.create_table(
        "repository_reviews",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("delivery_run_id", sa.Integer(), sa.ForeignKey("delivery_runs.id"), nullable=False),
        sa.Column("reviewer_member_id", sa.Integer(), sa.ForeignKey("members.id"), nullable=True),
        sa.Column("reviewer_agent_id", sa.Integer(), sa.ForeignKey("agents.id"), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("verdict", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("findings_json", sa.Text(), nullable=False, server_default="[]"),
        _ts(),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_repository_reviews_organization_id", "repository_reviews", ["organization_id"])
    op.create_index("ix_repository_reviews_delivery_run_id", "repository_reviews", ["delivery_run_id"])
    op.create_index("ix_repository_reviews_status", "repository_reviews", ["status"])

    op.create_table(
        "repository_merge_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("repository_id", sa.Integer(), sa.ForeignKey("repositories.id"), nullable=False),
        sa.Column("delivery_run_id", sa.Integer(), sa.ForeignKey("delivery_runs.id"), nullable=False, unique=True),
        sa.Column("provider", sa.String(40), nullable=False, server_default="local"),
        sa.Column("external_id", sa.String(160), nullable=False, server_default=""),
        sa.Column("title", sa.String(240), nullable=False, server_default=""),
        sa.Column("source_branch", sa.String(180), nullable=False),
        sa.Column("target_branch", sa.String(180), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="open"),
        sa.Column("url", sa.String(1000), nullable=False, server_default=""),
        sa.Column("merge_commit_sha", sa.String(80), nullable=False, server_default=""),
        _ts(), sa.Column("merged_at", sa.DateTime(), nullable=True), sa.Column("closed_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_repository_merge_requests_organization_id", "repository_merge_requests", ["organization_id"])
    op.create_index("ix_repository_merge_requests_repository_id", "repository_merge_requests", ["repository_id"])
    op.create_index("ix_repository_merge_requests_delivery_run_id", "repository_merge_requests", ["delivery_run_id"], unique=True)
    op.create_index("ix_repository_merge_requests_status", "repository_merge_requests", ["status"])
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("delivery_runs") as batch:
            batch.create_foreign_key(
                "fk_delivery_runs_merge_request_id",
                "repository_merge_requests",
                ["merge_request_id"],
                ["id"],
            )
    else:
        op.create_foreign_key(
            "fk_delivery_runs_merge_request_id",
            "delivery_runs",
            "repository_merge_requests",
            ["merge_request_id"],
            ["id"],
        )

    op.create_table(
        "repository_conflicts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("delivery_run_id", sa.Integer(), sa.ForeignKey("delivery_runs.id"), nullable=False),
        sa.Column("path", sa.String(500), nullable=False, server_default=""),
        sa.Column("conflict_type", sa.String(64), nullable=False, server_default="content"),
        sa.Column("status", sa.String(32), nullable=False, server_default="open"),
        sa.Column("resolution", sa.Text(), nullable=False, server_default=""),
        _ts(), sa.Column("resolved_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_repository_conflicts_organization_id", "repository_conflicts", ["organization_id"])
    op.create_index("ix_repository_conflicts_delivery_run_id", "repository_conflicts", ["delivery_run_id"])
    op.create_index("ix_repository_conflicts_status", "repository_conflicts", ["status"])

    op.create_table(
        "repository_rollbacks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("repository_id", sa.Integer(), sa.ForeignKey("repositories.id"), nullable=False),
        sa.Column("merge_request_id", sa.Integer(), sa.ForeignKey("repository_merge_requests.id"), nullable=True),
        sa.Column("requested_by_member_id", sa.Integer(), sa.ForeignKey("members.id"), nullable=True),
        sa.Column("reverted_commit_sha", sa.String(80), nullable=False),
        sa.Column("rollback_commit_sha", sa.String(80), nullable=False, server_default=""),
        sa.Column("status", sa.String(32), nullable=False, server_default="queued"),
        sa.Column("reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("error", sa.Text(), nullable=False, server_default=""),
        _ts(), sa.Column("completed_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_repository_rollbacks_organization_id", "repository_rollbacks", ["organization_id"])
    op.create_index("ix_repository_rollbacks_repository_id", "repository_rollbacks", ["repository_id"])


def downgrade():
    op.drop_table("repository_rollbacks")
    op.drop_table("repository_conflicts")
    op.drop_constraint("fk_delivery_runs_merge_request_id", "delivery_runs", type_="foreignkey")
    op.drop_table("repository_merge_requests")
    op.drop_table("repository_reviews")
    op.drop_table("repository_test_runs")
    op.drop_table("delivery_artifacts")
    op.drop_table("delivery_runs")
    op.drop_table("delivery_pipelines")
    op.drop_table("repository_test_profiles")
    op.drop_table("repository_identity_credentials")
    op.drop_table("repositories")
    op.drop_index("ix_api_keys_member_id", table_name="api_keys")
    op.drop_constraint("fk_api_keys_member_id_members", "api_keys", type_="foreignkey")
    op.drop_column("api_keys", "member_id")
