"""M2c D8 — chẩn đoán sẵn sàng agent: readiness_assessments (bảng hỏi + kiểm tra tự động theo lớp công ty →
điểm từng lớp, điểm chung, việc cần sửa, quy trình lighthouse đề xuất)."""
import sqlalchemy as sa
from alembic import op

revision = "0043_agent_readiness"
down_revision = "0042_compliance_calendar"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "readiness_assessments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("trigger", sa.String(24), nullable=False, server_default='manual'),
        sa.Column("answers", sa.JSON(), nullable=True),
        sa.Column("score", sa.Integer(), nullable=False, server_default='0'),
        sa.Column("level", sa.String(24), nullable=False, server_default=''),
        sa.Column("layers", sa.JSON(), nullable=True),
        sa.Column("checks", sa.JSON(), nullable=True),
        sa.Column("lighthouse", sa.JSON(), nullable=True),
        sa.Column("created_by_member_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_readiness_assessments_organization_id", "readiness_assessments", ["organization_id"])
    op.create_index("ix_readiness_assessments_company_id", "readiness_assessments", ["company_id"])
    op.create_index("ix_readiness_assessments_created_at", "readiness_assessments", ["created_at"])


def downgrade() -> None:
    op.drop_table("readiness_assessments")

