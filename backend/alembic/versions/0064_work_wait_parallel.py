"""W1 — chờ không giữ ghế + đồng thời theo ghế.

* tasks.wait_kind / wait_ref / wait_since — việc đang chờ người (duyệt / trả lời) không giữ chỗ chạy của ghế;
* task_runs.waiting_since — lượt còn mở trên gateway nhưng đang chờ duyệt lệnh exec (không tính vào chỗ chạy);
* agents.max_parallel_runs — số lượt chạy cùng lúc của ghế (mặc định 1, tối đa 3 — default, chưa chốt);
* seat_leases.max_parallel_runs — sàn của bên cho thuê cho ghế thuê (NULL = 1)."""
import sqlalchemy as sa
from alembic import op

revision = "0064_work_wait_parallel"
down_revision = "0063_business_ledger"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tasks", sa.Column("wait_kind", sa.String(16), nullable=True))
    op.add_column("tasks", sa.Column("wait_ref", sa.String(64), nullable=True))
    op.add_column("tasks", sa.Column("wait_since", sa.DateTime(), nullable=True))
    op.create_index("ix_tasks_wait_kind", "tasks", ["wait_kind"])
    op.add_column("task_runs", sa.Column("waiting_since", sa.DateTime(), nullable=True))
    op.add_column("agents", sa.Column("max_parallel_runs", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("seat_leases", sa.Column("max_parallel_runs", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("seat_leases", "max_parallel_runs")
    op.drop_column("agents", "max_parallel_runs")
    op.drop_column("task_runs", "waiting_since")
    op.drop_index("ix_tasks_wait_kind", table_name="tasks")
    op.drop_column("tasks", "wait_since")
    op.drop_column("tasks", "wait_ref")
    op.drop_column("tasks", "wait_kind")
