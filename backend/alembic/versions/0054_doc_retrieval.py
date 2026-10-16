"""M3b — tài liệu thành tri thức agent: cắt theo đề mục (knowledge_chunks.section/section_no/search_text + GIN FTS trên
Postgres), tóm tắt cốt lõi (knowledge_documents.core_summary, versions.core_summary), mâu thuẫn lúc gửi duyệt
(versions.conflicts), company_facts, document_flags, knowledge_documents.flag_count."""
import sqlalchemy as sa
from alembic import op

revision = "0054_doc_retrieval"
down_revision = "0053_document_library"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("knowledge_chunks") as batch:
        batch.add_column(sa.Column("section", sa.String(300), nullable=False, server_default=""))
        batch.add_column(sa.Column("section_no", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("search_text", sa.Text(), nullable=False, server_default=""))
    with op.batch_alter_table("knowledge_documents") as batch:
        batch.add_column(sa.Column("core_summary", sa.Text(), nullable=False, server_default=""))
        batch.add_column(sa.Column("flag_count", sa.Integer(), nullable=False, server_default="0"))
    with op.batch_alter_table("knowledge_document_versions") as batch:
        batch.add_column(sa.Column("core_summary", sa.Text(), nullable=False, server_default=""))
        batch.add_column(sa.Column("conflicts", sa.JSON(), nullable=True))
    op.create_table(
        "company_facts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("key", sa.String(80), nullable=False),
        sa.Column("value", sa.String(500), nullable=False, server_default=""),
        sa.Column("value_num", sa.Float(), nullable=True),
        sa.Column("unit", sa.String(24), nullable=False, server_default=""),
        sa.Column("source_kind", sa.String(16), nullable=False, server_default="document"),
        sa.Column("source_doc_id", sa.Integer(), nullable=True),
        sa.Column("source_version_no", sa.Integer(), nullable=True),
        sa.Column("source_section", sa.String(300), nullable=False, server_default=""),
        sa.Column("excerpt", sa.String(500), nullable=False, server_default=""),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("updated_by_member_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    for c in ("organization_id", "company_id", "key", "source_doc_id", "status"):
        op.create_index(f"ix_company_facts_{c}", "company_facts", [c])
    op.create_table(
        "document_flags",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("document_id", sa.Integer(), sa.ForeignKey("knowledge_documents.id"), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=True),
        sa.Column("reason", sa.String(24), nullable=False),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column("member_id", sa.Integer(), nullable=True),
        sa.Column("task_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="open"),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_document_flags_document_id", "document_flags", ["document_id"])
    op.create_index("ix_document_flags_status", "document_flags", ["status"])
    if op.get_bind().dialect.name == "postgresql":
        op.execute("CREATE INDEX IF NOT EXISTS ix_knowledge_chunks_fts ON knowledge_chunks USING GIN (to_tsvector('simple', search_text))")


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP INDEX IF EXISTS ix_knowledge_chunks_fts")
    op.drop_table("document_flags")
    op.drop_table("company_facts")
    with op.batch_alter_table("knowledge_document_versions") as batch:
        batch.drop_column("conflicts")
        batch.drop_column("core_summary")
    with op.batch_alter_table("knowledge_documents") as batch:
        batch.drop_column("flag_count")
        batch.drop_column("core_summary")
    with op.batch_alter_table("knowledge_chunks") as batch:
        batch.drop_column("search_text")
        batch.drop_column("section_no")
        batch.drop_column("section")
