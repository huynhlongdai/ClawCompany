"""D2.1 — hàng đợi wakeup.

Mỗi hàng là một lý do để đánh thức một seat (``assigned``, ``mentioned``,
``handoff``, ``approval_resolved``, ``blocker_cleared``, ``review_requested``,
``routine``, ``goal_created``). ``dedupe_key`` UNIQUE làm ``enqueue`` idempotent.
"""
import sqlalchemy as sa
from alembic import op

revision = "0021_wakeups"
down_revision = "0020_tool_permissions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "wakeups",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("member_id", sa.Integer(), sa.ForeignKey("members.id"), nullable=False),
        sa.Column("reason", sa.String(length=32), nullable=False),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("tasks.id"), nullable=True),
        sa.Column("payload", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("dedupe_key", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="queued"),
        sa.Column("skip_reason", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("run_id", sa.Integer(), nullable=True),
        sa.Column("coalesced_into_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("processed_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("dedupe_key", name="uq_wakeups_dedupe_key"),
    )
    for col in ("organization_id", "member_id", "reason", "task_id", "status", "created_at"):
        op.create_index(f"ix_wakeups_{col}", "wakeups", [col])


def downgrade() -> None:
    for col in ("created_at", "status", "task_id", "reason", "member_id", "organization_id"):
        op.drop_index(f"ix_wakeups_{col}", table_name="wakeups")
    op.drop_table("wakeups")
