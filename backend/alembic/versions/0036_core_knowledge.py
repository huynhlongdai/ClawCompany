"""Kiến thức cốt lõi 3 lớp: riêng agent / nghề nghiệp (chức danh) / công ty — biên dịch vào AGENTS.md."""
import sqlalchemy as sa
from alembic import op

revision = "0036_core_knowledge"
down_revision = "0035_career"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("knowledge_documents") as batch:
        batch.add_column(sa.Column("is_core", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column("role_keyword", sa.String(length=120), nullable=False, server_default=""))


def downgrade() -> None:
    with op.batch_alter_table("knowledge_documents") as batch:
        batch.drop_column("role_keyword")
        batch.drop_column("is_core")
