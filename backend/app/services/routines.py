"""D3.4 — Routines: việc định kỳ (cron theo múi giờ) và việc theo webhook.

Một routine nói *việc gì* (``runbook``), *giao ai* (seat hoặc phòng ban), và
*khi nào* (trigger ``cron`` hoặc ``webhook``). Mỗi lần kích hoạt là một
``routine_runs`` có ``idempotency_key`` UNIQUE — chỗ duy nhất quyết "đã chạy
lần này chưa". Ghi run TRƯỚC khi tạo task: hai tiến trình (beat + API, hay
webhook gửi lại) cùng kích hoạt thì một bên trúng IntegrityError và dừng, nên
không bao giờ có task trùng.

Luồng một lần chạy (mode ``create_task``)::

    tick/webhook/manual → fire() → routine_runs(queued) → task mới
        → giao seat: wakeup "routine" (dedupe routine:rr<id>) → drain → task_run
        → giao phòng: routing.route_to_department (D3.1) → trưởng phòng chọn người
    reconcile() đọc kết cục thật từ wakeup/task_run → succeeded | failed

Mode ``run_only``: không tạo task mới; đánh thức seat trên *một* task thường
trực của routine (mở lại nếu đã xong) — cho việc "kiểm tra rồi báo".

Chạy bù (``catch_up``) khi hệ thống tắt qua giờ hẹn:
``skip_missed`` ghi mỗi giờ lỡ là run ``skipped`` (nhìn thấy được, không chạy);
``run_once`` chạy bù đúng một lần cho cả loạt giờ lỡ.

Đồng thời: lần trước còn ``queued/running`` → lần này ``skipped`` (concurrent).
Seat bận/ngoài giờ không phải lỗi: wakeup được xếp lại (D2.1), run tiếp tục chờ.

Lỗi liên tiếp ≥ ``max_consecutive_failures`` → routine tự dừng
(``enabled=False``), audit ``routine.paused``, báo Hộp việc (``routine_paused``).
"""
from __future__ import annotations

import hmac
import json
import secrets
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Company, Department, Member, Project, Task, TaskRun, Wakeup
from app.models.routines import CATCH_UP, ROUTINE_MODES, Routine, RoutineRun, RoutineTrigger
from app.services.company_event_bus import emit_event
from app.services.recurring_ops import compute_next

SOURCE = "routines"
GRACE = timedelta(minutes=5)          # trễ tối đa vẫn tính là "đúng giờ"
MAX_MISSED_RECORDED = 20              # số giờ lỡ ghi thành run skipped mỗi lần tick
RUN_TIMEOUT = timedelta(hours=12)     # run treo quá lâu → failed (để luật tự dừng còn tác dụng)
DEFERRABLE = ("seat_busy", "outside_active_hours")
OPEN = ("queued", "running")
STANDING_PROJECT = "Việc định kỳ"


class RoutineError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


# ------------------------------------------------------------------ mẫu

TEMPLATES: dict[str, dict] = {
    "nina_morning_report": {
        "name": "Báo cáo sáng của Nina",
        "cron": "30 8 * * *", "timezone": "Asia/Ho_Chi_Minh", "mode": "create_task", "snapshot": True,
        "runbook": ("Viết báo cáo sáng cho ban điều hành từ bảng số liệu bên dưới (số thật lúc tạo việc):\n"
                    "1. Ba điều quan trọng nhất hôm nay.\n2. Việc trễ hạn / bị chặn và ai cần gỡ.\n"
                    "3. Phê duyệt đang chờ và rủi ro nếu chậm.\n4. Chi phí 24h qua so với ngân sách.\n"
                    "Gửi báo cáo bằng một bình luận trên việc này rồi chuyển việc sang review."),
    },
    "sla_review": {
        "name": "Rà soát SLA",
        "cron": "0 10 * * 1-5", "timezone": "Asia/Ho_Chi_Minh", "mode": "create_task", "snapshot": True,
        "runbook": ("Rà các sự cố SLA đang mở và việc quá hạn trong bảng số liệu. Với mỗi mục: nguyên nhân, "
                    "người chịu trách nhiệm, đề xuất (giao lại / nới hạn / leo thang). Không tự đóng sự cố."),
    },
    "weekly_cost_review": {
        "name": "Tổng kết chi phí tuần",
        "cron": "0 9 * * 1", "timezone": "Asia/Ho_Chi_Minh", "mode": "create_task", "snapshot": True,
        "runbook": ("Tổng kết chi phí 7 ngày qua theo seat và theo ngân sách: ai tiêu nhiều nhất, lượt chạy "
                    "lỗi tốn tiền, ngân sách sắp chạm ngưỡng. Đề xuất điều chỉnh hạn mức nếu cần."),
    },
}


