"""Nhịp giờ cho gói P1 (beat ``business.tick``). Mỗi module có ``tick(db)``; module nào lỗi thì ghi lỗi, không chặn module khác."""
from __future__ import annotations

from sqlalchemy.orm import Session

MODULES = ("crm", "contracts")


def run(db: Session) -> dict:
    import importlib
    out: dict = {}
    for name in MODULES:
        try:
            out[name] = importlib.import_module(f"app.services.{name}").tick(db)
        except Exception as exc:  # noqa: BLE001
            db.rollback(); out[f"{name}_error"] = str(exc)[:300]
    return out
