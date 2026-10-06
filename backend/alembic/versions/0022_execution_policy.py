"""D2.2 — execution policy của task.

``tasks.execution_policy``: các chặng (review / approval) phải qua trước khi
task được ``done``. ``tasks.execution_state``: đang ở chặng nào, vòng thứ mấy,
lịch sử quyết định, cờ ``missing_report``. JSONB trên Postgres, JSON ở nơi khác.
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0022_execution_policy"
down_revision = "0021_wakeups"
branch_labels = None
depends_on = None

JSONX = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.add_column("tasks", sa.Column("execution_policy", JSONX, nullable=True))
    op.add_column("tasks", sa.Column("execution_state", JSONX, nullable=True))


def downgrade() -> None:
    op.drop_column("tasks", "execution_state")
    op.drop_column("tasks", "execution_policy")
