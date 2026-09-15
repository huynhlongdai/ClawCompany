"""v20: keep OpenClaw session streams open and turn them into company records.

v19 could dispatch a task into a real OpenClaw session, but the stream only
existed for the lifetime of an HTTP call. Anything the agent did after the
request returned was lost: no runtime events, no status change when the run
finished, and — worst of all — approval prompts from the gateway expired
without a human ever seeing them.

This module runs one long-lived consumer per session key inside the API
process. It is deliberately modest about what it guarantees:

- Ownership is a **shared lease** (v21, ``runtime_leases``), so two workers
  can no longer both consume one session. Reporting is a **shared registry**
  (v22, ``stream_registry``), so any worker can answer "what is running?"
  instead of only describing its own memory. When Redis is absent both
  degrade to this process and say so, rather than implying cluster safety.
- It owns its own database session. Request-scoped sessions die with the
  request; a consumer that outlives the request must not borrow one.
- It never crashes the app. A consumer that fails records the failure and
  stops; the caller can restart it.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models import Agent, Approval, Member, Task
from app.realtime import broker
from app.runtime import openclaw_protocol as ocp
from app.runtime.factory import get_runtime
from app.services.company_event_bus import emit_event
from app.services import runtime_gap
from app.services import stream_reconcile
from app.services.runtime_events import persist_runtime_event
from app.services.runtime_leases import store as lease_store
from app.services.stream_registry import registry

SOURCE = "runtime_stream"

# v22: a follower that lost its lease mid-stream leaves the session claimable
# so another worker can pick it up without waiting for a human.
ORPHAN_STATUSES = ("stopped", "failed")

# Company task status after a run ends, keyed by the upstream terminal state.
# A completed run goes to review rather than done: the agent finishing is not
# the same as the company accepting the work.
TERMINAL_STATUS = {
    "complete": "review",
    "completed": "review",
    "error": "blocked",
    "aborted": "todo",
    "cancelled": "todo",
    "canceled": "todo",
}


@dataclass
class ConsumerState:
    session_key: str
    task_id: int | None
    organization_id: int
    started_at: datetime = field(default_factory=datetime.utcnow)
    events: int = 0
    approvals: int = 0
    last_event_type: str = ""
    status: str = "running"  # running | finished | failed | stopped | declined
    error: str = ""
    lease_backend: str = ""  # v21: "redis" (shared) or "memory" (this process only)

    def public(self) -> dict:
        return {
            "session_key": self.session_key,
            "task_id": self.task_id,
            "organization_id": self.organization_id,
            "started_at": self.started_at.isoformat(),
            "events": self.events,
            "approvals": self.approvals,
            "last_event_type": self.last_event_type,
            "status": self.status,
            "error": self.error,
            "lease_backend": self.lease_backend,
        }


class StreamSupervisor:
    """Tracks one consumer task per session key in this process."""

    def __init__(self) -> None:
        self._tasks: dict[str, asyncio.Task] = {}
        self._state: dict[str, ConsumerState] = {}

    def is_following(self, session_key: str) -> bool:
        task = self._tasks.get(session_key)
        return task is not None and not task.done()

    def follow(self, *, session_key: str, organization_id: int, task_id: int | None = None) -> ConsumerState:
        """Start following a session, unless another process already owns it.

        v21: the claim is a shared lease, so two API workers can no longer
        both subscribe to the same session and double-write its events. A
        refused claim is a normal outcome and is reported as `declined`.
        """
        if self.is_following(session_key):
            return self._state[session_key]
        state = ConsumerState(session_key=session_key, task_id=task_id, organization_id=organization_id)
        lease = lease_store.acquire(session_key)
        if lease is None:
            state.status = "declined"
            state.error = f"Session already followed by {lease_store.holder(session_key) or 'another process'}"
            self._state[session_key] = state
            return state
        state.lease_backend = lease.backend
        self._state[session_key] = state
        self._tasks[session_key] = asyncio.create_task(
            _consume(state), name=f"openclaw-stream:{session_key}"
        )
        return state

    def stop(self, session_key: str) -> bool:
        task = self._tasks.get(session_key)
        if task is None or task.done():
            return False
        task.cancel()
        lease_store.release(session_key)
        state = self._state.get(session_key)
        if state is not None:
            state.status = "stopped"
        return True

    def stop_all(self) -> int:
        return sum(1 for key in list(self._tasks) if self.stop(key))

    def snapshot(self, organization_id: int | None = None) -> list[dict]:
        rows = [s.public() for s in self._state.values()
                if organization_id is None or s.organization_id == organization_id]
        return sorted(rows, key=lambda r: r["started_at"], reverse=True)


supervisor = StreamSupervisor()


async def _consume(state: ConsumerState) -> None:
    """Read one session's events until it ends, persisting as we go."""
    runtime = get_runtime()
    db: Session = SessionLocal()
    try:
        # v25: the attach is the trigger. Before the first live event, report
        # the hole we just inherited and pull back any approval prompt raised
        # while nobody was listening. This never raises.
        await stream_reconcile.reconcile(
            db, organization_id=state.organization_id, session_key=state.session_key,
            task_id=state.task_id, reason="follow",
        )
        async for event in runtime.stream_run(state.session_key):
            state.events += 1
            state.last_event_type = str(event.get("type") or "")
            # v21: keep the shared claim alive; losing it means another process
            # took over, so we stop rather than write the same events twice.
            if not lease_store.renew(state.session_key):
                state.status = "stopped"
                state.error = "Lease lost to another process"
                return
            handle_event(db, state, event)
            registry.publish(state.public())
            if event.get("terminal"):
                break
        state.status = "finished"
    except asyncio.CancelledError:
        state.status = "stopped"
        raise
    except Exception as exc:  # noqa: BLE001 - a broken stream must not kill the API
        state.status = "failed"
        state.error = str(exc)[:500]
        emit_event(
            db, organization_id=state.organization_id, event_type="openclaw.stream.failed",
            source=SOURCE, aggregate_type="session", aggregate_id=state.session_key,
            payload={"error": state.error, "task_id": state.task_id},
        )
    finally:
        # Report the final state before dropping the claim, so a sweeper that
        # reads the registry sees why we stopped rather than a missing row.
        registry.publish(state.public())
        lease_store.release(state.session_key)
        registry.withdraw(state.session_key)
        db.close()