def templates() -> list[dict]:
    return [{"key": k, **{f: v[f] for f in ("name", "cron", "timezone", "mode", "runbook")}}
            for k, v in TEMPLATES.items()]


# ------------------------------------------------------------------ số liệu

def snapshot(db: Session, organization_id: int, company_id: int | None, now: datetime | None = None) -> dict:
    """Số liệu thật lúc tạo việc — thay cho phần "chỉ đếm" của decision_loop."""
    from app.models import Approval, SLAIncident
    from app.models.extended import InboxItem
    now = now or datetime.utcnow()
    projects = db.query(Project.id).filter(Project.company_id == company_id) if company_id else None
    tq = db.query(Task)
    if projects is not None:
        tq = tq.filter(Task.project_id.in_(projects))
    by_status = dict(tq.with_entities(Task.status, func.count(Task.id)).group_by(Task.status).all())
    overdue = tq.filter(Task.due_at.isnot(None), Task.due_at < now,
                        Task.status.notin_(("done", "cancelled", "archived"))).count()
    day = now - timedelta(hours=24)
    rq = db.query(TaskRun).filter(TaskRun.organization_id == organization_id, TaskRun.ended_at.isnot(None),
                                  TaskRun.ended_at >= day)
    runs = dict(rq.with_entities(TaskRun.status, func.count(TaskRun.id)).group_by(TaskRun.status).all())
    cost = float(rq.with_entities(func.coalesce(func.sum(TaskRun.cost_usd), 0.0)).scalar() or 0.0)
    week = float(db.query(func.coalesce(func.sum(TaskRun.cost_usd), 0.0)).filter(
        TaskRun.organization_id == organization_id, TaskRun.ended_at.isnot(None),
        TaskRun.ended_at >= now - timedelta(days=7)).scalar() or 0.0)
    return {
        "at": now.isoformat(timespec="minutes") + "Z",
        "tasks_by_status": {k or "backlog": v for k, v in sorted(by_status.items(), key=lambda x: x[0] or "")},
        "tasks_overdue": overdue,
        "tasks_blocked": by_status.get("blocked", 0),
        "approvals_pending": db.query(Approval).filter(Approval.organization_id == organization_id,
                                                       Approval.status == "pending").count(),
        "sla_open": db.query(SLAIncident).filter(SLAIncident.organization_id == organization_id,
                                                 SLAIncident.status.in_(["open", "escalated"])).count(),
        "inbox_unread": db.query(InboxItem).filter(InboxItem.organization_id == organization_id,
                                                   InboxItem.status == "unread").count(),
        "runs_24h": runs, "cost_24h_usd": round(cost, 4), "cost_7d_usd": round(week, 4),
    }


def snapshot_text(s: dict) -> str:
    st = ", ".join(f"{k} {v}" for k, v in s["tasks_by_status"].items()) or "chưa có"
    runs = ", ".join(f"{k} {v}" for k, v in s["runs_24h"].items()) or "không có"
    return ("\n\n## Số liệu lúc " + s["at"] + "\n"
            f"- Việc theo trạng thái: {st}\n- Quá hạn: {s['tasks_overdue']} · Bị chặn: {s['tasks_blocked']}\n"
            f"- Phê duyệt chờ: {s['approvals_pending']} · Sự cố SLA mở: {s['sla_open']} · "
            f"Hộp việc chưa đọc: {s['inbox_unread']}\n"
            f"- Lượt chạy 24h: {runs}\n- Chi phí 24h: ${s['cost_24h_usd']:.4f} · 7 ngày: ${s['cost_7d_usd']:.4f}")


