"""M2c D5 — KPI chia tầng: mục tiêu công ty (``executive_goals`` / ``portfolio_objectives``) →
KPI phòng ban → KPI chức danh (từ ``positions.kpis`` của M2b) → KPI từng seat.

Số thực tế:
* ``manual`` — người nhập theo kỳ (``kpi_measurements``);
* còn lại tính trực tiếp từ dữ liệu đang có, trong cửa sổ kỳ hiện tại (giờ Việt Nam), theo phạm vi
  của tầng (cả công ty / thành viên một phòng / người ngồi chức danh / một seat):
  ``tasks_done`` · ``cycle_time_minutes`` (D4, lần chạy xong; tầng seat = bước của seat) ·
  ``on_time_rate`` (bước D4 xong trong thời lượng kỳ vọng, %) · ``process_runs_done`` ·
  ``cost_per_task_usd`` (chi phí lượt chạy / việc xong) · ``first_pass_rate`` (% qua review lần đầu,
  cùng cách đếm với scorecard M6) · ``approvals_pending`` · ``approval_turnaround_hours``.
  Có số nhập tay cho kỳ hiện tại thì số nhập tay thắng (ghi rõ nguồn).

Tiến độ = thực tế / mục tiêu (hướng ``down``: mục tiêu / thực tế), chặn 0–150 %. Cuộn lên: tầng cha
lấy trung bình có trọng số tiến độ của tầng con (``rollup``) bên cạnh số của chính nó.
Scorecard agent (M6 ``career.scorecard``) nhận ``kpis`` của seat qua ``seat_kpis``.

M2d.2: "việc xong trong kỳ" dùng ``tasks.completed_at`` (lúc chuyển "done"; hàng cũ chưa có → ``updated_at``).
Số đã tính được lưu theo kỳ ở ``kpi_snapshots`` (beat ``kpi.snapshot`` mỗi giờ + nút "Chụp số ngay") — hết kỳ
thì hàng của kỳ đó đóng băng (``final``); ``history`` trả các kỳ gần nhất cho đường xu hướng.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Approval, Company, Department, Member, Project, Task
from app.models.company_foundation import Position
from app.models.company_ops import (KpiDefinition, KpiMeasurement, KpiSnapshot, Process, ProcessInstance,
                                    ProcessStepRun)

TZ = ZoneInfo("Asia/Ho_Chi_Minh")
LEVELS = ("company", "department", "position", "seat")
PERIODS = ("week", "month", "quarter")
METRICS = {
    "manual": {"vi": "Nhập tay", "en": "Manual", "unit": "", "direction": "up"},
    "tasks_done": {"vi": "Số việc xong", "en": "Tasks done", "unit": "việc", "direction": "up"},
    "cycle_time_minutes": {"vi": "Thời gian chu trình TB (phút)", "en": "Avg cycle time (min)", "unit": "phút", "direction": "down"},
    "on_time_rate": {"vi": "% bước quy trình đúng hạn", "en": "% process steps on time", "unit": "%", "direction": "up"},
    "process_runs_done": {"vi": "Lần chạy quy trình xong", "en": "Process runs done", "unit": "lần", "direction": "up"},
    "cost_per_task_usd": {"vi": "Chi phí mỗi việc (USD)", "en": "Cost per task (USD)", "unit": "USD", "direction": "down"},
    "first_pass_rate": {"vi": "% qua review lần đầu", "en": "% first-pass reviews", "unit": "%", "direction": "up"},
    "approvals_pending": {"vi": "Phê duyệt đang chờ", "en": "Pending approvals", "unit": "", "direction": "down"},
    "approval_turnaround_hours": {"vi": "Thời gian duyệt TB (giờ)", "en": "Avg approval time (h)", "unit": "giờ", "direction": "down"},
    # M2e.3: % lần nộp kết quả đúng hợp đồng dữ liệu (gồm lượt chạy kết thúc mà chưa nộp)
    "output_conformance_rate": {"vi": "% kết quả đúng hợp đồng dữ liệu", "en": "% outputs matching the data contract", "unit": "%", "direction": "up"},
    # M2e.4: % đồng hồ SLA (phản hồi đầu + xử lý xong) đóng đúng hạn
    "sla_attainment_rate": {"vi": "% đạt SLA", "en": "% SLA met", "unit": "%", "direction": "up"},
}
OPEN_TASK = ("backlog", "todo", "in_progress", "review", "blocked")


def _err(status: int, msg: str) -> HTTPException:
    return HTTPException(status, msg)


# ------------------------------------------------------------------ kỳ

def period_window(period: str, now: datetime | None = None) -> tuple[str, datetime, datetime]:
    """(khoá kỳ, bắt đầu UTC naive, kết thúc UTC naive) của kỳ chứa ``now`` theo giờ Việt Nam."""
    now = now or datetime.utcnow()
    local = now.replace(tzinfo=ZoneInfo("UTC")).astimezone(TZ)
    if period == "week":
        start = (local - timedelta(days=local.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=7)
        y, w, _ = start.isocalendar()
        key = f"{y}-W{w:02d}"
    elif period == "quarter":
        q = (local.month - 1) // 3
        start = local.replace(month=q * 3 + 1, day=1, hour=0, minute=0, second=0, microsecond=0)
        end = start.replace(year=start.year + 1, month=1) if q == 3 else start.replace(month=q * 3 + 4)
        key = f"{local.year}-Q{q + 1}"
    else:
        start = local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        end = start.replace(year=start.year + 1, month=1) if start.month == 12 else start.replace(month=start.month + 1)
        key = f"{local.year}-{local.month:02d}"
    to_utc = lambda d: d.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)  # noqa: E731
    return key, to_utc(start), to_utc(end)


# ------------------------------------------------------------------ phạm vi + chỉ số

def scope_members(db: Session, k: KpiDefinition) -> list[int] | None:
    """None = cả công ty (lọc theo dự án của công ty)."""
    if k.level == "seat" and k.member_id:
        return [k.member_id]
    if k.level == "position" and k.position_id:
        return [m.id for m in db.query(Member).filter(Member.position_id == k.position_id, Member.status != "archived").all()]
    if k.level == "department" and k.department_id:
        return [m.id for m in db.query(Member).filter(Member.department_id == k.department_id, Member.status != "archived").all()]
    return None


def _tasks(db: Session, company_id: int, members: list[int] | None):
    q = db.query(Task).join(Project, Project.id == Task.project_id).filter(Project.company_id == company_id)
    if members is not None:
        q = q.filter(Task.assignee_member_id.in_(members or [-1]))
    return q


def _done_at():
    """Mốc "xong" của một việc: completed_at (M2d.2), hàng cũ chưa có → updated_at."""
    return func.coalesce(Task.completed_at, Task.updated_at)


# chỉ số "tại một thời điểm" (không có cửa sổ kỳ) → không tính lại được cho kỳ đã qua
POINT_IN_TIME = ("approvals_pending",)


def compute(db: Session, k: KpiDefinition, now: datetime | None = None) -> float | None:
    from app.models.work_graph import TaskRun
    key, start, end = period_window(k.period, now)
    members = scope_members(db, k)
    m = k.metric
    if m == "tasks_done":
        return float(_tasks(db, k.company_id, members).filter(Task.status == "done", _done_at() >= start,
                                                              _done_at() < end).count())
    if m in ("cycle_time_minutes", "on_time_rate", "process_runs_done"):
        if members is None and m != "on_time_rate":
            q = db.query(ProcessInstance).filter(ProcessInstance.company_id == k.company_id, ProcessInstance.status == "done",
                                                 ProcessInstance.finished_at >= start, ProcessInstance.finished_at < end)
            if k.process_id:
                q = q.filter(ProcessInstance.process_id == k.process_id)
            rows = q.all()
            if m == "process_runs_done":
                return float(len(rows))
            vals = [r.cycle_seconds for r in rows if r.cycle_seconds is not None]
            return round(sum(vals) / len(vals) / 60, 1) if vals else None
        q = (db.query(ProcessStepRun).join(ProcessInstance, ProcessInstance.id == ProcessStepRun.instance_id)
             .filter(ProcessInstance.company_id == k.company_id, ProcessStepRun.status == "done",
                     ProcessStepRun.finished_at >= start, ProcessStepRun.finished_at < end))
        if members is not None:
            q = q.filter(ProcessStepRun.assignee_member_id.in_(members or [-1]))
        if k.process_id:
            q = q.filter(ProcessInstance.process_id == k.process_id)
        rows = q.all()
        if m == "process_runs_done":
            return float(len({r.instance_id for r in rows}))
        if m == "on_time_rate":
            timed = [r for r in rows if r.expected_minutes and r.cycle_seconds is not None]
            return round(100 * sum(1 for r in timed if r.cycle_seconds <= r.expected_minutes * 60) / len(timed), 1) if timed else None
        vals = [r.cycle_seconds for r in rows if r.cycle_seconds is not None]
        return round(sum(vals) / len(vals) / 60, 1) if vals else None
    if m == "cost_per_task_usd":
        tasks = _tasks(db, k.company_id, members)
        done = tasks.filter(Task.status == "done", _done_at() >= start, _done_at() < end).count()
        ids = [t.id for t in tasks.with_entities(Task.id).all()]
        q = db.query(TaskRun).filter(TaskRun.created_at >= start, TaskRun.created_at < end, TaskRun.task_id.in_(ids or [-1]))
        cost = sum(r.cost_usd or 0 for r in q.all())
        return round(cost / done, 4) if done else None
    if m == "first_pass_rate":
        reviewed = first = 0
        for t in _tasks(db, k.company_id, members).filter(Task.status == "done", _done_at() >= start, _done_at() < end).all():
            hist = [h for h in ((t.execution_state or {}).get("history") or []) if h.get("decision")]
            if hist:
                reviewed += 1
                first += hist[0]["decision"] == "approve"
        return round(100 * first / reviewed, 1) if reviewed else None
    if m == "sla_attainment_rate":
        from app.services import operating_time
        a = operating_time.attainment(db, company_id=k.company_id, member_ids=members, start=start, end=end)
        return round(100 * a["rate"], 1) if a["rate"] is not None else None
    if m == "output_conformance_rate":
        from app.services import io_contracts
        c = io_contracts.conformance(db, member_ids=members, company_id=k.company_id, start=start, end=end)
        return round(100 * c["rate"], 1) if c["rate"] is not None else None
    if m in ("approvals_pending", "approval_turnaround_hours"):
        all_members = [x.id for x in db.query(Member).filter(Member.company_id == k.company_id).all()]
        req = members if members is not None else all_members
        q = db.query(Approval).filter(Approval.organization_id == k.organization_id,
                                      Approval.requester_member_id.in_(req or [-1]))
        if m == "approvals_pending":
            return float(q.filter(Approval.status == "pending").count())
        rows = q.filter(Approval.status.in_(("approved", "rejected")), Approval.updated_at >= start, Approval.updated_at < end).all()
        vals = [(r.updated_at - r.created_at).total_seconds() / 3600 for r in rows if r.updated_at and r.created_at]
        return round(sum(vals) / len(vals), 2) if vals else None
    return None


# ------------------------------------------------------------------ lịch sử theo kỳ (M2d.2)

def previous_now(period: str, now: datetime, back: int) -> datetime:
    """Một thời điểm nằm trong kỳ cách kỳ hiện tại ``back`` kỳ (dùng để tính lại kỳ cũ)."""
    t = now
    for _ in range(back):
        _, start, _ = period_window(period, t)
        t = start - timedelta(seconds=1)
    return t


def snapshot(db: Session, k: KpiDefinition, *, now: datetime | None = None, trigger: str = "beat",
             final: bool = False) -> KpiSnapshot | None:
    """Ghi số của KPI cho kỳ chứa ``now`` (upsert theo KPI × kỳ). Kỳ đã đóng băng thì giữ nguyên."""
    now = now or datetime.utcnow()
    key, _, _ = period_window(k.period, now)
    row = db.query(KpiSnapshot).filter(KpiSnapshot.kpi_id == k.id, KpiSnapshot.period_key == key).first()
    if row is not None and row.final:
        return row
    ev = evaluate(db, k, now)
    if row is None:
        row = KpiSnapshot(kpi_id=k.id, company_id=k.company_id, period=k.period, period_key=key)
        db.add(row)
    row.value, row.value_source = ev["value"], ev["value_source"] or ""
    row.target, row.progress, row.health = k.target, ev["progress"], ev["health"]
    row.trigger, row.final, row.computed_at = trigger, final, datetime.utcnow()
    db.commit()
    return row


def snapshot_company(db: Session, company_id: int, *, now: datetime | None = None, trigger: str = "beat",
                     backfill: int = 0) -> dict:
    """Chụp số mọi KPI đang hoạt động của công ty cho kỳ hiện tại; kỳ trước chưa đóng băng → tính lại tại
    cuối kỳ đó và đóng băng. ``backfill`` = số kỳ cũ cần tính lại từ dữ liệu hiện có (bỏ qua chỉ số tại một
    thời điểm như phê duyệt đang chờ — không dựng lại được quá khứ)."""
    now = now or datetime.utcnow()
    rows = db.query(KpiDefinition).filter(KpiDefinition.company_id == company_id, KpiDefinition.status == "active").all()
    co = db.get(Company, company_id)
    born = getattr(co, "created_at", None)
    made = closed = back = 0
    for k in rows:
        # 1) kỳ trước đang có số "chạy" → tính lại tại cuối kỳ đó rồi đóng băng
        t1 = previous_now(k.period, now, 1)
        key1, _, _ = period_window(k.period, t1)
        have1 = db.query(KpiSnapshot).filter(KpiSnapshot.kpi_id == k.id, KpiSnapshot.period_key == key1).first()
        if have1 is not None and not have1.final:
            snapshot(db, k, now=t1, trigger="close", final=True)
            closed += 1
        # 2) kỳ cũ chưa có số → tính lại từ dữ liệu hiện có (chỉ khi được yêu cầu)
        for bk in range(backfill, 0, -1):
            t = previous_now(k.period, now, bk)
            key, _, end = period_window(k.period, t)
            if k.metric in POINT_IN_TIME or (k.created_at and end <= k.created_at and k.metric == "manual"):
                continue
            if born and end <= born:
                continue          # kỳ trước khi có công ty: "0 việc xong" là số giả, không ghi
            if db.query(KpiSnapshot).filter(KpiSnapshot.kpi_id == k.id, KpiSnapshot.period_key == key).first():
                continue
            snapshot(db, k, now=t, trigger="backfill", final=True)
            back += 1
        snapshot(db, k, now=now, trigger=trigger)
        made += 1
    return {"company_id": company_id, "snapshots": made, "closed": closed, "backfilled": back}


def tick(db: Session) -> dict:
    """Beat ``kpi.snapshot`` (mỗi giờ): mọi công ty có KPI."""
    ids = [r[0] for r in db.query(KpiDefinition.company_id).join(Company, Company.id == KpiDefinition.company_id)
           .filter(KpiDefinition.status == "active", Company.status != "archived").distinct().all()]
    out = []
    for cid in ids:
        try:
            out.append(snapshot_company(db, cid))
        except Exception as exc:  # noqa: BLE001 — một công ty lỗi không chặn công ty khác
            db.rollback()
            out.append({"company_id": cid, "error": str(exc)[:200]})
    return {"companies": len(ids), "results": out}


def history(db: Session, k: KpiDefinition, limit: int = 8) -> list[dict]:
    rows = (db.query(KpiSnapshot).filter(KpiSnapshot.kpi_id == k.id, KpiSnapshot.period == k.period)
            .order_by(KpiSnapshot.period_key.desc())
            .limit(limit).all())
    return [{"period_key": r.period_key, "value": r.value, "progress": r.progress, "health": r.health,
             "final": r.final, "trigger": r.trigger, "source": r.value_source} for r in reversed(rows)]


def manual_value(db: Session, k: KpiDefinition, period_key: str) -> KpiMeasurement | None:
    return (db.query(KpiMeasurement).filter(KpiMeasurement.kpi_id == k.id, KpiMeasurement.period_key == period_key)
            .order_by(KpiMeasurement.id.desc()).first())


def progress(value: float | None, target: float | None, direction: str) -> float | None:
    if value is None or target is None:
        return None
    if direction == "down":
        if value <= 0:
            return 150.0
        p = 100 * target / value
    else:
        if target == 0:
            return 100.0 if value >= 0 else 0.0
        p = 100 * value / target
    return round(max(0.0, min(150.0, p)), 1)


def health(p: float | None) -> str:
    if p is None:
        return "no_data"
    return "on_track" if p >= 90 else "at_risk" if p >= 60 else "off_track"


# ------------------------------------------------------------------ đọc

def _owner_label(db: Session, k: KpiDefinition) -> str:
    if k.level == "seat" and k.member_id:
        m = db.get(Member, k.member_id); return m.name if m else f"#{k.member_id}"
    if k.level == "position" and k.position_id:
        p = db.get(Position, k.position_id); return p.title if p else f"#{k.position_id}"
    if k.level == "department" and k.department_id:
        d = db.get(Department, k.department_id); return d.name if d else f"#{k.department_id}"
    co = db.get(Company, k.company_id)
    return co.name if co else ""


def evaluate(db: Session, k: KpiDefinition, now: datetime | None = None) -> dict:
    key, start, end = period_window(k.period, now)
    man = manual_value(db, k, key)
    auto = compute(db, k, now) if k.metric != "manual" else None
    value, source = (man.value, "manual") if man is not None else (auto, "auto" if auto is not None else None)
    p = progress(value, k.target, k.direction)
    goal = None
    if k.goal_id:
        from app.models import ExecutiveGoal
        g = db.get(ExecutiveGoal, k.goal_id)
        goal = {"id": g.id, "title": g.title, "progress": g.progress, "status": g.status} if g else None
    obj = None
    if k.objective_id:
        from app.models import PortfolioObjective
        o = db.get(PortfolioObjective, k.objective_id)
        obj = {"id": o.id, "title": o.title, "status": o.status} if o else None
    return {"id": k.id, "level": k.level, "name": k.name, "unit": k.unit or METRICS.get(k.metric, {}).get("unit", ""),
            "target": k.target, "direction": k.direction, "period": k.period, "period_key": key,
            "metric": k.metric, "metric_vi": METRICS.get(k.metric, {}).get("vi", k.metric), "process_id": k.process_id,
            "department_id": k.department_id, "position_id": k.position_id, "member_id": k.member_id,
            "parent_id": k.parent_id, "goal": goal, "objective": obj, "weight": k.weight, "source": k.source,
            "owner": _owner_label(db, k), "value": value, "value_source": source, "auto_value": auto,
            "progress": p, "health": health(p),
            "note": man.note if man is not None else ""}


def _tree(rows: list[dict]) -> list[dict]:
    by = {r["id"]: {**r, "children": []} for r in rows}
    roots = []
    for r in by.values():
        if r["parent_id"] and r["parent_id"] in by:
            by[r["parent_id"]]["children"].append(r)
        else:
            roots.append(r)

    def roll(n: dict) -> float | None:
        kids = [(roll(c), c["weight"] or 1) for c in n["children"]]
        vals = [(p, w) for p, w in kids if p is not None]
        n["rollup"] = round(sum(p * w for p, w in vals) / sum(w for _, w in vals), 1) if vals else None
        n["rollup_health"] = health(n["rollup"]) if vals else None
        own = n["progress"]
        return own if own is not None else n["rollup"]
    for r in roots:
        roll(r)
    order = {lv: i for i, lv in enumerate(LEVELS)}
    roots.sort(key=lambda x: (order.get(x["level"], 9), x["id"]))
    return roots


def list_kpis(db: Session, org_id: int, company_id: int | None, *, now: datetime | None = None) -> dict:
    from app.models import ExecutiveGoal, PortfolioObjective
    from app.services.company_foundation import _company
    co = _company(db, org_id, company_id)
    rows = (db.query(KpiDefinition).filter(KpiDefinition.company_id == co.id, KpiDefinition.status == "active")
            .order_by(KpiDefinition.id).all())
    items = [{**evaluate(db, k, now), "history": history(db, k)} for k in rows]
    tree = _tree(items)
    scored = [i["progress"] for i in items if i["progress"] is not None]
    company_rows = [n for n in tree if n["level"] == "company"]
    comp = [n["progress"] if n["progress"] is not None else n.get("rollup") for n in company_rows]
    comp = [c for c in comp if c is not None]
    return {"company_id": co.id, "company_name": co.name, "items": items, "tree": tree,
            "summary": {"kpis": len(items), "with_data": len(scored),
                        "company_progress": round(sum(comp) / len(comp), 1) if comp else None,
                        "on_track": sum(1 for i in items if i["health"] == "on_track"),
                        "at_risk": sum(1 for i in items if i["health"] == "at_risk"),
                        "off_track": sum(1 for i in items if i["health"] == "off_track")},
            "metrics": [{"key": k, **v} for k, v in METRICS.items()],
            "goals": [{"id": g.id, "title": g.title} for g in db.query(ExecutiveGoal).filter(
                ExecutiveGoal.organization_id == org_id, ExecutiveGoal.company_id.in_((co.id,))).order_by(ExecutiveGoal.id.desc()).limit(50).all()],
            "objectives": [{"id": o.id, "title": o.title} for o in db.query(PortfolioObjective).filter(
                PortfolioObjective.organization_id == org_id).order_by(PortfolioObjective.id.desc()).limit(50).all()],
            "departments": [{"id": d.id, "name": d.name} for d in db.query(Department).filter(Department.company_id == co.id).all()],
            "positions": [{"id": p.id, "title": p.title, "department_id": p.department_id} for p in db.query(Position).filter(
                Position.company_id == co.id, Position.status != "archived").all()],
            "members": [{"id": m.id, "name": m.name, "type": m.member_type} for m in db.query(Member).filter(
                Member.company_id == co.id, Member.status != "archived").order_by(Member.id).all()],
            "processes": [{"id": p.id, "name": p.name} for p in db.query(Process).filter(
                Process.company_id == co.id, Process.status != "archived").all()]}


# ------------------------------------------------------------------ ghi

def _kpi(db: Session, org_id: int, kid: int) -> KpiDefinition:
    k = db.get(KpiDefinition, kid)
    if k is None or k.organization_id != org_id or k.status != "active":
        raise _err(404, "Không thấy KPI này. Tải lại tab KPI — có thể nó đã bị xoá.")
    return k


def _apply(db: Session, co: Company, k: KpiDefinition, data: dict, fields: set[str]) -> None:
    if "name" in fields:
        name = (data.get("name") or "").strip()
        if not name:
            raise _err(422, "KPI cần có tên, ví dụ \"Đơn giao đúng hẹn\".")
        k.name = name[:200]
    for f, allowed, msg in (("level", LEVELS, "Tầng KPI phải là company, department, position hoặc seat."),
                            ("period", PERIODS, "Kỳ KPI phải là week, month hoặc quarter."),
                            ("direction", ("up", "down"), "Hướng phải là up (càng cao càng tốt) hoặc down."),
                            ("metric", tuple(METRICS), "Nguồn số không hợp lệ — chọn trong danh sách hoặc \"Nhập tay\".")):
        if f in fields and data.get(f) is not None:
            if data[f] not in allowed:
                raise _err(422, msg)
            setattr(k, f, data[f])
    if "metric" in fields and "direction" not in fields and data.get("metric"):
        k.direction = METRICS[data["metric"]]["direction"]
    if "unit" in fields:
        k.unit = (data.get("unit") or "")[:40]
    if "target" in fields:
        k.target = data.get("target")
    if "weight" in fields and data.get("weight") is not None:
        if data["weight"] <= 0:
            raise _err(422, "Trọng số phải lớn hơn 0.")
        k.weight = float(data["weight"])
    for f, model, label in (("department_id", Department, "Phòng ban"), ("position_id", Position, "Chức danh"),
                            ("member_id", Member, "Seat"), ("process_id", Process, "Quy trình")):
        if f in fields:
            v = data.get(f)
            if v is not None:
                row = db.get(model, v)
                if row is None or getattr(row, "company_id", co.id) != co.id:
                    raise _err(422, f"{label} #{v} không thuộc công ty {co.name}.")
            setattr(k, f, v)
    if "parent_id" in fields:
        v = data.get("parent_id")
        if v is not None:
            par = db.get(KpiDefinition, v)
            if par is None or par.company_id != co.id:
                raise _err(422, f"KPI cha #{v} không thuộc công ty này.")
            seen, cur = {k.id}, par
            while cur is not None:
                if cur.id in seen:
                    raise _err(409, "Không đặt được KPI cha này: sẽ tạo vòng (KPI con lại là cha của chính nó).")
                seen.add(cur.id)
                cur = db.get(KpiDefinition, cur.parent_id) if cur.parent_id else None
        k.parent_id = v
    for f in ("goal_id", "objective_id"):
        if f in fields:
            v = data.get(f)
            if v is not None:
                from app.models.v9 import ExecutiveGoal
                from app.models.v14 import PortfolioObjective
                row = db.get(ExecutiveGoal if f == "goal_id" else PortfolioObjective, v)
                # an org-wide goal (company_id NULL) of the same org is fine; another org's or company's is not
                if row is None or row.organization_id != co.organization_id or row.company_id not in (None, co.id):
                    label = "Mục tiêu" if f == "goal_id" else "Mục tiêu danh mục"
                    raise _err(422, f"{label} #{v} không thuộc công ty {co.name}.")
            setattr(k, f, v)
    need = {"department": k.department_id, "position": k.position_id, "seat": k.member_id}.get(k.level, True)
    if not need:
        raise _err(422, {"department": "KPI tầng phòng ban cần chọn phòng ban.", "position": "KPI tầng chức danh cần chọn chức danh.",
                         "seat": "KPI tầng seat cần chọn người/agent."}[k.level])


def create_kpi(db: Session, org_id: int, data: dict) -> dict:
    from app.services.company_foundation import _company
    co = _company(db, org_id, data.get("company_id"), write=True)
    k = KpiDefinition(organization_id=org_id, company_id=co.id, name="")
    _apply(db, co, k, data, set(data) | {"name"})
    db.add(k); db.commit(); db.refresh(k)
    return evaluate(db, k)


def update_kpi(db: Session, org_id: int, kid: int, data: dict, fields: set[str]) -> dict:
    k = _kpi(db, org_id, kid)
    _apply(db, db.get(Company, k.company_id), k, data, fields)
    db.commit(); db.refresh(k)
    return evaluate(db, k)


def delete_kpi(db: Session, org_id: int, kid: int) -> dict:
    k = _kpi(db, org_id, kid)
    for c in db.query(KpiDefinition).filter(KpiDefinition.parent_id == k.id).all():
        c.parent_id = k.parent_id
    k.status = "archived"
    db.commit()
    return {"id": k.id, "status": k.status}


def record(db: Session, org_id: int, kid: int, value: float, *, note: str = "", period_key: str | None = None,
           member_id: int | None = None) -> dict:
    k = _kpi(db, org_id, kid)
    key = period_key or period_window(k.period)[0]
    db.add(KpiMeasurement(kpi_id=k.id, period_key=key[:16], value=float(value), source="manual", note=note[:400],
                          recorded_by_member_id=member_id))
    db.commit()
    return evaluate(db, k)


# ------------------------------------------------------------------ chức danh → KPI (M2b → D5)

GUESS = (("chu trình", "cycle_time_minutes"), ("cycle", "cycle_time_minutes"), ("đúng hạn", "on_time_rate"),
         ("on time", "on_time_rate"), ("chi phí", "cost_per_task_usd"), ("cost", "cost_per_task_usd"),
         ("lần đầu", "first_pass_rate"), ("first", "first_pass_rate"), ("việc xong", "tasks_done"),
         ("tasks", "tasks_done"), ("đơn xử lý", "tasks_done"), ("lần chạy", "process_runs_done"))
PERIOD_OF = {"day": "week", "week": "week", "month": "month", "quarter": "quarter", "year": "quarter"}


def guess_metric(name: str) -> str:
    n = (name or "").lower()
    return next((m for kw, m in GUESS if kw in n), "manual")


def sync_positions(db: Session, org_id: int, company_id: int | None) -> dict:
    """Mỗi KPI của chức danh (M2b) → một KPI tầng chức danh (con của KPI phòng ban cùng nguồn số nếu có),
    và mỗi người đang ngồi → một KPI tầng seat (con). Chạy lại an toàn: cập nhật mục tiêu, không nhân đôi."""
    from app.services.company_foundation import _company, seats_of
    co = _company(db, org_id, company_id, write=True)
    made = updated = 0
    for p in db.query(Position).filter(Position.company_id == co.id, Position.status != "archived").all():
        for spec in (p.kpis or []):
            name = (spec.get("name") or "").strip()
            if not name:
                continue
            metric = guess_metric(name)
            row = (db.query(KpiDefinition).filter(KpiDefinition.company_id == co.id, KpiDefinition.level == "position",
                                                  KpiDefinition.position_id == p.id, KpiDefinition.name == name,
                                                  KpiDefinition.status == "active").first())
            parent = None
            if p.department_id:
                parent = (db.query(KpiDefinition).filter(KpiDefinition.company_id == co.id, KpiDefinition.level == "department",
                                                         KpiDefinition.department_id == p.department_id,
                                                         KpiDefinition.metric == metric, KpiDefinition.status == "active").first()
                          if metric != "manual" else None)
            if row is None:
                row = KpiDefinition(organization_id=org_id, company_id=co.id, level="position", position_id=p.id,
                                    department_id=p.department_id, name=name, source="position", metric=metric,
                                    direction=METRICS[metric]["direction"], parent_id=parent.id if parent else None)
                db.add(row); made += 1
            else:
                updated += 1
            row.target, row.unit = spec.get("target"), (spec.get("unit") or "")[:40]
            row.period = PERIOD_OF.get(spec.get("period") or "month", "month")
            db.commit(); db.refresh(row)
            for m in seats_of(db, p.id):
                seat = (db.query(KpiDefinition).filter(KpiDefinition.parent_id == row.id, KpiDefinition.level == "seat",
                                                       KpiDefinition.member_id == m.id, KpiDefinition.status == "active").first())
                if seat is None:
                    seat = KpiDefinition(organization_id=org_id, company_id=co.id, level="seat", member_id=m.id,
                                         position_id=p.id, department_id=p.department_id, parent_id=row.id, name=name,
                                         source="position", metric=metric, direction=row.direction)
                    db.add(seat); made += 1
                seat.target, seat.unit, seat.period = row.target, row.unit, row.period
                db.commit()
    return {"company_id": co.id, "created": made, "updated": updated}


def seat_kpis(db: Session, member_id: int) -> list[dict]:
    rows = db.query(KpiDefinition).filter(KpiDefinition.member_id == member_id, KpiDefinition.level == "seat",
                                          KpiDefinition.status == "active").all()
    return [{k: v for k, v in evaluate(db, r).items() if k in ("id", "name", "unit", "target", "value", "value_source",
                                                                "progress", "health", "period_key", "metric")} for r in rows]
