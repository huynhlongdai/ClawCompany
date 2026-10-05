"""D1.4 — mỗi lượt agent làm một task là một hàng, và task có người giữ.

Bảng ``task_runs`` và cột ``tasks.checkout_run_id``. Cột này chỉ đổi qua
``task_lifecycle.checkout/release`` bằng UPDATE có điều kiện, nên hai lượt
chạy không thể cùng nhận một task (kiểm bằng test song song trên Postgres).

Không backfill từ ``tasks.runtime_run_id``: cột đó chỉ giữ lượt cuối, các lượt
trước đã bị ghi đè; dựng lại một lượt từ nó sẽ thiếu giờ bắt đầu, chi phí và
kết cục — tức là một hàng nửa thật.
"""
import sqlalchemy as sa
from alembic import op

revision = "0019_task_runs"
down_revision = "0018_task_graph"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "task_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("tasks.id"), nullable=False),
        sa.Column("member_id", sa.Integer(), sa.ForeignKey("members.id"), nullable=True),
        sa.Column("trigger_kind", sa.String(length=32), nullable=False, server_default="manual"),
        sa.Column("wakeup_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="queued"),
        sa.Column("session_key", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("runtime_run_id", sa.String(length=160), nullable=False, server_default=""),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.Column("cost_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("tokens_in", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tokens_out", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    for col in ("organization_id", "task_id", "member_id", "status", "runtime_run_id"):
        op.create_index(f"ix_task_runs_{col}", "task_runs", [col])
    with op.batch_alter_table("tasks") as batch:
        batch.add_column(sa.Column("checkout_run_id", sa.Integer(), nullable=True))
    op.create_index("ix_tasks_checkout_run_id", "tasks", ["checkout_run_id"])


def downgrade() -> None:
    op.drop_index("ix_tasks_checkout_run_id", table_name="tasks")
    with op.batch_alter_table("tasks") as batch:
        batch.drop_column("checkout_run_id")
    for col in ("runtime_run_id", "status", "member_id", "task_id", "organization_id"):
        op.drop_index(f"ix_task_runs_{col}", table_name="task_runs")
    op.drop_table("task_runs")
