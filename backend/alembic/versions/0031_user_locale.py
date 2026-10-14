"""i18n — ngôn ngữ giao diện của từng người dùng: ``users.locale`` ("vi" | "en").

NULL/"vi" = tiếng Việt (mặc định). Trình duyệt giữ bản sao ở cookie ``cc_locale``;
cột này để ngôn ngữ đi theo tài khoản sang máy khác.
"""
import sqlalchemy as sa
from alembic import op

revision = "0031_user_locale"
down_revision = "0030_budget_soft_stop"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("locale", sa.String(length=8), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.drop_column("locale")
