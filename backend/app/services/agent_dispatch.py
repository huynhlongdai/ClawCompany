"""Dispatch a company task into a real OpenClaw session.

This supersedes `services.tasks.dispatch_task`, which had two problems:

1. It set `task.status = "running"`, a value that is not in the v18 task
   vocabulary (`backlog, todo, in_progress, review, done, cancelled`), so a
   dispatched task fell out of the board's transition table.
2. It let the runtime pick the session key, which meant every company task for
   an agent landed in that agent's main chat session together with the
   operator's own conversation.

Here a task gets its own session (`agent:<agentId>:company-task-<id>`), the
status moves to `in_progress`, and the runtime identifiers are persisted so the
task can be aborted or replayed later.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.core.config import settings
from app.runtime.factory import resolve_mode
from app.models import Agent, CustomerProjectAssignment, Member, Task
from app.realtime import broker
from app.runtime.factory import get_runtime
from app.services import openclaw_alignment as align
from app.services import task_graph, task_journal, work_context
from app.services import task_lifecycle as lifecycle

# Những lần không ghi được sổ, đọc được qua API để không ai tưởng sổ đầy đủ.
LOG_JOURNAL_FAILURES: list[dict] = []
from app.services.company_event_bus import emit_event
from app.services.metering import record_usage

SOURCE = "agent_dispatch"


class DispatchError(ValueError):
    """Raised when a task cannot be handed to the runtime."""


class DispatchConflict(DispatchError):
    """D1.3/D1.4: việc đang bị chặn hoặc đang có lượt chạy khác giữ (HTTP 409)."""


def resolve_seat(db: Session, task: Task) -> tuple[Member, Agent]:
    """Find the agent seat responsible for a task, with explicit failures."""
    if not task.assignee_member_id:
        raise DispatchError("Task has no assignee")
    member = db.get(Member, task.assignee_member_id)
    if member is None:
        raise DispatchError("Assignee not found")
    if member.member_type != "agent":
        raise DispatchError("Assignee is a human member, not an AI agent")
    agent = db.query(Agent).filter(Agent.member_id == member.id).first()
    if agent is None:
        raise DispatchError("Member has no agent record")
    if not agent.runtime_agent_id:
        raise DispatchError(
            "Agent seat is not bound to an OpenClaw agentId. Bind it with POST /api/v19/openclaw/bind."
        )
    # M3: seat tạm dừng / đã nghỉ / chưa có trên gateway không nhận lượt mới.
    from app.services.agent_hr import BLOCKED_LIFECYCLES, LIFECYCLE_VI
    if agent.lifecycle in BLOCKED_LIFECYCLES:
        raise DispatchError(f"{member.name} {LIFECYCLE_VI[agent.lifecycle]} — không giao lượt chạy mới")
    return member, agent


async def dispatch_task(db: Session, task: Task, *, trigger_kind: str = "manual",
                        wakeup_id: int | None = None) -> Task:
    member, agent = resolve_seat(db, task)
    # D1.3: việc mình chờ chưa xong thì agent làm gì cũng là làm trên giả định.
    waiting = task_graph.open_blockers(db, task.id)
    if waiting:
        raise DispatchConflict("Task còn bị chặn bởi "
                               + ", ".join(f"#{t.id}" for t in waiting) + " chưa xong")
    # D1.4: mỗi lượt là một hàng task_runs, và lượt phải giữ được task trước
    # khi chạy. Thua cuộc giữ chỗ thì dừng ngay, không thử lại.
    run_row = lifecycle.open_run(db, task, organization_id=member.organization_id,
                                 member_id=member.id, trigger_kind=trigger_kind,
                                 wakeup_id=wakeup_id)
    try:
        lifecycle.checkout(db, task, run_row.id)
    except lifecycle.CheckoutConflict as exc:
        lifecycle.finish_run(db, run_row, "skipped",
                             error_reason=f"checkout lost to run #{exc.holder}")
        raise DispatchConflict(exc.detail["message"]) from exc
    session_key = align.session_key_for_task(agent.runtime_agent_id, task.id)
    runtime = get_runtime()

    # v37: gửi gói ngữ cảnh bảy khối thay cho `task_brief` bốn dòng.
    #
    # Đo được trước khi đổi (`_reports/work-memory-gap.md`): brief cũ dài 358 ký
    # tự, trong đó 286 là văn bản cố định, và 10/12 dữ kiện công ty đã biết
    # không đi vào prompt — agent trả lời "không có thông tin" cho cả ba câu về
    # dự án, người giao việc và hạn chót.
    #
    # `task_brief` không bị xoá: nội dung của nó thành khối 7 (thoả thuận làm
    # việc) trong gói, vì bốn dòng đó là một hợp đồng chứ không phải mô tả.
    pack = work_context.build_pack(db, task, organization_id=member.organization_id)

    try:
        run = await _run_agent(runtime, agent, task, member, pack, session_key)
    except Exception as exc:
        lifecycle.finish_run(db, run_row, "failed", error_reason=str(exc))
        raise
    run_row.status = "running"
    run_row.started_at = datetime.utcnow()
    run_row.runtime_run_id = run.run_id or ""
    run_row.session_key = run.session_key or session_key
    db.add(run_row)

    task.runtime_task_id = run.task_id or str(task.id)
    task.runtime_run_id = run.run_id
    task.runtime_session_key = run.session_key or session_key
    # M1: gắn follower NGAY sau chat.send cho mọi đường dispatch (v19 start,
    # /tasks/{id}/dispatch, kéo thẻ). Trước đây chỉ wakeup và v20 move_task gắn,
    # nên việc giao tay không bao giờ nhận sự kiện, chi phí hay trạng thái cuối:
    # task kẹt ở in_progress dù agent đã trả lời (đo trên gateway thật, e2e4).
    follow_after_send(task.runtime_session_key, member.organization_id, task.id)
    return await _after_run(db, task, member, agent, run, pack)


def follow_after_send(session_key: str | None, organization_id: int, task_id: int) -> str | None:
    """Theo dõi phiên vừa gửi. Idempotent; lỗi follow không làm hỏng lượt đã gửi."""
    if not (session_key and settings.wakeup_follow and resolve_mode(settings.openclaw_mode) == "native"):
        return None
    try:
        from app.services.runtime_stream import supervisor
        state = supervisor.follow(session_key=session_key, organization_id=organization_id, task_id=task_id)
        return getattr(state, "status", "following")
    except Exception as exc:  # noqa: BLE001
        print(f"[M1] follow after dispatch failed: {exc}")
        return f"error: {exc}"


async def _run_agent(runtime, agent, task, member, pack, session_key):
    return await runtime.run_agent(
        runtime_agent_id=agent.runtime_agent_id,
        input_text=pack["text"],
        metadata={
            "company_task_id": task.id,
            "project_id": task.project_id,
            "organization_id": member.organization_id,
            "label": f"Task #{task.id}",
        },
        session_key=session_key,
    )


async def _after_run(db: Session, task: Task, member: Member, agent: Agent, run, pack) -> Task:

    # Ghi vào sổ của task: lần chạy này đã bắt đầu, với gói ngữ cảnh cỡ nào.
    # Đây là thứ khối 4 của lần dispatch KẾ TIẾP sẽ đọc — tầng bộ nhớ công việc
    # chỉ hoạt động nếu mỗi lượt đều chịu ghi lại.
    try:
        task_journal.append(
            db, task, kind="attempt", actor_member_id=member.id,
            summary=f"Giao cho {member.name} qua seat {agent.runtime_agent_id}",
            detail=f"Gói ngữ cảnh {pack['chars']} ký tự"
                   + (f", đã lược: {', '.join(pack['trimmed'])}" if pack["trimmed"] else "")
                   + f"\nSession: {task.runtime_session_key}",
            runtime_run_id=run.run_id or "", runtime_session_key=task.runtime_session_key or "",
        )
    except task_journal.JournalError as exc:
        # Không ghi được sổ thì việc vẫn phải chạy; nhưng phải để lại dấu vết,
        # vì một sổ ghi có lỗ là một sổ ghi nói dối về lịch sử.
        LOG_JOURNAL_FAILURES.append({"task_id": task.id, "error": str(exc)})
    # Stay inside the board vocabulary. A dispatched task is in_progress.
    if task.status not in ("in_progress", "review", "done"):
        lifecycle.transition(db, task, "in_progress", system=True, via="dispatch",
                             reason=f"dispatched to {agent.runtime_agent_id}",
                             commit=False, emit=False)
    db.add(task)
    db.commit()
    db.refresh(task)

    assignment = (
        db.query(CustomerProjectAssignment)
        .filter(CustomerProjectAssignment.project_id == task.project_id)
        .first()
    )
    record_usage(
        db,
        organization_id=member.organization_id,
        customer_id=assignment.customer_id if assignment else None,
        agent_id=agent.id,
        task_id=task.id,
        runtime_run_id=run.run_id,
        event_type="task_dispatch",
        quantity=1,
        unit="run",
        unit_cost=0,
        metadata={
            "project_id": task.project_id,
            "runtime_agent_id": agent.runtime_agent_id,
            "session_key": task.runtime_session_key,
            "runtime_mode": settings.openclaw_mode,
        },
    )
    emit_event(
        db,
        organization_id=member.organization_id,
        event_type="openclaw.task.dispatched",
        source=SOURCE,
        company_id=member.company_id,
        aggregate_type="task",
        aggregate_id=str(task.id),
        payload={
            "run_id": run.run_id,
            "session_key": task.runtime_session_key,
            "runtime_agent_id": agent.runtime_agent_id,
        },
    )
    await broker.publish(
        f"org:{member.organization_id}",
        {
            "type": "task.dispatched",
            "task_id": task.id,
            "project_id": task.project_id,
            "agent_id": agent.id,
            "run_id": run.run_id,
            "session_key": task.runtime_session_key,
            "status": task.status,
        },
    )
    return task


async def abort_task(db: Session, task: Task, *, back_to: str = "todo") -> dict:
    """Abort the running session for a task and park it back on the board."""
    if not task.runtime_session_key and not task.runtime_run_id:
        raise DispatchError("Task has no active runtime run")
    runtime = get_runtime()
    handle = task.runtime_session_key or task.runtime_run_id
    result = await runtime.cancel_run(handle)

    if back_to not in ("todo", "backlog", "review", "cancelled"):
        raise DispatchError(f"Unsupported status after abort: {back_to}")
    holder = lifecycle.current_run(db, task)
    if holder is not None:
        lifecycle.finish_run(db, holder, "cancelled", error_reason="aborted by operator",
                             commit=False)
    lifecycle.transition(db, task, back_to, system=True, via="abort",
                         reason="run aborted by operator", commit=False, emit=False)
    db.add(task)
    db.commit()
    db.refresh(task)

    member = db.get(Member, task.assignee_member_id) if task.assignee_member_id else None
    if member is not None:
        emit_event(
            db,
            organization_id=member.organization_id,
            event_type="openclaw.task.aborted",
            source=SOURCE,
            company_id=member.company_id,
            aggregate_type="task",
            aggregate_id=str(task.id),
            payload={"run_id": task.runtime_run_id, "status": task.status},
        )
    return {"task_id": task.id, "status": task.status, "runtime": result}
