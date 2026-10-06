"""D1.4 — nơi DUY NHẤT được ghi ``tasks.status`` và ``tasks.checkout_run_id``.

Trước gói này có 12 chỗ tự gán ``task.status = ...`` (move của v18/v20/v27,
dispatch, abort, kết thúc run, lưu trữ/khôi phục dự án, đỗ việc khi kích hoạt
lại thành viên, orchestration, công cụ của agent). Mỗi chỗ một luật: chỗ thì
kiểm bảng chuyển, chỗ thì không; công cụ ``company/tasks/{id}/status`` còn nhận
bất kỳ chuỗi nào. ``tools/lint_task_status.py`` (chạy trong CI) đỏ nếu có chỗ
gán mới ngoài file này.

Hai loại chuyển:
- ``system=False`` (người/agent yêu cầu): kiểm bảng chuyển, đòi người nhận khi
  vào in_progress/review, và từ chối khi còn task chặn đang mở.
- ``system=True`` (hệ thống ghi lại sự thật đã xảy ra: run kết thúc, lưu trữ
  dây chuyền, khôi phục): chỉ kiểm từ vựng. Lý do đi kèm là bắt buộc.
"""
from __future__ import annotations

from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from app.models import Company, Project, Task, TaskRun
from app.models.work_graph import OPEN_RUN_STATUSES
from app.services import write_trail
from app.services.company_event_bus import emit_event

SOURCE = "task_lifecycle"

TASK_STATUSES = ("backlog", "todo", "in_progress", "review", "blocked", "done", "cancelled")
OPEN_TASK_STATUSES = ("backlog", "todo", "in_progress", "review", "blocked")
# A task may only move along these edges. This stops an agent from silently
# flipping work from backlog straight to done without review.
TASK_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "backlog": ("todo", "cancelled"),
    "todo": ("in_progress", "backlog", "cancelled"),
    "in_progress": ("review", "todo", "blocked", "cancelled"),
    "review": ("done", "in_progress", "cancelled"),
    "blocked": ("in_progress", "todo", "cancelled"),
    "done": ("review",),
    "cancelled": ("backlog",),
}
# Vào những trạng thái này nghĩa là "đang làm/đã xong" — không được khi việc
# mình chờ còn chưa xong.
GATED_BY_BLOCKERS = ("in_progress", "review", "done")
NEEDS_ASSIGNEE = ("in_progress", "review")


class CheckoutConflict(HTTPException):
    def __init__(self, task_id: int, holder: int | None):
        super().__init__(409, {"error": "task_checked_out", "task_id": task_id,
                               "held_by_run_id": holder,
                               "message": f"Task #{task_id} đang được lượt chạy #{holder} giữ"
                               if holder else f"Task #{task_id} không ở trạng thái nhận được"})
        self.holder = holder


def _tenant(db: Session, task: Task) -> tuple[int | None, int | None]:
    project = db.get(Project, task.project_id) if task.project_id else None
    company = db.get(Company, project.company_id) if project else None
    return (company.organization_id if company else None, company.id if company else None)


def check(db: Session, task: Task, to: str) -> None:
    """Luật cho một chuyển do người/agent yêu cầu. Ném HTTPException."""
    from app.services import task_graph  # tránh vòng import

    if to not in TASK_STATUSES:
        raise HTTPException(400, f"status must be one of: {', '.join(TASK_STATUSES)}")
    current = task.status or "backlog"
    allowed = TASK_TRANSITIONS.get(current, ())
    if to not in allowed:
        raise HTTPException(409, f"Cannot move a task from '{current}' to '{to}'. "
                                 f"Allowed: {', '.join(allowed) or 'none'}")
    if to in NEEDS_ASSIGNEE and task.assignee_member_id is None:
        raise HTTPException(400, "Assign the task before moving it into progress")
    if to in GATED_BY_BLOCKERS:
        open_ = task_graph.open_blockers(db, task.id)
        if open_:
            ids = ", ".join(f"#{t.id}" for t in open_)
            raise HTTPException(409, {"error": "blocked_by_open_tasks",
                                      "blocked_by": [t.id for t in open_],
                                      "message": f"Task còn bị chặn bởi {ids} chưa xong"})


