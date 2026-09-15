"""v27: the three things v18 wrote down as debts and nobody came back for.

Section 8.5 of the handover has been honest since v18 about what the write
half of the cockpit never finished:

1. ``Project.progress`` was typed by a human. A number that nobody computes
   is a number nobody can trust, and the board right next to it already
   knows the answer.
2. No optimistic concurrency: two people editing the same project meant the
   later save silently won, and neither was told.
3. No archive/delete, because the cascade needed designing. Nine versions of
   runtime work later, that cascade has a hazard v18 could not have known
   about: a task can be attached to a *live OpenClaw session*.

All three are fixed here with no new tables and no migration: revisions come
from the ``updated_at`` column every entity already has, and archiving uses
the existing status vocabulary rather than inventing a state the rest of the
system would not recognise.
"""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Project, Task
from app.services.company_event_bus import emit_event
from app.services.runtime_leases import store as lease_store

SOURCE = "board_truth"

# Cancelled work is not failed work waiting to be done -- it is work that was
# taken off the board. Counting it as incomplete would make a project that
# dropped half its scope look permanently stuck at 50%.
EXCLUDED_FROM_PROGRESS = ("cancelled",)

# Only "done" counts. "review" is deliberately not half a point: partial
# credit is how a progress number starts drifting away from anything you can
# point at, and v18's hand-typed value already proved where that ends.
COMPLETE_STATUSES = ("done",)

# A task holding one of these is work the company still owes; archiving the
# project cancels them, which is a real decision and is reported as one.
OPEN_STATUSES = ("backlog", "todo", "in_progress", "review", "blocked")

ARCHIVE_STATUS = "cancelled"  # from v18's PROJECT_STATUSES; no new vocabulary

PROGRESS_EVENT = "project.progress.derived"
ARCHIVE_EVENT = "project.archived"
CONFLICT_EVENT = "board.write.conflict"


# -- revisions --------------------------------------------------------------


def revision(entity) -> str:
    """An opaque revision token for one row.

    Built from ``updated_at``, which SQLAlchemy already maintains via
    ``onupdate`` on every entity in ``models/entities.py``. That is why v27
    needs no migration -- but it also means the token only changes when a
    write actually touches the row, which is exactly the semantics we want.
    """
    stamp = getattr(entity, "updated_at", None)
    return f"{entity.__class__.__name__.lower()}:{entity.id}:{stamp.isoformat() if stamp else '0'}"


def check_revision(db: Session, entity, expected: str | None, *,
                   organization_id: int | None = None) -> None:
    """Reject a write based on a stale read.

    ``expected`` being None means the caller opted out, which keeps every
    pre-v27 client working. Opting in is what buys the protection; silently
    requiring it would break v18's own endpoints.

    The 409 carries the *current* revision so a client can re-read, show the
    difference and retry. A conflict that only says "no" forces a blind
    overwrite on the next attempt, which is the problem we started with.
    """
    if expected is None:
        return
    current = revision(entity)
    if expected == current:
        return
    if organization_id is not None:
        try:
            emit_event(db, organization_id=organization_id, event_type=CONFLICT_EVENT,
                       source=SOURCE, aggregate_type=entity.__class__.__name__.lower(),
                       aggregate_id=str(entity.id),
                       payload={"expected": expected, "current": current})
        except Exception:  # noqa: BLE001 - never turn a 409 into a 500
            pass
    raise HTTPException(409, detail={
        "error": "Stale revision: this row changed since you read it",
        "expected_revision": expected,
        "current_revision": current,
        "last_edited_at": getattr(entity, "updated_at", None).isoformat()
        if getattr(entity, "updated_at", None) else None,
    })


# -- derived progress -------------------------------------------------------


def task_counts(db: Session, project_id: int) -> dict[str, int]:
    rows = db.execute(
        select(Task.status, func.count(Task.id)).where(Task.project_id == project_id)
        .group_by(Task.status)
    ).all()
    return {str(status): int(count) for status, count in rows}


def derive(db: Session, project: Project) -> dict:
    """What the board says this project's progress is.

    A project with no countable tasks returns ``derivable: false`` rather
    than 0%. "Nothing to measure" and "measured zero" are different
    statements, and only one of them justifies overwriting a number a human
    typed on purpose.
    """
    counts = task_counts(db, project.id)
    total = sum(counts.values())
    excluded = sum(counts.get(s, 0) for s in EXCLUDED_FROM_PROGRESS)
    countable = total - excluded
    complete = sum(counts.get(s, 0) for s in COMPLETE_STATUSES)
    derivable = countable > 0
    derived = round(100 * complete / countable) if derivable else None
    return {
        "project_id": project.id,
        "counts": counts,
        "total_tasks": total,
        "countable": countable,
        "excluded": excluded,
        "complete": complete,
        "derivable": derivable,
        "derived_progress": derived,
        "stored_progress": project.progress,
        "drift": None if derived is None else derived - int(project.progress or 0),
        "complete_statuses": list(COMPLETE_STATUSES),
        "excluded_statuses": list(EXCLUDED_FROM_PROGRESS),
        "revision": revision(project),
    }


