"""M3g (P1) — khách hàng của doanh nghiệp + đồng ý xử lý dữ liệu cá nhân (Luật BVDLCN 91/2025, NĐ 356/2025): crm_contacts,
crm_consents (bằng chứng, rút đồng ý), crm_interactions (nối task / inbox / conversation), crm_data_requests (hạn NĐ 356 Đ5).
(Kế hoạch đánh số 0059; 0059 đã dùng cho ngưỡng đổi giá nên lấy 0060 — chuỗi migration phải liền.)"""
import sqlalchemy as sa
from alembic import op

revision = "0060_crm_consent"
down_revision = "0059_price_change_threshold"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "crm_contacts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False, server_default='person'),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("phone", sa.String(40), nullable=False, server_default=''),
        sa.Column("email", sa.String(200), nullable=False, server_default=''),
        sa.Column("address", sa.Text(), nullable=False, server_default=''),
        sa.Column("org_name", sa.String(200), nullable=False, server_default=''),
        sa.Column("tags", sa.JSON(), nullable=True),
        sa.Column("segment", sa.String(60), nullable=False, server_default=''),
        sa.Column("source", sa.String(24), nullable=False, server_default='manual'),
        sa.Column("owner_member_id", sa.Integer(), nullable=True),
        sa.Column("department_id", sa.Integer(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=False, server_default=''),
        sa.Column("status", sa.String(16), nullable=False, server_default='active'),
        sa.Column("restricted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("search_text", sa.Text(), nullable=False, server_default=''),
        sa.Column("created_by_member_id", sa.Integer(), nullable=True),
        sa.Column("erased_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_crm_contacts_organization_id", "crm_contacts", ["organization_id"])
    op.create_index("ix_crm_contacts_company_id", "crm_contacts", ["company_id"])
    op.create_table(
        "crm_consents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("contact_id", sa.Integer(), sa.ForeignKey("crm_contacts.id"), nullable=False),
        sa.Column("purpose", sa.String(24), nullable=False),
        sa.Column("channel", sa.String(16), nullable=False, server_default='other'),
        sa.Column("status", sa.String(16), nullable=False, server_default='granted'),
        sa.Column("granted_at", sa.DateTime(), nullable=False),
        sa.Column("evidence", sa.Text(), nullable=False, server_default=''),
        sa.Column("evidence_doc_id", sa.Integer(), nullable=True),
        sa.Column("notice_ref", sa.String(80), nullable=False, server_default=''),
        sa.Column("recorded_by_member_id", sa.Integer(), nullable=True),
        sa.Column("withdrawn_at", sa.DateTime(), nullable=True),
        sa.Column("withdrawn_reason", sa.Text(), nullable=False, server_default=''),
        sa.Column("withdrawn_by_member_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_crm_consents_organization_id", "crm_consents", ["organization_id"])
    op.create_index("ix_crm_consents_company_id", "crm_consents", ["company_id"])
    op.create_index("ix_crm_consents_contact_id", "crm_consents", ["contact_id"])
    op.create_table(
        "crm_interactions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("contact_id", sa.Integer(), sa.ForeignKey("crm_contacts.id"), nullable=False),
        sa.Column("kind", sa.String(24), nullable=False, server_default='note'),
        sa.Column("channel", sa.String(16), nullable=False, server_default=''),
        sa.Column("direction", sa.String(8), nullable=False, server_default=''),
        sa.Column("purpose", sa.String(24), nullable=False, server_default='service'),
        sa.Column("summary", sa.Text(), nullable=False, server_default=''),
        sa.Column("code", sa.String(48), nullable=False, server_default=''),
        sa.Column("params", sa.JSON(), nullable=True),
        sa.Column("task_id", sa.Integer(), nullable=True),
        sa.Column("inbox_item_id", sa.Integer(), nullable=True),
        sa.Column("conversation_id", sa.Integer(), nullable=True),
        sa.Column("member_id", sa.Integer(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_crm_interactions_organization_id", "crm_interactions", ["organization_id"])
    op.create_index("ix_crm_interactions_company_id", "crm_interactions", ["company_id"])
    op.create_index("ix_crm_interactions_contact_id", "crm_interactions", ["contact_id"])
    op.create_table(
        "crm_data_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("contact_id", sa.Integer(), sa.ForeignKey("crm_contacts.id"), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default='open'),
        sa.Column("channel", sa.String(16), nullable=False, server_default='other'),
        sa.Column("received_at", sa.DateTime(), nullable=False),
        sa.Column("ack_due_at", sa.DateTime(), nullable=False),
        sa.Column("due_at", sa.DateTime(), nullable=False),
        sa.Column("acknowledged_at", sa.DateTime(), nullable=True),
        sa.Column("requester_note", sa.Text(), nullable=False, server_default=''),
        sa.Column("handler_member_id", sa.Integer(), nullable=True),
        sa.Column("task_id", sa.Integer(), nullable=True),
        sa.Column("result_note", sa.Text(), nullable=False, server_default=''),
        sa.Column("evidence", sa.JSON(), nullable=True),
        sa.Column("reminded_at", sa.DateTime(), nullable=True),
        sa.Column("closed_at", sa.DateTime(), nullable=True),
        sa.Column("closed_by_member_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_crm_data_requests_organization_id", "crm_data_requests", ["organization_id"])
    op.create_index("ix_crm_data_requests_company_id", "crm_data_requests", ["company_id"])
    op.create_index("ix_crm_data_requests_contact_id", "crm_data_requests", ["contact_id"])


def downgrade() -> None:
    for t in ("crm_data_requests", "crm_interactions", "crm_consents", "crm_contacts"):
        op.drop_table(t)
