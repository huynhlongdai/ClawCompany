"""M3e — vòng học tài liệu: doc_proposals (đề xuất sửa tài liệu từ cờ / lỗ hổng / eval trượt / bài học / agent → phiên bản
nháp → duyệt → ban hành → chạy lại eval) + retrieval_eval_runs (lịch sử eval theo công ty)."""
import sqlalchemy as sa
from alembic import op

revision = "0058_doc_feedback"
down_revision = "0057_doc_ingestion"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "doc_proposals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("document_id", sa.Integer(), nullable=True),
        sa.Column("version_id", sa.Integer(), nullable=True),
        sa.Column("new_document", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="open"),
        sa.Column("title", sa.String(300), nullable=False, server_default=""),
        sa.Column("rationale", sa.Text(), nullable=False, server_default=""),
        sa.Column("source_refs", sa.JSON(), nullable=True),
        sa.Column("eval_before", sa.JSON(), nullable=True),
        sa.Column("eval_after", sa.JSON(), nullable=True),
        sa.Column("eval_pending", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_by_member_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("closed_at", sa.DateTime(), nullable=True),
    )
    for col in ("organization_id", "company_id", "document_id", "version_id", "status"):
        op.create_index(f"ix_doc_proposals_{col}", "doc_proposals", [col])
    op.create_table(
        "retrieval_eval_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("trigger", sa.String(24), nullable=False, server_default="manual"),
        sa.Column("questions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("recall", sa.Float(), nullable=False, server_default="0"),
        sa.Column("top1", sa.Float(), nullable=False, server_default="0"),
        sa.Column("section_recall", sa.Float(), nullable=False, server_default="0"),
        sa.Column("misses", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    for col in ("organization_id", "company_id", "created_at"):
        op.create_index(f"ix_retrieval_eval_runs_{col}", "retrieval_eval_runs", [col])


def downgrade() -> None:
    op.drop_table("retrieval_eval_runs")
    op.drop_table("doc_proposals")
