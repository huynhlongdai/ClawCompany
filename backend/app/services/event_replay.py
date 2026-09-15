"""v34: replay company events whose trigger side effects never ran.

Background. ``company_event_bus.emit_event`` writes the event row first and
then tries to fan out: realtime publish, webhook outbox, and (for callers that
ask for it) ``trigger_engine.process_event``. The row is the durable part; the
fan-out is not. So a process that died mid-turn, or a trigger action that threw,
leaves an event sitting at ``status='pending'`` or ``status='error'`` forever.
Nothing in v16-v33 ever went back for those rows.

What this module does NOT do, stated up front because it is the honest limit:
it cannot recover a runtime event that the OpenClaw gateway produced while we
were disconnected. We hold no upstream cursor and the gateway exposes no
backfill RPC we have verified, so an event that never reached
``persist_runtime_event`` is simply gone. This replays what is already on disk.
"""

import json
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.models import CompanyEvent, RuntimeEvent
from app.services.company_event_bus import emit_event, payload_of
from app.services.trigger_engine import process_event

SOURCE = "event_replay"
REPLAY_EVENT = "company.events.replayed"
REEMIT_EVENT = "company.events.reemitted"

# Statuses we consider replayable. "processed" is deliberately absent:
# process_event() short-circuits on it anyway, and re-running a completed
# trigger would duplicate whatever the action created.
REPLAYABLE = ("pending", "error")

# An event that is only seconds old is probably still in flight in another
# worker. Replaying it would race that worker, so leave it alone.
QUIET_SECONDS = 60

# Bound on one call. Replay executes trigger actions, which can create tasks,
# messages and workflow runs, so this stays small enough to be reviewable.
MAX_REPLAY = 200

# The event_type prefix that persist_runtime_event() uses when it mirrors a
# runtime event onto the company bus.
RUNTIME_PREFIX = "runtime."
RUNTIME_SOURCE = "openclaw_runtime"


class ReplayError(RuntimeError):
    pass


def explain() -> dict:
    """Say plainly what replay covers, so nobody over-trusts it."""
    return {
        "source": SOURCE,
        "replays": "company_events rows still in " + "/".join(REPLAYABLE),
        "mechanism": "trigger_engine.process_event, the same path the live emit uses",
        "skips_processed": True,
        "quiet_seconds": QUIET_SECONDS,
        "max_per_call": MAX_REPLAY,
        "can_recover_lost_gateway_events": False,
        "why_not": (
            "We keep no upstream cursor and have verified no gateway backfill RPC. "
            "An event that never reached persist_runtime_event was never written down."
        ),
        "does_not_do": [
            "does not re-meter usage: replay never calls record_usage again",
            "does not re-deliver webhooks: that outbox has its own retry",
            "does not reorder events; replay follows occurred_at ascending",
            "does not undo a half-finished trigger action from the first attempt",
        ],
    }


def _cutoff(now: datetime | None = None) -> datetime:
    return (now or datetime.utcnow()) - timedelta(seconds=QUIET_SECONDS)


def _age_seconds(item: CompanyEvent, now: datetime) -> float:
    if item.occurred_at is None:
        return 0.0
    return max(0.0, (now - item.occurred_at).total_seconds())


def _row(item: CompanyEvent, now: datetime) -> dict:
    return {
        "event_id": item.id,
        "event_type": item.event_type,
        "source": item.source,
        "status": item.status,
        "aggregate_type": item.aggregate_type,
        "aggregate_id": item.aggregate_id,
        "correlation_id": item.correlation_id,
        "error": (item.error or "")[:300],
        "occurred_at": item.occurred_at.isoformat() if item.occurred_at else None,
        "age_seconds": round(_age_seconds(item, now), 1),
    }


def _query(db: Session, organization_id: int, statuses: tuple[str, ...], cutoff: datetime):
    return (
        db.query(CompanyEvent)
        .filter(
            CompanyEvent.organization_id == organization_id,
            CompanyEvent.status.in_(list(statuses)),
            CompanyEvent.occurred_at <= cutoff,
        )
        .order_by(CompanyEvent.occurred_at.asc(), CompanyEvent.id.asc())
    )


def _statuses(statuses) -> tuple[str, ...]:
    if not statuses:
        return REPLAYABLE
    wanted = tuple(str(s) for s in statuses)
    bad = [s for s in wanted if s not in REPLAYABLE]
    if bad:
        raise ReplayError(f"Only {sorted(REPLAYABLE)} can be replayed, got {bad}")
    return wanted


