"""M2e.4 — vận hành 24/7. Spec: docs/m2e-agent-native-company.md (mục M2e.4).

* Ghế **agent** luôn trực: không giờ làm, không ngày nghỉ, không lễ (không có hàng ``seat_schedules``).
* Ghế **người** có giờ làm theo tuần (giờ Việt Nam mặc định: T2–T6 08:00–17:30, T7 08:00–12:00), nghỉ phép theo ngày,
  nghỉ lễ theo ``public_holidays`` của tổ chức (ngày làm bù = làm như thứ Hai).
* **SLA** theo bước quy trình hoặc chức danh: phản hồi đầu (việc chuyển Đang làm / ghi sổ) và xử lý xong. Phút SLA tính
  theo giờ trực của ghế nhận việc — agent: đồng hồ thật; người: chỉ phút trong giờ làm. Quá hạn → leo thang theo
  ``escalation.chain`` (tới NGƯỜI) + Hộp việc ``sla_breach``; việc chưa bắt tay mà người nhận đang ngoài giờ → chuyển
  ghế agent cùng chức danh nếu có.
* **Ngoài giờ**: việc (bước quy trình hoặc có SLA) giao cho người đang ngoài giờ → chuyển ghế agent cùng chức danh
  (``rerouted``), không có agent → giữ người và xếp hàng với "người xử lý lúc HH:MM" (``queued``).
* Độ phủ: lưới 7×24 mỗi chức danh (giờ agent vs giờ người), tỷ lệ đạt SLA, hàng chờ.

Giới hạn thật: lưới độ phủ dựa trên lịch tuần mẫu (nghỉ phép/lễ hiện ở danh sách ghế, không trừ vào lưới); SLA đo bằng
mốc trạng thái việc, không đo câu trả lời đầu tiên gửi khách trên kênh chat."""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Member, Project, Task
from app.models.agent_native import AfterHoursRoute, SeatLeave, SeatSchedule, SlaPolicy, SlaTimer
from app.models.company_foundation import Position

TZ = "Asia/Ho_Chi_Minh"
UTC = ZoneInfo("UTC")
DEFAULT_WEEKLY = {"0": [["08:00", "17:30"]], "1": [["08:00", "17:30"]], "2": [["08:00", "17:30"]],
                  "3": [["08:00", "17:30"]], "4": [["08:00", "17:30"]], "5": [["08:00", "12:00"]], "6": []}
OPEN = ("backlog", "todo", "in_progress", "review", "blocked")
MAX_MINUTES = 60 * 24 * 30
LEAVE_KINDS = ("annual", "sick", "other")


def _err(status: int, msg: str) -> HTTPException:
    return HTTPException(status, msg)


def is_agent(m: Member | None) -> bool:
    return m is not None and m.member_type == "agent"


def _active(m: Member | None) -> bool:
    return m is not None and (m.status or "active") in ("active", "onboarding")


# ------------------------------------------------------------------ lịch của ghế người

