"""M3a — thư viện tài liệu lõi: cột sổ tài liệu trên knowledge_documents, knowledge_document_versions (bất biến),
document_links, document_files (tệp gốc + sha256), sops.document_id.

Backfill tài liệu cũ: status=published, version_no=1, doc_class=document, agent_use = core nếu is_core còn lại retrieve,
doc_type đoán theo tiêu đề, doc_code = DOC-<id>, một phiên bản 1 'published' chép nội dung hiện tại."""
import re

import sqlalchemy as sa
from alembic import op

revision = "0053_document_library"
down_revision = "0052_seat_leases"
branch_labels = None
depends_on = None

COLS = [
    ("doc_code", sa.String(40), "''"), ("doc_class", sa.String(16), "'document'"), ("doc_type", sa.String(40), "'other'"),
    ("owner_position_id", sa.Integer(), None), ("owner_member_id", sa.Integer(), None), ("audience", sa.JSON(), None),
    ("sensitivity", sa.String(32), "'internal'"), ("agent_use", sa.String(16), "'retrieve'"),
    ("customer_facing", sa.Boolean(), "false"), ("lease_shareable", sa.Boolean(), "false"), ("exportable", sa.Boolean(), "false"),
    ("status", sa.String(16), "'published'"), ("version_no", sa.Integer(), "1"), ("current_version_id", sa.Integer(), None),
    ("effective_from", sa.DateTime(), None), ("effective_to", sa.DateTime(), None), ("review_interval_days", sa.Integer(), None),
    ("review_due_at", sa.DateTime(), None), ("review_notified_at", sa.DateTime(), None), ("last_reviewed_at", sa.DateTime(), None),
    ("last_reviewed_by", sa.Integer(), None), ("supersedes_id", sa.Integer(), None), ("source_of_truth", sa.String(80), "'internal'"),
    ("file_id", sa.Integer(), None), ("retention_class", sa.String(32), "''"), ("retain_until", sa.DateTime(), None),
    ("legal_hold", sa.Boolean(), "false"), ("reuse_count", sa.Integer(), "0"), ("last_used_at", sa.DateTime(), None),
]
GUESS = [(r"đổi trả|hoàn tiền|bảo hành|chính sách|policy", "policy"), (r"kịch bản|faq|câu hỏi|hỏi đáp", "faq"),
         (r"brand|thương hiệu|giọng", "brand_guide"), (r"sop|quy trình", "sop"), (r"giờ làm|kênh hỗ trợ|sổ tay|handbook", "handbook"),
         (r"giá|bảng giá|price", "price_list"), (r"hợp đồng|contract", "contract")]


def _server_default(dflt):
    if dflt is None:
        return None
    if dflt in ("true", "false"):
        return sa.text(dflt)
    return sa.text(dflt)


def upgrade() -> None:
    with op.batch_alter_table("knowledge_documents") as batch:
        for name, typ, dflt in COLS:
            batch.add_column(sa.Column(name, typ, nullable=dflt is None, server_default=_server_default(dflt)))
        batch.create_index("ix_knowledge_documents_doc_code", ["doc_code"])
        batch.create_index("ix_knowledge_documents_doc_type", ["doc_type"])
        batch.create_index("ix_knowledge_documents_status", ["status"])
        batch.create_index("ix_knowledge_documents_review_due_at", ["review_due_at"])
    op.create_table(
        "knowledge_document_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("document_id", sa.Integer(), sa.ForeignKey("knowledge_documents.id"), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
        sa.Column("title", sa.String(220), nullable=False, server_default=""),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column("content_hash", sa.String(64), nullable=False, server_default=""),
        sa.Column("file_id", sa.Integer(), nullable=True),
        sa.Column("change_note", sa.Text(), nullable=False, server_default=""),
        sa.Column("author_member_id", sa.Integer(), sa.ForeignKey("members.id"), nullable=True),
        sa.Column("author_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("approval_id", sa.Integer(), nullable=True),
        sa.Column("approver_member_id", sa.Integer(), sa.ForeignKey("members.id"), nullable=True),
        sa.Column("approved_by_member_id", sa.Integer(), sa.ForeignKey("members.id"), nullable=True),
        sa.Column("approved_at", sa.DateTime(), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=False, server_default=""),
        sa.Column("effective_from", sa.DateTime(), nullable=True),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_knowledge_document_versions_document_id", "knowledge_document_versions", ["document_id"])
    op.create_index("ix_knowledge_document_versions_status", "knowledge_document_versions", ["status"])
    op.create_table(
        "document_links",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("document_id", sa.Integer(), sa.ForeignKey("knowledge_documents.id"), nullable=False),
        sa.Column("target_type", sa.String(32), nullable=False),
        sa.Column("target_id", sa.Integer(), nullable=False),
        sa.Column("note", sa.String(300), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_document_links_document_id", "document_links", ["document_id"])
    op.create_table(
        "document_files",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=True),
        sa.Column("filename", sa.String(300), nullable=False, server_default=""),
        sa.Column("mime", sa.String(120), nullable=False, server_default="application/octet-stream"),
        sa.Column("size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.Column("extracted_chars", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("meta", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_document_files_organization_id", "document_files", ["organization_id"])
    op.create_index("ix_document_files_company_id", "document_files", ["company_id"])
    op.create_index("ix_document_files_sha256", "document_files", ["sha256"])
    with op.batch_alter_table("sops") as batch:
        batch.add_column(sa.Column("document_id", sa.Integer(), nullable=True))

    b = op.get_bind()
    rows = b.execute(sa.text("SELECT id, title, is_core, content, content_hash, created_at FROM knowledge_documents")).fetchall()
    for r in rows:
        t = (r.title or "").lower()
        typ = next((v for pat, v in GUESS if re.search(pat, t)), "other")
        b.execute(sa.text("UPDATE knowledge_documents SET doc_type=:t, doc_code=:c, agent_use=:u, status='published', version_no=1 "
                          "WHERE id=:id"), {"t": typ, "c": f"DOC-{r.id}", "u": "core" if r.is_core else "retrieve", "id": r.id})
        b.execute(sa.text("INSERT INTO knowledge_document_versions (document_id, version_no, status, title, content, content_hash, "
                          "change_note, review_note, published_at, created_at) VALUES (:d, 1, 'published', :ti, :co, :h, "
                          "'Nhập từ kho tri thức cũ (0053)', '', :ca, :ca)"),
                  {"d": r.id, "ti": r.title or "", "co": r.content or "", "h": r.content_hash or "", "ca": r.created_at})
    b.execute(sa.text("UPDATE knowledge_documents SET current_version_id = (SELECT v.id FROM knowledge_document_versions v "
                      "WHERE v.document_id = knowledge_documents.id ORDER BY v.id DESC LIMIT 1)"))


def downgrade() -> None:
    with op.batch_alter_table("sops") as batch:
        batch.drop_column("document_id")
    op.drop_table("document_files")
    op.drop_table("document_links")
    op.drop_table("knowledge_document_versions")
    with op.batch_alter_table("knowledge_documents") as batch:
        for ix in ("doc_code", "doc_type", "status", "review_due_at"):
            batch.drop_index(f"ix_knowledge_documents_{ix}")
        for name, _t, _d in reversed(COLS):
            batch.drop_column(name)
