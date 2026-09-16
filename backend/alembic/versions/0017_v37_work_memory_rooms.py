"""v37 — sổ ghi công việc và phòng họp có chủ toạ.

Hai bảng mới (``task_journal_entries``, ``room_conductor_runs``) và sáu cột thêm
vào ``collaboration_rooms``.

Vì sao migration này tồn tại: đo được trong `_reports/work-memory-gap.md` rằng
10/12 dữ kiện công việc mà công ty đã biết không đi vào prompt của agent, và
OpenClaw không có tầng bộ nhớ nào cho *một công việc* (năm tầng của nó đều
per-agent hoặc per-session).

Không backfill dữ liệu: sổ ghi bắt đầu từ rỗng là câu trả lời đúng. Một task cũ
chưa từng được ghi sổ thì đúng là chưa có lịch sử, và bịa ra lịch sử từ
``company_events`` sẽ tạo ra những dòng "đã làm gì" mà không ai từng viết.
"""
import sqlalchemy as sa
from alembic import op

revision = "0017_v37_work_memory_rooms"
down_revision = "0016_v36_metrics_calendar"
branch_labels = None
depends_on = None


ROOM_COLUMNS = (
    ("chair_member_id", sa.Integer(), True, None),
    ("cost_budget_usd", sa.Float(), False, "0"),
    ("cost_spent_usd", sa.Float(), False, "0"),
    ("stall_count", sa.Integer(), False, "0"),
    ("stopped_reason", sa.String(length=32), False, "''"),
)


def upgrade() -> None:
    op.create_table(
        "task_journal_entries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("tasks.id"), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("actor_member_id", sa.Integer(), sa.ForeignKey("members.id"), nullable=True),
        sa.Column("kind", sa.String(length=32), nullable=False, server_default="note"),
        sa.Column("summary", sa.String(length=400), nullable=False, server_default=""),
        sa.Column("detail", sa.Text(), nullable=False, server_default=""),
        sa.Column("runtime_run_id", sa.String(length=160), nullable=False, server_default=""),
        sa.Column("runtime_session_key", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("outcome", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("cost_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        # Hai lượt ghi song song không thể chiếm cùng một số thứ tự.
        sa.UniqueConstraint("task_id", "seq", name="uq_task_journal_seq"),
    )
    op.create_index("ix_task_journal_task", "task_journal_entries", ["task_id"])
    op.create_index("ix_task_journal_org", "task_journal_entries", ["organization_id"])
    op.create_index("ix_task_journal_kind", "task_journal_entries", ["kind"])
    op.create_index("ix_task_journal_created", "task_journal_entries", ["created_at"])

    op.create_table(
        "room_conductor_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("room_id", sa.Integer(), sa.ForeignKey("collaboration_rooms.id"), nullable=False),
        sa.Column("turn_id", sa.Integer(), sa.ForeignKey("room_turns.id"), nullable=True),
        sa.Column("speaker_member_id", sa.Integer(), sa.ForeignKey("members.id"), nullable=False),
        sa.Column("runtime_agent_id", sa.String(length=160), nullable=False, server_default=""),
        sa.Column("runtime_session_key", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("runtime_run_id", sa.String(length=160), nullable=False, server_default=""),
        sa.Column("prompt_chars", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reply_chars", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("elapsed_seconds", sa.Float(), nullable=False, server_default="0"),
        sa.Column("cost_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="ok"),
        sa.Column("error", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_room_conductor_room", "room_conductor_runs", ["room_id"])
    op.create_index("ix_room_conductor_org", "room_conductor_runs", ["organization_id"])
    op.create_index("ix_room_conductor_speaker", "room_conductor_runs", ["speaker_member_id"])
    op.create_index("ix_room_conductor_status", "room_conductor_runs", ["status"])
    op.create_index("ix_room_conductor_created", "room_conductor_runs", ["created_at"])

    # SQLite không ALTER được cột có FK tại chỗ; batch_alter_table lo phần đó
    # bằng cách tạo bảng mới rồi copy. Bài học từ migration 0001.
    with op.batch_alter_table("collaboration_rooms") as batch:
        for name, type_, nullable, default in ROOM_COLUMNS:
            batch.add_column(sa.Column(name, type_, nullable=nullable,
                                       server_default=default))
    op.create_index("ix_collab_room_chair", "collaboration_rooms", ["chair_member_id"])


def downgrade() -> None:
    op.drop_index("ix_collab_room_chair", table_name="collaboration_rooms")
    with op.batch_alter_table("collaboration_rooms") as batch:
        for name, _, _, _ in reversed(ROOM_COLUMNS):
            batch.drop_column(name)

    for index in ("ix_room_conductor_created", "ix_room_conductor_status",
                  "ix_room_conductor_speaker", "ix_room_conductor_org",
                  "ix_room_conductor_room"):
        op.drop_index(index, table_name="room_conductor_runs")
    op.drop_table("room_conductor_runs")

    for index in ("ix_task_journal_created", "ix_task_journal_kind",
                  "ix_task_journal_org", "ix_task_journal_task"):
        op.drop_index(index, table_name="task_journal_entries")
    op.drop_table("task_journal_entries")
