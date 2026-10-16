"""M3f — sản phẩm/dịch vụ & bảng giá của doanh nghiệp: catalog_products (SKU duy nhất trong công ty, chính sách riêng,
tài liệu mô tả) + catalog_prices (lịch sử giá, tiền tệ mặc định VND, hiệu lực từ/đến, duyệt đổi giá qua ma trận price_change).
(Kế hoạch đánh số 0058; M3c/M3e dời lượt sau nên lấy 0056 — chuỗi migration phải liền.)"""
import sqlalchemy as sa
from alembic import op

revision = "0056_catalog"
down_revision = "0055_document_requirements"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "catalog_products",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("sku", sa.String(64), nullable=False),
        sa.Column("name", sa.String(220), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("kind", sa.String(16), nullable=False, server_default="product"),
        sa.Column("category", sa.String(120), nullable=False, server_default=""),
        sa.Column("unit", sa.String(32), nullable=False, server_default="cái"),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("policies", sa.JSON(), nullable=True),
        sa.Column("document_id", sa.Integer(), nullable=True),
        sa.Column("search_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_by_member_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("company_id", "sku", name="uq_catalog_product_sku"),
    )
    op.create_index("ix_catalog_products_organization_id", "catalog_products", ["organization_id"])
    op.create_index("ix_catalog_products_company_id", "catalog_products", ["company_id"])
    op.create_table(
        "catalog_prices",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("catalog_products.id"), nullable=False),
        sa.Column("channel", sa.String(32), nullable=False, server_default="default"),
        sa.Column("amount", sa.Numeric(16, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="VND"),
        sa.Column("effective_from", sa.DateTime(), nullable=False),
        sa.Column("effective_to", sa.DateTime(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("previous_price_id", sa.Integer(), nullable=True),
        sa.Column("change_pct", sa.Numeric(8, 2), nullable=True),
        sa.Column("risk", sa.String(16), nullable=False, server_default="normal"),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column("approval_id", sa.Integer(), nullable=True),
        sa.Column("requested_by_member_id", sa.Integer(), nullable=True),
        sa.Column("approver_member_id", sa.Integer(), nullable=True),
        sa.Column("decided_by_member_id", sa.Integer(), nullable=True),
        sa.Column("decided_at", sa.DateTime(), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_catalog_prices_organization_id", "catalog_prices", ["organization_id"])
    op.create_index("ix_catalog_prices_company_id", "catalog_prices", ["company_id"])
    op.create_index("ix_catalog_prices_product_id", "catalog_prices", ["product_id"])


def downgrade() -> None:
    op.drop_table("catalog_prices")
    op.drop_table("catalog_products")
