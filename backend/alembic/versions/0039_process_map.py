"""M2c D4 — bản đồ quy trình: processes (nhóm APQC, chức danh làm chủ), process_steps (chức danh,
SOP, thời lượng kỳ vọng, loại việc của ma trận phân quyền), process_instances + process_step_runs (mỗi bước
một task; thời gian chu trình của bước và của lần chạy)."""
import sqlalchemy as sa
from alembic import op

revision = "0039_process_map"
down_revision = "0038_company_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "processes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("category", sa.String(8), nullable=False, server_default='6'),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=''),
        sa.Column("owner_position_id", sa.Integer(), sa.ForeignKey("positions.id"), nullable=True),
        sa.Column("template_key", sa.String(64), nullable=False, server_default=''),
        sa.Column("status", sa.String(24), nullable=False, server_default='active'),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_processes_organization_id", "processes", ["organization_id"])
    op.create_index("ix_processes_company_id", "processes", ["company_id"])
    op.create_table(
        "process_steps",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("process_id", sa.Integer(), sa.ForeignKey("processes.id"), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False, server_default='1'),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("instructions", sa.Text(), nullable=False, server_default=''),
        sa.Column("position_id", sa.Integer(), sa.ForeignKey("positions.id"), nullable=True),
        sa.Column("sop_id", sa.Integer(), sa.ForeignKey("sops.id"), nullable=True),
        sa.Column("expected_minutes", sa.Integer(), nullable=True),
        sa.Column("action_type", sa.String(40), nullable=False, server_default=''),
        sa.Column("risk", sa.String(16), nullable=False, server_default=''),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_process_steps_process_id", "process_steps", ["process_id"])
    op.create_table(
        "process_instances",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("process_id", sa.Integer(), sa.ForeignKey("processes.id"), nullable=False),
        sa.Column("title", sa.String(220), nullable=False, server_default=''),
        sa.Column("status", sa.String(16), nullable=False, server_default='running'),
        sa.Column("amount_usd", sa.Float(), nullable=True),
        sa.Column("input_json", sa.JSON(), nullable=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=True),
        sa.Column("started_by_member_id", sa.Integer(), sa.ForeignKey("members.id"), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("cycle_seconds", sa.Float(), nullable=True),
    )
    op.create_index("ix_process_instances_organization_id", "process_instances", ["organization_id"])
    op.create_index("ix_process_instances_company_id", "process_instances", ["company_id"])
    op.create_index("ix_process_instances_process_id", "process_instances", ["process_id"])
    op.create_index("ix_process_instances_status", "process_instances", ["status"])
    op.create_index("ix_process_instances_started_at", "process_instances", ["started_at"])
    op.create_table(
        "process_step_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("instance_id", sa.Integer(), sa.ForeignKey("process_instances.id"), nullable=False),
        sa.Column("step_id", sa.Integer(), sa.ForeignKey("process_steps.id"), nullable=True),
        sa.Column("seq", sa.Integer(), nullable=False, server_default='1'),
        sa.Column("name", sa.String(200), nullable=False, server_default=''),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("tasks.id"), nullable=True),
        sa.Column("position_id", sa.Integer(), nullable=True),
        sa.Column("assignee_member_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default='waiting'),
        sa.Column("approval_required", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("approver_member_id", sa.Integer(), nullable=True),
        sa.Column("authority_rule_id", sa.Integer(), nullable=True),
        sa.Column("expected_minutes", sa.Integer(), nullable=True),
        sa.Column("note", sa.String(400), nullable=False, server_default=''),
        sa.Column("activated_at", sa.DateTime(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("cycle_seconds", sa.Float(), nullable=True),
    )
    op.create_index("ix_process_step_runs_instance_id", "process_step_runs", ["instance_id"])
    op.create_index("ix_process_step_runs_task_id", "process_step_runs", ["task_id"])


def downgrade() -> None:
    op.drop_table("process_step_runs")
    op.drop_table("process_instances")
    op.drop_table("process_steps")
    op.drop_table("processes")