def handle_event(db: Session, state: ConsumerState, event: dict) -> None:
    """Persist one normalized gateway event and apply its side effects.

    Split out from the consumer loop so it can be tested without a gateway.
    """
    task = db.get(Task, state.task_id) if state.task_id else None
    agent_id = None
    member = None
    if task is not None and task.assignee_member_id:
        member = db.get(Member, task.assignee_member_id)
        agent = db.query(Agent).filter(Agent.member_id == task.assignee_member_id).first()
        agent_id = agent.id if agent else None

    persist_runtime_event(
        db,
        organization_id=state.organization_id,
        run_id=str(event.get("runId") or state.session_key),
        event=event,
        agent_id=agent_id,
        task_id=state.task_id,
        session_key=state.session_key,
    )

    if str(event.get("family") or "") in ocp.APPROVAL_EVENTS:
        state.approvals += 1
        record_approval(db, state, event, member=member)

    if event.get("terminal") and task is not None:
        apply_terminal_state(db, task, state, event)


def record_approval(db: Session, state: ConsumerState, event: dict, member: Member | None = None) -> Approval | None:
    """Turn a gateway permission prompt into a row in the company queue.

    Resolution events update the matching pending row instead of creating a
    second one, so the queue does not fill with duplicates when the operator
    answers in the OpenClaw UI.
    """
    raw = event.get("raw") if isinstance(event.get("raw"), dict) else {}
    request_id = str(raw.get("id") or raw.get("approvalId") or raw.get("requestId") or "")
    policy_key = f"openclaw:{state.session_key}:{request_id}" if request_id else f"openclaw:{state.session_key}"
    decision = str(raw.get("decision") or raw.get("result") or "").lower()

    existing = (
        db.query(Approval)
        .filter(Approval.organization_id == state.organization_id, Approval.policy_key == policy_key)
        .order_by(Approval.id.desc())
        .first()
    )

    if decision in ("approve", "approved", "allow", "deny", "denied", "reject", "rejected"):
        if existing is None:
            return None
        existing.status = "approved" if decision.startswith(("approve", "allow")) else "rejected"
        existing.resolution_note = f"Resolved in OpenClaw: {decision}"
        db.add(existing)
        db.commit()
        db.refresh(existing)
        return existing

    if existing is not None and existing.status == "pending":
        return existing  # idempotent: the gateway may re-announce a pending prompt

    tool = str(raw.get("tool") or raw.get("toolName") or raw.get("command") or "action")
    approval = Approval(
        organization_id=state.organization_id,
        company_id=member.company_id if member is not None else None,
        requester_member_id=member.id if member is not None else None,
        action=f"OpenClaw agent requests: {tool}"[:220],
        risk=str(raw.get("risk") or ("high" if tool in ocp.HTTP_DENIED_TOOLS else "medium"))[:24],
        policy_key=policy_key[:120],
        status="pending",
        evidence=json.dumps(
            {"session_key": state.session_key, "task_id": state.task_id, "event": raw},
            ensure_ascii=False, default=str,
        ),
    )
    db.add(approval)
    db.commit()
    db.refresh(approval)
    emit_event(
        db, organization_id=state.organization_id, event_type="openclaw.approval.requested",
        source=SOURCE, company_id=approval.company_id, aggregate_type="approval",
        aggregate_id=str(approval.id),
        payload={"session_key": state.session_key, "task_id": state.task_id, "tool": tool},
    )
    return approval


