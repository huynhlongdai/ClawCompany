"""v34: make progress sync a scheduled operation instead of a manual button.

v33 shipped ``progress_autosync``: it can find projects whose stored progress
has drifted from the board and write the corrected value. But the only way to
run it was a human pressing the v33 endpoint. This module registers the sweep
as a ``RecurringOperation`` of type ``progress_sync`` so the existing scheduler
loop (``recurring_ops.due_operations`` -> ``execute_operation``) picks it up.

Design notes worth knowing before trusting this:

* We do not add a scheduler. We reuse the one already in the repo. If nothing
  in your deployment calls ``due_operations`` on a timer, registering a schedule
  changes nothing -- ``readiness()`` says so out loud.
* The cron parser is ``recurring_ops.compute_next``, a five-field subset. A
  schedule is validated here at registration time so a typo fails loudly at
  registration rather than silently at 03:00.
* Scheduled runs default to ``dry_run=False`` because a scheduled dry run would
  only write log lines. Registration therefore requires an explicit opt-in.
"""

import json
from datetime import datetime

from sqlalchemy.orm import Session

from app.models import RecurringOperation
from app.services import progress_autosync
from app.services.company_event_bus import emit_event
from app.services.recurring_ops import compute_next, create_recurring_operation

SOURCE = "progress_schedule"
OPERATION_TYPE = "progress_sync"
SCHEDULED_EVENT = "company.progress.schedule_run"

# A drift sweep is cheap but it writes. Hourly is frequent enough for a board
# that humans move a few times a day, and rare enough to keep the audit trail
# readable.
DEFAULT_SCHEDULE = "15 * * * *"
DEFAULT_TIMEZONE = "UTC"

# Per-run ceiling handed to progress_autosync.sync.
DEFAULT_LIMIT = 100


class ScheduleError(RuntimeError):
    pass


def readiness() -> dict:
    """Whether a registered schedule will actually fire.

    We can only report what is knowable from inside the API process: the
    operation type is wired, and the cron parser exists. Whether a worker is
    calling due_operations() is a deployment fact we cannot observe here, so we
    say that instead of guessing.
    """
    return {
        "source": SOURCE,
        "operation_type": OPERATION_TYPE,
        "handler_wired": True,
        "scheduler_observed": False,
        "scheduler_note": (
            "recurring_ops.due_operations must be polled by a worker/beat process. "
            "This service cannot see whether that process is running; check the "
            "last_run_at of the registered operation to confirm."
        ),
        "default_schedule": DEFAULT_SCHEDULE,
        "writes": "project.progress via board_truth.sync_progress",
        "does_not_do": [
            "does not create a scheduler; it reuses recurring_operations",
            "does not run on task status change; this is a poll, not a trigger",
            "does not touch projects progress_autosync already refuses to touch",
        ],
    }


def validate_schedule(schedule: str, timezone_name: str = DEFAULT_TIMEZONE) -> dict:
    """Parse a cron expression now so it cannot fail later unseen."""
    try:
        next_run = compute_next(schedule, timezone_name or DEFAULT_TIMEZONE)
    except Exception as exc:  # noqa: BLE001 - surfaced to the caller as 400
        raise ScheduleError(f"Invalid schedule {schedule!r}: {exc}") from exc
    return {"schedule": schedule, "timezone": timezone_name or DEFAULT_TIMEZONE,
            "next_run_at": next_run.isoformat()}


def _payload(item: RecurringOperation) -> dict:
    try:
        value = json.loads(item.payload_json or "{}")
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _row(item: RecurringOperation) -> dict:
    payload = _payload(item)
    return {
        "operation_id": item.id,
        "name": item.name,
        "company_id": item.company_id,
        "schedule": item.schedule,
        "timezone": item.timezone,
        "enabled": bool(item.enabled),
        "dry_run": bool(payload.get("dry_run", False)),
        "limit": int(payload.get("limit") or DEFAULT_LIMIT),
        "last_status": item.last_status,
        "last_run_at": item.last_run_at.isoformat() if item.last_run_at else None,
        "next_run_at": item.next_run_at.isoformat() if item.next_run_at else None,
        "never_ran": item.last_run_at is None,
    }


