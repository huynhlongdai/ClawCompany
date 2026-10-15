"""M2c D7 — lịch tuân thủ VN: company_profiles.compliance (kỳ kê khai, có lao động, chức danh kế toán),
compliance_rules (nghĩa vụ là dữ liệu sửa được, kèm căn cứ pháp lý), compliance_deadlines (hạn theo kỳ, nhắc, việc)."""
import sqlalchemy as sa
from alembic import op

revision = "0042_compliance_calendar"
down_revision = "0041_operating_rhythm"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("company_profiles") as batch:
        batch.add_column(sa.Column("compliance", sa.JSON(), nullable=True))
    op.create_table(
        "compliance_rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("key", sa.String(64), nullable=False, server_default=''),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("category", sa.String(16), nullable=False, server_default='tax'),
        sa.Column("entity_types", sa.JSON(), nullable=True),
        sa.Column("condition", sa.JSON(), nullable=True),
        sa.Column("frequency", sa.String(16), nullable=False, server_default='monthly'),
        sa.Column("due_rule", sa.JSON(), nullable=True),
        sa.Column("legal_basis", sa.Text(), nullable=False, server_default=''),
        sa.Column("note", sa.Text(), nullable=False, server_default=''),
        sa.Column("remind_days", sa.Integer(), nullable=False, server_default='7'),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("needs_review", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("effective_from", sa.Date(), nullable=True),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column("source", sa.String(16), nullable=False, server_default='default'),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_compliance_rules_organization_id", "compliance_rules", ["organization_id"])
    op.create_index("ix_compliance_rules_company_id", "compliance_rules", ["company_id"])
    op.create_table(
        "compliance_deadlines",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("rule_id", sa.Integer(), sa.ForeignKey("compliance_rules.id"), nullable=False),
        sa.Column("period_label", sa.String(32), nullable=False),
        sa.Column("statutory_date", sa.Date(), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default='upcoming'),
        sa.Column("assignee_member_id", sa.Integer(), nullable=True),
        sa.Column("task_id", sa.Integer(), nullable=True),
        sa.Column("reminded_at", sa.DateTime(), nullable=True),
        sa.Column("done_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint('rule_id', 'period_label', name='uq_compliance_deadline_period'),
    )
    op.create_index("ix_compliance_deadlines_organization_id", "compliance_deadlines", ["organization_id"])
    op.create_index("ix_compliance_deadlines_company_id", "compliance_deadlines", ["company_id"])
    op.create_index("ix_compliance_deadlines_rule_id", "compliance_deadlines", ["rule_id"])
    op.create_index("ix_compliance_deadlines_due_date", "compliance_deadlines", ["due_date"])


def downgrade() -> None:
    op.drop_table("compliance_deadlines")
    op.drop_table("compliance_rules")
    with op.batch_alter_table("company_profiles") as batch:
        batch.drop_column("compliance")