# ------------------------------------------------------------------ tạo / sửa

def _aware(now: datetime) -> datetime:
    return now.replace(tzinfo=timezone.utc) if now.tzinfo is None else now


def next_slot(cron: str, tz: str, after: datetime) -> datetime:
    """Giờ hẹn kế tiếp (UTC naive) *sau* ``after`` (UTC naive)."""
    return compute_next(cron, tz, base=_aware(after))


def _check_cron(cron: str, tz: str) -> None:
    try:
        ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError):
        raise RoutineError("invalid_argument", f"Múi giờ không hợp lệ: {tz}")
    try:
        next_slot(cron, tz, datetime.utcnow())
    except Exception as exc:  # noqa: BLE001
        raise RoutineError("invalid_argument", f"Cron không hợp lệ ({cron}): {exc}")


def _company_of(db: Session, organization_id: int, member: Member | None, dept: Department | None) -> int | None:
    if dept is not None:
        return dept.company_id
    return member.company_id if member is not None else None


def _standing_project(db: Session, company_id: int) -> Project:
    p = db.query(Project).filter(Project.company_id == company_id, Project.name == STANDING_PROJECT).first()
    if p is None:
        p = Project(company_id=company_id, name=STANDING_PROJECT, status="active",
                    description="Việc do routine tạo (D3.4)")
        db.add(p); db.commit(); db.refresh(p)
    return p


def create_routine(db: Session, organization_id: int, *, name: str, runbook: str = "",
                   assignee_member_id: int | None = None, department_id: int | None = None,
                   project_id: int | None = None, mode: str = "create_task", timezone_name: str = "Asia/Ho_Chi_Minh",
                   catch_up: str = "skip_missed", cron: str = "", webhook: bool = False,
                   max_consecutive_failures: int = 3, owner_member_id: int | None = None,
                   template_key: str = "", now: datetime | None = None) -> Routine:
    name = (name or "").strip()
    if not name:
        raise RoutineError("invalid_argument", "Tên routine là bắt buộc")
    if mode not in ROUTINE_MODES:
        raise RoutineError("invalid_argument", f"mode phải là {' | '.join(ROUTINE_MODES)}")
    if catch_up not in CATCH_UP:
        raise RoutineError("invalid_argument", f"catch_up phải là {' | '.join(CATCH_UP)}")
    if bool(assignee_member_id) == bool(department_id):
        raise RoutineError("invalid_argument", "Giao cho đúng một bên: assignee_member_id hoặc department_id")
    if mode == "run_only" and not assignee_member_id:
        raise RoutineError("invalid_argument", "run_only cần một seat cụ thể")
    if not cron and not webhook:
        raise RoutineError("invalid_argument", "Cần ít nhất một trigger: cron hoặc webhook")
    if max_consecutive_failures < 1:
        raise RoutineError("invalid_argument", "max_consecutive_failures ≥ 1")
    member = dept = None
    if assignee_member_id:
        member = db.get(Member, assignee_member_id)
        if member is None or member.organization_id != organization_id:
            raise RoutineError("not_found", f"Không thấy thành viên #{assignee_member_id}")
    if department_id:
        dept = db.get(Department, department_id)
        co = db.get(Company, dept.company_id) if dept else None
        if dept is None or co is None or co.organization_id != organization_id:
            raise RoutineError("not_found", f"Không thấy phòng #{department_id}")
        if not dept.head_member_id:
            raise RoutineError("invalid_argument", "Phòng chưa có trưởng phòng để định tuyến")
    company_id = _company_of(db, organization_id, member, dept)
    if project_id:
        p = db.get(Project, project_id)
        if p is None or p.company_id != company_id:
            raise RoutineError("not_found", f"Không thấy dự án #{project_id} trong công ty của người nhận")
    if cron:
        _check_cron(cron, timezone_name)
    r = Routine(organization_id=organization_id, company_id=company_id, project_id=project_id, name=name[:200],
                template_key=template_key, runbook=runbook or "", assignee_member_id=assignee_member_id,
                department_id=department_id, owner_member_id=owner_member_id, mode=mode, timezone=timezone_name,
                catch_up=catch_up, enabled=True, max_consecutive_failures=max_consecutive_failures)
    db.add(r); db.commit(); db.refresh(r)
    now = now or datetime.utcnow()
    if cron:
        db.add(RoutineTrigger(routine_id=r.id, kind="cron", cron=cron, next_run_at=next_slot(cron, timezone_name, now)))
    if webhook:
        db.add(RoutineTrigger(routine_id=r.id, kind="webhook", secret=secrets.token_urlsafe(24)))
    db.commit()
    emit_event(db, organization_id=organization_id, company_id=company_id, event_type="routine.created",
               source=SOURCE, aggregate_type="routine", aggregate_id=str(r.id), actor_member_id=owner_member_id,
               payload={"routine_id": r.id, "name": r.name, "cron": cron, "webhook": webhook, "mode": mode,
                        "template": template_key})
    return r


