"""D3.5 — Hộp việc gộp theo task + approval hết hạn / leo thang.

``inbox_items``: ``task_id`` + ``group_key`` để các báo cho cùng một việc gộp
vào một dòng (``count``, ``kinds``, ``body`` giữ các dòng gần nhất).

``approvals``: ``expires_at`` (hạn duyệt), ``escalate_to_member_id`` (người
nhận khi quá hạn — mặc định là quản lý của người duyệt), ``escalated_at``.
"""
import sqlalchemy as sa
from alembic import op

revision = "0025_inbox_escalation"
down_revision = "0024_department_routing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("inbox_items", sa.Column("task_id", sa.Integer(), nullable=True))
    op.add_column("inbox_items", sa.Column("group_key", sa.String(length=160), nullable=False, server_default=""))
    op.add_column("inbox_items", sa.Column("kinds", sa.String(length=200), nullable=False, server_default=""))
    op.add_column("inbox_items", sa.Column("count", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("inbox_items", sa.Column("body", sa.Text(), nullable=False, server_default=""))
    op.create_index("ix_inbox_items_task_id", "inbox_items", ["task_id"])
    op.create_index("ix_inbox_items_group_key", "inbox_items", ["group_key"])
    with op.batch_alter_table("approvals") as batch:
        batch.add_column(sa.Column("expires_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("escalate_to_member_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("escalated_at", sa.DateTime(), nullable=True))
        batch.create_foreign_key("fk_approvals_escalate_to_member_id", "members",
                                 ["escalate_to_member_id"], ["id"])
    op.create_index("ix_approvals_expires_at", "approvals", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_approvals_expires_at", table_name="approvals")
    with op.batch_alter_table("approvals") as batch:
        batch.drop_constraint("fk_approvals_escalate_to_member_id", type_="foreignkey")
        for c in ("escalated_at", "escalate_to_member_id", "expires_at"):
            batch.drop_column(c)
    op.drop_index("ix_inbox_items_group_key", table_name="inbox_items")
    op.drop_index("ix_inbox_items_task_id", table_name="inbox_items")
    for c in ("body", "count", "kinds", "group_key", "task_id"):
        op.drop_column("inbox_items", c)
