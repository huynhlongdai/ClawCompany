"""D3.1 — trưởng phòng định tuyến.

``tasks.assignee_department_id``: việc giao cho một phòng (chưa/không cần chỉ
định người). Trưởng phòng (``departments.head_member_id``) được đánh thức với
lý do ``routed`` để chọn người trong phòng.

``departments.guide``: hướng dẫn phòng — đi vào gói ngữ cảnh định tuyến.
"""
import sqlalchemy as sa
from alembic import op

revision = "0024_department_routing"
down_revision = "0023_budget_scopes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("tasks") as batch:
        batch.add_column(sa.Column("assignee_department_id", sa.Integer(), nullable=True))
        batch.create_foreign_key("fk_tasks_assignee_department_id", "departments",
                                 ["assignee_department_id"], ["id"])
    op.create_index("ix_tasks_assignee_department_id", "tasks", ["assignee_department_id"])
    op.add_column("departments", sa.Column("guide", sa.Text(), nullable=False, server_default=""))


def downgrade() -> None:
    op.drop_column("departments", "guide")
    op.drop_index("ix_tasks_assignee_department_id", table_name="tasks")
    with op.batch_alter_table("tasks") as batch:
        batch.drop_constraint("fk_tasks_assignee_department_id", type_="foreignkey")
        batch.drop_column("assignee_department_id")
