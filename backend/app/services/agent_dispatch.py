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

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import Agent, CustomerProjectAssignment, Member, Task
from app.realtime import broker
from app.runtime.factory import get_runtime
from app.services import openclaw_alignment as align
from app.services.company_event_bus import emit_event
from app.services.metering import record_usage

SOURCE = "agent_dispatch"


class DispatchError(ValueError):
    """Raised when a task cannot be handed to the runtime."""


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
    return member, agent


async def dispatch_task(db: Session, task: Task) -> Task:
    member, agent = resolve_seat(db, task)
    session_key = align.session_key_for_task(agent.runtime_agent_id, task.id)
    runtime = get_runtime()

    run = await runtime.run_agent(
        runtime_agent_id=agent.runtime_agent_id,
        input_text=align.task_brief(db, task),
        metadata={
            "company_task_id": task.id,
            "project_id": task.project_id,
            "organization_id": member.organization_id,
            "label": f"Task #{task.id}",
        },
        session_key=session_key,
    )

    task.runtime_task_id = run.task_id or str(task.id)
    task.runtime_run_id = run.run_id
    task.runtime_session_key = run.session_key or session_key
    # Stay inside the board vocabulary. A dispatched task is in_progress.
    if task.status not in ("in_progress", "review", "done"):
        task.status = "in_progress"
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
    task.status = back_to
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
