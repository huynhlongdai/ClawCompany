"""M2d.1 — quy trình v2: rẽ nhánh có điều kiện + bước song song (fan-out/fan-in).

process_steps / process_step_runs thêm depends_on (JSON: seq các bước đứng trước), condition (JSON
{field, op, value}), branch (nhãn nhánh); step runs thêm outcome + skip_reason. Quy trình tuyến tính
cũ được chuyển đổi: bước seq>1 phụ thuộc bước seq-1, bước 1 không phụ thuộc — chạy y như trước."""
import sqlalchemy as sa
from alembic import op

revision = "0044_process_branching"
down_revision = "0043_agent_readiness"
branch_labels = None
depends_on = None


def _linearize(table: str, group_col: str) -> None:
    bind = op.get_bind()
    t = sa.table(table, sa.column("id", sa.Integer), sa.column(group_col, sa.Integer),
                 sa.column("seq", sa.Integer), sa.column("depends_on", sa.JSON))
    rows = bind.execute(sa.select(t.c.id, t.c.seq)).fetchall()
    for rid, seq in rows:
        bind.execute(t.update().where(t.c.id == rid).values(depends_on=[seq - 1] if (seq or 1) > 1 else []))


def upgrade() -> None:
    for table in ("process_steps", "process_step_runs"):
        op.add_column(table, sa.Column("depends_on", sa.JSON(), nullable=True))
        op.add_column(table, sa.Column("condition", sa.JSON(), nullable=True))
        op.add_column(table, sa.Column("branch", sa.String(60), nullable=False, server_default=""))
    op.add_column("process_step_runs", sa.Column("outcome", sa.String(200), nullable=False, server_default=""))
    op.add_column("process_step_runs", sa.Column("skip_reason", sa.String(300), nullable=False, server_default=""))
    _linearize("process_steps", "process_id")
    _linearize("process_step_runs", "instance_id")


def downgrade() -> None:
    for c in ("outcome", "skip_reason"):
        op.drop_column("process_step_runs", c)
    for table in ("process_steps", "process_step_runs"):
        for c in ("depends_on", "condition", "branch"):
            op.drop_column(table, c)