def from_template(db: Session, organization_id: int, key: str, *, assignee_member_id: int | None = None,
                  department_id: int | None = None, owner_member_id: int | None = None,
                  cron: str | None = None, now: datetime | None = None) -> Routine:
    t = TEMPLATES.get(key)
    if t is None:
        raise RoutineError("not_found", f"Không có mẫu '{key}'")
    if not assignee_member_id and not department_id:
        nina = (db.query(Member).filter(Member.organization_id == organization_id, Member.member_type == "agent",
                                        Member.name.ilike("nina%")).order_by(Member.id).first())
        if nina is None:
            raise RoutineError("invalid_argument", "Chọn người nhận (không thấy seat Nina)")
        assignee_member_id = nina.id
    return create_routine(db, organization_id, name=t["name"], runbook=t["runbook"],
                          assignee_member_id=assignee_member_id, department_id=department_id,
                          mode=t["mode"], timezone_name=t["timezone"], cron=cron or t["cron"],
                          owner_member_id=owner_member_id, template_key=key, now=now)


def set_enabled(db: Session, r: Routine, enabled: bool, *, now: datetime | None = None,
                actor_member_id: int | None = None) -> Routine:
    now = now or datetime.utcnow()
    r.enabled = enabled
    if enabled:
        # Bật lại: xoá chuỗi lỗi và tính lại giờ hẹn từ bây giờ (không chạy bù thời gian bị dừng).
        r.consecutive_failures, r.paused_reason = 0, ""
        for t in db.query(RoutineTrigger).filter(RoutineTrigger.routine_id == r.id, RoutineTrigger.kind == "cron"):
            t.next_run_at = next_slot(t.cron, r.timezone, now)
    db.commit(); db.refresh(r)
    emit_event(db, organization_id=r.organization_id, company_id=r.company_id,
               event_type="routine.enabled" if enabled else "routine.disabled", source=SOURCE,
               aggregate_type="routine", aggregate_id=str(r.id), actor_member_id=actor_member_id,
               payload={"routine_id": r.id})
    return r


# ------------------------------------------------------------------ kích hoạt

def _local(dt: datetime, tz: str) -> str:
    return _aware(dt).astimezone(ZoneInfo(tz)).strftime("%d/%m/%Y %H:%M")


def fire(db: Session, r: Routine, *, kind: str, key: str, trigger: RoutineTrigger | None = None,
         scheduled_for: datetime | None = None, payload: dict | None = None,
         now: datetime | None = None) -> tuple[RoutineRun, bool]:
    """Một lần kích hoạt. Trả ``(run, created)``; ``created=False`` = trùng key."""
    now = now or datetime.utcnow()
    run = RoutineRun(routine_id=r.id, trigger_id=trigger.id if trigger else None, trigger_kind=kind,
                     idempotency_key=key[:200], scheduled_for=scheduled_for, status="queued",
                     payload_json=json.dumps(payload or {}, ensure_ascii=False, default=str)[:20000])
    db.add(run)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return db.query(RoutineRun).filter(RoutineRun.idempotency_key == key[:200]).one(), False
    db.refresh(run)
    if trigger is not None:
        trigger.last_fired_at = now
    r.last_run_at = now
    busy = (db.query(RoutineRun).filter(RoutineRun.routine_id == r.id, RoutineRun.id != run.id,
                                        RoutineRun.status.in_(OPEN)).order_by(RoutineRun.id).first())
    if busy is not None:
        _finish(db, r, run, "skipped", f"concurrent: lần #{busy.id} chưa xong", now=now)
        return run, True
    try:
        _start(db, r, run, payload or {}, now)
    except Exception as exc:  # noqa: BLE001 — lỗi tạo việc là một lần chạy lỗi, không làm hỏng tick
        db.rollback()
        run = db.get(RoutineRun, run.id)
        _finish(db, r, run, "failed", f"start_error: {exc}", now=now)
    return run, True