def schedules(db: Session, organization_id: int, *, company_id: int | None = None) -> dict:
    query = db.query(RecurringOperation).filter(
        RecurringOperation.organization_id == organization_id,
        RecurringOperation.operation_type == OPERATION_TYPE,
    )
    if company_id is not None:
        query = query.filter(RecurringOperation.company_id == company_id)
    rows = query.order_by(RecurringOperation.id.asc()).all()
    return {
        "organization_id": organization_id,
        "count": len(rows),
        "enabled": len([r for r in rows if r.enabled]),
        "stale": len([r for r in rows if r.enabled and r.last_run_at is None]),
        "rows": [_row(r) for r in rows],
        "readiness": readiness(),
    }


def register(db: Session, organization_id: int, *, company_id: int | None = None,
             schedule: str = DEFAULT_SCHEDULE, timezone_name: str = DEFAULT_TIMEZONE,
             limit: int = DEFAULT_LIMIT, dry_run_runs: bool = False, enabled: bool = True,
             name: str = "") -> dict:
    """Register (or refuse to duplicate) a progress sync schedule.

    ``dry_run_runs`` controls what the *scheduled run* does, not this call. This
    call always writes the schedule row.
    """
    validate_schedule(schedule, timezone_name)
    existing = (
        db.query(RecurringOperation)
        .filter(
            RecurringOperation.organization_id == organization_id,
            RecurringOperation.operation_type == OPERATION_TYPE,
            RecurringOperation.company_id == company_id,
        )
        .first()
    )
    if existing:
        raise ScheduleError(
            f"A progress sync schedule already exists for this scope (operation {existing.id}). "
            "Update or disable it instead of adding a second one."
        )
    item = create_recurring_operation(
        db, organization_id=organization_id, company_id=company_id,
        name=name or "Đồng bộ tiến độ dự án", schedule=schedule,
        timezone_name=timezone_name or DEFAULT_TIMEZONE, operation_type=OPERATION_TYPE,
        payload={"dry_run": bool(dry_run_runs), "limit": max(1, min(int(limit), progress_autosync.MAX_SYNC))},
        enabled=bool(enabled),
    )
    return _row(item)


def set_enabled(db: Session, organization_id: int, operation_id: int, *, enabled: bool) -> dict:
    item = db.get(RecurringOperation, int(operation_id))
    if not item or item.organization_id != organization_id or item.operation_type != OPERATION_TYPE:
        raise ScheduleError(f"Progress sync schedule {operation_id} not found in this organization")
    item.enabled = bool(enabled)
    item.next_run_at = compute_next(item.schedule, item.timezone) if enabled else None
    db.add(item)
    db.commit()
    db.refresh(item)
    return _row(item)


def run_scheduled(db: Session, item: RecurringOperation) -> dict:
    """The handler ``recurring_ops.execute_operation`` calls for this type.

    Any exception propagates: ``execute_operation`` already records
    ``last_status='failed'`` and keeps the error in its audit payload, so
    swallowing it here would only hide the failure.
    """
    payload = _payload(item)
    dry_run = bool(payload.get("dry_run", False))
    limit = max(1, min(int(payload.get("limit") or DEFAULT_LIMIT), progress_autosync.MAX_SYNC))
    result = progress_autosync.sync(
        db, organization_id=item.organization_id, company_id=item.company_id,
        dry_run=dry_run, limit=limit,
    )
    summary = {
        "operation_id": item.id,
        "company_id": item.company_id,
        "dry_run": dry_run,
        "limit": limit,
        "synced": len(result.get("synced") or []),
        "skipped": len(result.get("skipped") or []),
        "failed": len(result.get("failed") or []),
        "ran_at": datetime.utcnow().isoformat(),
    }
    emit_event(
        db, organization_id=item.organization_id, company_id=item.company_id,
        event_type=SCHEDULED_EVENT, source=SOURCE, aggregate_type="recurring_operation",
        aggregate_id=str(item.id), payload=summary,
    )
    summary["detail"] = result
    return summary