def apply_terminal_state(db: Session, task: Task, state: ConsumerState, event: dict) -> Task:
    """Move the task when its run ends, staying inside the board vocabulary."""
    upstream_state = str(event.get("state") or "")
    new_status = TERMINAL_STATUS.get(upstream_state)
    if new_status is None or task.status == new_status:
        return task
    previous = task.status
    task.status = new_status
    db.add(task)
    db.commit()
    db.refresh(task)
    emit_event(
        db, organization_id=state.organization_id, event_type=f"openclaw.run.{upstream_state}",
        source=SOURCE, aggregate_type="task", aggregate_id=str(task.id),
        payload={"from": previous, "to": new_status, "session_key": state.session_key,
                 "error": event.get("errorMessage")},
    )
    return task


def resumable_sessions(db: Session, limit: int = 200) -> list[Task]:
    """Tasks that were left mid-run: in progress, with a session, unfinished.

    After a restart nothing is following these sessions, so their events and
    approval prompts would be lost until someone manually pressed a button.
    """
    return (
        db.query(Task)
        .filter(Task.status == "in_progress", Task.runtime_session_key != "",
                Task.runtime_session_key.isnot(None))
        .order_by(Task.id.desc())
        .limit(limit)
        .all()
    )


def resume_followers(db: Session, organization_id: int | None = None, limit: int = 200) -> dict:
    """Re-attach followers after a restart.

    Leases make this safe to call from every worker on boot: only one of them
    wins each session, the rest are declined.
    """
    resumed, declined, skipped = [], [], []
    for task in resumable_sessions(db, limit=limit):
        org_id = organization_id
        if org_id is None:
            member = db.get(Member, task.assignee_member_id) if task.assignee_member_id else None
            if member is None:
                skipped.append(task.id)
                continue
            org_id = member.organization_id
        elif task.assignee_member_id:
            member = db.get(Member, task.assignee_member_id)
            if member is None or member.organization_id != org_id:
                skipped.append(task.id)
                continue
        state = supervisor.follow(session_key=task.runtime_session_key,
                                  organization_id=org_id, task_id=task.id)
        (resumed if state.status == "running" else declined).append(task.id)
    return {"resumed": resumed, "declined": declined, "skipped": skipped,
            "lease": lease_store.status()}


