"""Phase B việc 6 — trần chi USD theo ghế và chính sách model theo loại việc.

Ứng dụng dùng toàn cầu nên mọi số tiền là USD. Hai trần, đều tuỳ chọn, lưu
trong hồ sơ tuyển (``spec``) để có phiên bản và khôi phục được:

* ``daily_cap_usd`` — tổng chi của ghế trong ngày (theo ``settings.spend_day_tz``);
* ``monthly_budget`` — tổng chi trong tháng dương lịch (trước đây chỉ ghi vào
  USER.md, giờ chặn thật).

Chi = tổng ``task_runs.cost_usd`` của ghế (số gateway báo về). Chạm trần thì
lượt mới không chạy; lượt đang chạy không bị cắt giữa chừng.
"""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import Agent, Member

THINKING_LEVELS = ("off", "minimal", "low", "medium", "high")
KINDS = ("light", "default", "planning", "decision")
KIND_VI = {"light": "Việc vặt (tóm tắt, phân loại)", "default": "Việc thường",
           "planning": "Kế hoạch, review, phân tích", "decision": "Quyết định lớn"}


def _bounds(now: datetime | None = None) -> tuple[datetime, datetime]:
    """(đầu ngày, đầu tháng) theo giờ UTC naive — so được với cột DateTime."""
    tz = ZoneInfo(settings.spend_day_tz or "UTC")
    local = (now or datetime.now(timezone.utc)).astimezone(tz)
    day = local.replace(hour=0, minute=0, second=0, microsecond=0)
    month = day.replace(day=1)
    to_utc = lambda d: d.astimezone(timezone.utc).replace(tzinfo=None)  # noqa: E731
    return to_utc(day), to_utc(month)


def spent(db: Session, member_id: int, since: datetime) -> float:
    from app.models.work_graph import TaskRun
    v = db.query(func.coalesce(func.sum(TaskRun.cost_usd), 0.0)).filter(
        TaskRun.member_id == member_id, TaskRun.created_at >= since).scalar()
    return round(float(v or 0.0), 6)


def _spec_for(db: Session, member: Member) -> dict:
    from app.services.agent_hr import hire_spec
    agent = db.query(Agent).filter(Agent.member_id == member.id).first()
    return hire_spec(db, agent) if agent else {}


def state(db: Session, member: Member, spec: dict | None = None) -> dict:
    spec = _spec_for(db, member) if spec is None else spec
    day0, month0 = _bounds()
    daily, monthly = spec.get("daily_cap_usd"), spec.get("monthly_budget")
    out = {"currency": "USD", "day_tz": settings.spend_day_tz or "UTC",
           "daily_cap_usd": daily, "monthly_budget": monthly,
           "spent_today_usd": spent(db, member.id, day0), "spent_month_usd": spent(db, member.id, month0)}
    out["blocked"] = block_reason(out)
    return out


def block_reason(s: dict) -> str:
    if s.get("daily_cap_usd") not in (None, "") and s["spent_today_usd"] >= float(s["daily_cap_usd"]):
        return (f"budget: trần chi ngày của ghế: đã chi ${s['spent_today_usd']:.2f} / "
                f"${float(s['daily_cap_usd']):.2f}")
    if s.get("monthly_budget") not in (None, "") and s["spent_month_usd"] >= float(s["monthly_budget"]):
        return (f"budget: hạn mức tháng của ghế: đã chi ${s['spent_month_usd']:.2f} / "
                f"${float(s['monthly_budget']):.2f}")
    return ""


def check(db: Session, member: Member | None) -> str:
    """Lý do chặn (chuỗi rỗng = được chạy). Không bao giờ ném lỗi."""
    if member is None or member.member_type != "agent":
        return ""
    try:
        from app.services import seat_leases   # R2: hợp đồng thuê (trạng thái, hạn, trần tháng) đứng trước
        lr = seat_leases.block_reason(db, member)
        if lr:
            return lr
        return block_reason(state(db, member))
    except Exception:  # noqa: BLE001 - trần chi không được làm hỏng đường giao việc
        return ""


# ------------------------------------------------------------- chính sách model

def clean_money(v, label: str) -> float | None:
    from fastapi import HTTPException
    if v in (None, ""):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        raise HTTPException(422, f"{label} phải là số USD")
    if f < 0:
        raise HTTPException(422, f"{label} không được âm")
    return round(f, 4)


def clean_model_policy(p) -> dict:
    """``{"tiers": {kind: T1..T4}, "thinking": {kind: level}, "fallback": model_id}``;
    chỉ giữ phần người dùng đặt (bỏ trống = theo router mặc định)."""
    from fastapi import HTTPException
    from app.services.model_routing import FALLBACK_MODEL, TIERS
    if not p:
        return {}
    if not isinstance(p, dict):
        raise HTTPException(422, "Chính sách model phải là object")
    out: dict = {}
    tiers = {k: v for k, v in (p.get("tiers") or {}).items() if v}
    for k, v in tiers.items():
        if k not in KINDS or v not in TIERS:
            raise HTTPException(422, f"Tầng model không hợp lệ: {k}={v}")
    thinking = {k: v for k, v in (p.get("thinking") or {}).items() if v}
    for k, v in thinking.items():
        if k not in KINDS or v not in THINKING_LEVELS:
            raise HTTPException(422, f"Mức thinking không hợp lệ: {k}={v}")
    fallback = (p.get("fallback") or "").strip()
    allowed = {t.model_id for t in TIERS.values()} | {FALLBACK_MODEL}
    if fallback and fallback not in allowed:
        raise HTTPException(422, f"Model dự phòng phải là một trong: {', '.join(sorted(allowed))}")
    if tiers:
        out["tiers"] = dict(sorted(tiers.items()))
    if thinking:
        out["thinking"] = dict(sorted(thinking.items()))
    if fallback:
        out["fallback"] = fallback
    return out


def options() -> dict:
    from app.services.model_routing import FALLBACK_MODEL, TIERS
    return {"kinds": [{"key": k, "label": KIND_VI[k]} for k in KINDS],
            "tiers": [{"key": t.key, "label": t.label, "model": t.model_id, "reasoning": t.reasoning}
                      for t in TIERS.values()],
            "thinking_levels": list(THINKING_LEVELS),
            "fallbacks": [t.model_id for t in TIERS.values()] + [FALLBACK_MODEL]}
