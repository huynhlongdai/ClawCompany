"""M5a — phiên bản hồ sơ nhân sự AI + kết quả kiểm tra giữ vai."""
import sqlalchemy as sa
from alembic import op

revision = "0032_agent_profile_versions"
down_revision = "0031_user_locale"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_profile_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("agent_id", sa.Integer(), sa.ForeignKey("agents.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("profile_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("files_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("changed_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("note", sa.String(length=300), nullable=False, server_default=""),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("persona_score", sa.Float(), nullable=True),
        sa.Column("persona_report_json", sa.Text(), nullable=False, server_default=""),
        sa.Column("persona_checked_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("agent_id", "version", name="uq_agent_profile_versions_agent_version"),
    )
    op.create_index("ix_agent_profile_versions_organization_id", "agent_profile_versions", ["organization_id"])
    op.create_index("ix_agent_profile_versions_agent_id", "agent_profile_versions", ["agent_id"])
    op.create_index("ix_agent_profile_versions_created_at", "agent_profile_versions", ["created_at"])


def downgrade() -> None:
    op.drop_table("agent_profile_versions")
