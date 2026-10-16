"""M3c — nạp & phân loại tài liệu: doc_imports (lần nạp + đề xuất phân loại/trích sự kiện, sha256 chống trùng),
doc_sources (nguồn đồng bộ url | gdrive | notion theo công ty, token mã hoá), doc_source_items (mục ngoài ↔ tài liệu).
(Kế hoạch đánh số 0055; 0055/0056 đã dùng cho M3d/M3f nên lấy 0057 — chuỗi migration phải liền.)"""
import sqlalchemy as sa
from alembic import op

revision = "0057_doc_ingestion"
down_revision = "0056_catalog"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "doc_imports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("source", sa.String(16), nullable=False, server_default="upload"),
        sa.Column("source_ref", sa.String(500), nullable=False, server_default=""),
        sa.Column("source_id", sa.Integer(), nullable=True),
        sa.Column("filename", sa.String(300), nullable=False, server_default=""),
        sa.Column("sha256", sa.String(64), nullable=False, server_default=""),
        sa.Column("status", sa.String(16), nullable=False, server_default="done"),
        sa.Column("document_id", sa.Integer(), nullable=True),
        sa.Column("version_no", sa.Integer(), nullable=True),
        sa.Column("duplicate_of_id", sa.Integer(), nullable=True),
        sa.Column("extracted_chars", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("ocr_used", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("method", sa.String(32), nullable=False, server_default=""),
        sa.Column("suggestions", sa.JSON(), nullable=True),
        sa.Column("proposals", sa.JSON(), nullable=True),
        sa.Column("proposals_status", sa.String(16), nullable=False, server_default=""),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_by_member_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    for col in ("organization_id", "company_id", "source_id", "sha256", "status", "document_id"):
        op.create_index(f"ix_doc_imports_{col}", "doc_imports", [col])
    op.create_table(
        "doc_sources",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("name", sa.String(200), nullable=False, server_default=""),
        sa.Column("config", sa.JSON(), nullable=True),
        sa.Column("credential_enc", sa.Text(), nullable=False, server_default=""),
        sa.Column("credential_hint", sa.String(16), nullable=False, server_default=""),
        sa.Column("default_doc_type", sa.String(40), nullable=False, server_default=""),
        sa.Column("interval_minutes", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("status", sa.String(24), nullable=False, server_default="needs_account"),
        sa.Column("last_synced_at", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_by_member_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_doc_sources_organization_id", "doc_sources", ["organization_id"])
    op.create_index("ix_doc_sources_company_id", "doc_sources", ["company_id"])
    op.create_table(
        "doc_source_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_id", sa.Integer(), sa.ForeignKey("doc_sources.id"), nullable=False),
        sa.Column("external_id", sa.String(300), nullable=False),
        sa.Column("title", sa.String(300), nullable=False, server_default=""),
        sa.Column("external_version", sa.String(120), nullable=False, server_default=""),
        sa.Column("sha256", sa.String(64), nullable=False, server_default=""),
        sa.Column("document_id", sa.Integer(), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_doc_source_items_source_id", "doc_source_items", ["source_id"])
    op.create_index("ix_doc_source_items_document_id", "doc_source_items", ["document_id"])


def downgrade() -> None:
    op.drop_table("doc_source_items")
    op.drop_table("doc_sources")
    op.drop_table("doc_imports")
