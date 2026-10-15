"""M5b việc 9 — kho tri thức hợp nhất (nguồn/hash/phạm vi agent), lỗ hổng kiến thức, khoá học."""
import sqlalchemy as sa
from alembic import op

revision = "0033_learning"
down_revision = "0032_agent_profile_versions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("knowledge_documents") as batch:
        batch.add_column(sa.Column("source_url", sa.String(length=1000), nullable=False, server_default=""))
        batch.add_column(sa.Column("content_hash", sa.String(length=64), nullable=False, server_default=""))
        batch.add_column(sa.Column("synced_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("agent_id", sa.Integer(), nullable=True))
        batch.create_foreign_key("fk_knowledge_documents_agent_id", "agents", ["agent_id"], ["id"])
    op.create_index("ix_knowledge_documents_content_hash", "knowledge_documents", ["content_hash"])
    op.create_index("ix_knowledge_documents_agent_id", "knowledge_documents", ["agent_id"])
    op.create_table(
        "knowledge_gaps",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("member_id", sa.Integer(), sa.ForeignKey("members.id"), nullable=True),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("question_key", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("source", sa.String(length=24), nullable=False, server_default="search"),
        sa.Column("task_id", sa.Integer(), nullable=True),
        sa.Column("count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="open"),
        sa.Column("resolved_document_id", sa.Integer(), sa.ForeignKey("knowledge_documents.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
    )
    for c in ("organization_id", "member_id", "question_key", "status", "created_at"):
        op.create_index(f"ix_knowledge_gaps_{c}", "knowledge_gaps", [c])
    op.create_table(
        "courses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=True),
        sa.Column("title", sa.String(length=220), nullable=False),
        sa.Column("goal", sa.Text(), nullable=False, server_default=""),
        sa.Column("document_ids", sa.JSON(), nullable=True),
        sa.Column("study_hour", sa.Integer(), nullable=True),
        sa.Column("study_tz", sa.String(length=64), nullable=False, server_default="Asia/Ho_Chi_Minh"),
        sa.Column("pass_score", sa.Integer(), nullable=False, server_default="80"),
        sa.Column("quiz", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="active"),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_courses_organization_id", "courses", ["organization_id"])
    op.create_table(
        "course_enrollments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("course_id", sa.Integer(), sa.ForeignKey("courses.id"), nullable=False),
        sa.Column("agent_id", sa.Integer(), sa.ForeignKey("agents.id"), nullable=False),
        sa.Column("module_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="learning"),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("certified_at", sa.DateTime(), nullable=True),
        sa.Column("last_session_at", sa.DateTime(), nullable=True),
        sa.Column("log", sa.JSON(), nullable=True),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("course_id", "agent_id", name="uq_course_enrollments_course_agent"),
    )
    op.create_index("ix_course_enrollments_course_id", "course_enrollments", ["course_id"])
    op.create_index("ix_course_enrollments_agent_id", "course_enrollments", ["agent_id"])
    op.create_index("ix_course_enrollments_status", "course_enrollments", ["status"])


def downgrade() -> None:
    op.drop_table("course_enrollments")
    op.drop_table("courses")
    op.drop_table("knowledge_gaps")
    op.drop_index("ix_knowledge_documents_agent_id", table_name="knowledge_documents")
    op.drop_index("ix_knowledge_documents_content_hash", table_name="knowledge_documents")
    with op.batch_alter_table("knowledge_documents") as b:
        b.drop_constraint("fk_knowledge_documents_agent_id", type_="foreignkey")
        for c in ("agent_id", "synced_at", "content_hash", "source_url"):
            b.drop_column(c)
