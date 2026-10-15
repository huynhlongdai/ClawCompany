"""M2c D6 — nhịp vận hành: rhythm_configs (giờ giao ban / báo cáo tuần theo múi giờ công ty, agent viết),
rhythm_reports (bản đã gửi; UNIQUE công ty × phạm vi × loại × kỳ)."""
import sqlalchemy as sa
from alembic import op

revision = "0041_operating_rhythm"
down_revision = "0040_kpi_cascade"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rhythm_configs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("standup_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("standup_hour", sa.Integer(), nullable=False, server_default='8'),
        sa.Column("weekly_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("weekly_dow", sa.Integer(), nullable=False, server_default='4'),
        sa.Column("weekly_hour", sa.Integer(), nullable=False, server_default='17'),
        sa.Column("timezone", sa.String(64), nullable=False, server_default='Asia/Ho_Chi_Minh'),
        sa.Column("per_department", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("agent_author", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_rhythm_configs_organization_id", "rhythm_configs", ["organization_id"])
    op.create_index("ix_rhythm_configs_company_id", "rhythm_configs", ["company_id"], unique=True)
    op.create_table(
        "rhythm_reports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("department_id", sa.Integer(), sa.ForeignKey("departments.id"), nullable=True),
        sa.Column("scope_key", sa.String(24), nullable=False, server_default=''),
        sa.Column("kind", sa.String(16), nullable=False, server_default='standup'),
        sa.Column("period_key", sa.String(16), nullable=False, server_default=''),
        sa.Column("title", sa.String(220), nullable=False, server_default=''),
        sa.Column("content", sa.Text(), nullable=False, server_default=''),
        sa.Column("fallback", sa.Text(), nullable=False, server_default=''),
        sa.Column("data_json", sa.JSON(), nullable=True),
        sa.Column("author", sa.String(120), nullable=False, server_default='system'),
        sa.Column("author_note", sa.String(400), nullable=False, server_default=''),
        sa.Column("recipients", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint('company_id', 'scope_key', 'kind', 'period_key', name='uq_rhythm_report_period'),
    )
    op.create_index("ix_rhythm_reports_organization_id", "rhythm_reports", ["organization_id"])
    op.create_index("ix_rhythm_reports_company_id", "rhythm_reports", ["company_id"])
    op.create_index("ix_rhythm_reports_created_at", "rhythm_reports", ["created_at"])


def downgrade() -> None:
    op.drop_table("rhythm_reports")
    op.drop_table("rhythm_configs")

