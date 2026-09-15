"""v6 baseline schema, scoped to the tables that existed at the baseline.

Revision ID: 0001_baseline
Revises:

The original prototype baseline called ``Base.metadata.create_all()`` without a
``tables`` argument.  Because Alembic imports the *current* model metadata,
that made a fresh install accidentally create future-version tables before
those versioned migrations ran.  Keep the historical baseline metadata-driven
for compatibility, but pin it to the exact v6 table set so the migration chain
is deterministic on fresh databases.
"""
from alembic import op
import sqlalchemy as sa

from app.db.base import Base
import app.models  # noqa: F401

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None

BASELINE_TABLES = [
    "organizations",
    "companies",
    "departments",
    "members",
    "agents",
    "projects",
    "tasks",
    "knowledge_documents",
    "approvals",
    "inbox_items",
    "missions",
    "workflows",
    "workflow_runs",
    "automations",
    "sops",
    "decisions",
    "conversations",
    "conversation_messages",
    "customers",
    "customer_agent_assignments",
    "reports",
    "analytics_metrics",
    "audit_events",
    "integrations",
    "skills",
    "tools",
    "marketplace_templates",
    "subscriptions",
    "organization_settings",
    "role_bindings",
    "permission_policies",
    "users",
    "user_organization_access",
    "api_keys",
    "knowledge_chunks",
    "background_jobs",
]


# Cùng một lớp lỗi mà docstring trên đã kể, nhưng ở mức CỘT thay vì mức bảng.
# Bản vá cũ ghim danh sách *bảng* của v6, nhưng định nghĩa bảng vẫn lấy từ
# metadata HIỆN TẠI. Nên trên một database sạch, baseline tạo luôn những cột mà
# các migration sau mới được quyền thêm, và chuỗi migration vỡ:
#
#   0013 -> DuplicateColumn: column "row_revision" of relation "companies"
#           already exists
#
# (Đo được trên Postgres 16 thật; SQLite thì lặng lẽ cho qua vì
# ``checkfirst=True`` chỉ kiểm sự tồn tại của bảng, không kiểm cột.)
#
# Cách sửa: sau khi create_all, bỏ đúng những cột/ràng buộc mà migration sau
# sở hữu, để mỗi migration về sau thực sự làm công việc của nó. Đăng ký dưới
# đây là hợp đồng: thêm cột mới vào một bảng baseline thì phải khai ở đây kèm
# migration sở hữu nó. Test ``test_migration_chain.py`` chạy trọn chuỗi trên
# một database sạch nên sẽ đỏ nếu ai quên.
# Không kê ``api_keys.member_id`` ở đây: 0006 đã tự kiểm tra cột tồn tại
# trước khi thêm, nên nó vốn không vỡ. Bỏ cột đó đi còn làm SQLite vỡ tiếp ở
# index ``ix_api_keys_member_id`` mà model khai -- một việc vô ích.
COLUMNS_OWNED_BY_LATER_MIGRATIONS = {
    "companies": ["row_revision"],                  # 0013_v30_row_revision_counter
    "members": ["row_revision"],                    # 0013
    "projects": ["row_revision"],                   # 0013
    "tasks": ["row_revision"],                      # 0013
    "departments": ["row_revision", "status"],      # 0013, 0014
}

# 0014 tự tạo index unique này; model cũng khai nó, nên create_all sẽ tạo
# trước và 0014 sẽ vỡ vì trùng tên.
INDEXES_OWNED_BY_LATER_MIGRATIONS = [("uq_departments_company_name", "departments")]


def _tables():
    return [Base.metadata.tables[name] for name in BASELINE_TABLES]


def _strip_future_columns() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    for index, table in INDEXES_OWNED_BY_LATER_MIGRATIONS:
        if table not in existing_tables:
            continue
        if index in {i["name"] for i in inspector.get_indexes(table)}:
            op.drop_index(index, table_name=table)

    for table, columns in COLUMNS_OWNED_BY_LATER_MIGRATIONS.items():
        if table not in existing_tables:
            continue
        present = {c["name"] for c in inspector.get_columns(table)}
        pending = [c for c in columns if c in present]
        if not pending:
            continue
        # batch_alter_table thay vì drop_column trực tiếp: trên SQLite, bỏ một
        # cột đang được khoá ngoại tham chiếu sẽ vỡ
        #   "error in table api_keys after drop column: unknown column
        #    member_id in foreign key definition"
        # vì SQLite không sửa được định nghĩa FK tại chỗ. Batch mode dựng lại
        # bảng nên xử lý được; trên Postgres nó chỉ là ALTER TABLE thường.
        with op.batch_alter_table(table) as batch:
            for column in pending:
                batch.drop_column(column)


def upgrade():
    Base.metadata.create_all(bind=op.get_bind(), tables=_tables(), checkfirst=True)
    _strip_future_columns()


def downgrade():
    Base.metadata.drop_all(bind=op.get_bind(), tables=list(reversed(_tables())), checkfirst=True)
