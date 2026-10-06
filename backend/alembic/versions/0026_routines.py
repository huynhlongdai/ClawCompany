"""D3.4 — routines, routine_triggers, routine_runs (xem app/models/routines.py)."""
import sqlalchemy as sa
from alembic import op

revision = "0026_routines"
down_revision = "0025_inbox_escalation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "routines",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("template_key", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("runbook", sa.Text(), nullable=False, server_default=""),
        sa.Column("assignee_member_id", sa.Integer(), sa.ForeignKey("members.id"), nullable=True),
        sa.Column("department_id", sa.Integer(), sa.ForeignKey("departments.id"), nullable=True),
        sa.Column("owner_member_id", sa.Integer(), sa.ForeignKey("members.id"), nullable=True),
        sa.Column("mode", sa.String(length=16), nullable=False, server_default="create_task"),
        sa.Column("timezone", sa.String(length=64), nullable=False, server_default="Asia/Ho_Chi_Minh"),
        sa.Column("catch_up", sa.String(length=16), nullable=False, server_default="skip_missed"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("max_consecutive_failures", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("consecutive_failures", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("paused_reason", sa.String(length=300), nullable=False, server_default=""),
        sa.Column("standing_task_id", sa.Integer(), nullable=True),
        sa.Column("last_run_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_routines_organization_id", "routines", ["organization_id"])
    op.create_index("ix_routines_company_id", "routines", ["company_id"])
    op.create_index("ix_routines_assignee_member_id", "routines", ["assignee_member_id"])
    op.create_table(
        "routine_triggers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("routine_id", sa.Integer(), sa.ForeignKey("routines.id"), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False, server_default="cron"),
        sa.Column("cron", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("secret", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("next_run_at", sa.DateTime(), nullable=True),
        sa.Column("last_fired_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_routine_triggers_routine_id", "routine_triggers", ["routine_id"])
    op.create_index("ix_routine_triggers_next_run_at", "routine_triggers", ["next_run_at"])
    op.create_table(
        "routine_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("routine_id", sa.Integer(), sa.ForeignKey("routines.id"), nullable=False),
        sa.Column("trigger_id", sa.Integer(), nullable=True),
        sa.Column("trigger_kind", sa.String(length=16), nullable=False, server_default="cron"),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("scheduled_for", sa.DateTime(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="queued"),
        sa.Column("task_id", sa.Integer(), nullable=True),
        sa.Column("wakeup_id", sa.Integer(), nullable=True),
        sa.Column("task_run_id", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=False, server_default=""),
        sa.Column("payload_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("idempotency_key", name="uq_routine_runs_idempotency_key"),
    )
    op.create_index("ix_routine_runs_routine_id", "routine_runs", ["routine_id"])
    op.create_index("ix_routine_runs_status", "routine_runs", ["status"])
    op.create_index("ix_routine_runs_task_id", "routine_runs", ["task_id"])
    op.create_index("ix_routine_runs_created_at", "routine_runs", ["created_at"])


def downgrade() -> None:
    op.drop_table("routine_runs")
    op.drop_table("routine_triggers")
    op.drop_table("routines")
