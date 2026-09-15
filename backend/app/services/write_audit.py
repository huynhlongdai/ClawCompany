"""v29: an audit feed that somebody actually reads.

Section 19.6 wrote down an uncomfortable fact about v28: the guard emitted
``board.write.guarded`` on every protected write and ``board.write.conflict``
on every lost race, and *no screen consumed either one*. An audit trail that
nothing reads is a log file with extra steps -- it cannot be used to answer
"who changed this", which is the only question it exists for.

This module turns those events into rows. It adds no table and no column:
``CompanyEvent`` already carries actor, aggregate, payload and timestamp,
scoped to the organization. All that was missing was a reader.

What it deliberately does not do:

* It does not reconstruct old field values for events that never recorded
  them. ``board.write.guarded`` carries the fields that changed, not their
  previous contents, so the row says which fields moved and stops there.
* It does not merge the runtime stream events into one story. Gap and
  reconcile events are included because they explain *why* a write looks
  strange, but they stay labelled as runtime, not as human edits.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.v10 import CompanyEvent
from app.services.company_event_bus import payload_of

SOURCE = "write_audit"

# The write half of the cockpit: guarded updates, lost races, archives and
# restores across projects (v27/v28) and the org tree (v29).
WRITE_EVENTS = (
    "board.write.guarded",
    "board.write.conflict",
    "project.archived",
    "project.restored",
    "project.progress.derived",
    "company.archived",
    "company.restored",
    "department.archived",
    "department.restored",
    "member.archived",
    "member.restored",
)

# Runtime events that explain an odd-looking write rather than being one.
RUNTIME_EVENTS = (
    "openclaw.stream.gap",
    "openclaw.stream.reconciled",
)

CATEGORIES = {
    "board.write.guarded": "write",
    "board.write.conflict": "conflict",
    "project.archived": "archive",
    "project.restored": "restore",
    "project.progress.derived": "derived",
    "company.archived": "archive",
    "company.restored": "restore",
    "department.archived": "archive",
    "department.restored": "restore",
    "member.archived": "archive",
    "member.restored": "restore",
    "openclaw.stream.gap": "runtime",
    "openclaw.stream.reconciled": "runtime",
}

DEFAULT_LIMIT = 50
MAX_LIMIT = 200


def event_types(*, include_runtime: bool = False) -> tuple[str, ...]:
    return WRITE_EVENTS + RUNTIME_EVENTS if include_runtime else WRITE_EVENTS


def _fields(payload: dict) -> list[str]:
    raw = payload.get("fields")
    if isinstance(raw, dict):
        return sorted(str(k) for k in raw)
    if isinstance(raw, (list, tuple)):
        return [str(item) for item in raw]
    return []


def _summary(event_type: str, payload: dict) -> str:
    """One line a human can read without opening the payload."""
    entity = payload.get("entity") or payload.get("kind") or ""
    if event_type == "board.write.guarded":
        changes = payload.get("changes")
        if isinstance(changes, dict) and changes:
            from app.services.field_diff import describe
            label = entity or "row"
            return f"Guarded update on {label}: {describe(changes)}"
        fields = _fields(payload)
        what = ", ".join(fields) if fields else "no fields"
        return f"Guarded update on {entity or 'row'}: {what}"
    if event_type == "board.write.conflict":
        return ("Write rejected: the row changed first "
                f"(expected {payload.get('expected_revision') or 'unknown'})")
    if event_type == "project.archived":
        cancelled = payload.get("cancelled_task_ids") or []
        return f"Project archived, {len(cancelled)} open task(s) cancelled"
    if event_type == "project.restored":
        restored = payload.get("restored_task_ids") or payload.get("restored_tasks") or []
        return f"Project restored, {len(restored)} task(s) reopened"
    if event_type == "project.progress.derived":
        return f"Progress recomputed from the board to {payload.get('progress')}%"
    if event_type.endswith(".archived"):
        counts = payload.get("archived_members") or []
        return f"{(entity or event_type.split('.')[0]).title()} archived, {len(counts)} member(s) offboarded"
    if event_type.endswith(".restored"):
        counts = payload.get("restored_members") or []
        return f"{(entity or event_type.split('.')[0]).title()} restored, {len(counts)} member(s) reinstated"
    if event_type == "openclaw.stream.gap":
        return f"Runtime stream gap of {payload.get('gap_seconds') or '?'}s"
    if event_type == "openclaw.stream.reconciled":
        return "Runtime stream reconciled after a gap"
    return event_type


def row_of(event: CompanyEvent) -> dict:
    payload = payload_of(event)
    if not isinstance(payload, dict):
        payload = {}
    return {
        "id": event.id,
        "event_type": event.event_type,
        "category": CATEGORIES.get(event.event_type, "other"),
        "source": event.source or "",
        "entity_type": event.aggregate_type or (payload.get("entity") or payload.get("kind") or ""),
        "entity_id": event.aggregate_id or "",
        "company_id": event.company_id,
        "actor_member_id": event.actor_member_id or payload.get("actor_member_id"),
        "fields": _fields(payload),
        # v31: present only for guarded writes made after the diff landed.
        # Absent is meaningful and is not the same as "nothing changed".
        "changes": payload.get("changes") if isinstance(payload.get("changes"), dict) else None,
        # v31 bugfix: an empty ``changes`` dict is a write whose values did
        # not move, not a write with recoverable before-values. Reporting it
        # as has_values made the reader show an empty history and claim it
        # was complete.
        "has_values": bool(isinstance(payload.get("changes"), dict) and payload.get("changes")),
        "applied": payload.get("applied", True) is not False,
        "revision": payload.get("revision") or "",
        "previous_revision": payload.get("previous_revision") or payload.get("current_revision") or "",
        "summary": _summary(event.event_type, payload),
        "occurred_at": event.occurred_at.isoformat() if event.occurred_at else "",
        "correlation_id": event.correlation_id or "",
    }


def feed(db: Session, organization_id: int, *, company_id: int | None = None,
         entity_type: str | None = None, entity_id: str | None = None,
         categories: tuple[str, ...] | None = None,
         include_runtime: bool = False, since_hours: int | None = None,
         limit: int = DEFAULT_LIMIT, cursor: int | None = None) -> dict:
    """Newest-first audit rows for the write half of the workspace.

    v30 adds the cursor v29 admitted was missing. ``cursor`` is the id of
    the last event *scanned* by the previous page, not the last row
    returned: category filtering happens in Python, so paging on the last
    returned row would skip every event the filter dropped at the tail of
    the page. Event ids are monotonic and events are never rewritten, so
    an id cursor is stable in a way an offset is not.
    """
    limit = max(1, min(int(limit or DEFAULT_LIMIT), MAX_LIMIT))
    types = event_types(include_runtime=include_runtime)
    stmt = select(CompanyEvent).where(CompanyEvent.organization_id == organization_id,
                                      CompanyEvent.event_type.in_(types))
    if cursor is not None:
        try:
            stmt = stmt.where(CompanyEvent.id < int(cursor))
        except (TypeError, ValueError):
            # A malformed cursor returns the first page instead of an error:
            # paging is a convenience, and a broken bookmark should not turn
            # an audit screen into a 400.
            cursor = None
    if company_id is not None:
        stmt = stmt.where(CompanyEvent.company_id == company_id)
    if entity_type:
        stmt = stmt.where(CompanyEvent.aggregate_type == entity_type)
    if entity_id:
        stmt = stmt.where(CompanyEvent.aggregate_id == str(entity_id))
    if since_hours:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=int(since_hours))
        stmt = stmt.where(CompanyEvent.occurred_at >= cutoff)
    # Fetch a window wider than the page so category filtering, which the
    # column cannot express, still fills a page when it can.
    fetch = limit * 4 if categories else limit
    events = db.execute(stmt.order_by(CompanyEvent.id.desc()).limit(fetch)).scalars().all()

    rows = [row_of(event) for event in events]
    if categories:
        wanted = tuple(categories)
        rows = [row for row in rows if row["category"] in wanted]
    trimmed = len(rows) > limit
    rows = rows[:limit]

    # The cursor advances past everything scanned, so the next page cannot
    # re-serve an event this page filtered out.
    if trimmed:
        scanned_to = rows[-1]["id"] if rows else (events[-1].id if events else None)
    else:
        scanned_to = events[-1].id if events else None
    more = trimmed or (len(events) >= fetch)
    next_cursor = scanned_to if (more and scanned_to is not None) else None

    tallies: dict[str, int] = {}
    for row in rows:
        tallies[row["category"]] = tallies.get(row["category"], 0) + 1
    return {
        "organization_id": organization_id,
        "rows": rows,
        "returned": len(rows),
        "limit": limit,
        "counts_by_category": tallies,
        "conflicts": tallies.get("conflict", 0),
        "event_types": list(types),
        "include_runtime": include_runtime,
        # Honest about the ceiling: this is a page of the newest events, not
        # a complete history, and nothing here prunes or rewrites events.
        "truncated": len(events) >= fetch,
        "cursor": cursor,
        "next_cursor": next_cursor,
        "has_more": next_cursor is not None,
    }


def entity_history(db: Session, organization_id: int, entity_type: str, entity_id: str,
                   *, limit: int = DEFAULT_LIMIT, cursor: int | None = None) -> dict:
    """The audit trail for one row, oldest-last, same shape as ``feed``."""
    return feed(db, organization_id, entity_type=entity_type, entity_id=entity_id,
                include_runtime=False, limit=limit, cursor=cursor)
