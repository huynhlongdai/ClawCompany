"""v24: say out loud what was missed while a session had no follower.

v22 made takeover automatic, and then buried the consequence in a docs
footnote: re-subscribing does **not** replay what the agent did while nobody
was listening. The company transcript simply has a hole in it, and until now
nothing in the product said so. An operator reading the event list would see
continuous activity and reasonably assume it was complete.

This module measures the hole and records it. It does not try to fill it:
whether the gateway can replay missed events is a question about the gateway,
not about us, and inventing plausible filler would be worse than a gap.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.models import RuntimeEvent
from app.services.company_event_bus import emit_event
from app.services.runtime_events import persist_runtime_event

SOURCE = "runtime_gap"

# Event type written into the transcript itself, so the hole is visible where
# someone would actually notice it rather than only in a side table.
GAP_EVENT = "openclaw.stream.gap"

# Below this, the "gap" is just the round trip of a takeover and recording it
# would be noise. Above it, something plausibly happened unobserved.
MIN_GAP_SECONDS = 5.0


def last_event_at(db: Session, session_key: str) -> datetime | None:
    """When did we last record anything for this session?"""
    row = (
        db.query(RuntimeEvent)
        .filter(RuntimeEvent.runtime_session_key == session_key)
        .order_by(RuntimeEvent.created_at.desc(), RuntimeEvent.id.desc())
        .first()
    )
    return row.created_at if row is not None else None


def measure(db: Session, session_key: str, *, now: datetime | None = None) -> dict:
    """How long has this session been unobserved?

    A session we have never recorded anything for returns ``observed: False``
    with no seconds, because "unknown" and "zero" are very different answers
    and only one of them is true.
    """
    now = now or datetime.utcnow()
    last = last_event_at(db, session_key)
    if last is None:
        return {
            "session_key": session_key,
            "observed": False,
            "last_event_at": None,
            "gap_seconds": None,
            "significant": False,
        }
    seconds = max(0.0, (now - last).total_seconds())
    return {
        "session_key": session_key,
        "observed": True,
        "last_event_at": last.isoformat(),
        "gap_seconds": round(seconds, 3),
        "significant": seconds >= MIN_GAP_SECONDS,
    }


def record(
    db: Session,
    *,
    organization_id: int,
    session_key: str,
    task_id: int | None = None,
    reason: str = "takeover",
    now: datetime | None = None,
) -> dict | None:
    """Write the gap into the transcript and the company event bus.

    Returns ``None`` when there is nothing worth reporting, so callers can use
    the return value to decide whether to surface anything to a human.
    """
    measurement = measure(db, session_key, now=now)
    if not measurement["significant"]:
        return None

    payload = {
        "session_key": session_key,
        "task_id": task_id,
        "reason": reason,
        "gap_seconds": measurement["gap_seconds"],
        "last_event_at": measurement["last_event_at"],
        # Stated explicitly because this is the whole point of the module:
        # the events are not coming back.
        "replayed": False,
        "note": (
            "No follower was attached for this period. OpenClaw does not replay "
            "missed session events, so anything the agent did here is absent from "
            "the company transcript."
        ),
    }

    persist_runtime_event(
        db,
        organization_id=organization_id,
        run_id=session_key,
        event={"type": GAP_EVENT, "family": "gap", "state": "", "terminal": False, "raw": payload},
        task_id=task_id,
        session_key=session_key,
    )
    emit_event(
        db,
        organization_id=organization_id,
        event_type=GAP_EVENT,
        source=SOURCE,
        aggregate_type="session",
        aggregate_id=session_key,
        payload=payload,
    )
    return payload