def backlog(db: Session, organization_id: int, *, limit: int = 50, statuses=None,
            company_id: int | None = None) -> dict:
    """Read-only: what is stuck, oldest first."""
    now = datetime.utcnow()
    wanted = _statuses(statuses)
    query = _query(db, organization_id, wanted, _cutoff(now))
    if company_id is not None:
        query = query.filter(CompanyEvent.company_id == company_id)
    rows = query.limit(max(1, min(int(limit), MAX_REPLAY))).all()
    total = query.count()
    by_type: dict[str, int] = {}
    for item in rows:
        by_type[item.event_type] = by_type.get(item.event_type, 0) + 1
    oldest = rows[0] if rows else None
    return {
        "organization_id": organization_id,
        "statuses": list(wanted),
        "stuck_total": total,
        "returned": len(rows),
        "by_event_type": by_type,
        "oldest_age_seconds": round(_age_seconds(oldest, now), 1) if oldest else 0.0,
        "quiet_seconds": QUIET_SECONDS,
        "rows": [_row(item, now) for item in rows],
    }


def replay(db: Session, organization_id: int, *, dry_run: bool = True, limit: int | None = None,
           statuses=None, company_id: int | None = None, actor_member_id: int | None = None) -> dict:
    """Re-run the trigger pass for stuck events.

    Each event is processed independently: one failing trigger action marks that
    event ``error`` again and the loop continues. A failure is reported, never
    swallowed and never retried inside the same call.
    """
    now = datetime.utcnow()
    wanted = _statuses(statuses)
    cap = MAX_REPLAY if limit is None else max(1, min(int(limit), MAX_REPLAY))
    query = _query(db, organization_id, wanted, _cutoff(now))
    if company_id is not None:
        query = query.filter(CompanyEvent.company_id == company_id)
    rows = query.limit(cap).all()

    planned = [_row(item, now) for item in rows]
    if dry_run:
        return {
            "dry_run": True,
            "organization_id": organization_id,
            "candidates": len(rows),
            "max_per_call": cap,
            "replayed": 0,
            "failed": [],
            "rows": planned,
        }

    replayed: list[dict] = []
    failed: list[dict] = []
    executions = 0
    for item in rows:
        try:
            outcome = process_event(db, item)
        except Exception as exc:  # noqa: BLE001 - one bad event must not stop the sweep
            db.rollback()
            failed.append({"event_id": item.id, "event_type": item.event_type, "error": str(exc)[:300]})
            continue
        ran = list(outcome.get("executions") or [])
        executions += len(ran)
        replayed.append({
            "event_id": item.id,
            "event_type": item.event_type,
            "status": item.status,
            "executions": len(ran),
            "execution_failures": len([e for e in ran if getattr(e, "status", "") == "failed"]),
            "already_processed": bool(outcome.get("already_processed")),
        })

    summary = {
        "replayed": len(replayed),
        "failed": len(failed),
        "trigger_executions": executions,
        "statuses": list(wanted),
    }
    emit_event(
        db, organization_id=organization_id, company_id=company_id, event_type=REPLAY_EVENT,
        source=SOURCE, aggregate_type="organization", aggregate_id=str(organization_id),
        actor_member_id=actor_member_id, payload=summary,
    )
    return {
        "dry_run": False,
        "organization_id": organization_id,
        "candidates": len(rows),
        "max_per_call": cap,
        "replayed": len(replayed),
        "failed": failed,
        "trigger_executions": executions,
        "rows": replayed,
    }


def _mirrored_run_ids(db: Session, organization_id: int, run_ids: list[str]) -> set[str]:
    if not run_ids:
        return set()
    rows = (
        db.query(CompanyEvent.aggregate_id)
        .filter(
            CompanyEvent.organization_id == organization_id,
            CompanyEvent.aggregate_type == "runtime_run",
            CompanyEvent.aggregate_id.in_(run_ids),
        )
        .all()
    )
    return {row[0] for row in rows}


