"""Chuỗi migration phải chạy trọn trên một database sạch.

Vì sao cần: 15 migration của dự án này **chưa từng được chạy** trước
2026-09-15, và khi chạy thật trên Postgres 16 chúng vỡ ở hai chỗ mà không một
test nào trong 636 test thấy:

1. ``alembic_version.version_num`` là VARCHAR(32) mặc định, còn sáu revision id
   dài hơn thế (dài nhất 42 ký tự) -> ``StringDataRightTruncation`` ở 0010.
2. ``0001_baseline`` gọi ``create_all`` với metadata HIỆN TẠI, nên nó tạo sẵn
   những cột mà 0006/0013/0014 mới được quyền thêm -> ``DuplicateColumn`` ở
   0013.

Test này chạy ``alembic upgrade head`` trên một database trống và đòi tới được
head. Trên SQLite nó bắt được lỗi (2) -- cột trùng làm ``ALTER TABLE ADD
COLUMN`` vỡ. Lỗi (1) chỉ Postgres bắt được vì SQLite không cưỡng chế độ dài
VARCHAR; ``test_version_table_is_wide_enough`` dưới đây thay thế bằng cách
kiểm tra tĩnh: mọi revision id phải ngắn hơn chiều rộng mà ``env.py`` bảo đảm.

Muốn kiểm cả lỗi (1) trên database thật:

    .venv/bin/python tools/devstack.py up
    eval "$(.venv/bin/python tools/devstack.py env)"
    cd backend && ../.venv/bin/python -m alembic upgrade head
"""
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect

BACKEND = Path(__file__).resolve().parents[1]
VERSIONS = BACKEND / "alembic" / "versions"


def _revision_ids() -> list[str]:
    ids = []
    for path in sorted(VERSIONS.glob("0*.py")):
        match = re.search(r'^revision\s*=\s*["\']([^"\']+)["\']', path.read_text(encoding="utf-8"), re.M)
        assert match, f"{path.name} không khai revision"
        ids.append(match.group(1))
    return ids


def test_version_table_is_wide_enough_for_every_revision_id():
    """Mọi revision id phải vừa cột mà env.py bảo đảm.

    Alembic mặc định tạo cột 32 ký tự; env.py nới lên VERSION_NUM_LENGTH. Nếu
    ai thêm một revision id dài hơn thế, migration sẽ vỡ trên Postgres nhưng
    vẫn xanh trên SQLite -- test này bắt trước.
    """
    env_src = (BACKEND / "alembic" / "env.py").read_text(encoding="utf-8")
    match = re.search(r"VERSION_NUM_LENGTH\s*=\s*(\d+)", env_src)
    assert match, "env.py phải khai VERSION_NUM_LENGTH"
    limit = int(match.group(1))

    too_long = [rid for rid in _revision_ids() if len(rid) > limit]
    assert not too_long, f"revision id dài hơn {limit} ký tự: {too_long}"

    # Và phải thực sự có revision dài hơn 32, nếu không thì bản vá env.py là
    # vô nghĩa và ai đó có thể xoá nó mà không thấy hậu quả.
    assert any(len(rid) > 32 for rid in _revision_ids()), (
        "không còn revision nào dài hơn 32 ký tự; xem lại vì sao env.py phải nới cột"
    )


def test_baseline_registers_every_column_later_migrations_add():
    """Cột mà migration sau thêm vào bảng baseline phải được khai ở baseline.

    Đây là hợp đồng mà ``0001_baseline`` mô tả. Test đọc mọi
    ``op.add_column("<bảng baseline>", ...)`` trong các migration sau và đòi
    cột đó có mặt trong ``COLUMNS_OWNED_BY_LATER_MIGRATIONS``.
    """
    sys.path.insert(0, str(BACKEND))
    import importlib.util

    spec = importlib.util.spec_from_file_location("baseline", VERSIONS / "0001_baseline.py")
    baseline = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(baseline)

    baseline_tables = set(baseline.BASELINE_TABLES)
    registered = {
        (table, column)
        for table, columns in baseline.COLUMNS_OWNED_BY_LATER_MIGRATIONS.items()
        for column in columns
    }

    added: set[tuple[str, str]] = set()
    for path in sorted(VERSIONS.glob("0*.py")):
        if path.name.startswith("0001_"):
            continue
        src = path.read_text(encoding="utf-8")
        for table, column in re.findall(
            r'op\.add_column\(\s*["\'](\w+)["\']\s*,\s*sa\.Column\(\s*["\'](\w+)["\']', src
        ):
            if table in baseline_tables:
                added.add((table, column))
        # Dạng vòng lặp: op.add_column(table, sa.Column("row_revision", ...))
        for column in re.findall(
            r'op\.add_column\(\s*table\s*,\s*sa\.Column\(\s*["\'](\w+)["\']', src
        ):
            loop_tables = re.search(r'TABLES\s*=\s*\(([^)]*)\)', src)
            if loop_tables:
                for name in re.findall(r'["\'](\w+)["\']', loop_tables.group(1)):
                    if name in baseline_tables:
                        added.add((name, column))

    # Một migration có thể tự lo bằng cách kiểm tra cột đã tồn tại chưa
    # (0006 làm đúng như vậy). Trường hợp đó không cần khai ở baseline.
    guarded: set[tuple[str, str]] = set()
    for path in sorted(VERSIONS.glob("0*.py")):
        src = path.read_text(encoding="utf-8")
        if "get_columns(" not in src:
            continue
        for table, column in added:
            if re.search(rf'if\s+["\']?{column}["\']?\s+not in', src):
                guarded.add((table, column))

    missing = sorted(added - registered - guarded)
    assert not missing, (
        "những cột này do migration sau thêm vào bảng baseline mà không tự kiểm "
        "tra tồn tại, nên phải khai ở "
        f"0001_baseline.COLUMNS_OWNED_BY_LATER_MIGRATIONS: {missing}"
    )


@pytest.mark.parametrize("_", [0])
def test_chain_reaches_head_on_a_clean_database(tmp_path, _):
    """``alembic upgrade head`` từ database trống phải tới được head."""
    db_path = tmp_path / "chain.db"
    env = dict(os.environ)
    env["DATABASE_URL"] = f"sqlite:///{db_path}"
    env["JWT_SECRET"] = "test"
    env["VECTOR_BACKEND"] = "hash"

    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=str(BACKEND), env=env, capture_output=True, text=True, timeout=600,
    )
    assert result.returncode == 0, (
        "chuỗi migration không tới được head:\n"
        + result.stdout[-3000:] + "\n" + result.stderr[-3000:]
    )

    engine = create_engine(f"sqlite:///{db_path}")
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())

    # Vài bảng mốc của từng giai đoạn, để một chuỗi "chạy xong nhưng rỗng"
    # không thể đi qua test này.
    for table in ("organizations", "companies", "departments", "tasks",
                  "alembic_version"):
        assert table in tables, f"thiếu bảng {table}"

    # Cột của 0013 và 0014 phải tồn tại sau chuỗi -- đúng là do migration thêm,
    # không phải do baseline tạo sẵn.
    department_columns = {c["name"] for c in inspector.get_columns("departments")}
    assert "row_revision" in department_columns
    assert "status" in department_columns

    version = engine.connect().exec_driver_sql(
        "SELECT version_num FROM alembic_version"
    ).scalar()
    assert version == _revision_ids()[-1], f"head không khớp: {version}"
    engine.dispose()
