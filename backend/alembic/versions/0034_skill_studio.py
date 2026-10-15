"""M5b việc 10 — Skill Studio: thư viện kỹ năng công ty, phiên bản (eval + duyệt), nơi đã cài."""
import sqlalchemy as sa
from alembic import op

revision = "0034_skill_studio"
down_revision = "0033_learning"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "company_skills",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=220), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="active"),
        sa.Column("current_version_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("organization_id", "slug", name="uq_company_skills_org_slug"),
    )
    op.create_index("ix_company_skills_organization_id", "company_skills", ["organization_id"])
    op.create_table(
        "company_skill_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("skill_id", sa.Integer(), sa.ForeignKey("company_skills.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("description", sa.String(length=160), nullable=False, server_default=""),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column("source", sa.String(length=16), nullable=False, server_default="manual"),
        sa.Column("origin_agent_id", sa.Integer(), sa.ForeignKey("agents.id"), nullable=True),
        sa.Column("workshop_proposal_id", sa.String(length=160), nullable=False, server_default=""),
        sa.Column("workshop_revision_hash", sa.String(length=80), nullable=False, server_default=""),
        sa.Column("scan", sa.JSON(), nullable=True),
        sa.Column("eval_cases", sa.JSON(), nullable=True),
        sa.Column("eval_report", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="draft"),
        sa.Column("approval_id", sa.Integer(), sa.ForeignKey("approvals.id"), nullable=True),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("decided_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_company_skill_versions_skill_id", "company_skill_versions", ["skill_id"])
    op.create_index("ix_company_skill_versions_status", "company_skill_versions", ["status"])
    op.create_index("ix_company_skill_versions_workshop_proposal_id", "company_skill_versions", ["workshop_proposal_id"])
    op.create_table(
        "company_skill_installs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("skill_id", sa.Integer(), sa.ForeignKey("company_skills.id"), nullable=False),
        sa.Column("version_id", sa.Integer(), sa.ForeignKey("company_skill_versions.id"), nullable=False),
        sa.Column("agent_id", sa.Integer(), sa.ForeignKey("agents.id"), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="installed"),
        sa.Column("error", sa.Text(), nullable=False, server_default=""),
        sa.Column("installed_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("skill_id", "agent_id", name="uq_company_skill_installs_skill_agent"),
    )
    op.create_index("ix_company_skill_installs_skill_id", "company_skill_installs", ["skill_id"])
    op.create_index("ix_company_skill_installs_agent_id", "company_skill_installs", ["agent_id"])


def downgrade() -> None:
    op.drop_table("company_skill_installs")
    op.drop_table("company_skill_versions")
    op.drop_table("company_skills")
