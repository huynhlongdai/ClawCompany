"""D1.3 — task biết mục tiêu, task cha và các task đang chặn nó.

Bốn cột mới trên ``tasks`` (parent_task_id, goal_id, due_at,
acceptance_criteria) và bảng ``task_dependencies``.

Không backfill: task cũ không có cha/mục tiêu là đúng sự thật — chưa ai từng
nối chúng. Đoán mục tiêu từ tên dự án sẽ tạo ra liên kết không ai đặt.
"""
import sqlalchemy as sa
from alembic import op

revision = "0018_task_graph"
down_revision = "0017_v37_work_memory_rooms"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("tasks") as batch:
        batch.add_column(sa.Column("parent_task_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("goal_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("due_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("acceptance_criteria", sa.Text(), nullable=False,
                                   server_default=""))
        batch.create_foreign_key("fk_tasks_parent_task", "tasks", ["parent_task_id"], ["id"])
        batch.create_foreign_key("fk_tasks_goal", "executive_goals", ["goal_id"], ["id"])
    op.create_index("ix_tasks_parent_task_id", "tasks", ["parent_task_id"])
    op.create_index("ix_tasks_goal_id", "tasks", ["goal_id"])

    op.create_table(
        "task_dependencies",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("tasks.id"), nullable=False),
        sa.Column("blocked_by_task_id", sa.Integer(), sa.ForeignKey("tasks.id"), nullable=False),
        sa.Column("created_by_member_id", sa.Integer(), sa.ForeignKey("members.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("task_id", "blocked_by_task_id", name="uq_task_dependency"),
    )
    op.create_index("ix_task_dependencies_task_id", "task_dependencies", ["task_id"])
    op.create_index("ix_task_dependencies_blocked_by_task_id", "task_dependencies",
                    ["blocked_by_task_id"])


def downgrade() -> None:
    op.drop_index("ix_task_dependencies_blocked_by_task_id", table_name="task_dependencies")
    op.drop_index("ix_task_dependencies_task_id", table_name="task_dependencies")
    op.drop_table("task_dependencies")
    op.drop_index("ix_tasks_goal_id", table_name="tasks")
    op.drop_index("ix_tasks_parent_task_id", table_name="tasks")
    with op.batch_alter_table("tasks") as batch:
        batch.drop_constraint("fk_tasks_goal", type_="foreignkey")
        batch.drop_constraint("fk_tasks_parent_task", type_="foreignkey")
        batch.drop_column("acceptance_criteria")
        batch.drop_column("due_at")
        batch.drop_column("goal_id")
        batch.drop_column("parent_task_id")
