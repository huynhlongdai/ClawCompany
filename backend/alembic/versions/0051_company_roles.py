"""R1 — vai trò theo công ty (company_access) + user ↔ nhiều ghế (user_seats); bỏ unique users.member_id.

Dữ liệu cũ: mỗi users.member_id → một dòng user_seats (công ty = công ty của ghế). Không tạo company_access nào:
người dùng cũ giữ nguyên phạm vi cả tổ chức theo vai trò org (tương thích)."""
import sqlalchemy as sa
from alembic import op

revision = "0051_company_roles"
down_revision = "0050_operating_time"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "company_access",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("role", sa.String(16), nullable=False, server_default="viewer"),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("user_id", "company_id", name="uq_company_access_user_company"),
    )
    for c in ("user_id", "organization_id", "company_id"):
        op.create_index(f"ix_company_access_{c}", "company_access", [c])
    op.create_table(
        "user_seats",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("member_id", sa.Integer(), sa.ForeignKey("members.id"), nullable=False),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("user_id", "company_id", name="uq_user_seats_user_company"),
        sa.UniqueConstraint("member_id", name="uq_user_seats_member"),
    )
    for c in ("user_id", "member_id", "organization_id", "company_id"):
        op.create_index(f"ix_user_seats_{c}", "user_seats", [c])
    bind = op.get_bind()
    bind.execute(sa.text(
        "INSERT INTO user_seats (user_id, member_id, organization_id, company_id, created_at) "
        "SELECT u.id, m.id, m.organization_id, m.company_id, CURRENT_TIMESTAMP FROM users u "
        "JOIN members m ON m.id = u.member_id WHERE u.member_id IS NOT NULL"))
    insp = sa.inspect(bind)
    if bind.dialect.name == "postgresql":
        for uc in insp.get_unique_constraints("users"):
            if uc.get("column_names") == ["member_id"] and uc.get("name"):
                op.drop_constraint(uc["name"], "users", type_="unique")
        for ix in insp.get_indexes("users"):
            if ix.get("unique") and ix.get("column_names") == ["member_id"]:
                op.drop_index(ix["name"], table_name="users")
    # SQLite (chỉ dùng dev/test): unique cũ không tên, không bỏ được tại chỗ; không sao vì ghế mới đi qua
    # user_seats, users.member_id chỉ là ghế chính.
    if "ix_users_member_id" not in {i["name"] for i in sa.inspect(bind).get_indexes("users")}:
        op.create_index("ix_users_member_id", "users", ["member_id"])


def downgrade() -> None:
    op.drop_index("ix_users_member_id", table_name="users")
    op.drop_table("user_seats")
    op.drop_table("company_access")
