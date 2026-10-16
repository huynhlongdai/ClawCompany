"""R2 — cho thuê agent: seat_leases (hợp đồng thuê ghế) + lease_usage (đo đếm theo hợp đồng, chi phí thật + số tiền
tính cho bên thuê); task_runs.lease_id / billed_usd."""
import sqlalchemy as sa
from alembic import op

revision = "0052_seat_leases"
down_revision = "0051_company_roles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "seat_leases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False, server_default=""),
        sa.Column("offer_code", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
        sa.Column("status_reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("provider_org_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("provider_company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("provider_member_id", sa.Integer(), sa.ForeignKey("members.id"), nullable=False),
        sa.Column("provider_agent_id", sa.Integer(), sa.ForeignKey("agents.id"), nullable=False),
        sa.Column("provider_version", sa.Integer(), nullable=True),
        sa.Column("renter_org_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=True),
        sa.Column("renter_company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=True),
        sa.Column("renter_position_id", sa.Integer(), sa.ForeignKey("positions.id"), nullable=True),
        sa.Column("renter_member_id", sa.Integer(), sa.ForeignKey("members.id"), nullable=True),
        sa.Column("renter_agent_id", sa.Integer(), sa.ForeignKey("agents.id"), nullable=True),
        sa.Column("starts_at", sa.DateTime(), nullable=True),
        sa.Column("ends_at", sa.DateTime(), nullable=True),
        sa.Column("offer_expires_at", sa.DateTime(), nullable=True),
        sa.Column("price_per_task_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("price_per_hour_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("price_per_month_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("markup_pct", sa.Float(), nullable=False, server_default="0"),
        sa.Column("monthly_cost_cap_usd", sa.Float(), nullable=True),
        sa.Column("allowed_tools", sa.JSON(), nullable=True),
        sa.Column("knowledge_scope", sa.JSON(), nullable=True),
        sa.Column("data_handling", sa.Text(), nullable=False, server_default=""),
        sa.Column("approval_policy", sa.JSON(), nullable=True),
        sa.Column("change_requests", sa.JSON(), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("accepted_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("activated_at", sa.DateTime(), nullable=True),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.Column("wiped_at", sa.DateTime(), nullable=True),
        sa.Column("wipe_report", sa.JSON(), nullable=True),
    )
    for c in ("status", "provider_org_id", "provider_company_id", "provider_member_id", "provider_agent_id",
              "renter_org_id", "renter_company_id", "renter_member_id", "renter_agent_id", "ends_at"):
        op.create_index(f"ix_seat_leases_{c}", "seat_leases", [c])
    op.create_index("ix_seat_leases_offer_code", "seat_leases", ["offer_code"], unique=True)
    op.create_table(
        "lease_usage",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("lease_id", sa.Integer(), sa.ForeignKey("seat_leases.id"), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("period", sa.String(7), nullable=False),
        sa.Column("usage_event_id", sa.Integer(), sa.ForeignKey("usage_events.id"), nullable=True),
        sa.Column("task_run_id", sa.Integer(), sa.ForeignKey("task_runs.id"), nullable=True),
        sa.Column("task_id", sa.Integer(), nullable=True),
        sa.Column("session_key", sa.String(200), nullable=False, server_default=""),
        sa.Column("channel", sa.String(16), nullable=False, server_default="task"),
        sa.Column("caller", sa.String(200), nullable=False, server_default=""),
        sa.Column("quantity", sa.Float(), nullable=False, server_default="1"),
        sa.Column("cost_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("billed_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("tokens_in", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tokens_out", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    for c in ("lease_id", "period", "usage_event_id", "task_run_id", "created_at"):
        op.create_index(f"ix_lease_usage_{c}", "lease_usage", [c])
    with op.batch_alter_table("task_runs") as b:
        b.add_column(sa.Column("lease_id", sa.Integer(), nullable=True))
        b.add_column(sa.Column("billed_usd", sa.Float(), nullable=False, server_default="0"))
    op.create_index("ix_task_runs_lease_id", "task_runs", ["lease_id"])


def downgrade() -> None:
    op.drop_index("ix_task_runs_lease_id", table_name="task_runs")
    with op.batch_alter_table("task_runs") as b:
        b.drop_column("billed_usd")
        b.drop_column("lease_id")
    op.drop_table("lease_usage")
    op.drop_table("seat_leases")
