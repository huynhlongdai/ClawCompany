"""M2c D5 — KPI chia tầng: kpi_definitions (công ty → phòng → chức danh → seat, nối mục tiêu
executive_goals/portfolio_objectives, nguồn số tự tính hoặc nhập tay), kpi_measurements (số theo kỳ)."""
import sqlalchemy as sa
from alembic import op

revision = "0040_kpi_cascade"
down_revision = "0039_process_map"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "kpi_definitions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("level", sa.String(16), nullable=False, server_default='company'),
        sa.Column("department_id", sa.Integer(), sa.ForeignKey("departments.id"), nullable=True),
        sa.Column("position_id", sa.Integer(), sa.ForeignKey("positions.id"), nullable=True),
        sa.Column("member_id", sa.Integer(), sa.ForeignKey("members.id"), nullable=True),
        sa.Column("parent_id", sa.Integer(), sa.ForeignKey("kpi_definitions.id"), nullable=True),
        sa.Column("goal_id", sa.Integer(), sa.ForeignKey("executive_goals.id"), nullable=True),
        sa.Column("objective_id", sa.Integer(), sa.ForeignKey("portfolio_objectives.id"), nullable=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("unit", sa.String(40), nullable=False, server_default=''),
        sa.Column("target", sa.Float(), nullable=True),
        sa.Column("direction", sa.String(8), nullable=False, server_default='up'),
        sa.Column("period", sa.String(16), nullable=False, server_default='month'),
        sa.Column("metric", sa.String(40), nullable=False, server_default='manual'),
        sa.Column("process_id", sa.Integer(), sa.ForeignKey("processes.id"), nullable=True),
        sa.Column("weight", sa.Float(), nullable=False, server_default='1.0'),
        sa.Column("source", sa.String(24), nullable=False, server_default='custom'),
        sa.Column("status", sa.String(16), nullable=False, server_default='active'),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_kpi_definitions_organization_id", "kpi_definitions", ["organization_id"])
    op.create_index("ix_kpi_definitions_company_id", "kpi_definitions", ["company_id"])
    op.create_index("ix_kpi_definitions_member_id", "kpi_definitions", ["member_id"])
    op.create_index("ix_kpi_definitions_parent_id", "kpi_definitions", ["parent_id"])
    op.create_table(
        "kpi_measurements",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kpi_id", sa.Integer(), sa.ForeignKey("kpi_definitions.id"), nullable=False),
        sa.Column("period_key", sa.String(16), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("source", sa.String(16), nullable=False, server_default='manual'),
        sa.Column("note", sa.String(400), nullable=False, server_default=''),
        sa.Column("recorded_by_member_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_kpi_measurements_kpi_id", "kpi_measurements", ["kpi_id"])
    op.create_index("ix_kpi_measurements_period_key", "kpi_measurements", ["period_key"])
    op.create_index("ix_kpi_measurements_created_at", "kpi_measurements", ["created_at"])


def downgrade() -> None:
    op.drop_table("kpi_measurements")
    op.drop_table("kpi_definitions")