def _hm(s: str) -> int:
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def clean_weekly(raw) -> dict:
    if not isinstance(raw, dict):
        raise _err(422, "Giờ làm phải theo dạng {\"0\": [[\"08:00\", \"17:30\"]], …} (0 = thứ Hai … 6 = Chủ nhật).")
    out = {}
    for k in map(str, range(7)):
        ranges = raw.get(k, raw.get(int(k), [])) or []
        clean = []
        for r in ranges:
            if not (isinstance(r, (list, tuple)) and len(r) == 2 and all(isinstance(x, str) and re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d|24:00", x) for x in r)):
                raise _err(422, f"Ngày {k}: khung giờ \"{r}\" không hợp lệ — dùng [\"HH:MM\", \"HH:MM\"].")
            if _hm(r[1]) <= _hm(r[0]):
                raise _err(422, f"Ngày {k}: giờ kết thúc {r[1]} phải sau giờ bắt đầu {r[0]} (ca qua đêm: tách thành hai ngày).")
            clean.append([r[0], r[1]])
        clean.sort(key=lambda r: _hm(r[0]))
        for a, b in zip(clean, clean[1:]):
            if _hm(b[0]) < _hm(a[1]):
                raise _err(422, f"Ngày {k}: hai khung giờ chồng nhau ({a[0]}–{a[1]} và {b[0]}–{b[1]}).")
        out[k] = clean
    return out


def schedule_of(db: Session, m: Member) -> dict:
    if is_agent(m):
        return {"always_on": True, "timezone": TZ, "weekly": None, "observe_holidays": False, "default": False}
    row = db.query(SeatSchedule).filter(SeatSchedule.member_id == m.id).first()
    if row is None:
        return {"always_on": False, "timezone": TZ, "weekly": DEFAULT_WEEKLY, "observe_holidays": True, "default": True}
    return {"always_on": False, "timezone": row.timezone or TZ, "weekly": row.weekly or DEFAULT_WEEKLY,
            "observe_holidays": bool(row.observe_holidays), "default": False}


def _day_info(db: Session, m: Member, d: date, sched: dict, cache: dict) -> tuple[list[list[str]], str]:
    """(khung giờ của ngày ``d`` theo giờ địa phương, lý do nghỉ nếu cả ngày nghỉ)."""
    from app.models.company_ops import PublicHoliday
    key = ("leave", m.id)
    if key not in cache:
        cache[key] = db.query(SeatLeave).filter(SeatLeave.member_id == m.id).all()
    for lv in cache[key]:
        if lv.start_date <= d <= lv.end_date:
            return [], f"nghỉ phép ({lv.kind})"
    weekly = sched["weekly"] or DEFAULT_WEEKLY
    if sched["observe_holidays"]:
        hk = ("hol", m.organization_id, d.year)
        if hk not in cache:
            cache[hk] = {h.day: h for h in db.query(PublicHoliday).filter(PublicHoliday.organization_id == m.organization_id,
                                                                          PublicHoliday.year == d.year).all()}
        h = cache[hk].get(d)
        if h is not None and h.kind == "holiday":
            return [], f"nghỉ lễ: {h.name}"
        if h is not None and h.kind == "makeup_workday":
            return weekly.get("0") or [], ""
    return weekly.get(str(d.weekday())) or [], ""


def _intervals(db: Session, m: Member, start_utc: datetime, days: int, cache: dict | None = None) -> list[tuple[datetime, datetime]]:
    """Khung giờ làm (UTC naive) từ ngày địa phương chứa ``start_utc`` trong ``days`` ngày."""
    sched = schedule_of(db, m)
    tz = ZoneInfo(sched["timezone"])
    cache = {} if cache is None else cache
    local0 = start_utc.replace(tzinfo=UTC).astimezone(tz).date()
    out = []
    for i in range(days):
        d = local0 + timedelta(days=i)
        ranges, _ = _day_info(db, m, d, sched, cache)
        for a, b in ranges:
            sa = datetime(d.year, d.month, d.day, tzinfo=tz) + timedelta(minutes=_hm(a))
            sb = datetime(d.year, d.month, d.day, tzinfo=tz) + timedelta(minutes=_hm(b))
            out.append((sa.astimezone(UTC).replace(tzinfo=None), sb.astimezone(UTC).replace(tzinfo=None)))
    return out


def on_duty(db: Session, m: Member | None, now: datetime | None = None) -> bool:
    if not _active(m):
        return False
    if is_agent(m):
        return True
    now = now or datetime.utcnow()
    return any(a <= now < b for a, b in _intervals(db, m, now - timedelta(days=1), 2))


def next_on_duty(db: Session, m: Member, now: datetime | None = None) -> datetime | None:
    now = now or datetime.utcnow()
    if is_agent(m):
        return now
    for a, b in _intervals(db, m, now - timedelta(days=1), 32):
        if b > now:
            return max(a, now)
    return None


def add_working_minutes(db: Session, m: Member | None, start: datetime, minutes: int) -> datetime:
    """Hạn = ``start`` + ``minutes`` phút TRỰC của ghế (agent: đồng hồ thật)."""
    if m is None or is_agent(m):
        return start + timedelta(minutes=minutes)
    left = minutes
    for a, b in _intervals(db, m, start - timedelta(days=1), 62):
        if b <= start:
            continue
        a = max(a, start)
        span = (b - a).total_seconds() / 60
        if span >= left:
            return a + timedelta(minutes=left)
        left -= span
    return start + timedelta(minutes=minutes)       # không có giờ làm trong 2 tháng → đồng hồ thật


def local_hm(db: Session, m: Member | None, t: datetime | None) -> str:
    if t is None:
        return "—"
    tz = ZoneInfo(schedule_of(db, m)["timezone"] if m is not None else TZ)
    loc = t.replace(tzinfo=UTC).astimezone(tz)
    now = datetime.utcnow().replace(tzinfo=UTC).astimezone(tz)
    return loc.strftime("%H:%M") if loc.date() == now.date() else loc.strftime("%H:%M %d/%m")


def weekly_minutes(sched: dict) -> int:
    if sched.get("always_on"):
        return 7 * 24 * 60
    return sum(_hm(b) - _hm(a) for ranges in (sched["weekly"] or {}).values() for a, b in ranges)


def save_schedule(db: Session, org_id: int, member_id: int, data: dict) -> dict:
    m = _member(db, org_id, member_id)
    if is_agent(m):
        raise _err(422, f"{m.name} là ghế agent — luôn trực 24/7, không có giờ làm hay ngày nghỉ.")
    row = db.query(SeatSchedule).filter(SeatSchedule.member_id == m.id).first() or SeatSchedule(member_id=m.id)
    if "weekly" in data:
        row.weekly = clean_weekly(data["weekly"])
    if "timezone" in data and data["timezone"]:
        try:
            ZoneInfo(data["timezone"])
        except Exception:  # noqa: BLE001
            raise _err(422, f"Múi giờ \"{data['timezone']}\" không hợp lệ (ví dụ Asia/Ho_Chi_Minh).") from None
        row.timezone = data["timezone"]
    if "observe_holidays" in data:
        row.observe_holidays = bool(data["observe_holidays"])
    db.add(row); db.commit()
    return seat_view(db, m)


def _member(db: Session, org_id: int, member_id: int) -> Member:
    m = db.get(Member, member_id)
    if m is None or m.organization_id != org_id:
        raise _err(404, "Không thấy ghế này.")
    from app.core import company_scope as _cs
    _cs.check(m.company_id)  # R1 vai trò theo công ty
    return m


def add_leave(db: Session, org_id: int, member_id: int, data: dict) -> dict:
    m = _member(db, org_id, member_id)
    if is_agent(m):
        raise _err(422, f"{m.name} là ghế agent — không có ngày nghỉ.")
    try:
        a, b = date.fromisoformat(str(data.get("start_date"))), date.fromisoformat(str(data.get("end_date") or data.get("start_date")))
    except ValueError:
        raise _err(422, "Ngày nghỉ phải dạng YYYY-MM-DD.") from None
    if b < a:
        raise _err(422, "Ngày kết thúc nghỉ phải từ ngày bắt đầu trở đi.")
    if (b - a).days > 365:
        raise _err(422, "Một lần nghỉ tối đa 1 năm.")
    kind = data.get("kind") or "annual"
    if kind not in LEAVE_KINDS:
        raise _err(422, "Loại nghỉ: annual (phép năm), sick (ốm), other (khác).")
    lv = SeatLeave(member_id=m.id, start_date=a, end_date=b, kind=kind, note=(data.get("note") or "")[:300])
    db.add(lv); db.commit()
    return seat_view(db, m)


def delete_leave(db: Session, org_id: int, leave_id: int) -> dict:
    lv = db.get(SeatLeave, leave_id)
    m = db.get(Member, lv.member_id) if lv else None
    if lv is None or m is None or m.organization_id != org_id:
        raise _err(404, "Không thấy ngày nghỉ này.")
    from app.core import company_scope as _cs
    _cs.check(m.company_id)  # R1 vai trò theo công ty
    db.delete(lv); db.commit()
    return seat_view(db, m)


def seat_view(db: Session, m: Member, now: datetime | None = None) -> dict:
    now = now or datetime.utcnow()
    sched = schedule_of(db, m)
    duty = on_duty(db, m, now)
    nxt = None if duty or is_agent(m) else next_on_duty(db, m, now)
    tz = ZoneInfo(sched["timezone"])
    today = now.replace(tzinfo=UTC).astimezone(tz).date()
    leaves = [] if is_agent(m) else db.query(SeatLeave).filter(SeatLeave.member_id == m.id, SeatLeave.end_date >= today - timedelta(days=30)).order_by(SeatLeave.start_date).all()
    _, off_reason = (([], "") if is_agent(m) else _day_info(db, m, today, sched, {}))
    return {"member_id": m.id, "name": m.name, "member_type": m.member_type, "position_id": m.position_id,
            "always_on": sched["always_on"], "timezone": sched["timezone"], "weekly": sched["weekly"],
            "observe_holidays": sched["observe_holidays"], "default_schedule": sched["default"],
            "weekly_hours": round(weekly_minutes(sched) / 60, 1), "on_duty": duty,
            "next_on_duty": nxt.isoformat() if nxt else None, "next_on_duty_local": local_hm(db, m, nxt) if nxt else None,
            "off_today": off_reason,
            "leaves": [{"id": lv.id, "start_date": lv.start_date.isoformat(), "end_date": lv.end_date.isoformat(),
                        "kind": lv.kind, "note": lv.note} for lv in leaves]}


# ------------------------------------------------------------------ chọn ghế / ngoài giờ

def seats_by_duty(db: Session, seats: list[Member], now: datetime | None = None) -> list[Member]:
    """Ghế đang trực trước (agent luôn trực), giữ nguyên thứ tự còn lại."""
    now = now or datetime.utcnow()
    return sorted(seats, key=lambda m: 0 if on_duty(db, m, now) else 1)


def _position_of_task(db: Session, task: Task) -> int | None:
    from app.models.company_ops import ProcessStepRun
    run = db.query(ProcessStepRun).filter(ProcessStepRun.task_id == task.id).first()
    if run is not None and run.position_id:
        return run.position_id
    m = db.get(Member, task.assignee_member_id) if task.assignee_member_id else None
    return m.position_id if m is not None else None


def _company_of(db: Session, task: Task) -> tuple[int | None, int | None]:
    from app.models import Company
    pr = db.get(Project, task.project_id) if task.project_id else None
    co = db.get(Company, pr.company_id) if pr else None
    return (co.organization_id if co else None, co.id if co else None)


def route(db: Session, task: Task, now: datetime | None = None) -> dict | None:
    """Việc của ghế người đang ngoài giờ → chuyển agent cùng chức danh, hoặc xếp hàng chờ người. Idempotent theo việc."""
    from app.services import inbox, task_journal, wakeup
    now = now or datetime.utcnow()
    if task.status not in ("backlog", "todo") or not task.assignee_member_id:
        return None
    m = db.get(Member, task.assignee_member_id)
    if m is None or is_agent(m) or on_duty(db, m, now):
        return None
    if db.query(AfterHoursRoute).filter(AfterHoursRoute.task_id == task.id, AfterHoursRoute.status == "open").first():
        return None
    org, co = _company_of(db, task)
    pid = _position_of_task(db, task)
    agents = [s for s in db.query(Member).filter(Member.position_id == pid, Member.member_type == "agent").all() if _active(s)] if pid else []
    nxt = next_on_duty(db, m, now)
    if agents:
        from app.services.process_map import _open_load
        to = min(agents, key=lambda s: (_open_load(db, s.id), s.id))
        r = AfterHoursRoute(organization_id=org or m.organization_id, company_id=co, task_id=task.id, from_member_id=m.id,
                            to_member_id=to.id, position_id=pid, action="rerouted", next_available_at=nxt,
                            reason=f"{m.name} ngoài giờ (trực lại {local_hm(db, m, nxt)}) → {to.name} (agent cùng chức danh, trực 24/7)",
                            status="done")
        task.assignee_member_id = to.id
        db.add(r); db.commit()
        from app.models.company_ops import ProcessStepRun
        for run in db.query(ProcessStepRun).filter(ProcessStepRun.task_id == task.id).all():
            run.assignee_member_id = to.id
        for t in db.query(SlaTimer).filter(SlaTimer.task_id == task.id, SlaTimer.status == "running").all():
            t.member_id, t.seat_type = to.id, "agent"
            t.due_at = add_working_minutes(db, to, t.started_at, t.minutes)
        db.commit()
        _journal(db, task, f"Ngoài giờ: chuyển từ {m.name} sang {to.name} (agent cùng chức danh, trực 24/7)")
        inbox.notify(db, organization_id=r.organization_id, recipients=[m.id], kind="after_hours", task_id=task.id,
                     title=f"Việc tới ngoài giờ đã chuyển cho {to.name}: {task.title}"[:220],
                     line=r.reason[:400], source="operating_time", company_id=co)
        wakeup.enqueue_for_task(db, task, "assigned", dedupe_key=f"after_hours:t{task.id}", member_id=to.id,
                                payload={"after_hours_from": m.id})
        return {"action": "rerouted", "to": to.id, "to_name": to.name, "next_on_duty": nxt.isoformat() if nxt else None}
    r = AfterHoursRoute(organization_id=org or m.organization_id, company_id=co, task_id=task.id, from_member_id=m.id,
                        to_member_id=None, position_id=pid, action="queued", next_available_at=nxt,
                        reason=f"Không có agent cùng chức danh — chờ {m.name}, người xử lý lúc {local_hm(db, m, nxt)}", status="open")
    db.add(r); db.commit()
    _journal(db, task, f"Ngoài giờ của {m.name}: xếp hàng — người xử lý lúc {local_hm(db, m, nxt)}")
    inbox.notify(db, organization_id=r.organization_id, recipients=[m.id], kind="after_hours", task_id=task.id,
                 title=f"Việc chờ anh/chị lúc {local_hm(db, m, nxt)}: {task.title}"[:220],
                 line=r.reason[:400], source="operating_time", company_id=co)
    return {"action": "queued", "next_on_duty": nxt.isoformat() if nxt else None, "next_on_duty_local": local_hm(db, m, nxt)}


def _journal(db: Session, task: Task, text: str) -> None:
    from app.services import task_journal
    try:
        task_journal.append(db, task, kind="note", summary=text[:390])
    except Exception as exc:  # noqa: BLE001
        db.rollback(); print(f"[m2e.4] journal: {exc}")


# ------------------------------------------------------------------ SLA

def _policy(db: Session, org_id: int, pid: int) -> SlaPolicy:
    p = db.get(SlaPolicy, pid)
    if p is None or p.organization_id != org_id:
        raise _err(404, "Không thấy SLA này.")
    from app.core import company_scope as _cs
    _cs.check(p.company_id)  # R1 vai trò theo công ty
    return p


def _apply_policy(db: Session, p: SlaPolicy, data: dict) -> None:
    from app.models.company_ops import Process, ProcessStep
    if "position_id" in data or "process_step_id" in data:
        pos_id, step_id = data.get("position_id"), data.get("process_step_id")
        if bool(pos_id) == bool(step_id):
            raise _err(422, "SLA gắn đúng một nơi: một chức danh HOẶC một bước quy trình.")
        if pos_id:
            pos = db.get(Position, pos_id)
            if pos is None or pos.company_id != p.company_id:
                raise _err(422, f"Chức danh #{pos_id} không thuộc công ty này.")
        if step_id:
            st = db.get(ProcessStep, step_id)
            pr = db.get(Process, st.process_id) if st else None
            if pr is None or pr.company_id != p.company_id:
                raise _err(422, f"Bước quy trình #{step_id} không thuộc công ty này.")
        p.position_id, p.process_step_id = pos_id or None, step_id or None
    for f in ("first_response_minutes", "resolution_minutes"):
        if f in data:
            v = data[f]
            if v is not None and (not isinstance(v, int) or isinstance(v, bool) or not 1 <= v <= MAX_MINUTES):
                raise _err(422, "Phút SLA phải là số nguyên dương (tối đa 30 ngày).")
            setattr(p, f, v)
    if "name" in data:
        p.name = (data.get("name") or "").strip()[:200]
    if "enabled" in data:
        p.enabled = bool(data["enabled"])
    if not p.first_response_minutes and not p.resolution_minutes:
        raise _err(422, "SLA cần ít nhất một mốc: phản hồi đầu hoặc xử lý xong (phút).")
    if p.first_response_minutes and p.resolution_minutes and p.resolution_minutes < p.first_response_minutes:
        raise _err(422, "Thời hạn xử lý xong phải dài hơn thời hạn phản hồi đầu.")


def create_policy(db: Session, org_id: int, data: dict) -> SlaPolicy:
    from app.services.company_foundation import _company
    co = _company(db, org_id, data.get("company_id"), write=True)
    p = SlaPolicy(organization_id=org_id, company_id=co.id, enabled=True)
    _apply_policy(db, p, {"position_id": data.get("position_id"), "process_step_id": data.get("process_step_id"),
                          **{k: v for k, v in data.items() if k not in ("company_id",)}})
    db.add(p); db.commit(); db.refresh(p)
    return p


def update_policy(db: Session, org_id: int, pid: int, data: dict) -> SlaPolicy:
    p = _policy(db, org_id, pid)
    _apply_policy(db, p, data)
    db.commit(); db.refresh(p)
    return p


def delete_policy(db: Session, org_id: int, pid: int) -> dict:
    p = _policy(db, org_id, pid)
    db.query(SlaTimer).filter(SlaTimer.policy_id == p.id, SlaTimer.status == "running").update({"status": "cancelled"})
    db.query(SlaTimer).filter(SlaTimer.policy_id == p.id).update({"policy_id": None})
    db.delete(p); db.commit()
    return {"deleted": pid}


def public_policy(db: Session, p: SlaPolicy) -> dict:
    from app.models.company_ops import Process, ProcessStep
    pos = db.get(Position, p.position_id) if p.position_id else None
    st = db.get(ProcessStep, p.process_step_id) if p.process_step_id else None
    pr = db.get(Process, st.process_id) if st else None
    return {"id": p.id, "company_id": p.company_id, "name": p.name, "position_id": p.position_id,
            "position": pos.title if pos else None, "process_step_id": p.process_step_id,
            "step": f"{pr.name} · B{st.seq} {st.name}" if st and pr else None,
            "first_response_minutes": p.first_response_minutes, "resolution_minutes": p.resolution_minutes,
            "enabled": bool(p.enabled)}


def policy_for(db: Session, task: Task) -> SlaPolicy | None:
    from app.models.company_ops import ProcessStepRun
    run = db.query(ProcessStepRun).filter(ProcessStepRun.task_id == task.id).first()
    if run is not None and run.step_id:
        p = db.query(SlaPolicy).filter(SlaPolicy.process_step_id == run.step_id, SlaPolicy.enabled.is_(True)).first()
        if p is not None:
            return p
    pid = _position_of_task(db, task)
    if pid:
        return db.query(SlaPolicy).filter(SlaPolicy.position_id == pid, SlaPolicy.enabled.is_(True)).first()
    return None


def start_timers(db: Session, task: Task, *, now: datetime | None = None, policy: SlaPolicy | None = None) -> list[SlaTimer]:
    """Bật đồng hồ SLA cho việc (một lần mỗi loại). Không có SLA áp dụng → không làm gì."""
    now = now or datetime.utcnow()
    if task.status in ("done", "cancelled"):
        return []
    p = policy or policy_for(db, task)
    if p is None:
        return []
    if db.query(SlaTimer).filter(SlaTimer.task_id == task.id).count():
        return []
    m = db.get(Member, task.assignee_member_id) if task.assignee_member_id else None
    org, co = _company_of(db, task)
    out = []
    for kind, minutes in (("first_response", p.first_response_minutes), ("resolution", p.resolution_minutes)):
        if not minutes:
            continue
        if kind == "first_response" and task.status in ("in_progress", "review"):
            continue
        t = SlaTimer(organization_id=org or p.organization_id, company_id=co, task_id=task.id, policy_id=p.id, kind=kind,
                     member_id=m.id if m else None, position_id=_position_of_task(db, task),
                     seat_type=("agent" if is_agent(m) else "human") if m else "", minutes=minutes, started_at=now,
                     due_at=add_working_minutes(db, m, now, minutes), status="running")
        db.add(t); out.append(t)
    db.commit()
    return out


def on_task_status(db: Session, task: Task, to: str) -> None:
    """Gọi từ ``task_lifecycle.transition``. Không bao giờ ném."""
    try:
        now = datetime.utcnow()
        timers = db.query(SlaTimer).filter(SlaTimer.task_id == task.id, SlaTimer.status.in_(("running", "breached"))).all()
        if not timers:
            return
        for t in timers:
            if to == "cancelled" and t.status == "running":
                t.status = "cancelled"
            elif t.kind == "first_response" and to in ("in_progress", "review", "done") and t.met_at is None:
                t.met_at = now
                t.status = "met" if t.status == "running" else t.status
            elif t.kind == "resolution" and to == "done" and t.met_at is None:
                t.met_at = now
                t.status = "met" if t.status == "running" else t.status
        db.commit()
        if to in ("done", "cancelled"):
            db.query(AfterHoursRoute).filter(AfterHoursRoute.task_id == task.id, AfterHoursRoute.status == "open").update({"status": "done"})
            db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback(); print(f"[m2e.4] sla status task #{task.id}: {exc}")


def breach(db: Session, t: SlaTimer, now: datetime) -> dict:
    from app.services import escalation, inbox
    task = db.get(Task, t.task_id)
    m = db.get(Member, task.assignee_member_id) if task and task.assignee_member_id else None
    t.status, t.breached_at = "breached", now
    target, why = escalation.human_target(db, m) if m is not None else (None, "")
    t.escalated_to_member_id = target
    db.commit()
    rerouted = None
    if task is not None and m is not None and not is_agent(m) and not on_duty(db, m, now) and task.status in ("backlog", "todo"):
        rerouted = route(db, task, now)
    label = "phản hồi đầu" if t.kind == "first_response" else "xử lý xong"
    over = int((now - t.due_at).total_seconds() // 60)
    if task is not None:
        _journal(db, task, f"Quá hạn SLA {label} ({t.minutes} phút, trễ {over} phút) → leo thang tới "
                           f"{db.get(Member, target).name if target else 'chưa có người'}")
        if target:
            inbox.notify(db, organization_id=t.organization_id, recipients=[target], kind="sla_breach", task_id=task.id,
                         title=f"Quá hạn SLA {label}: {task.title}"[:220], priority="high", source="sla",
                         line=f"{m.name if m else 'Chưa giao'} · hạn {t.minutes} phút trực, trễ {over} phút · {why}"[:400],
                         company_id=t.company_id)
    return {"timer": t.id, "task": t.task_id, "kind": t.kind, "escalated_to": target, "rerouted": rerouted}


def tick(db: Session, now: datetime | None = None) -> dict:
    """Beat ``sla.tick``: bật đồng hồ còn thiếu (SLA theo chức danh), quá hạn → leo thang, việc ngoài giờ → chuyển/xếp
    hàng, hàng chờ tới giờ người trực → đóng."""
    from app.models import Company
    from app.models.company_ops import ProcessStepRun
    now = now or datetime.utcnow()
    started = breached = routed = 0
    live = {c.id for c in db.query(Company).filter(Company.status != "archived").all()}
    pols = db.query(SlaPolicy).filter(SlaPolicy.enabled.is_(True), SlaPolicy.company_id.in_(live or [-1])).all()
    since = now - timedelta(days=7)
    # 1) SLA theo chức danh: việc mở của ghế chức danh đó chưa có đồng hồ
    pos_pol = {p.position_id: p for p in pols if p.position_id}
    if pos_pol:
        seats = {m.id: m.position_id for m in db.query(Member).filter(Member.position_id.in_(list(pos_pol))).all()}
        for task in db.query(Task).filter(Task.assignee_member_id.in_(list(seats) or [-1]), Task.status.in_(("backlog", "todo", "in_progress")),
                                          Task.created_at >= since).all():
            if not db.query(SlaTimer).filter(SlaTimer.task_id == task.id).count():
                started += len(start_timers(db, task, now=now))
    # 2) quá hạn
    for t in db.query(SlaTimer).filter(SlaTimer.status == "running", SlaTimer.due_at <= now).all():
        breach(db, t, now); breached += 1
    # 3) ngoài giờ: việc bước quy trình / có SLA, chưa bắt tay, giao người đang ngoài giờ
    cand = set(r.task_id for r in db.query(ProcessStepRun).filter(ProcessStepRun.status == "active").all() if r.task_id)
    cand |= set(t.task_id for t in db.query(SlaTimer).filter(SlaTimer.status.in_(("running", "breached"))).all())
    for tid in cand:
        task = db.get(Task, tid)
        if task is not None and task.status == "todo" and route(db, task, now):
            routed += 1
    # 4) hàng chờ: người đã trực lại → đóng
    for r in db.query(AfterHoursRoute).filter(AfterHoursRoute.status == "open").all():
        task = db.get(Task, r.task_id)
        m = db.get(Member, r.from_member_id) if r.from_member_id else None
        if task is None or task.status not in ("backlog", "todo") or (m is not None and on_duty(db, m, now)):
            r.status = "done"
    db.commit()
    return {"started": started, "breached": breached, "routed": routed}


def attainment(db: Session, *, company_id: int | None = None, member_ids: list[int] | None = None,
               start: datetime | None = None, end: datetime | None = None, days: int = 30) -> dict:
    q = db.query(SlaTimer).filter(SlaTimer.status.in_(("met", "breached")))
    start = start or datetime.utcnow() - timedelta(days=days)
    q = q.filter(SlaTimer.started_at >= start)
    if end is not None:
        q = q.filter(SlaTimer.started_at < end)
    if company_id is not None:
        q = q.filter(SlaTimer.company_id == company_id)
    if member_ids is not None:
        q = q.filter(SlaTimer.member_id.in_(member_ids or [-1]))
    rows = q.all()
    # met: đúng hạn; breached rồi mới xong vẫn tính là trễ
    met = sum(1 for t in rows if t.status == "met" and t.met_at is not None and t.met_at <= t.due_at)
    return {"closed": len(rows), "met": met, "breached": len(rows) - met,
            "rate": round(met / len(rows), 4) if rows else None,
            "agent": _rate([t for t in rows if t.seat_type == "agent"]), "human": _rate([t for t in rows if t.seat_type == "human"])}


def _rate(rows: list[SlaTimer]) -> float | None:
    if not rows:
        return None
    return round(sum(1 for t in rows if t.status == "met" and t.met_at and t.met_at <= t.due_at) / len(rows), 4)


# ------------------------------------------------------------------ độ phủ 7×24

def _grid(db: Session, seats: list[Member]) -> list[list[dict]]:
    grid = [[{"agents": 0, "humans": 0} for _ in range(24)] for _ in range(7)]
    for m in seats:
        if not _active(m):
            continue
        if is_agent(m):
            for d in range(7):
                for h in range(24):
                    grid[d][h]["agents"] += 1
            continue
        weekly = schedule_of(db, m)["weekly"] or DEFAULT_WEEKLY
        for d in range(7):
            for a, b in weekly.get(str(d)) or []:
                for h in range(24):
                    if min(_hm(b), (h + 1) * 60) - max(_hm(a), h * 60) >= 30:     # ≥ 30 phút trong giờ đó
                        grid[d][h]["humans"] += 1
    return grid


def coverage(db: Session, org_id: int, company_id: int | None, now: datetime | None = None) -> dict:
    from app.services.company_foundation import _company
    from app.models.company_ops import ProcessStep, Process
    now = now or datetime.utcnow()
    co = _company(db, org_id, company_id)
    positions = db.query(Position).filter(Position.company_id == co.id, Position.status != "archived").order_by(Position.id).all()
    out = []
    total_cells = covered_cells = 0
    for p in positions:
        seats = db.query(Member).filter(Member.position_id == p.id, Member.status.notin_(("archived", "retired"))).order_by(Member.id).all()
        grid = _grid(db, seats)
        cells = sum(1 for d in grid for c in d if c["agents"] or c["humans"])
        if seats:
            total_cells += 168; covered_cells += cells
        open_tasks = (db.query(Task).filter(Task.assignee_member_id.in_([s.id for s in seats] or [-1]),
                                            Task.status.in_(("backlog", "todo"))).count())
        queued = db.query(AfterHoursRoute).filter(AfterHoursRoute.position_id == p.id, AfterHoursRoute.status == "open").all()
        out.append({"position_id": p.id, "title": p.title, "grid": grid, "covered_hours": cells,
                    "agent_hours": sum(1 for d in grid for c in d if c["agents"]),
                    "human_hours": sum(1 for d in grid for c in d if c["humans"]),
                    "seats": [seat_view(db, s, now) for s in seats], "queue": open_tasks,
                    "queued_after_hours": [{"task_id": r.task_id, "next_available_at": r.next_available_at.isoformat() if r.next_available_at else None,
                                            "reason": r.reason} for r in queued],
                    "sla": public_policy(db, pp) if (pp := db.query(SlaPolicy).filter(SlaPolicy.position_id == p.id).first()) else None})
    pols = db.query(SlaPolicy).filter(SlaPolicy.company_id == co.id).order_by(SlaPolicy.id).all()
    timers = (db.query(SlaTimer).filter(SlaTimer.company_id == co.id).order_by(SlaTimer.id.desc()).limit(30).all())
    names = {m.id: m.name for m in db.query(Member).filter(Member.company_id == co.id).all()}
    routes = (db.query(AfterHoursRoute).filter(AfterHoursRoute.company_id == co.id).order_by(AfterHoursRoute.id.desc()).limit(20).all())
    steps = [{"id": s.id, "label": f"{pr.name} · B{s.seq} {s.name}"} for s, pr in
             db.query(ProcessStep, Process).join(Process, Process.id == ProcessStep.process_id)
             .filter(Process.company_id == co.id, Process.status != "archived").order_by(Process.id, ProcessStep.seq).all()]
    humans = [seat_view(db, m, now) for m in db.query(Member).filter(Member.company_id == co.id, Member.member_type == "human",
                                                                   Member.status.notin_(("archived", "retired"))).order_by(Member.id).all()]
    return {"company_id": co.id, "company_name": co.name, "now": now.isoformat(),
            "coverage_rate": round(covered_cells / total_cells, 4) if total_cells else None,
            "sla": attainment(db, company_id=co.id),
            "queue": sum(x["queue"] for x in out),
            "queued_after_hours": db.query(AfterHoursRoute).filter(AfterHoursRoute.company_id == co.id, AfterHoursRoute.status == "open").count(),
            "breached_open": db.query(SlaTimer).join(Task, Task.id == SlaTimer.task_id).filter(
                SlaTimer.company_id == co.id, SlaTimer.status == "breached", SlaTimer.met_at.is_(None),
                Task.status.in_(OPEN)).count(),     # việc đã xong/huỷ không còn là "quá hạn chưa xong"
            "positions": out, "policies": [public_policy(db, p) for p in pols], "steps": steps, "humans": humans,
            "timers": [{"id": t.id, "task_id": t.task_id, "kind": t.kind, "seat": names.get(t.member_id or -1), "seat_type": t.seat_type,
                        "minutes": t.minutes, "started_at": t.started_at.isoformat(), "due_at": t.due_at.isoformat(),
                        "met_at": t.met_at.isoformat() if t.met_at else None, "status": t.status,
                        "escalated_to": names.get(t.escalated_to_member_id or -1)} for t in timers],
            "routes": [{"id": r.id, "task_id": r.task_id, "action": r.action, "from": names.get(r.from_member_id or -1),
                        "to": names.get(r.to_member_id or -1), "reason": r.reason, "status": r.status,
                        "created_at": r.created_at.isoformat() if r.created_at else None} for r in routes]}


# ------------------------------------------------------------------ giao ban: ca đêm của agent

def overnight(db: Session, company_id: int, now: datetime, *, tz: str = TZ, department_members: list[int] | None = None) -> dict:
    """Việc agent làm ngoài giờ hành chính (18:00 hôm trước → 08:00 hôm nay, giờ địa phương)."""
    from app.models.work_graph import TaskRun
    z = ZoneInfo(tz)
    loc = now.replace(tzinfo=UTC).astimezone(z)
    # đêm gần nhất: 18:00 hôm trước → 08:00 hôm nay; giao ban sớm hơn 08:00 → tới thời điểm hiện tại
    end_l = min(loc, loc.replace(hour=8, minute=0, second=0, microsecond=0))
    start_l = (end_l - timedelta(days=1)).replace(hour=18, minute=0, second=0, microsecond=0)
    a, b = (x.astimezone(UTC).replace(tzinfo=None) for x in (start_l, end_l))
    agents = [m.id for m in db.query(Member).filter(Member.company_id == company_id, Member.member_type == "agent").all()
              if department_members is None or m.id in department_members]
    done_at = func.coalesce(Task.completed_at, Task.updated_at)
    done = (db.query(Task).join(Project, Project.id == Task.project_id)
            .filter(Project.company_id == company_id, Task.assignee_member_id.in_(agents or [-1]), Task.status == "done",
                    done_at >= a, done_at < b).all())
    runs = db.query(TaskRun).filter(TaskRun.member_id.in_(agents or [-1]), TaskRun.created_at >= a, TaskRun.created_at < b).all()
    rerouted = db.query(AfterHoursRoute).filter(AfterHoursRoute.company_id == company_id, AfterHoursRoute.action == "rerouted",
                                                AfterHoursRoute.created_at >= a, AfterHoursRoute.created_at < b).count()
    queued = db.query(AfterHoursRoute).filter(AfterHoursRoute.company_id == company_id, AfterHoursRoute.status == "open").all()
    return {"window": f"{start_l.strftime('%H:%M %d/%m')}–{end_l.strftime('%H:%M %d/%m')}", "done": len(done),
            "done_titles": [t.title for t in done[:5]], "runs": len(runs), "cost_usd": round(sum(r.cost_usd or 0 for r in runs), 4),
            "rerouted": rerouted, "queued": len(queued),
            "queued_next": sorted({r.next_available_at for r in queued if r.next_available_at})[:1]}
