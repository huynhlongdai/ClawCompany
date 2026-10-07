"""M2 — Đội ngũ: bảng ``invitations`` + ``user_organization_access.status``.

``status`` = "revoked" chặn ngay token cũ của người bị thu quyền (role đọc lại từ
DB mỗi request thay vì tin JWT)."""
import sqlalchemy as sa
from alembic import op

revision = "0028_team_invitations"
down_revision = "0027_strategy_plans"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("user_organization_access",
                  sa.Column("status", sa.String(length=24), nullable=False, server_default="active"))
    op.create_table(
        "invitations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=True),
        sa.Column("department_id", sa.Integer(), sa.ForeignKey("departments.id"), nullable=True),
        sa.Column("manager_member_id", sa.Integer(), sa.ForeignKey("members.id"), nullable=True),
        sa.Column("member_id", sa.Integer(), sa.ForeignKey("members.id"), nullable=True),
        sa.Column("email", sa.String(length=240), nullable=False),
        sa.Column("display_name", sa.String(length=160), nullable=False, server_default=""),
        sa.Column("role", sa.String(length=24), nullable=False, server_default="member"),
        sa.Column("job_title", sa.String(length=160), nullable=False, server_default=""),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="pending"),
        sa.Column("invited_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("accepted_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("accepted_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_invitations_organization_id", "invitations", ["organization_id"])
    op.create_index("ix_invitations_email", "invitations", ["email"])
    op.create_index("ix_invitations_status", "invitations", ["status"])
    op.create_index("ix_invitations_token_hash", "invitations", ["token_hash"], unique=True)


def downgrade() -> None:
    op.drop_table("invitations")
    op.drop_column("user_organization_access", "status")
