"""v28: un-archiving that actually restores the work.

v27's archive cascade cancels every open task and says so, but section 18.7
was blunt about the other half: reversing it meant setting the project's
status back by hand, and the tasks it cancelled stayed cancelled, because
the only record of which ones they were lived in an event payload nobody
read back.

This module reads that payload back. The archive event is already durable,
already scoped to the organization and already carries
``cancelled_task_ids`` -- so restore needs no new table and no new column,
just the discipline to treat the event bus as a source of truth rather than
a log nobody consults.

Two deliberate limits:

* A task that somebody moved *after* the archive is left alone. The event
  says what we cancelled, not what we own forever, and overwriting a newer
  human decision to honour an older automatic one is the wrong direction.
* Archives recorded before v28 have no ``previous_status``, so the project
  returns to ``planning`` and the response says ``previous_status_known:
  false``. Guessing "active" would look tidier and be a fabrication.
"""

from __future__ import annotations

import json

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CompanyEvent, Project, Task
from app.services.board_truth import ARCHIVE_EVENT, ARCHIVE_STATUS, OPEN_STATUSES, revision
from app.services.company_event_bus import emit_event

SOURCE = "board_restore"
RESTORE_EVENT = "project.restored"
RESTORE_STATUS = "planning"  # from v18's PROJECT_STATUSES; no new vocabulary
RESTORE_TASK_STATUS = "todo"


def last_archive_event(db: Session, project: Project, organization_id: int) -> CompanyEvent | None:
    """The most recent archive of this project, within this organization.

    ``organization_id`` is part of the filter and not an afterthought: the
    aggregate id is a bare integer, so without it a caller could read another
    tenant's archive payload through their own project id.
    """
    return db.execute(
        select(CompanyEvent)
        .where(CompanyEvent.organization_id == organization_id,
               CompanyEvent.event_type == ARCHIVE_EVENT,
               CompanyEvent.aggregate_id == str(project.id))
        .order_by(CompanyEvent.id.desc())
        .limit(1)
    ).scalars().first()


def _payload(event: CompanyEvent | None) -> dict:
    if event is None:
        return {}
    try:
        value = json.loads(event.payload_json or "{}")
    except Exception:  # noqa: BLE001
        return {}
    return value if isinstance(value, dict) else {}


def _task_statuses(payload: dict) -> dict[int, str]:
    """Per-task statuses as recorded by the archive, keyed by task id.

    A malformed or pre-v29 payload yields an empty mapping, which makes
    every task fall back to ``RESTORE_TASK_STATUS`` -- the v28 behaviour --
    instead of raising on data we do not control.
    """
    raw = payload.get("task_statuses")
    if not isinstance(raw, dict):
        return {}
    out: dict[int, str] = {}
    for key, value in raw.items():
        if not str(key).isdigit() or not isinstance(value, str):
            continue
        if value in OPEN_STATUSES:
            out[int(key)] = value
    return out


def restore_preview(db: Session, project: Project, organization_id: int) -> dict:
    event = last_archive_event(db, project, organization_id)
    payload = _payload(event)
    recorded = [int(i) for i in payload.get("cancelled_task_ids", []) if str(i).isdigit()]
    rows = db.execute(select(Task).where(Task.project_id == project.id,
                                          Task.id.in_(recorded))).scalars().all() if recorded else []
    restorable = [t for t in rows if t.status == "cancelled"]
    moved_on = [t for t in rows if t.status != "cancelled"]
    previous = payload.get("previous_status")
    # v29: archives written from v29 onward record each task's prior status,
    # so a blocked task comes back blocked instead of being flattened to
    # "todo". Older archives carry ids only, and the response says which
    # tasks fall back rather than pretending the fidelity is there.
    recorded_statuses = _task_statuses(payload)
    return {
        "project_id": project.id,
        "project_status": project.status,
        "is_archived": project.status == ARCHIVE_STATUS,
        "archive_event_id": event.id if event else None,
        "archived_at": event.occurred_at.isoformat() if event and event.occurred_at else None,
        "recorded_cancelled_tasks": len(recorded),
        "will_restore_tasks": [{"task_id": t.id, "title": t.title,
                                "restore_to": recorded_statuses.get(t.id, RESTORE_TASK_STATUS),
                                "prior_status_known": t.id in recorded_statuses}
                               for t in restorable],
        "task_statuses_recorded": len(recorded_statuses),
        "will_skip_tasks": [{"task_id": t.id, "title": t.title, "status": t.status}
                             for t in moved_on],
        "missing_tasks": sorted(set(recorded) - {t.id for t in rows}),
        "previous_status": previous or RESTORE_STATUS,
        "previous_status_known": bool(previous),
        "restore_task_status": RESTORE_TASK_STATUS,
        "revision": revision(project),
    }


def restore_project(db: Session, project: Project, organization_id: int, *,
                    actor_member_id: int | None = None) -> dict:
    """Put an archived project back, including the tasks the archive cancelled."""
    if project.status != ARCHIVE_STATUS:
        raise HTTPException(409, detail={
            "error": "Project is not archived",
            "status": project.status,
            "archive_status": ARCHIVE_STATUS,
        })
    preview = restore_preview(db, project, organization_id)
    if preview["archive_event_id"] is None:
        raise HTTPException(409, detail={
            "error": "No archive record found for this project, so there is nothing "
                     "to restore from",
            "hint": "Set the status back through /api/v18/workspace/projects/{id}; "
                    "cancelled tasks must then be reopened individually",
        })

    restored: list[dict] = []
    for entry in preview["will_restore_tasks"]:
        task = db.get(Task, entry["task_id"])
        if task is not None and task.status == ARCHIVE_STATUS:
            task.status = entry["restore_to"]
            db.add(task)
            restored.append({"task_id": task.id, "status": task.status,
                             "prior_status_known": entry["prior_status_known"]})
    project.status = preview["previous_status"]
    db.add(project); db.commit(); db.refresh(project)

    result = {
        "project_id": project.id,
        "status": project.status,
        "previous_status_known": preview["previous_status_known"],
        "restored_tasks": restored,
        "restored_task_ids": [r["task_id"] for r in restored],
        "skipped_tasks": preview["will_skip_tasks"],
        "restore_task_status": RESTORE_TASK_STATUS,
        "archive_event_id": preview["archive_event_id"],
        "revision": revision(project),
    }
    try:
        emit_event(db, organization_id=organization_id, event_type=RESTORE_EVENT,
                   source=SOURCE, company_id=project.company_id,
                   aggregate_type="project", aggregate_id=str(project.id),
                   payload={**result, "actor_member_id": actor_member_id})
    except Exception:  # noqa: BLE001
        pass
    return result