def _start(db: Session, r: Routine, run: RoutineRun, payload: dict, now: datetime) -> None:
    from app.services import routing, wakeup
    from app.services import workspace_ops as ops
    text = r.runbook or ""
    if TEMPLATES.get(r.template_key, {}).get("snapshot"):
        text += snapshot_text(snapshot(db, r.organization_id, r.company_id, now))
    if payload:
        text += "\n\n## Dữ liệu webhook\n```json\n" + json.dumps(payload, ensure_ascii=False, indent=1)[:4000] + "\n```"
    stamp = _local(run.scheduled_for or now, r.timezone)
    if r.mode == "run_only":
        task = _standing_task(db, r)
        task.description = f"{r.runbook}\n\n(lần chạy {stamp})" + text[len(r.runbook or ""):]
        db.commit()
    else:
        project = db.get(Project, r.project_id) if r.project_id else _standing_project(db, r.company_id)
        task = ops.create_task(db, project, r.organization_id, title=f"{r.name} — {stamp}"[:220],
                               description=text, assignee_member_id=r.assignee_member_id,
                               actor_member_id=r.owner_member_id)
    baseline = db.query(func.max(TaskRun.id)).filter(TaskRun.task_id == task.id).scalar() or 0
    run.task_id = task.id
    run.payload_json = json.dumps({**json.loads(run.payload_json or "{}"), "_after_task_run_id": baseline},
                                  ensure_ascii=False)
    db.commit()
    if r.department_id:
        res = routing.route_to_department(db, task, r.department_id, organization_id=r.organization_id,
                                          actor_member_id=r.owner_member_id, reason=f"routine #{r.id}: {r.name}")
        wk = (res.get("wake") or {}) if isinstance(res, dict) else {}
        run.wakeup_id = wk.get("wakeup_id") if isinstance(wk, dict) else None
    else:
        wk = wakeup.enqueue_for_task(db, task, "routine", dedupe_key=f"routine:rr{run.id}",
                                     payload={"routine_id": r.id, "routine_run_id": run.id})
        run.wakeup_id = wk.id if wk is not None else None
        if wk is None:
            # Người (không phải seat agent) nhận: việc đã nằm trong danh sách của họ — thế là xong.
            db.commit()
            _finish(db, r, run, "succeeded", "", now=now)
            return
    db.commit()
    emit_event(db, organization_id=r.organization_id, company_id=r.company_id, event_type="routine.fired",
               source=SOURCE, aggregate_type="routine", aggregate_id=str(r.id),
               payload={"routine_id": r.id, "run_id": run.id, "kind": run.trigger_kind, "task_id": task.id,
                        "wakeup_id": run.wakeup_id, "key": run.idempotency_key})


def _standing_task(db: Session, r: Routine) -> Task:
    from app.services import task_lifecycle as lifecycle
    task = db.get(Task, r.standing_task_id) if r.standing_task_id else None
    if task is None or task.status in ("cancelled", "archived"):
        project = db.get(Project, r.project_id) if r.project_id else _standing_project(db, r.company_id)
        task = Task(project_id=project.id, title=f"{r.name} (thường trực)"[:220], description=r.runbook or "",
                    assignee_member_id=r.assignee_member_id, status="todo")
        db.add(task); db.commit(); db.refresh(task)
        r.standing_task_id = task.id
        db.commit()
    if task.status not in ("backlog", "todo", "in_progress"):
        lifecycle.transition(db, task, "todo", reason=f"routine #{r.id}: mở lại việc thường trực", via="routine",
                             system=True, organization_id=r.organization_id, company_id=r.company_id)
    if task.assignee_member_id != r.assignee_member_id:
        task.assignee_member_id = r.assignee_member_id
        db.commit()
    return task


