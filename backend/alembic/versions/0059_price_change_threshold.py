"""M3 cleanup — ngưỡng % đổi giá cần chủ duyệt (price_change) thành cài đặt theo công ty (trước: hằng số 10 trong code).
NULL = mặc định 10%."""
import sqlalchemy as sa
from alembic import op

revision = "0059_price_change_threshold"
down_revision = "0058_doc_feedback"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("company_profiles", sa.Column("price_change_high_pct", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("company_profiles", "price_change_high_pct")
