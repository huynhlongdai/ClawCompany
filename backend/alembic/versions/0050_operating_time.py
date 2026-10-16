"""M2e.4 — vận hành 24/7: giờ làm + nghỉ phép của ghế người (ghế agent luôn trực), SLA theo bước quy trình / chức danh
với đồng hồ (sla_timers), việc tới ngoài giờ của người → chuyển agent cùng chức danh hoặc xếp hàng (after_hours_routes)."""
import sqlalchemy as sa
from alembic import op

revision = "0050_operating_time"
down_revision = "0049_io_contracts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "seat_schedules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("member_id", sa.Integer(), sa.ForeignKey("members.id"), nullable=False, unique=True),
        sa.Column("timezone", sa.String(64), nullable=False, server_default="Asia/Ho_Chi_Minh"),
        sa.Column("weekly", sa.JSON(), nullable=True),
        sa.Column("observe_holidays", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.create_table(
        "seat_leaves",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("member_id", sa.Integer(), sa.ForeignKey("members.id"), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False, server_default="annual"),
        sa.Column("note", sa.String(300), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_seat_leaves_member_id", "seat_leaves", ["member_id"])
    op.create_table(
        "sla_policies",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("position_id", sa.Integer(), sa.ForeignKey("positions.id"), nullable=True),
        sa.Column("process_step_id", sa.Integer(), sa.ForeignKey("process_steps.id"), nullable=True),
        sa.Column("name", sa.String(200), nullable=False, server_default=""),
        sa.Column("first_response_minutes", sa.Integer(), nullable=True),
        sa.Column("resolution_minutes", sa.Integer(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    for c in ("organization_id", "company_id", "position_id", "process_step_id"):
        op.create_index(f"ix_sla_policies_{c}", "sla_policies", [c])
    op.create_table(
        "sla_timers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=True),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("tasks.id"), nullable=False),
        sa.Column("policy_id", sa.Integer(), sa.ForeignKey("sla_policies.id"), nullable=True),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("member_id", sa.Integer(), nullable=True),
        sa.Column("position_id", sa.Integer(), nullable=True),
        sa.Column("seat_type", sa.String(8), nullable=False, server_default=""),
        sa.Column("minutes", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("due_at", sa.DateTime(), nullable=False),
        sa.Column("met_at", sa.DateTime(), nullable=True),
        sa.Column("breached_at", sa.DateTime(), nullable=True),
        sa.Column("escalated_to_member_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="running"),
    )
    for c in ("organization_id", "company_id", "task_id", "status", "due_at"):
        op.create_index(f"ix_sla_timers_{c}", "sla_timers", [c])
    op.create_table(
        "after_hours_routes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=True),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("tasks.id"), nullable=False),
        sa.Column("from_member_id", sa.Integer(), nullable=True),
        sa.Column("to_member_id", sa.Integer(), nullable=True),
        sa.Column("position_id", sa.Integer(), nullable=True),
        sa.Column("action", sa.String(16), nullable=False),
        sa.Column("next_available_at", sa.DateTime(), nullable=True),
        sa.Column("reason", sa.String(300), nullable=False, server_default=""),
        sa.Column("status", sa.String(16), nullable=False, server_default="open"),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    for c in ("organization_id", "company_id", "task_id", "status"):
        op.create_index(f"ix_after_hours_routes_{c}", "after_hours_routes", [c])


def downgrade() -> None:
    for t in ("after_hours_routes", "sla_timers", "sla_policies", "seat_leaves", "seat_schedules"):
        op.drop_table(t)