# ------------------------------------------------------------------ kết cục

def _finish(db: Session, r: Routine, run: RoutineRun, status: str, error: str, *, now: datetime) -> None:
    run.status, run.error, run.finished_at = status, (error or "")[:4000], now
    if status == "succeeded":
        r.consecutive_failures = 0
    db.commit()
    if status == "failed":
        _failed(db, r, run, now)


def _failed(db: Session, r: Routine, run: RoutineRun, now: datetime) -> None:
    from app.services import inbox
    from app.services.audit import log_event
    r.consecutive_failures = (r.consecutive_failures or 0) + 1
    db.commit()
    emit_event(db, organization_id=r.organization_id, company_id=r.company_id, event_type="routine.run_failed",
               source=SOURCE, aggregate_type="routine", aggregate_id=str(r.id),
               payload={"routine_id": r.id, "run_id": run.id, "error": run.error[:500],
                        "consecutive_failures": r.consecutive_failures})
    if not r.enabled or r.consecutive_failures < r.max_consecutive_failures:
        return
    r.enabled = False
    r.paused_reason = f"Tự dừng sau {r.consecutive_failures} lần lỗi liên tiếp; lần cuối: {run.error}"[:300]
    db.commit()
    payload = {"routine_id": r.id, "consecutive_failures": r.consecutive_failures, "last_error": run.error[:500],
               "last_run_id": run.id}
    log_event(db, r.organization_id, "routine.paused", "routines", str(r.id), actor_name="system:routines",
              result="paused", risk="medium", payload=payload)
    emit_event(db, organization_id=r.organization_id, company_id=r.company_id, event_type="routine.paused",
               source=SOURCE, aggregate_type="routine", aggregate_id=str(r.id), payload=payload)
    inbox.notify(db, organization_id=r.organization_id, recipients=[r.owner_member_id or r.assignee_member_id],
                 kind="routine_paused", title=f"Routine “{r.name}” đã tự dừng", related_type="routine",
                 related_id=str(r.id), priority="high", source="routines",
                 line=f"{r.consecutive_failures} lần lỗi liên tiếp — {run.error[:160]}")


def _latest_wakeup(db: Session, wakeup_id: int | None) -> Wakeup | None:
    wk = db.get(Wakeup, wakeup_id) if wakeup_id else None
    for _ in range(10):  # theo chuỗi xếp lại (seat bận / ngoài giờ → wakeup mới)
        if wk is None:
            return None
        nxt = json.loads(wk.payload or "{}").get("requeued_as")
        if not nxt:
            return wk
        wk = db.get(Wakeup, nxt)
    return wk


def reconcile(db: Session, run: RoutineRun, *, now: datetime | None = None) -> RoutineRun:
    """Đọc kết cục thật của một lần chạy từ task_run/wakeup."""
    now = now or datetime.utcnow()
    if run.status not in OPEN or not run.task_id:
        return run
    r = db.get(Routine, run.routine_id)
    after = int(json.loads(run.payload_json or "{}").get("_after_task_run_id") or 0)
    tr = (db.query(TaskRun).filter(TaskRun.task_id == run.task_id, TaskRun.id > after,
                                   TaskRun.trigger_kind != "routed").order_by(TaskRun.id.desc()).first())
    if tr is not None:
        run.task_run_id = tr.id
        if tr.status == "completed":
            _finish(db, r, run, "succeeded", "", now=now)
        elif tr.status in ("failed", "cancelled", "skipped"):
            _finish(db, r, run, "failed", f"task_run #{tr.id} {tr.status}: {tr.error_reason or ''}".strip(), now=now)
        elif run.status != "running":
            run.status = "running"; db.commit()
        return run
    wk = _latest_wakeup(db, run.wakeup_id)
    if wk is not None and wk.status in ("skipped", "failed") and not wk.skip_reason.startswith(DEFERRABLE):
        _finish(db, r, run, "failed", f"wakeup #{wk.id} {wk.status}: {wk.skip_reason}", now=now)
        return run
    if now - (run.created_at or now) > RUN_TIMEOUT:
        _finish(db, r, run, "failed", f"timeout: quá {RUN_TIMEOUT} chưa có kết quả", now=now)
    return run


