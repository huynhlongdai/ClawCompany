"""M2d.3 — ngày lễ chỉ để tính hạn pháp lý: public_holidays (sửa được theo tổ chức × năm) +
compliance_deadlines.legal_due_date. Chuyển dữ liệu D7: due_date cũ (đã dời cuối tuần) → legal_due_date;
due_date = statutory_date (hạn theo lịch, agent nộp sớm, nhắc theo ngày này)."""
import sqlalchemy as sa
from alembic import op

revision = "0046_holiday_legal_due"
down_revision = "0045_kpi_history"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "public_holidays",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False, server_default="holiday"),
        sa.Column("status", sa.String(24), nullable=False, server_default="official"),
        sa.Column("source_url", sa.String(400), nullable=False, server_default=""),
        sa.Column("note", sa.String(400), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("organization_id", "day", name="uq_public_holidays_org_day"),
    )
    op.create_index("ix_public_holidays_organization_id", "public_holidays", ["organization_id"])
    op.create_index("ix_public_holidays_year", "public_holidays", ["year"])
    op.add_column("compliance_deadlines", sa.Column("legal_due_date", sa.Date(), nullable=True))
    op.execute("UPDATE compliance_deadlines SET legal_due_date = due_date, due_date = statutory_date")


def downgrade() -> None:
    op.execute("UPDATE compliance_deadlines SET due_date = legal_due_date WHERE legal_due_date IS NOT NULL")
    op.drop_column("compliance_deadlines", "legal_due_date")
    op.drop_table("public_holidays")
