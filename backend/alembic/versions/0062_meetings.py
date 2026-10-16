"""M3i (P1) — họp & quyết định: meetings (biên bản nháp → chờ duyệt → đã duyệt = khoá + hồ sơ meeting_minutes M3a), meeting_actions
(việc sau họp → task), mở rộng decisions (số, người quyết, căn cứ thẩm quyền, hiệu lực, thay thế, liên kết, agent_visible).
Cột mới của decisions khai trong 0001 COLUMNS_OWNED_BY_LATER_MIGRATIONS."""
import sqlalchemy as sa
from alembic import op

revision = "0062_meetings"
down_revision = "0061_contracts"
branch_labels = None
depends_on = None

DECISION_COLS = [
    sa.Column("number", sa.String(48), nullable=True),
    sa.Column("meeting_id", sa.Integer(), nullable=True),
    sa.Column("body", sa.Text(), nullable=True),
    sa.Column("decided_by_member_id", sa.Integer(), nullable=True),
    sa.Column("decided_at", sa.DateTime(), nullable=True),
    sa.Column("authority_basis", sa.Text(), nullable=True),
    sa.Column("authority_rule_id", sa.Integer(), nullable=True),
    sa.Column("effective_from", sa.Date(), nullable=True),
    sa.Column("effective_to", sa.Date(), nullable=True),
    sa.Column("supersedes_id", sa.Integer(), nullable=True),
    sa.Column("linked", sa.JSON(), nullable=True),
    sa.Column("agent_visible", sa.Boolean(), nullable=True),
]


def upgrade() -> None:
    op.create_table(
        "meetings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("kind", sa.String(24), nullable=False, server_default='other'),
        sa.Column("title", sa.String(220), nullable=False),
        sa.Column("held_at", sa.DateTime(), nullable=False),
        sa.Column("location", sa.String(200), nullable=False, server_default=''),
        sa.Column("chair_member_id", sa.Integer(), nullable=True),
        sa.Column("secretary_member_id", sa.Integer(), nullable=True),
        sa.Column("attendee_ids", sa.JSON(), nullable=True),
        sa.Column("guests", sa.Text(), nullable=False, server_default=''),
        sa.Column("agenda", sa.Text(), nullable=False, server_default=''),
        sa.Column("notes", sa.Text(), nullable=False, server_default=''),
        sa.Column("minutes", sa.Text(), nullable=False, server_default=''),
        sa.Column("status", sa.String(16), nullable=False, server_default='draft'),
        sa.Column("rhythm_report_id", sa.Integer(), nullable=True),
        sa.Column("minutes_document_id", sa.Integer(), nullable=True),
        sa.Column("approver_member_id", sa.Integer(), nullable=True),
        sa.Column("approved_by_member_id", sa.Integer(), nullable=True),
        sa.Column("approved_at", sa.DateTime(), nullable=True),
        sa.Column("created_by_member_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_meetings_organization_id", "meetings", ["organization_id"])
    op.create_index("ix_meetings_company_id", "meetings", ["company_id"])
    op.create_table(
        "meeting_actions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("meeting_id", sa.Integer(), sa.ForeignKey("meetings.id"), nullable=False),
        sa.Column("title", sa.String(220), nullable=False),
        sa.Column("assignee_member_id", sa.Integer(), nullable=True),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("decision_id", sa.Integer(), nullable=True),
        sa.Column("task_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_meeting_actions_organization_id", "meeting_actions", ["organization_id"])
    op.create_index("ix_meeting_actions_company_id", "meeting_actions", ["company_id"])
    op.create_index("ix_meeting_actions_meeting_id", "meeting_actions", ["meeting_id"])
    with op.batch_alter_table("decisions") as b:
        for c in DECISION_COLS:
            b.add_column(c)


def downgrade() -> None:
    with op.batch_alter_table("decisions") as b:
        for c in DECISION_COLS:
            b.drop_column(c.name)
    op.drop_table("meeting_actions")
    op.drop_table("meetings")
