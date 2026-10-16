"""M3j (P1) — tài chính kinh doanh đơn giản: fin_categories, fin_entries (thu/chi VND, huỷ thay xoá, liên kết sản phẩm/hợp đồng/
khách/chứng từ), fin_budgets (ngân sách tháng theo nhóm + phòng). Không phải sổ kế toán theo chế độ kế toán."""
import sqlalchemy as sa
from alembic import op

revision = "0063_business_ledger"
down_revision = "0062_meetings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "fin_categories",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("kind", sa.String(8), nullable=False),
        sa.Column("key", sa.String(40), nullable=False, server_default=''),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint('company_id', 'kind', 'name', name='uq_fin_category_name'),
    )
    op.create_index("ix_fin_categories_organization_id", "fin_categories", ["organization_id"])
    op.create_index("ix_fin_categories_company_id", "fin_categories", ["company_id"])
    op.create_table(
        "fin_entries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("kind", sa.String(8), nullable=False),
        sa.Column("category_id", sa.Integer(), sa.ForeignKey("fin_categories.id"), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default='VND'),
        sa.Column("occurred_on", sa.Date(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=''),
        sa.Column("department_id", sa.Integer(), nullable=True),
        sa.Column("partner_id", sa.Integer(), nullable=True),
        sa.Column("contact_id", sa.Integer(), nullable=True),
        sa.Column("contract_id", sa.Integer(), nullable=True),
        sa.Column("product_id", sa.Integer(), nullable=True),
        sa.Column("quantity", sa.Numeric(14, 3), nullable=True),
        sa.Column("document_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(8), nullable=False, server_default='recorded'),
        sa.Column("void_reason", sa.Text(), nullable=False, server_default=''),
        sa.Column("voided_by_member_id", sa.Integer(), nullable=True),
        sa.Column("source", sa.String(12), nullable=False, server_default='manual'),
        sa.Column("created_by_member_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_fin_entries_organization_id", "fin_entries", ["organization_id"])
    op.create_index("ix_fin_entries_company_id", "fin_entries", ["company_id"])
    op.create_index("ix_fin_entries_category_id", "fin_entries", ["category_id"])
    op.create_index("ix_fin_entries_occurred_on", "fin_entries", ["occurred_on"])
    op.create_table(
        "fin_budgets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("category_id", sa.Integer(), sa.ForeignKey("fin_categories.id"), nullable=False),
        sa.Column("department_id", sa.Integer(), nullable=True),
        sa.Column("period", sa.String(7), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("alert_pct", sa.Integer(), nullable=False, server_default='80'),
        sa.Column("alerted_at", sa.DateTime(), nullable=True),
        sa.Column("created_by_member_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint('company_id', 'category_id', 'department_id', 'period', name='uq_fin_budget'),
    )
    op.create_index("ix_fin_budgets_organization_id", "fin_budgets", ["organization_id"])
    op.create_index("ix_fin_budgets_company_id", "fin_budgets", ["company_id"])
    op.create_index("ix_fin_budgets_category_id", "fin_budgets", ["category_id"])


def downgrade() -> None:
    for t in ("fin_budgets", "fin_entries", "fin_categories"):
        op.drop_table(t)
