"""M2e.3 — hợp đồng dữ liệu vào/ra chuẩn: io_contracts (theo công ty, gắn chức danh và/hoặc bước quy trình),
task_contracts (hợp đồng + dữ liệu vào của một việc, ảnh chụp schema lúc giao), task_outputs (mỗi lần nộp kết quả,
hợp lệ hay không + lỗi); process_steps.contract_id, process_step_runs.output_json."""
import sqlalchemy as sa
from alembic import op

revision = "0049_io_contracts"
down_revision = "0048_runtime_rules"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "io_contracts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("position_id", sa.Integer(), sa.ForeignKey("positions.id"), nullable=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("input_schema", sa.JSON(), nullable=True),
        sa.Column("output_schema", sa.JSON(), nullable=True),
        sa.Column("acceptance", sa.JSON(), nullable=True),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("outcome_field", sa.String(80), nullable=False, server_default=""),
        sa.Column("template_key", sa.String(64), nullable=False, server_default=""),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    for c in ("organization_id", "company_id", "position_id"):
        op.create_index(f"ix_io_contracts_{c}", "io_contracts", [c])
    op.create_table(
        "task_contracts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("tasks.id"), nullable=False, unique=True),
        sa.Column("contract_id", sa.Integer(), sa.ForeignKey("io_contracts.id"), nullable=True),
        sa.Column("contract_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("name", sa.String(200), nullable=False, server_default=""),
        sa.Column("output_schema", sa.JSON(), nullable=True),
        sa.Column("acceptance", sa.JSON(), nullable=True),
        sa.Column("outcome_field", sa.String(80), nullable=False, server_default=""),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("input_json", sa.JSON(), nullable=True),
        sa.Column("input_errors", sa.JSON(), nullable=True),
        sa.Column("step_run_id", sa.Integer(), sa.ForeignKey("process_step_runs.id"), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="open"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_errors", sa.JSON(), nullable=True),
        sa.Column("accepted_output_id", sa.Integer(), nullable=True),
        sa.Column("escalated_to_member_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_task_contracts_contract_id", "task_contracts", ["contract_id"])
    op.create_table(
        "task_outputs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=True),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("tasks.id"), nullable=False),
        sa.Column("contract_id", sa.Integer(), sa.ForeignKey("io_contracts.id"), nullable=True),
        sa.Column("member_id", sa.Integer(), sa.ForeignKey("members.id"), nullable=True),
        sa.Column("position_id", sa.Integer(), nullable=True),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("output_json", sa.JSON(), nullable=True),
        sa.Column("valid", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("errors", sa.JSON(), nullable=True),
        sa.Column("via", sa.String(16), nullable=False, server_default="api"),
        sa.Column("run_id", sa.String(120), nullable=False, server_default=""),
        sa.Column("session_key", sa.String(240), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    for c in ("organization_id", "company_id", "task_id", "contract_id", "member_id", "created_at"):
        op.create_index(f"ix_task_outputs_{c}", "task_outputs", [c])
    with op.batch_alter_table("process_steps") as b:     # batch: SQLite không ALTER thêm khoá ngoại được
        b.add_column(sa.Column("contract_id", sa.Integer(), sa.ForeignKey("io_contracts.id", name="fk_process_steps_contract_id"),
                               nullable=True))
    op.add_column("process_step_runs", sa.Column("output_json", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("process_step_runs", "output_json")
    with op.batch_alter_table("process_steps") as b:
        b.drop_column("contract_id")
    op.drop_table("task_outputs")
    op.drop_table("task_contracts")
    op.drop_table("io_contracts")