def sync_progress(db: Session, project: Project, organization_id: int, *,
                  expected_revision: str | None = None,
                  actor_member_id: int | None = None) -> dict:
    """Write the derived number onto the project.

    Kept as an explicit action rather than a trigger on every task move: the
    stored column is still what dashboards and exports read, and quietly
    rewriting a human's number on an unrelated write is how you lose their
    trust in the field entirely. The drift is visible; applying it is a
    decision.
    """
    check_revision(db, project, expected_revision, organization_id=organization_id)
    truth = derive(db, project)
    if not truth["derivable"]:
        return {**truth, "applied": False, "reason": "no countable tasks"}
    if truth["drift"] == 0:
        return {**truth, "applied": False, "reason": "already in sync"}
    before = int(project.progress or 0)
    project.progress = int(truth["derived_progress"])
    db.add(project); db.commit(); db.refresh(project)
    try:
        emit_event(db, organization_id=organization_id, event_type=PROGRESS_EVENT,
                   source=SOURCE, company_id=project.company_id,
                   aggregate_type="project", aggregate_id=str(project.id),
                   payload={"from": before, "to": project.progress,
                            "complete": truth["complete"], "countable": truth["countable"],
                            "actor_member_id": actor_member_id})
    except Exception:  # noqa: BLE001
        pass
    return {**derive(db, project), "applied": True, "previous_progress": before,
            "reason": ""}


# -- archive with cascade ---------------------------------------------------


def live_attachments(db: Session, project_id: int) -> list[dict]:
    """Tasks that are attached to a runtime session right now.

    This is the hazard v18 could not have designed for. Cancelling a task
    out from under a follower leaves an agent running inside OpenClaw with
    nothing on our side listening -- precisely the orphaned-stream state
    v22 through v26 exist to prevent.
    """
    rows = db.execute(
        select(Task).where(Task.project_id == project_id,
                           Task.status == "in_progress",
                           Task.runtime_session_key.isnot(None))
    ).scalars().all()
    out = []
    for task in rows:
        session_key = task.runtime_session_key or ""
        out.append({"task_id": task.id, "title": task.title, "session_key": session_key,
                    "followed_by": lease_store.holder(session_key) or ""})
    return out


def archive_preview(db: Session, project: Project) -> dict:
    counts = task_counts(db, project.id)
    open_tasks = sum(counts.get(s, 0) for s in OPEN_STATUSES)
    live = live_attachments(db, project.id)
    return {
        "project_id": project.id,
        "project_status": project.status,
        "already_archived": project.status == ARCHIVE_STATUS,
        "counts": counts,
        "will_cancel_tasks": open_tasks,
        "will_keep_done_tasks": counts.get("done", 0),
        "live_runtime_sessions": live,
        "blocked": bool(live),
        "blocked_reason": "tasks are attached to live OpenClaw sessions" if live else "",
        "archive_status": ARCHIVE_STATUS,
        "destructive": False,
        "revision": revision(project),
    }


def archive_project(db: Session, project: Project, organization_id: int, *,
                    force: bool = False, expected_revision: str | None = None,
                    actor_member_id: int | None = None) -> dict:
    """Archive a project and cancel the work it still owed.

    Nothing is deleted. ``cancelled`` is a status the whole system already
    understands, so an archived project stays readable, auditable and
    reversible instead of becoming a hole in every historical report.

    Live runtime sessions block the archive unless ``force`` is passed, and
    forcing reports which sessions were left running rather than pretending
    it stopped them. We cannot abort an agent from here -- that is
    ``/api/v19/tasks/{id}/abort`` -- and silently implying otherwise would be
    worse than refusing.
    """
    check_revision(db, project, expected_revision, organization_id=organization_id)
    preview = archive_preview(db, project)
    if preview["blocked"] and not force:
        raise HTTPException(409, detail={
            "error": "Project has tasks attached to live OpenClaw sessions",
            "live_runtime_sessions": preview["live_runtime_sessions"],
            "hint": "Abort them via /api/v19/tasks/{id}/abort, or pass force=true "
                    "to archive and leave those sessions running",
        })

    cancelled: list[int] = []
    # v29: record each task's status *before* we cancel it. v28 could restore
    # which tasks were cancelled but had to reopen all of them at "todo",
    # because the id list was the only thing this payload carried. A blocked
    # task and a task in review are not the same work item.
    task_statuses: dict[str, str] = {}
    tasks = db.execute(select(Task).where(Task.project_id == project.id)).scalars().all()
    for task in tasks:
        if task.status in OPEN_STATUSES:
            task_statuses[str(task.id)] = task.status
            task.status = "cancelled"
            db.add(task)
            cancelled.append(task.id)
    # v28 records what the project was before the archive, so restoring it
    # does not have to guess. Older archive events have no such field and the
    # restore path says so rather than inventing one.
    previous_status = project.status
    project.status = ARCHIVE_STATUS
    db.add(project); db.commit(); db.refresh(project)

    result = {
        "project_id": project.id,
        "status": project.status,
        "previous_status": previous_status,
        "cancelled_task_ids": cancelled,
        "task_statuses": task_statuses,
        "kept_done_tasks": preview["will_keep_done_tasks"],
        "forced": bool(force and preview["blocked"]),
        "left_running": preview["live_runtime_sessions"] if force else [],
        "deleted": False,
        "revision": revision(project),
    }
    try:
        emit_event(db, organization_id=organization_id, event_type=ARCHIVE_EVENT,
                   source=SOURCE, company_id=project.company_id,
                   aggregate_type="project", aggregate_id=str(project.id),
                   payload={**result, "actor_member_id": actor_member_id})
    except Exception:  # noqa: BLE001
        pass
    return result