def reconcile_open(db: Session, *, now: datetime | None = None, routine_id: int | None = None,
                   organization_id: int | None = None) -> int:
    q = db.query(RoutineRun).filter(RoutineRun.status.in_(OPEN))
    if routine_id is not None:
        q = q.filter(RoutineRun.routine_id == routine_id)
    if organization_id is not None:
        q = q.join(Routine, Routine.id == RoutineRun.routine_id).filter(Routine.organization_id == organization_id)
    rows = q.order_by(RoutineRun.id).limit(500).all()
    for run in rows:
        reconcile(db, run, now=now)
    return len(rows)


# ------------------------------------------------------------------ tick (cron)

def _slots(t: RoutineTrigger, tz: str, now: datetime) -> list[datetime]:
    out, slot = [], t.next_run_at
    while slot is not None and slot <= now and len(out) < 10_000:
        out.append(slot)
        slot = next_slot(t.cron, tz, slot)
    return out


def tick(db: Session, *, now: datetime | None = None, organization_id: int | None = None) -> list[dict]:
    """Beat ``routines.tick``: đọc kết cục, rồi kích hoạt các giờ hẹn đã tới."""
    now = now or datetime.utcnow()
    reconcile_open(db, now=now, organization_id=organization_id)
    out = []
    q = (db.query(RoutineTrigger, Routine).join(Routine, Routine.id == RoutineTrigger.routine_id)
         .filter(RoutineTrigger.kind == "cron", RoutineTrigger.enabled.is_(True), Routine.enabled.is_(True),
                 RoutineTrigger.next_run_at.isnot(None), RoutineTrigger.next_run_at <= now))
    if organization_id is not None:
        q = q.filter(Routine.organization_id == organization_id)
    due = q.order_by(RoutineTrigger.next_run_at, RoutineTrigger.id).limit(200).all()
    for t, r in due:
        slots = _slots(t, r.timezone, now)
        on_time = [s for s in slots if now - s <= GRACE]
        missed = [s for s in slots if now - s > GRACE]
        # Dời giờ hẹn TRƯỚC khi kích hoạt: tick chồng nhau không thấy lại cùng giờ (UNIQUE vẫn là chốt cuối).
        t.next_run_at = next_slot(t.cron, r.timezone, now)
        db.commit()
        if missed and r.catch_up == "run_once" and not on_time:
            run, created = fire(db, r, kind="catch_up", trigger=t, scheduled_for=missed[-1], now=now,
                                key=f"cron:t{t.id}:{missed[-1]:%Y%m%dT%H%M}",
                                payload={"missed_slots": len(missed), "first_missed": missed[0].isoformat()})
            out.append({"routine_id": r.id, "run_id": run.id, "kind": "catch_up", "created": created,
                        "missed": len(missed)})
            missed = missed[:-1]
        for s in missed[-MAX_MISSED_RECORDED:]:
            run = RoutineRun(routine_id=r.id, trigger_id=t.id, trigger_kind="cron", status="skipped",
                             idempotency_key=f"cron:t{t.id}:{s:%Y%m%dT%H%M}", scheduled_for=s, finished_at=now,
                             error=f"missed: hệ thống không chạy lúc {_local(s, r.timezone)} (catch_up={r.catch_up})")
            db.add(run)
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
        if missed:
            out.append({"routine_id": r.id, "kind": "missed", "skipped": len(missed)})
        if on_time:
            s = on_time[-1]
            run, created = fire(db, r, kind="cron", trigger=t, scheduled_for=s, now=now,
                                key=f"cron:t{t.id}:{s:%Y%m%dT%H%M}")
            out.append({"routine_id": r.id, "run_id": run.id, "kind": "cron", "created": created,
                        "status": run.status})
    return out


