"""W1 — mỗi ghế chạy được mấy lượt cùng lúc, và giành chỗ chạy sao cho hai worker không cùng lấy một chỗ.

Trước W1: ``wakeup.skip_reason`` thấy ghế có *bất kỳ* lượt mở nào là ``seat_busy`` — một lượt đang chờ người
duyệt lệnh exec cũng giữ ghế, nên một phê duyệt chậm làm đứng cả hàng việc của agent. Kiểm tra lại không nguyên
tử: hai drain chạy song song (Celery 4 tiến trình) cùng thấy "ghế rảnh" rồi cùng gửi.

Ở đây:

* **giới hạn** = ``agents.max_parallel_runs`` (mặc định ``DEFAULT_LIMIT`` = 1, tối đa ``MAX_LIMIT`` = 3 — *default,
  chưa chốt* §5.3 D2), ghế thuê còn bị chặn bởi sàn của hợp đồng (``seat_leases.max_parallel_runs``, NULL = 1);
* **đang chạy** = lượt mở (queued/dispatched/running) **không** chờ người (``waiting_since`` NULL) và chưa quá
  ``STALE_RUN_MINUTES`` (giữ đúng luật cũ "lượt im quá lâu = follower lỡ frame cuối");
* **giành chỗ nguyên tử** (``open_run``): khoá dòng ``agents`` của ghế bằng một UPDATE (Postgres: khoá dòng tới
  khi commit; SQLite: khoá ghi cả DB), đếm lượt đang chạy, còn chỗ thì tạo hàng ``task_runs`` NGAY trong cùng giao
  dịch rồi commit. Worker thứ hai chờ khoá, đếm lại thấy hàng vừa tạo → ``SeatBusy``. Không có cửa sổ "đã đếm
  nhưng chưa ghi".
* lượt chờ người được **tiếp tục** (``resume_run``) luôn được nhận lại dù ghế đang đầy — gateway chạy tiếp ngay
  khi có quyết định, ta không chặn được. Ghế khi đó tạm vượt giới hạn và không nhận lượt MỚI cho tới khi về dưới
  giới hạn (ghi rõ trong ``view``: ``over_limit``).
"""
from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import func, or_, update
from sqlalchemy.orm import Session

from app.models import Agent, Member, Task, TaskRun
from app.models.work_graph import OPEN_RUN_STATUSES

DEFAULT_LIMIT = 1
MAX_LIMIT = 3          # default, chưa chốt (docs/work-module-review.md §5.3 D2)
SETTLED = False        # anh chưa chốt D2 — UI ghi "mặc định, chưa chốt"
STALE_RUN_MINUTES = 30