def transition(db: Session, task: Task, to: str, *, reason: str = "", via: str = "api",
               actor_member_id: int | None = None, system: bool = False,
               commit: bool = True, emit: bool = True, source: str = SOURCE,
               organization_id: int | None = None, company_id: int | None = None) -> Task:
    """Đổi trạng thái task. Trả về task (đã refresh nếu commit)."""
    current = task.status or "backlog"
    if to == current:
        return task
    if system:
        if to not in TASK_STATUSES:
            raise HTTPException(400, f"status must be one of: {', '.join(TASK_STATUSES)}")
        if not reason:
            raise ValueError("system transitions must say why")
    else:
        check(db, task, to)
    trail = write_trail.start("task", task)
    task.status = to
    db.add(task)
    if not commit:
        return task
    db.commit(); db.refresh(task)
    if emit:
        org, company = _tenant(db, task)
        org = organization_id or org
        if org is not None:
            payload = {"task_id": task.id, "project_id": task.project_id,
                       "from": current, "to": to, "via": via}
            if reason:
                payload["reason"] = reason
            payload.update(trail.finish(task))
            emit_event(db, organization_id=org, event_type=f"task.{to}", payload=payload,
                       company_id=company_id or company, source=source,
                       aggregate_type="task", aggregate_id=str(task.id),
                       actor_member_id=actor_member_id)
    if to in ("done", "cancelled"):
        wake_unblocked(db, task)
    return task


def wake_unblocked(db: Session, task: Task) -> list[int]:
    """D2.1: việc này đóng → việc nào hết bị chặn thì đánh thức người nhận của nó."""
    from app.models import TaskDependency
    from app.services import task_graph, wakeup
    woken = []
    for dep in db.query(TaskDependency).filter(TaskDependency.blocked_by_task_id == task.id).all():
        waiting = db.get(Task, dep.task_id)
        if waiting is None or task_graph.open_blockers(db, waiting.id):
            continue
        wk = wakeup.enqueue_for_task(db, waiting, "blocker_cleared",
                                     dedupe_key=f"blocker_cleared:t{waiting.id}:by{task.id}",
                                     payload={"cleared_by_task_id": task.id})
        if wk is not None:
            woken.append(waiting.id)
    return woken


# ------------------------------------------------------------------ checkout

def checkout(db: Session, task: Task, run_id: int, *,
             expected_statuses: tuple[str, ...] = OPEN_TASK_STATUSES) -> Task:
    """Giao task cho lượt chạy ``run_id`` bằng một UPDATE có điều kiện.

    Chỉ thành công khi task đang ở ``expected_statuses`` và không ai giữ (hoặc
    người giữ là một lượt đã kết thúc). Thua thì 409 ngay — không thử lại, vì
    thử lại nghĩa là hai agent cùng làm một việc.
    """
    finished = select(TaskRun.id).where(TaskRun.status.not_in(OPEN_RUN_STATUSES))
    result = db.execute(
        update(Task)
        .where(Task.id == task.id, Task.status.in_(expected_statuses),
               or_(Task.checkout_run_id.is_(None), Task.checkout_run_id == run_id,
                   Task.checkout_run_id.in_(finished)))
        .values(checkout_run_id=run_id)
        .execution_options(synchronize_session=False)
    )
    db.commit()
    db.refresh(task)
    if result.rowcount != 1:
        raise CheckoutConflict(task.id, task.checkout_run_id)
    return task


def release(db: Session, task: Task, run_id: int | None = None, *, commit: bool = True) -> bool:
    """Thả task. Nếu đưa ``run_id`` thì chỉ thả khi đúng lượt đó đang giữ."""
    cond = [Task.id == task.id]
    if run_id is not None:
        cond.append(Task.checkout_run_id == run_id)
    result = db.execute(update(Task).where(*cond).values(checkout_run_id=None)
                        .execution_options(synchronize_session=False))
    if commit:
        db.commit()
    db.refresh(task)
    return result.rowcount == 1


# ------------------------------------------------------------------ lượt chạy

def open_run(db: Session, task: Task, *, organization_id: int, member_id: int | None,
             trigger_kind: str = "manual", wakeup_id: int | None = None) -> TaskRun:
    run = TaskRun(organization_id=organization_id, task_id=task.id, member_id=member_id,
                  trigger_kind=trigger_kind, wakeup_id=wakeup_id, status="queued")
    db.add(run); db.commit(); db.refresh(run)
    return run


def finish_run(db: Session, run: TaskRun, status: str, *, error_reason: str = "",
               cost_usd: float | None = None, commit: bool = True) -> TaskRun:
    if run.status not in OPEN_RUN_STATUSES:
        return run  # đã kết thúc; sự kiện muộn không được viết lại kết cục
    run.status = status
    run.ended_at = datetime.utcnow()
    if error_reason:
        run.error_reason = error_reason[:4000]
    if cost_usd is not None:
        run.cost_usd = float(cost_usd)
    db.add(run)
    task = db.get(Task, run.task_id)
    if task is not None and task.checkout_run_id == run.id:
        task.checkout_run_id = None
        db.add(task)
    if commit:
        db.commit(); db.refresh(run)
    return run


def current_run(db: Session, task: Task) -> TaskRun | None:
    if task.checkout_run_id:
        run = db.get(TaskRun, task.checkout_run_id)
        if run is not None:
            return run
    if task.runtime_run_id:
        return db.execute(select(TaskRun).where(
            TaskRun.task_id == task.id, TaskRun.runtime_run_id == task.runtime_run_id)
            .order_by(TaskRun.id.desc())).scalars().first()
    return None
