"""M6 việc 11 — bộ đánh giá theo vai + lượt chạy (gắn phiên bản hồ sơ agent)."""
import sqlalchemy as sa
from alembic import op

revision = "0035_career"
down_revision = "0034_skill_studio"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "eval_suites",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("title", sa.String(length=220), nullable=False),
        sa.Column("role_keyword", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("department_id", sa.Integer(), sa.ForeignKey("departments.id"), nullable=True),
        sa.Column("cases", sa.JSON(), nullable=True),
        sa.Column("k", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_eval_suites_organization_id", "eval_suites", ["organization_id"])
    op.create_table(
        "eval_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("suite_id", sa.Integer(), sa.ForeignKey("eval_suites.id"), nullable=False),
        sa.Column("agent_id", sa.Integer(), sa.ForeignKey("agents.id"), nullable=False),
        sa.Column("profile_version", sa.Integer(), nullable=True),
        sa.Column("k", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("pass_at_1", sa.Float(), nullable=False, server_default="0"),
        sa.Column("pass_k", sa.Float(), nullable=False, server_default="0"),
        sa.Column("results", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_eval_runs_suite_id", "eval_runs", ["suite_id"])
    op.create_index("ix_eval_runs_agent_id", "eval_runs", ["agent_id"])
    op.create_index("ix_eval_runs_created_at", "eval_runs", ["created_at"])


def downgrade() -> None:
    op.drop_table("eval_runs")
    op.drop_table("eval_suites")
