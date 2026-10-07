"""M3 — Nhân sự AI: bảng ``agent_file_snapshots`` (bản ClawCompany của 5 file
hồ sơ agent, để phát hiện sửa tay trên gateway và đồng bộ lại)."""
import sqlalchemy as sa
from alembic import op

revision = "0029_agent_file_snapshots"
down_revision = "0028_team_invitations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_file_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("agent_id", sa.Integer(), sa.ForeignKey("agents.id"), nullable=False),
        sa.Column("name", sa.String(length=40), nullable=False),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column("hash", sa.String(length=80), nullable=False, server_default=""),
        sa.Column("source", sa.String(length=24), nullable=False, server_default="clawcompany"),
        sa.Column("updated_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("agent_id", "name", name="uq_agent_file_snapshots_agent_name"),
    )
    op.create_index("ix_agent_file_snapshots_agent_id", "agent_file_snapshots", ["agent_id"])


def downgrade() -> None:
    op.drop_index("ix_agent_file_snapshots_agent_id", table_name="agent_file_snapshots")
    op.drop_table("agent_file_snapshots")
