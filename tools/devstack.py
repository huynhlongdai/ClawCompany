#!/usr/bin/env python3
"""Dựng Postgres + Redis thật trong sandbox, không cần Docker và không cần root.

Vì sao cần: docker-compose.yml dựng pgvector/pg16 và redis:7-alpine, nhưng
nhiều môi trường phát triển (kể cả sandbox agent) không có Docker. Hai gói
``pgserver`` và ``redislite`` nhúng binary thật ở user-space, nên
``alembic upgrade head`` chạy trên **Postgres thật** thay vì SQLite -- đó là
điều kiện bắt buộc để kiểm chứng 15 migration của dự án này.

Dùng:
    .venv/bin/python tools/devstack.py up      # khởi động, in ra env
    .venv/bin/python tools/devstack.py env     # chỉ in env (stack đang chạy)
    .venv/bin/python tools/devstack.py down    # dừng
    eval "$(.venv/bin/python tools/devstack.py env)"

Trạng thái lưu ở ``.devstack/``; Postgres dùng unix socket nên không chiếm
cổng và không xung đột với bất cứ thứ gì khác trong máy.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / ".devstack"
PGDATA = STATE / "pgdata"
REDIS_DIR = STATE / "redis"
INFO = STATE / "stack.json"

DB_NAME = "clawcompany"


REDIS_PORT = 16379


def _redis_binary() -> Path:
    import redislite

    return Path(redislite.__file__).parent / "bin" / "redis-server"


def _redis_alive(port: int = REDIS_PORT) -> bool:
    import socket

    with socket.socket() as sock:
        sock.settimeout(1.0)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def _start_redis() -> str:
    """Khởi động redis-server nền, hoặc dùng lại tiến trình đang chạy."""
    REDIS_DIR.mkdir(parents=True, exist_ok=True)
    if _redis_alive():
        return f"127.0.0.1:{REDIS_PORT}"
    subprocess.Popen(
        [str(_redis_binary()), "--port", str(REDIS_PORT), "--save", "",
         "--appendonly", "no", "--daemonize", "no",
         "--dir", str(REDIS_DIR), "--logfile", str(REDIS_DIR / "redis.log")],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    for _ in range(50):
        if _redis_alive():
            return f"127.0.0.1:{REDIS_PORT}"
        time.sleep(0.2)
    raise RuntimeError("redis-server không lên; xem .devstack/redis/redis.log")


def _pg_server(cleanup_mode: str | None = None):
    """Handle tới Postgres.

    ``cleanup_mode=None`` là bắt buộc: mặc định của pgserver là ``"stop"``,
    nghĩa là server tắt ngay khi tiến trình Python cuối cùng giữ handle thoát
    -- tức Postgres chết đúng lúc script devstack kết thúc, và lệnh alembic
    ngay sau đó không tìm thấy socket.
    """
    import pgserver

    PGDATA.mkdir(parents=True, exist_ok=True)
    return pgserver.get_server(PGDATA, cleanup_mode=cleanup_mode)


def up() -> dict:
    STATE.mkdir(parents=True, exist_ok=True)

    db = _pg_server()
    socket_dir = str(PGDATA)

    # Database riêng cho ứng dụng: không dùng ``postgres`` để một lần
    # ``down --wipe`` không xoá luôn database hệ thống.
    existing = db.psql(f"SELECT 1 FROM pg_database WHERE datname='{DB_NAME}';")
    if "1" not in existing:
        db.psql(f'CREATE DATABASE "{DB_NAME}";')

    # pgvector: VECTOR_BACKEND=pgvector là mặc định của dự án, nên extension
    # phải có mặt trước khi migration chạy. ``db.psql()`` chỉ nói chuyện với
    # database mặc định, nên vào thẳng database ứng dụng bằng psycopg.
    import psycopg

    with psycopg.connect(db.get_uri(DB_NAME), autocommit=True) as conn:
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector;")

    # Redis: dùng binary mà ``redislite`` nhúng, nhưng chạy nó như một tiến
    # trình độc lập. Không dùng ``redislite.Redis()`` trực tiếp vì object đó
    # tắt server khi bị thu hồi -- tức Redis sẽ chết ngay khi script này thoát,
    # và mọi lệnh sau đó lại rơi về chế độ process-local.
    redis_socket = _start_redis()

    info = {
        "database_url": db.get_uri(DB_NAME).replace("postgresql://", "postgresql+psycopg://", 1),
        "pg_uri": db.get_uri(DB_NAME),
        "pg_socket_dir": socket_dir,
        "redis_url": f"redis://{redis_socket}/0",
        "redis_endpoint": redis_socket,
    }
    INFO.write_text(json.dumps(info, indent=2), encoding="utf-8")
    return info


def env_lines(info: dict) -> list[str]:
    return [
        f'export DATABASE_URL="{info["database_url"]}"',
        f'export REDIS_URL="{info["redis_url"]}"',
        f'export CELERY_BROKER_URL="{info["redis_url"][:-1] + "1"}"',
        f'export CELERY_RESULT_BACKEND="{info["redis_url"][:-1] + "2"}"',
        'export JWT_SECRET="local-dev-change-me"',
        'export VECTOR_BACKEND="pgvector"',
        'export EMBEDDING_PROVIDER="hash384"',
        'export OPENCLAW_MODE="native"',
        'export OPENCLAW_GATEWAY_WS="ws://127.0.0.1:18789"',
        # Cả hai origin: trình duyệt coi localhost và 127.0.0.1 là khác nhau.
        # Chỉ khai một cái thì mở UI bằng địa chỉ còn lại sẽ bị CORS chặn --
        # đã gặp thật khi chụp ảnh UI bằng headless chromium ở 127.0.0.1:3000.
        'export CORS_ORIGINS="http://localhost:3000,http://127.0.0.1:3000"',
    ]


def main() -> int:
    action = sys.argv[1] if len(sys.argv) > 1 else "up"

    if action == "up":
        info = up()
        print("# devstack đã lên", file=sys.stderr)
        print(f"#   postgres socket: {info['pg_socket_dir']}", file=sys.stderr)
        print(f"#   redis:           {info['redis_endpoint']}", file=sys.stderr)
        print("\n".join(env_lines(info)))
        return 0

    if action == "env":
        if not INFO.exists():
            print("devstack chưa chạy; gọi `up` trước", file=sys.stderr)
            return 1
        print("\n".join(env_lines(json.loads(INFO.read_text(encoding="utf-8")))))
        return 0

    if action == "down":
        import pgserver  # noqa: F401

        if PGDATA.exists():
            _pg_server(cleanup_mode="stop").cleanup()
        if "--wipe" in sys.argv:
            shutil.rmtree(STATE, ignore_errors=True)
            print("# devstack đã dừng và xoá dữ liệu", file=sys.stderr)
        else:
            print("# devstack đã dừng (dữ liệu còn nguyên)", file=sys.stderr)
        return 0

    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
