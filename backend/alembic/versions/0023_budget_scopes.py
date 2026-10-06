"""D2.3 — ngân sách ba nấc trên ``budget_envelopes`` (không tạo bảng mới).

``scope_type``/``scope_id``: hạn mức của công ty, phòng ban, seat, dự án hoặc
mục tiêu. ``warn_pct`` (mặc định 80): nấc cảnh báo. ``threshold_state``: nấc
đang ở (ok / warned / exhausted) để mỗi nấc chỉ kích một lần.
"""
import sqlalchemy as sa
from alembic import op

revision = "0023_budget_scopes"
down_revision = "0022_execution_policy"
branch_labels = None
depends_on = None

COLUMNS = (
    ("scope_type", sa.String(length=24), "company"),
    ("scope_id", sa.Integer(), None),
    ("warn_pct", sa.Integer(), "80"),
    ("period", sa.String(length=16), "total"),
    ("threshold_state", sa.String(length=16), "ok"),
)


def upgrade() -> None:
    for name, type_, default in COLUMNS:
        op.add_column("budget_envelopes", sa.Column(name, type_, nullable=default is None,
                                                    server_default=default))
    op.create_index("ix_budget_envelopes_scope_id", "budget_envelopes", ["scope_id"])


def downgrade() -> None:
    op.drop_index("ix_budget_envelopes_scope_id", table_name="budget_envelopes")
    for name, _, _ in reversed(COLUMNS):
        op.drop_column("budget_envelopes", name)
