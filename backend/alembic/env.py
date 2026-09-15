from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool, text

from app.core.config import settings
from app.db.base import Base
import app.models  # noqa

config = context.config
config.set_main_option("sqlalchemy.url", settings.database_url)
if config.config_file_name is not None:
    fileConfig(config.config_file_name)
target_metadata = Base.metadata

# Alembic tạo ``alembic_version.version_num`` là VARCHAR(32). Sáu revision id
# của dự án này dài hơn thế -- dài nhất là
# ``0014_v31_department_status_and_unique_name`` (42 ký tự). SQLite không cưỡng
# chế độ dài VARCHAR nên lỗi ẩn hoàn toàn; trên Postgres thật, migration chạy
# tới 0010 rồi vỡ:
#
#   StringDataRightTruncation: value too long for type character varying(32)
#   UPDATE alembic_version SET version_num='0010_v14_distributed_secure_execution'
#
# Alembic dùng lại bảng đang có thay vì áp kích thước của nó, nên chỉ cần bảo
# đảm cột đủ rộng TRƯỚC khi chạy. Cách này không đổi tên revision -- tên đó
# được docs, README và test tham chiếu tới.
VERSION_NUM_LENGTH = 128


def _ensure_version_table_is_wide_enough(connection) -> None:
    dialect = connection.dialect.name
    if dialect == "sqlite":
        return  # SQLite không cưỡng chế độ dài, và không ALTER COLUMN TYPE được
    connection.execute(
        text(
            f"CREATE TABLE IF NOT EXISTS alembic_version ("
            f"version_num VARCHAR({VERSION_NUM_LENGTH}) NOT NULL, "
            f"CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num))"
        )
    )
    if dialect == "postgresql":
        connection.execute(
            text(
                f"ALTER TABLE alembic_version "
                f"ALTER COLUMN version_num TYPE VARCHAR({VERSION_NUM_LENGTH})"
            )
        )
    connection.commit()


def run_migrations_offline():
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    connectable = engine_from_config(
        config.get_section(config.config_ini_section),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        _ensure_version_table_is_wide_enough(connection)
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
