"""M4b — nấc thứ ba của ngân sách: ``soft_stop_pct`` (dừng mềm cần duyệt).

``budget_envelopes.soft_stop_pct`` NULL = không có nấc dừng mềm (hành vi D2.3
cũ: cảnh báo → hết). Có giá trị (warn_pct < soft_stop_pct < 100): khi chi tiêu
chạm nấc này, ``threshold_state='soft_stopped'`` và mỗi lượt chạy mới của việc
trong phạm vi phải có phê duyệt ``budget_soft:e<id>:t<task>`` mới được gửi.
"""
import sqlalchemy as sa
from alembic import op

revision = "0030_budget_soft_stop"
down_revision = "0029_agent_file_snapshots"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("budget_envelopes", sa.Column("soft_stop_pct", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("budget_envelopes", "soft_stop_pct")
