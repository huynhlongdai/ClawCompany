"""M3h (P1) — hợp đồng & đối tác: biz_partners, biz_contracts (giá trị VND, hiệu lực, tự gia hạn, hạn báo trước, SLA có cấu trúc,
bản ký = record M3a, ký qua ma trận contract)."""
import sqlalchemy as sa
from alembic import op

revision = "0061_contracts"
down_revision = "0060_crm_consent"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "biz_partners",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False, server_default='supplier'),
        sa.Column("name", sa.String(220), nullable=False),
        sa.Column("tax_code", sa.String(20), nullable=False, server_default=''),
        sa.Column("contact_person", sa.String(160), nullable=False, server_default=''),
        sa.Column("phone", sa.String(40), nullable=False, server_default=''),
        sa.Column("email", sa.String(200), nullable=False, server_default=''),
        sa.Column("address", sa.Text(), nullable=False, server_default=''),
        sa.Column("rating", sa.Integer(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=False, server_default=''),
        sa.Column("status", sa.String(16), nullable=False, server_default='active'),
        sa.Column("search_text", sa.Text(), nullable=False, server_default=''),
        sa.Column("created_by_member_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_biz_partners_organization_id", "biz_partners", ["organization_id"])
    op.create_index("ix_biz_partners_company_id", "biz_partners", ["company_id"])
    op.create_table(
        "biz_contracts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("partner_id", sa.Integer(), sa.ForeignKey("biz_partners.id"), nullable=True),
        sa.Column("code", sa.String(48), nullable=False),
        sa.Column("title", sa.String(220), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False, server_default='service'),
        sa.Column("value_amount", sa.Numeric(18, 2), nullable=True),
        sa.Column("currency", sa.String(3), nullable=False, server_default='VND'),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("auto_renew", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("renewal_months", sa.Integer(), nullable=True),
        sa.Column("notice_days", sa.Integer(), nullable=True),
        sa.Column("sla", sa.JSON(), nullable=True),
        sa.Column("key_terms", sa.Text(), nullable=False, server_default=''),
        sa.Column("status", sa.String(16), nullable=False, server_default='draft'),
        sa.Column("document_id", sa.Integer(), nullable=True),
        sa.Column("owner_member_id", sa.Integer(), nullable=True),
        sa.Column("requested_by_member_id", sa.Integer(), nullable=True),
        sa.Column("approver_member_id", sa.Integer(), nullable=True),
        sa.Column("approval_id", sa.Integer(), nullable=True),
        sa.Column("decided_by_member_id", sa.Integer(), nullable=True),
        sa.Column("decided_at", sa.DateTime(), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=False, server_default=''),
        sa.Column("terminated_at", sa.DateTime(), nullable=True),
        sa.Column("notice_reminded_at", sa.DateTime(), nullable=True),
        sa.Column("end_reminded_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint('company_id', 'code', name='uq_biz_contract_code'),
    )
    op.create_index("ix_biz_contracts_organization_id", "biz_contracts", ["organization_id"])
    op.create_index("ix_biz_contracts_company_id", "biz_contracts", ["company_id"])
    op.create_index("ix_biz_contracts_partner_id", "biz_contracts", ["partner_id"])


def downgrade() -> None:
    op.drop_table("biz_contracts")
    op.drop_table("biz_partners")
