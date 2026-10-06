"""M0/M1: DB đang ở revision nào so với code — để /health và doctor nói thật.

Lỗi gốc anh gặp trên box là DB chưa chạy migration 0024–0027 trong khi code đã
mới; app vẫn báo ``status: ok``. Ở đây so ``alembic_version`` với head của thư
mục migration. SQLite (dev/test) dựng bằng create_all nên báo ``unmanaged``.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from sqlalchemy import text

BACKEND_DIR = Path(__file__).resolve().parents[2]


@lru_cache(maxsize=1)
def code_heads() -> tuple[str, ...]:
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    return tuple(sorted(ScriptDirectory.from_config(cfg).get_heads()))


def status(engine) -> dict:
    """``{"schema": ok|behind|unmanaged|error, "db": [...], "code": [...]}``. Không raise."""
    out: dict = {"schema": "error", "db": [], "code": []}
    try:
        out["code"] = list(code_heads())
    except Exception as exc:  # noqa: BLE001
        out["error"] = f"không đọc được migration: {str(exc)[:200]}"
        return out
    try:
        with engine.connect() as conn:
            rows = conn.execute(text("SELECT version_num FROM alembic_version")).fetchall()
        out["db"] = sorted(r[0] for r in rows)
    except Exception as exc:  # noqa: BLE001
        if engine.url.get_backend_name() == "sqlite":
            out["schema"] = "unmanaged"
            return out
        out["error"] = f"không đọc được alembic_version: {str(exc)[:200]}"
        return out
    out["schema"] = "ok" if out["db"] == out["code"] else "behind"
    if out["schema"] == "behind":
        out["fix"] = "Chạy: docker compose exec api alembic upgrade head"
    return out
