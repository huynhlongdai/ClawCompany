"""M4b — Chi phí: tổng chi model + ngân sách ba nấc theo công ty / phòng ban / agent.

Nguồn tiền (không thêm nguồn mới):
- ``usage_events`` loại ``model_usage`` do ``cost_ledger.record_message_usage``
  ghi từ ``session.message`` của gateway — số chi theo ngày / agent / phòng / công ty.
- ``budget_envelopes`` + ``budget_ledger_entries`` (D2.3) — hạn mức, giữ chỗ,
  quyết toán theo ``task_runs.cost_usd`` rồi đối chiếu ``sessions.usage``.

Ba nấc trên một phong bì: cảnh báo (``warn_pct``) → dừng mềm cần duyệt
(``soft_stop_pct``, tuỳ chọn) → dừng cứng (100% hạn mức). Luật chặn nằm ở
``budget_scope``; module này chỉ đọc gộp và kiểm tra dữ liệu nhập.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.models import Agent, BudgetEnvelope, BudgetLedgerEntry, Company, Department, Member, UsageEvent
from app.services import budget_scope
from app.services.cost_ledger import EVENT_TYPE
from app.services.work_board import WorkError

UI_SCOPES = {"company": "Công ty", "department": "Phòng ban", "team": "Nhóm", "member": "Agent"}


LEGACY_SCOPES = {"project": "Dự án", "goal": "Mục tiêu"}   # phong bì D2.3/v9 cũ: chỉ hiển thị, không tạo mới ở đây


def scope_name(db: Session, env: BudgetEnvelope) -> str:
    st, sid = budget_scope.scope_of(env)
    if st == "company":
        c = db.get(Company, sid) if sid else None
        return c.name if c else "Cả tổ chức"
    if st == "department":
        d = db.get(Department, sid) if sid else None
        return d.name if d else f"Phòng #{sid}"
    if st == "member":
        m = db.get(Member, sid) if sid else None
        return m.name if m else f"Thành viên #{sid}"
    if st == "team":
        from app.models.v16 import AgentTeam
        t = db.get(AgentTeam, sid) if sid else None
        return t.name if t else f"Nhóm #{sid}"
    if st == "project":
        from app.models import Project
        p = db.get(Project, sid) if sid else None
        return p.name if p else f"Dự án #{sid}"
    if st == "goal":
        from app.models import ExecutiveGoal
        g = db.get(ExecutiveGoal, sid) if sid else None
        return getattr(g, "title", None) or getattr(g, "name", None) or f"Mục tiêu #{sid}"
    return f"{st} #{sid}"


def budget_row(db: Session, env: BudgetEnvelope) -> dict:
    st, _ = budget_scope.scope_of(env)
    from app.models import Approval
    waiting = (db.query(Approval.id).filter(Approval.organization_id == env.organization_id,
                                            Approval.policy_key.like(f"{budget_scope.SOFT_PREFIX}e{env.id}:t%"),
                                            Approval.status == "pending").count())
    return {**budget_scope.public(env), "scope_vi": UI_SCOPES.get(st) or LEGACY_SCOPES.get(st, st), "scope_name": scope_name(db, env),
            "pending_approvals": waiting,
            "levels": [{"key": "warned", "pct": env.warn_pct or 80, "label": "Cảnh báo"},
                       *([{"key": "soft_stopped", "pct": env.soft_stop_pct, "label": "Dừng mềm (cần duyệt)"}]
                         if env.soft_stop_pct else []),
                       {"key": "exhausted", "pct": 100, "label": "Dừng cứng"}]}


def list_budgets(db: Session, organization_id: int, include_archived: bool = False) -> list[dict]:
    q = db.query(BudgetEnvelope).filter(BudgetEnvelope.organization_id == organization_id)
    if not include_archived:
        q = q.filter(BudgetEnvelope.status != "archived")
    order = {"exhausted": 0, "soft_stopped": 1, "warned": 2, "ok": 3}
    rows = [budget_row(db, e) for e in q.order_by(BudgetEnvelope.id).all()]
    return sorted(rows, key=lambda r: (order.get(r["threshold_state"], 4), -r["pct"], r["id"]))


def _usage_rows(db: Session, organization_id: int, since: datetime):
    return (db.query(UsageEvent).filter(UsageEvent.organization_id == organization_id,
                                        UsageEvent.event_type == EVENT_TYPE,
                                        UsageEvent.created_at >= since).all())


def overview(db: Session, organization_id: int, *, days: int = 30, now: datetime | None = None) -> dict:
    now = now or datetime.utcnow()
    days = max(1, min(int(days), 365))
    start_today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    rows = _usage_rows(db, organization_id, now - timedelta(days=days))
    agents = {a.id: a for a in db.query(Agent).filter(Agent.id.in_({r.agent_id for r in rows if r.agent_id} or {-1})).all()}
    members = {m.id: m for m in db.query(Member).filter(Member.organization_id == organization_id).all()}
    depts = {d.id: d.name for d in db.query(Department).all()} if rows else {}
    comps = {c.id: c.name for c in db.query(Company).filter(Company.organization_id == organization_id).all()}
    by_agent: dict[str, float] = {}
    by_dept: dict[str, float] = {}
    by_comp: dict[str, float] = {}
    by_day: dict[str, float] = {}
    tokens = 0
    for r in rows:
        amt = float(r.amount or 0)
        a = agents.get(r.agent_id) if r.agent_id else None
        m = members.get(a.member_id) if a else None
        by_agent[m.name if m else "(không rõ agent)"] = by_agent.get(m.name if m else "(không rõ agent)", 0) + amt
        dk = depts.get(m.department_id, "(chưa có phòng)") if m and m.department_id else "(chưa có phòng)"
        by_dept[dk] = by_dept.get(dk, 0) + amt
        ck = comps.get(m.company_id, "(không rõ công ty)") if m and m.company_id else "(không rõ công ty)"
        by_comp[ck] = by_comp.get(ck, 0) + amt
        day = r.created_at.strftime("%Y-%m-%d")
        by_day[day] = by_day.get(day, 0) + amt
        try:
            tokens += int(json.loads(r.metadata_json or "{}").get("total_tokens") or 0)
        except Exception:  # noqa: BLE001
            pass

    def total(since: datetime) -> float:
        return round(sum(float(r.amount or 0) for r in rows if r.created_at >= since), 6)

    def ranked(d: dict[str, float]) -> list[dict]:
        return sorted(({"name": k, "cost_usd": round(v, 6)} for k, v in d.items()), key=lambda x: -x["cost_usd"])

    budgets = list_budgets(db, organization_id)
    return {
        "generated_at": now.isoformat(), "days": days, "currency": "USD",
        "source": "usage_events (model_usage) — ghi từ session.message của gateway; ngân sách quyết toán theo "
                  "task_runs.cost_usd rồi đối chiếu sessions.usage",
        "totals": {"today": total(start_today), "d7": total(now - timedelta(days=7)),
                   "window": total(now - timedelta(days=days)), "model_calls": len(rows), "tokens": tokens},
        "by_agent": ranked(by_agent), "by_department": ranked(by_dept), "by_company": ranked(by_comp),
        "by_day": [{"day": k, "cost_usd": round(v, 6)} for k, v in sorted(by_day.items())],
        "budgets": budgets,
        "alerts": sum(1 for b in budgets if b["threshold_state"] != "ok"),
    }


# ------------------------------------------------------------------ ghi


def _levels(warn: int | None, soft: int | None) -> None:
    w = 80 if warn is None else int(warn)
    if not 1 <= w <= 99:
        raise WorkError(422, "bad_levels", "Nấc cảnh báo phải từ 1% đến 99%")
    if soft is not None and not (w < int(soft) < 100):
        raise WorkError(422, "bad_levels",
                        f"Nấc dừng mềm phải lớn hơn nấc cảnh báo ({w}%) và nhỏ hơn 100% (100% là dừng cứng)")


def _check_scope(db: Session, organization_id: int, scope_type: str, scope_id: int | None) -> int | None:
    if scope_type not in UI_SCOPES:
        raise WorkError(422, "bad_scope", "Phạm vi chỉ được là công ty, phòng ban, nhóm hoặc agent")
    if scope_id is None:
        raise WorkError(422, "bad_scope", "Chọn công ty, phòng ban, nhóm hoặc agent cho ngân sách")
    if scope_type == "company":
        c = db.get(Company, scope_id)
        ok = c is not None and c.organization_id == organization_id
        company_id = c.id if ok else None
    elif scope_type == "department":
        d = db.get(Department, scope_id)
        c = db.get(Company, d.company_id) if d else None
        ok = c is not None and c.organization_id == organization_id
        company_id = c.id if ok else None
    elif scope_type == "team":
        from app.models.v16 import AgentTeam
        t = db.get(AgentTeam, scope_id)
        ok = t is not None and t.organization_id == organization_id
        company_id = t.company_id if ok else None
    else:
        m = db.get(Member, scope_id)
        ok = m is not None and m.organization_id == organization_id
        company_id = m.company_id if ok else None
    if not ok:
        raise WorkError(404, "scope_not_found", "Không tìm thấy phạm vi này trong tổ chức của anh")
    return company_id


def create(db: Session, organization_id: int, data: dict) -> BudgetEnvelope:
    st, sid = data["scope_type"], data.get("scope_id")
    company_id = _check_scope(db, organization_id, st, sid)
    _levels(data.get("warn_pct"), data.get("soft_stop_pct"))
    dup = [e for e in db.query(BudgetEnvelope).filter(BudgetEnvelope.organization_id == organization_id,
                                                      BudgetEnvelope.status != "archived").all()
           if budget_scope.scope_of(e) == (st, sid)]
    if dup:
        raise WorkError(409, "duplicate_scope",
                        f"Phạm vi này đã có ngân sách '{dup[0].name}' — sửa ngân sách đó thay vì tạo thêm",
                        budget_id=dup[0].id)
    name = (data.get("name") or "").strip()
    if not name:
        fake = BudgetEnvelope(scope_type=st, scope_id=sid, company_id=company_id)
        name = f"{UI_SCOPES[st]} · {scope_name(db, fake)}"
    env = BudgetEnvelope(organization_id=organization_id, company_id=company_id, name=name[:180],
                         currency="USD", amount_limit=float(data["amount_limit"]), amount_reserved=0,
                         amount_spent=0, status="active", scope_type=st, scope_id=sid,
                         warn_pct=int(data.get("warn_pct") or 80), soft_stop_pct=data.get("soft_stop_pct"),
                         period="total", threshold_state="ok")
    db.add(env); db.commit(); db.refresh(env)
    return env


def update(db: Session, env: BudgetEnvelope, data: dict) -> dict:
    """Sửa tên / nấc / hạn mức. Phong bì đã dừng cứng chỉ mở lại qua override (có lý do, audit)."""
    if env.status == "archived":
        raise WorkError(409, "archived", "Ngân sách này đã lưu trữ")
    if "amount_limit" in data and data["amount_limit"] is not None and (env.threshold_state or "ok") == "exhausted":
        raise WorkError(409, "needs_override",
                        "Ngân sách đã dừng cứng — muốn mở lại hãy dùng 'Nâng hạn mức' và ghi lý do")
    warn = data.get("warn_pct", env.warn_pct)
    soft = data["soft_stop_pct"] if "soft_stop_pct" in data else env.soft_stop_pct
    _levels(warn, soft)
    if data.get("name"):
        env.name = data["name"].strip()[:180]
    env.warn_pct, env.soft_stop_pct = int(warn or 80), soft
    if data.get("amount_limit") is not None:
        if float(data["amount_limit"]) <= 0:
            raise WorkError(422, "bad_limit", "Hạn mức phải lớn hơn 0")
        env.amount_limit = float(data["amount_limit"])
    db.add(env); db.commit(); db.refresh(env)
    return budget_scope.check_thresholds(db, env)


def detail(db: Session, env: BudgetEnvelope) -> dict:
    from app.models import Approval
    ledger = (db.query(BudgetLedgerEntry).filter(BudgetLedgerEntry.budget_id == env.id)
              .order_by(BudgetLedgerEntry.id.desc()).limit(50).all())
    TYPE_VI = {"reserve": "Giữ chỗ", "spend": "Chi", "release": "Trả phần giữ", "credit": "Điều chỉnh giảm"}
    approvals = (db.query(Approval).filter(Approval.organization_id == env.organization_id,
                                           Approval.policy_key.like(f"{budget_scope.SOFT_PREFIX}e{env.id}:t%"))
                 .order_by(Approval.id.desc()).limit(20).all())
    return {"budget": budget_row(db, env),
            "spend": budget_scope.spend_breakdown(db, env.organization_id, env.id),
            "ledger": [{"id": x.id, "type": x.entry_type, "type_vi": TYPE_VI.get(x.entry_type, x.entry_type),
                        "amount": round(x.amount, 6), "source": x.source_id, "memo": x.memo,
                        "at": x.created_at.isoformat() if getattr(x, "created_at", None) else None} for x in ledger],
            "soft_approvals": [{"id": a.id, "action": a.action, "status": a.status} for a in approvals]}