async def tick_forever(interval_seconds: float) -> None:
    import asyncio
    from app.db.session import SessionLocal
    while True:
        db = SessionLocal()
        try:
            tick(db)
        except Exception as exc:  # noqa: BLE001
            print(f"[D3.4] routines tick: {exc}")
        finally:
            db.close()
        await asyncio.sleep(interval_seconds)


# ------------------------------------------------------------------ webhook / chạy tay

def webhook(db: Session, trigger_id: int, *, secret: str, idempotency_key: str, payload: dict | None,
            now: datetime | None = None) -> dict:
    t = db.get(RoutineTrigger, trigger_id)
    if t is None or t.kind != "webhook":
        raise RoutineError("not_found", "Không thấy webhook")
    if not secret or not hmac.compare_digest(secret, t.secret or ""):
        raise RoutineError("forbidden", "Sai secret")
    idem = (idempotency_key or "").strip()
    if not idem:
        raise RoutineError("invalid_argument", "Thiếu header Idempotency-Key")
    r = db.get(Routine, t.routine_id)
    if not r.enabled or not t.enabled:
        raise RoutineError("conflict", f"Routine đang dừng: {r.paused_reason or 'tắt tay'}")
    reconcile_open(db, now=now, routine_id=r.id)
    run, created = fire(db, r, kind="webhook", trigger=t, key=f"webhook:t{t.id}:{idem[:150]}",
                        payload=payload or {}, now=now)
    return {"duplicate": not created, **public_run(run)}


def run_now(db: Session, r: Routine, *, now: datetime | None = None) -> RoutineRun:
    reconcile_open(db, now=now, routine_id=r.id)
    run, _ = fire(db, r, kind="manual", key=f"manual:r{r.id}:{secrets.token_hex(8)}", now=now)
    return run


# ------------------------------------------------------------------ hiển thị

def public_run(run: RoutineRun) -> dict:
    return {"run_id": run.id, "routine_id": run.routine_id, "kind": run.trigger_kind, "status": run.status,
            "task_id": run.task_id, "wakeup_id": run.wakeup_id, "task_run_id": run.task_run_id,
            "scheduled_for": run.scheduled_for.isoformat() + "Z" if run.scheduled_for else None,
            "created_at": run.created_at.isoformat() + "Z" if run.created_at else None,
            "finished_at": run.finished_at.isoformat() + "Z" if run.finished_at else None,
            "error": run.error, "key": run.idempotency_key}


def public(db: Session, r: Routine, *, with_secret: bool = False) -> dict:
    trig = db.query(RoutineTrigger).filter(RoutineTrigger.routine_id == r.id).order_by(RoutineTrigger.id).all()
    last = (db.query(RoutineRun).filter(RoutineRun.routine_id == r.id).order_by(RoutineRun.id.desc()).first())
    return {
        "id": r.id, "name": r.name, "template_key": r.template_key, "runbook": r.runbook, "mode": r.mode,
        "assignee_member_id": r.assignee_member_id, "department_id": r.department_id, "project_id": r.project_id,
        "timezone": r.timezone, "catch_up": r.catch_up, "enabled": r.enabled,
        "consecutive_failures": r.consecutive_failures, "max_consecutive_failures": r.max_consecutive_failures,
        "paused_reason": r.paused_reason, "standing_task_id": r.standing_task_id,
        "last_run_at": r.last_run_at.isoformat() + "Z" if r.last_run_at else None,
        "last_run": public_run(last) if last else None,
        "triggers": [{"id": t.id, "kind": t.kind, "cron": t.cron, "enabled": t.enabled,
                      "next_run_at": t.next_run_at.isoformat() + "Z" if t.next_run_at else None,
                      "next_run_local": _local(t.next_run_at, r.timezone) if t.next_run_at else None,
                      "hook_path": f"/api/routines/hooks/{t.id}" if t.kind == "webhook" else None,
                      **({"secret": t.secret} if with_secret and t.kind == "webhook" else {})} for t in trig],
    }
