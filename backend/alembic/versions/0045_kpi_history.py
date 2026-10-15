"""M2d.2 — lịch sử KPI: kpi_snapshots (số đã tính theo kỳ) + tasks.completed_at (mốc "xong trong kỳ").

Backfill completed_at cho việc đang "done": lần cuối có sự kiện ``task.done`` của việc đó trong company_events;
không có sự kiện → updated_at (ghi rõ: xấp xỉ như trước)."""
import sqlalchemy as sa
from alembic import op

revision = "0045_kpi_history"
down_revision = "0044_process_branching"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tasks", sa.Column("completed_at", sa.DateTime(), nullable=True))
    op.create_index("ix_tasks_completed_at", "tasks", ["completed_at"])
    bind = op.get_bind()
    ev = bind.execute(sa.text("SELECT aggregate_id, MAX(occurred_at) FROM company_events "
                              "WHERE event_type = 'task.done' AND aggregate_type = 'task' GROUP BY aggregate_id")).fetchall()
    done = {r[0] for r in bind.execute(sa.text("SELECT id FROM tasks WHERE status = 'done'")).fetchall()}
    for agg, ts in ev:
        try:
            tid = int(agg)
        except (TypeError, ValueError):
            continue
        if tid in done and ts is not None:
            bind.execute(sa.text("UPDATE tasks SET completed_at = :ts WHERE id = :id"), {"ts": ts, "id": tid})
    bind.execute(sa.text("UPDATE tasks SET completed_at = updated_at WHERE status = 'done' AND completed_at IS NULL"))
    op.create_table(
        "kpi_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kpi_id", sa.Integer(), sa.ForeignKey("kpi_definitions.id"), nullable=False),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("period", sa.String(16), nullable=False, server_default="month"),
        sa.Column("period_key", sa.String(16), nullable=False),
        sa.Column("value", sa.Float(), nullable=True),
        sa.Column("value_source", sa.String(16), nullable=False, server_default=""),
        sa.Column("target", sa.Float(), nullable=True),
        sa.Column("progress", sa.Float(), nullable=True),
        sa.Column("health", sa.String(16), nullable=False, server_default="no_data"),
        sa.Column("trigger", sa.String(16), nullable=False, server_default="beat"),
        sa.Column("final", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("computed_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("kpi_id", "period_key", name="uq_kpi_snapshots_kpi_period"),
    )
    op.create_index("ix_kpi_snapshots_kpi_id", "kpi_snapshots", ["kpi_id"])
    op.create_index("ix_kpi_snapshots_company_id", "kpi_snapshots", ["company_id"])
    op.create_index("ix_kpi_snapshots_period_key", "kpi_snapshots", ["period_key"])


def downgrade() -> None:
    op.drop_table("kpi_snapshots")
    op.drop_index("ix_tasks_completed_at", "tasks")
    op.drop_column("tasks", "completed_at")
