"""D1.6 — quyền tool ba mức cho seat agent.

Bảng ``tool_permissions``. Không seed hàng nào: mặc định nằm trong code
(``services/tool_permissions.DEFAULTS``) để nâng cấp mặc định không cần
migration; bảng chỉ giữ những gì người quản trị đã chủ động đổi.
"""
import sqlalchemy as sa
from alembic import op

revision = "0020_tool_permissions"
down_revision = "0019_task_runs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tool_permissions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=True),
        sa.Column("member_id", sa.Integer(), sa.ForeignKey("members.id"), nullable=True),
        sa.Column("tool", sa.String(length=80), nullable=False),
        sa.Column("level", sa.String(length=16), nullable=False, server_default="off"),
        sa.Column("updated_by_member_id", sa.Integer(), sa.ForeignKey("members.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("organization_id", "role", "member_id", "tool", name="uq_tool_permission"),
    )
    for col in ("organization_id", "member_id", "tool"):
        op.create_index(f"ix_tool_permissions_{col}", "tool_permissions", [col])


def downgrade() -> None:
    for col in ("tool", "member_id", "organization_id"):
        op.drop_index(f"ix_tool_permissions_{col}", table_name="tool_permissions")
    op.drop_table("tool_permissions")
