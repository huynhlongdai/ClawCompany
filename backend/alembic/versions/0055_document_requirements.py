"""M3d — hồ sơ bắt buộc & lưu trữ: document_requirements (danh mục sửa được theo công ty, có căn cứ + cần kiểm tra),
knowledge_documents.disposal_notified_at / disposed_at / disposed_by. (Kế hoạch đánh số 0056 cho M3d vì 0055 dành cho M3c
nạp tài liệu; M3c dời sang lượt sau nên M3d lấy 0055 — chuỗi migration phải liền.)"""
import sqlalchemy as sa
from alembic import op

revision = "0055_document_requirements"
down_revision = "0054_doc_retrieval"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "document_requirements",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("key", sa.String(64), nullable=False, server_default=""),
        sa.Column("name", sa.String(240), nullable=False),
        sa.Column("name_en", sa.String(240), nullable=False, server_default=""),
        sa.Column("pack", sa.String(24), nullable=False, server_default="all"),
        sa.Column("doc_types", sa.JSON(), nullable=True),
        sa.Column("condition", sa.JSON(), nullable=True),
        sa.Column("level", sa.String(16), nullable=False, server_default="required"),
        sa.Column("legal_basis", sa.Text(), nullable=False, server_default=""),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column("needs_review", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("source", sa.String(16), nullable=False, server_default="default"),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_document_requirements_organization_id", "document_requirements", ["organization_id"])
    op.create_index("ix_document_requirements_company_id", "document_requirements", ["company_id"])
    with op.batch_alter_table("knowledge_documents") as batch:
        batch.add_column(sa.Column("disposal_notified_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("disposed_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("disposed_by", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("knowledge_documents") as batch:
        batch.drop_column("disposed_by")
        batch.drop_column("disposed_at")
        batch.drop_column("disposal_notified_at")
    op.drop_table("document_requirements")