async def announce(state: ConsumerState) -> None:
    await broker.publish(f"org:{state.organization_id}", {"type": "stream.following", **state.public()})


def cluster_snapshot(organization_id: int | None = None) -> dict:
    """Followers across every worker, with an honest note when we cannot.

    The shared registry is the source when Redis is present. Rows this
    process owns are merged in unconditionally: our own live state is fresher
    than anything we last published.
    """
    local = {row["session_key"]: row for row in supervisor.snapshot(organization_id)}
    merged = {row.get("session_key"): row for row in registry.snapshot(organization_id)}
    merged.update(local)
    rows = sorted(merged.values(), key=lambda r: str(r.get("started_at") or ""), reverse=True)
    return {
        "streams": rows,
        "registry": registry.status(),
        "lease": lease_store.status(),
        "process_local": not registry.cluster_wide,
        "local_sessions": len(local),
    }


def claimable_sessions(db: Session, limit: int = 200) -> list[Task]:
    """Mid-run tasks whose session currently has no lease holder.

    This is the difference v21 could not express: ``resumable_sessions`` lists
    everything mid-run, including sessions another worker is happily
    following. Claiming those would be refused anyway, so a sweep that runs
    every few seconds should only look at the genuinely unowned ones.
    """
    held = lease_store.scan()
    return [task for task in resumable_sessions(db, limit=limit)
            if task.runtime_session_key not in held]


def claim_orphans(db: Session, organization_id: int | None = None, limit: int = 200) -> dict:
    """Take over sessions whose previous follower died or lost its lease.

    v21 stopped the losing follower but left the session unattended until a
    human pressed "resume". This closes that window. It is safe to run from
    every worker: the lease decides the winner and the losers are declined.
    """
    claimed, declined, skipped, gaps = [], [], [], []
    for task in claimable_sessions(db, limit=limit):
        org_id = organization_id
        member = db.get(Member, task.assignee_member_id) if task.assignee_member_id else None
        if org_id is None:
            if member is None:
                skipped.append(task.id)
                continue
            org_id = member.organization_id
        elif member is None or member.organization_id != org_id:
            skipped.append(task.id)
            continue
        state = supervisor.follow(session_key=task.runtime_session_key,
                                  organization_id=org_id, task_id=task.id)
        if state.status == "running":
            claimed.append(task.id)
            # v24: re-subscribing does not replay what happened while nobody
            # was attached. Record the hole instead of leaving the transcript
            # looking continuous.
            gap = runtime_gap.record(db, organization_id=org_id,
                                     session_key=task.runtime_session_key,
                                     task_id=task.id, reason="takeover")
            if gap is not None:
                gaps.append(gap)
        else:
            declined.append(task.id)
    return {"claimed": claimed, "declined": declined, "skipped": skipped, "gaps": gaps,
            "lease": lease_store.status(), "registry": registry.status()}


async def sweep_orphans_forever(interval_seconds: int) -> None:
    """Background loop that keeps unattended sessions attended.

    Guarded by ``OPENCLAW_CLAIM_SWEEP_SECONDS`` (0 disables it). Every failure
    is swallowed: a sweeper must never be the reason the API dies.
    """
    while True:
        await asyncio.sleep(max(5, interval_seconds))
        db: Session = SessionLocal()
        try:
            claim_orphans(db)
        except Exception as exc:  # noqa: BLE001
            print(f"[v22] orphan sweep skipped: {str(exc)[:200]}")
        finally:
            db.close()
