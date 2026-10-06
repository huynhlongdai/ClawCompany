"""D3.3 — kế hoạch mục tiêu của Nina đi qua approvals: payload (JSONB) + revision.

``approvals.status`` thêm giá trị ``revision_requested`` (cột String, không cần đổi kiểu)."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0027_strategy_plans"
down_revision = "0026_routines"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("approvals", sa.Column("payload", sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
                                         nullable=True))
    op.add_column("approvals", sa.Column("revision", sa.Integer(), nullable=False, server_default="1"))


def downgrade() -> None:
    op.drop_column("approvals", "revision")
    op.drop_column("approvals", "payload")
