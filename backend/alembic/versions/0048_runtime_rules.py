"""M2e.2 — luật cứng cưỡng chế lúc chạy: company_rules + rule_violations."""
import sqlalchemy as sa
from alembic import op

revision = "0048_runtime_rules"
down_revision = "0047_company_scope"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "company_rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("position_id", sa.Integer(), sa.ForeignKey("positions.id"), nullable=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False, server_default="phrase"),
        sa.Column("pattern", sa.Text(), nullable=False, server_default=""),
        sa.Column("action", sa.String(16), nullable=False, server_default="revise"),
        sa.Column("message", sa.Text(), nullable=False, server_default=""),
        sa.Column("external_only", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("source", sa.String(16), nullable=False, server_default="manual"),
        sa.Column("source_ref", sa.String(64), nullable=False, server_default=""),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    for c in ("organization_id", "company_id", "position_id"):
        op.create_index(f"ix_company_rules_{c}", "company_rules", [c])
    op.create_table(
        "rule_violations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=True),
        sa.Column("member_id", sa.Integer(), sa.ForeignKey("members.id"), nullable=True),
        sa.Column("rule_id", sa.Integer(), sa.ForeignKey("company_rules.id"), nullable=True),
        sa.Column("agent_rid", sa.String(120), nullable=False, server_default=""),
        sa.Column("session_key", sa.String(240), nullable=False, server_default=""),
        sa.Column("run_id", sa.String(120), nullable=False, server_default=""),
        sa.Column("hook", sa.String(40), nullable=False, server_default=""),
        sa.Column("action_taken", sa.String(16), nullable=False, server_default=""),
        sa.Column("excerpt", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    for c in ("organization_id", "company_id", "member_id", "rule_id", "created_at"):
        op.create_index(f"ix_rule_violations_{c}", "rule_violations", [c])


def downgrade() -> None:
    op.drop_table("rule_violations")
    op.drop_table("company_rules")