class SeatBusy(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _agent_of(db: Session, member_id: int) -> Agent | None:
    return db.query(Agent).filter(Agent.member_id == member_id).first()


def lease_floor(db: Session, agent: Agent | None) -> int | None:
    """Sàn của bên cho thuê cho ghế thuê (None = không phải ghế thuê)."""
    if agent is None:
        return None
    from app.services import seat_leases
    ls = seat_leases.lease_of_agent(db, agent.id)
    if ls is None:
        return None
    return int(ls.max_parallel_runs or DEFAULT_LIMIT)


def configured(agent: Agent | None) -> int:
    v = int(getattr(agent, "max_parallel_runs", None) or DEFAULT_LIMIT) if agent is not None else DEFAULT_LIMIT
    return max(1, min(MAX_LIMIT, v))


def limit_of(db: Session, member_id: int, agent: Agent | None = None) -> int:
    agent = agent if agent is not None else _agent_of(db, member_id)
    lim = configured(agent)
    floor = lease_floor(db, agent)
    return min(lim, floor) if floor is not None else lim


def _active_q(db: Session, member_id: int, now: datetime):
    stale = now - timedelta(minutes=STALE_RUN_MINUTES)
    return db.query(TaskRun).filter(
        TaskRun.member_id == member_id, TaskRun.status.in_(OPEN_RUN_STATUSES), TaskRun.waiting_since.is_(None),
        or_(TaskRun.started_at >= stale, (TaskRun.started_at.is_(None)) & (TaskRun.created_at >= stale)))


def active_runs(db: Session, member_id: int, now: datetime | None = None) -> list[TaskRun]:
    return _active_q(db, member_id, now or datetime.utcnow()).order_by(TaskRun.id).all()


def waiting_runs(db: Session, member_id: int) -> list[TaskRun]:
    return (db.query(TaskRun).filter(TaskRun.member_id == member_id, TaskRun.status.in_(OPEN_RUN_STATUSES),
                                     TaskRun.waiting_since.isnot(None)).order_by(TaskRun.id).all())


def busy_reason(db: Session, member_id: int, now: datetime | None = None, agent: Agent | None = None) -> str:
    """'' khi còn chỗ; không thì ``seat_busy: …`` (tiền tố giữ nguyên để ``requeue_deferred`` xếp lại)."""
    runs = active_runs(db, member_id, now)
    lim = limit_of(db, member_id, agent)
    if len(runs) < lim:
        return ""
    last = runs[-1]
    if lim == 1:
        return f"seat_busy: run #{last.id} (task #{last.task_id})"
    return f"seat_busy: {len(runs)}/{lim} lượt — run #{last.id} (task #{last.task_id})"


def _lock_seat(db: Session, member_id: int) -> None:
    """Khoá dòng ``agents`` của ghế tới hết giao dịch (UPDATE không đổi giá trị vẫn khoá dòng trên Postgres và
    giành khoá ghi trên SQLite)."""
    db.execute(update(Agent).where(Agent.member_id == member_id)
               .values(max_parallel_runs=Agent.max_parallel_runs)
               .execution_options(synchronize_session=False))


def open_run(db: Session, task: Task, *, organization_id: int, member_id: int, trigger_kind: str = "manual",
             wakeup_id: int | None = None, now: datetime | None = None) -> TaskRun:
    """Giành một chỗ chạy của ghế VÀ tạo hàng ``task_runs`` trong cùng một giao dịch. Hết chỗ → ``SeatBusy``."""
    now = now or datetime.utcnow()
    db.commit()   # bắt đầu giao dịch sạch: khoá dưới đây phải là câu ghi đầu tiên
    try:
        _lock_seat(db, member_id)
        why = busy_reason(db, member_id, now)
        if why:
            db.rollback()
            raise SeatBusy(why)
        run = TaskRun(organization_id=organization_id, task_id=task.id, member_id=member_id,
                      trigger_kind=trigger_kind, wakeup_id=wakeup_id, status="queued")
        db.add(run)
        db.commit()
    except SeatBusy:
        raise
    except Exception:
        db.rollback()
        raise
    db.refresh(run)
    return run


def mark_waiting(db: Session, run: TaskRun, *, now: datetime | None = None, commit: bool = True) -> bool:
    """Lượt còn mở trên gateway nhưng đang chờ người → trả chỗ chạy của ghế."""
    if run.status not in OPEN_RUN_STATUSES or run.waiting_since is not None:
        return False
    run.waiting_since = now or datetime.utcnow()
    db.add(run)
    if commit:
        db.commit()
    return True


def resume_run(db: Session, run: TaskRun, *, now: datetime | None = None, commit: bool = True) -> bool:
    """Lượt chờ người được tiếp tục: nhận lại chỗ (kể cả khi ghế đang đầy — xem docstring module)."""
    if run.waiting_since is None:
        return False
    run.waiting_since = None
    run.started_at = now or datetime.utcnow()   # đồng hồ "im quá lâu" tính lại từ lúc chạy tiếp
    db.add(run)
    if commit:
        db.commit()
    return True


# ------------------------------------------------------------------ cài đặt / hiển thị


def view(db: Session, agent: Agent, member: Member, now: datetime | None = None) -> dict:
    runs = active_runs(db, member.id, now)
    waiting = waiting_runs(db, member.id)
    floor = lease_floor(db, agent)
    lim = limit_of(db, member.id, agent)
    waiting_tasks = db.query(Task).filter(Task.assignee_member_id == member.id, Task.wait_kind.isnot(None)).count()
    return {"agent_id": agent.id, "member_id": member.id,
            "max_parallel_runs": configured(agent), "effective_limit": lim,
            "default": DEFAULT_LIMIT, "max_allowed": MAX_LIMIT if floor is None else min(MAX_LIMIT, floor),
            "settled": SETTLED, "lease_floor": floor,
            "running": len(runs), "waiting_runs": len(waiting), "waiting_tasks": waiting_tasks,
            "over_limit": len(runs) > lim,
            "running_runs": [{"run_id": r.id, "task_id": r.task_id} for r in runs]}


def set_limit(db: Session, agent: Agent, member: Member, value, *, actor_member_id: int | None = None) -> dict:
    try:
        v = int(value)
    except (TypeError, ValueError):
        raise HTTPException(422, {"error": "invalid_parallel", "message": "Số lượt cùng lúc phải là số nguyên"})
    if v < 1 or v > MAX_LIMIT:
        raise HTTPException(422, {"error": "invalid_parallel", "min": 1, "max": MAX_LIMIT,
                                  "message": f"Số lượt cùng lúc phải từ 1 đến {MAX_LIMIT}"})
    floor = lease_floor(db, agent)
    if floor is not None and v > floor:
        raise HTTPException(422, {"error": "above_lease_floor", "floor": floor,
                                  "message": f"Agent thuê: bên cho thuê chỉ cho tối đa {floor} lượt cùng lúc"})
    before = configured(agent)
    agent.max_parallel_runs = v
    db.add(agent); db.commit(); db.refresh(agent)
    if before != v:
        from app.services.company_event_bus import emit_event
        emit_event(db, organization_id=member.organization_id, event_type="seat.parallel_changed",
                   source="seat_concurrency", company_id=member.company_id, aggregate_type="agent",
                   aggregate_id=str(agent.id), actor_member_id=actor_member_id,
                   payload={"from": before, "to": v, "member_id": member.id})
    return view(db, agent, member)


def free_slots(db: Session, member_id: int, now: datetime | None = None) -> int:
    return max(0, limit_of(db, member_id) - len(active_runs(db, member_id, now)))


def load_ratio(db: Session, member_id: int, now: datetime | None = None) -> float:
    """Tải so với giới hạn — để chọn ghế (ngoài giờ / định tuyến) ưu tiên ghế còn chỗ."""
    return len(active_runs(db, member_id, now)) / max(1, limit_of(db, member_id))


def counts_by_member(db: Session, member_ids: list[int], now: datetime | None = None) -> dict[int, int]:
    now = now or datetime.utcnow()
    stale = now - timedelta(minutes=STALE_RUN_MINUTES)
    rows = (db.query(TaskRun.member_id, func.count(TaskRun.id))
            .filter(TaskRun.member_id.in_(member_ids or [-1]), TaskRun.status.in_(OPEN_RUN_STATUSES),
                    TaskRun.waiting_since.is_(None),
                    or_(TaskRun.started_at >= stale, (TaskRun.started_at.is_(None)) & (TaskRun.created_at >= stale)))
            .group_by(TaskRun.member_id).all())
    return {int(m): int(n) for m, n in rows}


def routing_load(db: Session, member_id: int) -> float:
    """Tải để chọn ghế (định tuyến ngoài giờ / chọn người theo chức danh): việc đang mở KHÔNG tính việc đang chờ
    người, chia cho số lượt cùng lúc của ghế. Ghế 1 lượt, không có việc chờ → đúng bằng số việc mở như trước W1."""
    n = db.query(Task).filter(Task.assignee_member_id == member_id,
                              Task.status.in_(("backlog", "todo", "in_progress", "review", "blocked")),
                              Task.wait_kind.is_(None)).count()
    return n / max(1, limit_of(db, member_id))
