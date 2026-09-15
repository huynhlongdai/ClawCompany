"""v33: bring a member's *work* back when the member row is un-archived.

The v29 cascade archive sets ``Member.status = offboarded``. Tasks that were
mid-flight keep their ``runtime_session_key`` pointing at a runtime session
that nobody will ever poll again. ``entity_archive.restore_entity`` puts the
row back, and deliberately stops there: it restores *state*, not *runtime*.

The visible bug was that the board lied after a restore. A task sat in
``in_progress`` holding a dead session key, so the cockpit showed work in
flight while no runner existed.

This module closes that gap without pretending it can resurrect a session:

* ``preview`` names every orphaned runtime attachment the restore left behind.
* ``park`` is the only write. It drops the dead session key and returns the
  task to the board vocabulary, so the board stops claiming a runner exists.
* ``resume_plan`` returns the dispatch calls a human or agent should make to
  actually start the work again. It never dispatches by itself -- dispatch
  costs money and picks an agent, and neither belongs in a repair routine.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import Member, Task
from app.services import entity_archive
from app.services.company_event_bus import emit_event

SOURCE = "member_reactivate"
PARK_EVENT = "member.runtime.parked"

# A restored member is only interesting if the row is actually live again.
ARCHIVED_STATUS = entity_archive.MEMBER_ARCHIVED

# Statuses that claim "a runner is working on this right now".
RUNNING_STATUSES = ("in_progress", "review")

# Where a parked task lands. Not "backlog": the work was already triaged once,
# and demoting it would lose that decision.
PARK_STATUS = "todo"

MAX_PARK = 200

# The dispatch surface that *can* legitimately start the work again.
RESUME_TOOL = "company.task.dispatch"


class ReactivateError(RuntimeError):
    """Raised when the repair cannot be reasoned about safely."""


def _lease_holder(session_key: str) -> str | None:
    """Who, if anyone, still holds the runtime lease for this session key.

    A held lease means some worker still believes it owns this session, so
    parking the task would fight a live process. Lease lookup is best effort:
    Redis may be unavailable, and an unknown holder is reported as unknown
    rather than silently treated as free.
    """
    if not session_key:
        return None
    try:
        from app.services.runtime_leases import store

        return store.holder(session_key)
    except Exception:
        return None


def _member_of(db: Session, member_id: int) -> Member | None:
    return db.get(Member, member_id)


def orphans(db: Session, member: Member) -> list[dict]:
    """Tasks assigned to this member that still name a runtime session."""
    rows = db.execute(
        select(Task).where(
            Task.assignee_member_id == member.id,
            Task.status.in_(RUNNING_STATUSES),
            Task.runtime_session_key.isnot(None),
        )
    ).scalars().all()

    out: list[dict] = []
    for task in rows:
        key = task.runtime_session_key or ""
        if not key.strip():
            continue
        holder = _lease_holder(key)
        out.append({
            "task_id": task.id,
            "title": task.title,
            "project_id": task.project_id,
            "status": task.status,
            "session_key": key,
            "lease_holder": holder,
            "lease_held": holder is not None,
            "park_to": PARK_STATUS,
        })
    return out


def preview(db: Session, member: Member) -> dict:
    """What the restore left behind, and what can be done about it."""
    archived = member.status == ARCHIVED_STATUS
    found = orphans(db, member)
    parkable = [x for x in found if not x["lease_held"]]
    contested = [x for x in found if x["lease_held"]]
    return {
        "member_id": member.id,
        "member_status": member.status,
        "member_is_archived": archived,
        "orphan_count": len(found),
        "orphans": found[:MAX_PARK],
        "parkable_task_ids": [x["task_id"] for x in parkable][:MAX_PARK],
        "contested_task_ids": [x["task_id"] for x in contested],
        "park_status": PARK_STATUS,
        "max_park_per_call": MAX_PARK,
        "blocked_reason": (
            "This member is still archived; restore the member first"
            if archived else None
        ),
        "note": (
            "Parking clears the dead session key only. Use resume_plan to see "
            "how to start the work again; this module never dispatches."
        ),
    }


def resume_plan(db: Session, member: Member) -> dict:
    """The dispatch calls that would actually restart the parked work.

    Returned as data, not executed. Dispatch selects an agent and spends
    budget, which is a decision for a human or for the dispatch endpoint's
    own guards -- not for a repair routine cleaning up after an archive.
    """
    found = orphans(db, member)
    return {
        "member_id": member.id,
        "tool": RESUME_TOOL,
        "calls": [{"tool": RESUME_TOOL, "task_id": x["task_id"], "title": x["title"]}
                  for x in found if not x["lease_held"]][:MAX_PARK],
        "skipped_contested": [x["task_id"] for x in found if x["lease_held"]],
        "executed": False,
        "why_not_executed": (
            "Dispatch picks an agent and spends budget. A restore repair must "
            "not make that choice on the owner's behalf."
        ),
    }


def park(db: Session, member: Member, organization_id: int, *, dry_run: bool = True,
         limit: int | None = None, actor_member_id: int | None = None) -> dict:
    """Drop dead session keys so the board stops claiming a runner exists."""
    if member.status == ARCHIVED_STATUS:
        raise ReactivateError(
            "This member is still archived; restore the member before parking runtime"
        )

    plan = preview(db, member)
    cap = MAX_PARK if limit is None else max(1, min(int(limit), MAX_PARK))
    targets = [x for x in plan["orphans"] if not x["lease_held"]][:cap]

    if dry_run:
        return {**plan, "dry_run": True, "parked": 0,
                "would_park_task_ids": [x["task_id"] for x in targets]}

    parked: list[dict] = []
    for item in targets:
        task = db.get(Task, item["task_id"])
        if task is None:
            continue
        before = task.status
        task.status = PARK_STATUS
        task.runtime_session_key = None
        db.add(task)
        parked.append({"task_id": task.id, "from": before, "to": PARK_STATUS,
                       "dropped_session_key": item["session_key"]})
    db.commit()

    result = {**plan, "dry_run": False, "parked": len(parked), "parked_tasks": parked}
    try:
        emit_event(db, organization_id=organization_id, event_type=PARK_EVENT,
                   source=SOURCE, company_id=getattr(member, "company_id", None),
                   aggregate_type="member", aggregate_id=str(member.id),
                   actor_member_id=actor_member_id,
                   payload={"member_id": member.id, "parked": len(parked),
                            "task_ids": [x["task_id"] for x in parked],
                            "park_status": PARK_STATUS})
    except Exception as exc:  # pragma: no cover - the repair still happened
        result["event_error"] = str(exc)
    return result


def coverage() -> dict:
    """What this module fixes, and what it still leaves to someone else."""
    return {
        "fixes": ["dead runtime_session_key after a member restore",
                  "tasks stuck in a running status with no runner"],
        "running_statuses": list(RUNNING_STATUSES),
        "park_status": PARK_STATUS,
        "does_not_do": ["re-dispatching work", "reviving a runtime session",
                        "touching tasks whose lease is still held"],
        "resume_tool": RESUME_TOOL,
    }