def unmirrored_runtime_events(db: Session, organization_id: int, *, limit: int = 50) -> dict:
    """Runtime events on disk that never produced a company event.

    This is the narrow, checkable version of "lost events": the runtime row was
    written, then the emit_event call after it failed. Comparison is by run id,
    not per event, because ``aggregate_id`` on the company bus is the run id.
    """
    rows = (
        db.query(RuntimeEvent)
        .filter(RuntimeEvent.organization_id == organization_id)
        .order_by(RuntimeEvent.id.desc())
        .limit(max(1, min(int(limit) * 5, 500)))
        .all()
    )
    run_ids = sorted({r.runtime_run_id for r in rows if r.runtime_run_id})
    mirrored = _mirrored_run_ids(db, organization_id, run_ids)
    missing = [r for r in rows if r.runtime_run_id and r.runtime_run_id not in mirrored]
    return {
        "organization_id": organization_id,
        "scanned_runtime_events": len(rows),
        "distinct_runs": len(run_ids),
        "runs_with_company_event": len(mirrored),
        "unmirrored": len(missing),
        "rows": [
            {
                "runtime_event_id": r.id,
                "run_id": r.runtime_run_id,
                "event_type": r.event_type,
                "agent_id": r.agent_id,
                "task_id": r.task_id,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in missing[: max(1, int(limit))]
        ],
        "note": "Re-emitting these is safe for triggers but never re-meters usage.",
    }


def _event_json(item: RuntimeEvent) -> dict:
    try:
        value = json.loads(item.event_json or "{}")
        return value if isinstance(value, dict) else {"value": value}
    except Exception:
        return {}


def reemit_runtime_events(db: Session, organization_id: int, *, runtime_event_ids: list[int],
                          dry_run: bool = True, actor_member_id: int | None = None) -> dict:
    """Put a specific runtime event back on the company bus.

    Explicit ids only: no "re-emit everything" mode. Usage metering is skipped
    on purpose, so a replay can never inflate a customer's bill.
    """
    ids = [int(i) for i in (runtime_event_ids or [])]
    if not ids:
        raise ReplayError("Pass at least one runtime_event_id")
    if len(ids) > 50:
        raise ReplayError("Re-emit at most 50 runtime events per call")
    rows = (
        db.query(RuntimeEvent)
        .filter(RuntimeEvent.organization_id == organization_id, RuntimeEvent.id.in_(ids))
        .order_by(RuntimeEvent.id.asc())
        .all()
    )
    found = {r.id for r in rows}
    plan = [
        {"runtime_event_id": r.id, "run_id": r.runtime_run_id,
         "company_event_type": f"{RUNTIME_PREFIX}{r.event_type}"}
        for r in rows
    ]
    if dry_run:
        return {"dry_run": True, "missing_ids": sorted(set(ids) - found), "planned": plan, "emitted": 0}

    emitted = []
    for r in rows:
        item = emit_event(
            db, organization_id=organization_id, event_type=f"{RUNTIME_PREFIX}{r.event_type}",
            source=RUNTIME_SOURCE, aggregate_type="runtime_run", aggregate_id=r.runtime_run_id,
            actor_member_id=actor_member_id,
            payload={
                "runtime_event_id": r.id, "run_id": r.runtime_run_id, "agent_id": r.agent_id,
                "customer_id": r.customer_id, "task_id": r.task_id,
                "session_key": r.runtime_session_key, "event": _event_json(r),
                "replayed_by": SOURCE, "metered": False,
            },
        )
        emitted.append({"runtime_event_id": r.id, "company_event_id": item.id})
    emit_event(
        db, organization_id=organization_id, event_type=REEMIT_EVENT, source=SOURCE,
        aggregate_type="organization", aggregate_id=str(organization_id), actor_member_id=actor_member_id,
        payload={"count": len(emitted), "runtime_event_ids": [e["runtime_event_id"] for e in emitted]},
    )
    return {"dry_run": False, "missing_ids": sorted(set(ids) - found), "emitted": len(emitted), "rows": emitted}


def event_detail(db: Session, organization_id: int, event_id: int) -> dict:
    """One event, with its payload, for a human deciding whether to replay."""
    item = db.get(CompanyEvent, int(event_id))
    if not item or item.organization_id != organization_id:
        raise ReplayError(f"Company event {event_id} not found in this organization")
    now = datetime.utcnow()
    detail = _row(item, now)
    detail["payload"] = payload_of(item)
    detail["replayable"] = item.status in REPLAYABLE and _age_seconds(item, now) >= QUIET_SECONDS
    detail["processed_at"] = item.processed_at.isoformat() if item.processed_at else None
    return detail
