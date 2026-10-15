"""M2b nền công ty: hồ sơ pháp nhân + hiến chương (company_profiles), chức danh (positions,
members.position_id), ma trận phân quyền (authority_rules).

Dữ liệu cũ: mỗi (công ty, phòng ban, chức danh) khác nhau đang ghi ở members.role thành một
hàng positions, định biên = số người đang ngồi, và members.position_id trỏ về đó. Báo cáo cho
= chức danh của người quản lý (nếu cùng công ty). Không đổi members.role, nên lớp tri thức
"nghề nghiệp" (khớp chữ trong chức danh) và bộ eval theo vai chạy y như trước."""
from datetime import datetime

import sqlalchemy as sa
from alembic import op

revision = "0038_company_foundation"
down_revision = "0037_a2a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "company_profiles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("legal_name", sa.String(240), nullable=False, server_default=""),
        sa.Column("entity_type", sa.String(32), nullable=False, server_default=""),
        sa.Column("tax_code", sa.String(20), nullable=False, server_default=""),
        sa.Column("legal_representative", sa.String(160), nullable=False, server_default=""),
        sa.Column("representative_title", sa.String(120), nullable=False, server_default=""),
        sa.Column("registered_address", sa.String(400), nullable=False, server_default=""),
        sa.Column("charter_capital_usd", sa.Float(), nullable=True),
        sa.Column("charter_capital_note", sa.String(200), nullable=False, server_default=""),
        sa.Column("business_lines", sa.JSON(), nullable=True),
        sa.Column("founded_on", sa.Date(), nullable=True),
        sa.Column("mission", sa.Text(), nullable=False, server_default=""),
        sa.Column("values", sa.JSON(), nullable=True),
        sa.Column("brand_voice", sa.Text(), nullable=False, server_default=""),
        sa.Column("prohibitions", sa.JSON(), nullable=True),
        sa.Column("customer_promises", sa.JSON(), nullable=True),
        sa.Column("charter_version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_company_profiles_organization_id", "company_profiles", ["organization_id"])
    op.create_index("ix_company_profiles_company_id", "company_profiles", ["company_id"], unique=True)

    op.create_table(
        "positions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("department_id", sa.Integer(), sa.ForeignKey("departments.id"), nullable=True),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("job_description", sa.Text(), nullable=False, server_default=""),
        sa.Column("responsibilities", sa.JSON(), nullable=True),
        sa.Column("kpis", sa.JSON(), nullable=True),
        sa.Column("allowed_tools", sa.JSON(), nullable=True),
        sa.Column("allowed_skills", sa.JSON(), nullable=True),
        sa.Column("headcount", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("reports_to_position_id", sa.Integer(), sa.ForeignKey("positions.id"), nullable=True),
        sa.Column("status", sa.String(24), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    for col in ("organization_id", "company_id", "department_id"):
        op.create_index(f"ix_positions_{col}", "positions", [col])

    op.create_table(
        "authority_rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("action_type", sa.String(40), nullable=False),
        sa.Column("min_amount_usd", sa.Float(), nullable=True),
        sa.Column("max_amount_usd", sa.Float(), nullable=True),
        sa.Column("min_risk", sa.String(16), nullable=False, server_default=""),
        sa.Column("approver_kind", sa.String(24), nullable=False, server_default="manager"),
        sa.Column("approver_position_id", sa.Integer(), sa.ForeignKey("positions.id"), nullable=True),
        sa.Column("agent_alone_level", sa.String(16), nullable=False, server_default=""),
        sa.Column("note", sa.String(400), nullable=False, server_default=""),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("source", sa.String(32), nullable=False, server_default="custom"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    for col in ("organization_id", "company_id", "action_type"):
        op.create_index(f"ix_authority_rules_{col}", "authority_rules", [col])

    with op.batch_alter_table("members") as batch:
        batch.add_column(sa.Column("position_id", sa.Integer(), nullable=True))
        batch.create_foreign_key("fk_members_position_id", "positions", ["position_id"], ["id"])
        batch.create_index("ix_members_position_id", ["position_id"])

    _migrate_job_titles()


def _migrate_job_titles() -> None:
    """members.role (chức danh tự do) → positions. Gộp theo (công ty, phòng, chức danh)."""
    bind = op.get_bind()
    rows = bind.execute(sa.text(
        "SELECT id, organization_id, company_id, department_id, role, manager_id FROM members "
        "WHERE company_id IS NOT NULL AND role IS NOT NULL AND TRIM(role) <> '' "
        "AND (status IS NULL OR status <> 'archived') ORDER BY id")).fetchall()
    groups: dict[tuple, list] = {}
    for r in rows:
        groups.setdefault((r.organization_id, r.company_id, r.department_id, r.role.strip()), []).append(r)
    now = datetime.utcnow()
    pos_of_member: dict[int, int] = {}
    for (org, co, dept, title), members in groups.items():
        res = bind.execute(sa.text(
            "INSERT INTO positions (organization_id, company_id, department_id, title, job_description, headcount, "
            "status, created_at, updated_at) VALUES (:o, :c, :d, :t, '', :h, 'active', :n, :n) RETURNING id"),
            {"o": org, "c": co, "d": dept, "t": title[:160], "h": max(1, len(members)), "n": now})
        pid = res.scalar()
        for m in members:
            pos_of_member[m.id] = pid
            bind.execute(sa.text("UPDATE members SET position_id = :p WHERE id = :m"), {"p": pid, "m": m.id})
    # báo cáo cho: chức danh của người quản lý đầu tiên trong nhóm
    for (org, co, dept, title), members in groups.items():
        pid = pos_of_member[members[0].id]
        boss = next((pos_of_member.get(m.manager_id) for m in members if m.manager_id in pos_of_member), None)
        if boss and boss != pid:
            bind.execute(sa.text("UPDATE positions SET reports_to_position_id = :b WHERE id = :p"), {"b": boss, "p": pid})


def downgrade() -> None:
    with op.batch_alter_table("members") as batch:
        batch.drop_index("ix_members_position_id")
        batch.drop_constraint("fk_members_position_id", type_="foreignkey")
        batch.drop_column("position_id")
    op.drop_table("authority_rules")
    op.drop_table("positions")
    op.drop_table("company_profiles")
