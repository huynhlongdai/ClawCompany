"""v25: reconcile on attach, instead of hoping someone presses a button.

v24 built the two halves of honest recovery -- ``runtime_gap`` to report what
was missed and ``approval_backfill`` to recover the recoverable part -- and
then wired them to a manual endpoint. That is the wrong trigger. The moment
reconciliation matters is the moment a follower attaches to a session it was
not watching a second ago: on boot, on takeover, on a lease handover. A human
is not present at any of those moments.

So this module is the trigger the previous version was missing. It runs where
the attach happens and it is deliberately unable to break the stream it is
attached to: every failure is caught and reported, because a reconciliation
that kills the consumer is worse than no reconciliation at all.

v26 moves the record of each pass into the shared Redis ledger. Two things
were wrong with keeping it in process memory:

- The cooldown was per-worker, so a session bouncing between three workers
  asked the gateway three times in the window one worker would have asked
  once. A rate limit that multiplies with your worker count is not one.
- ``GET /runtime/reconcile`` answered from whichever worker took the request,
  so the history you saw depended on load balancing.

With no Redis the behaviour is exactly what it was, and the response says
``process_local: true`` rather than implying cluster coverage.
"""

from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy.orm import Session

from app.core.config import settings
from app.services import runtime_gap
from app.services.company_event_bus import emit_event
from app.services.redis_pool import pool

SOURCE = "stream_reconcile"

# One event per attach, so "why did this session suddenly gain four pending
# approvals" has an answer in the company event bus.
RECONCILE_EVENT = "openclaw.stream.reconciled"

# A claim sweep can re-attach the same session repeatedly when a lease keeps
# flapping. Asking the gateway to list approvals every few seconds for the
# same session is pointless load, and the second answer would be identical.
COOLDOWN_SECONDS = 30.0

# v26: shared ledger of the last pass per session. Kept far longer than the
# cooldown so the status endpoint has something to show, but still expiring:
# this is diagnostics, and the durable trace is the company event bus.
LEDGER_PREFIX = "clawcompany:stream-reconcile:"
LEDGER_INDEX = "clawcompany:stream-reconcile-index"
LEDGER_TTL = 3600

# Last outcome per session key, for the status endpoint and as the fallback
# when Redis is not available.
_last: dict[str, dict] = {}


def clear() -> None:
    """Forget the in-process history. Used by tests and by stop_all."""
    _last.clear()


def cluster_wide() -> bool:
    """True when the cooldown and the history are shared by every worker."""
    return pool.available


# -- shared ledger ---------------------------------------------------------


def _remember(outcome: dict) -> None:
    """Record a completed pass locally and, when possible, cluster-wide."""
    session_key = str(outcome.get("session_key") or "")
    _last[session_key] = outcome
    client = pool.client()
    if client is None or not session_key:
        return
    try:
        client.set(LEDGER_PREFIX + session_key, json.dumps(outcome, default=str), ex=LEDGER_TTL)
        client.sadd(LEDGER_INDEX, session_key)
    except Exception as exc:  # noqa: BLE001 - bookkeeping never breaks an attach
        pool.drop(str(exc))


def _recall(session_key: str) -> dict | None:
    """The last pass for a session, preferring whatever the cluster knows."""
    client = pool.client()
    if client is not None:
        try:
            raw = client.get(LEDGER_PREFIX + session_key)
            if raw:
                return json.loads(raw)
            # Nothing shared: fall through to local rather than claiming the
            # session has never been reconciled.
        except Exception as exc:  # noqa: BLE001
            pool.drop(str(exc))
        except ValueError:
            return None
    return _last.get(session_key)


def history(organization_id: int | None = None) -> list[dict]:
    """Every remembered pass, newest first, cluster-wide when Redis is up."""
    rows: dict[str, dict] = {}
    client = pool.client()
    if client is not None:
        try:
            members = list(client.smembers(LEDGER_INDEX))
            stale: list[str] = []
            raws = client.mget([LEDGER_PREFIX + key for key in members]) if members else []
            for session_key, raw in zip(members, raws):
                if not raw:
                    stale.append(session_key)
                    continue
                try:
                    rows[session_key] = json.loads(raw)
                except ValueError:
                    continue
            if stale:
                client.srem(LEDGER_INDEX, *stale)
        except Exception as exc:  # noqa: BLE001
            pool.drop(str(exc))
    # Local entries fill gaps but never overwrite a shared row: another
    # worker's newer pass is more current than our own older one.
    for session_key, row in _last.items():
        rows.setdefault(session_key, row)
    out = [row for row in rows.values()
           if organization_id is None or row.get("organization_id") == organization_id]
    return sorted(out, key=lambda r: str(r.get("at") or ""), reverse=True)


def _cooling_down(session_key: str, now: datetime) -> float | None:
    previous = _recall(session_key)
    if previous is None or not previous.get("ran"):
        return None
    try:
        at = datetime.fromisoformat(str(previous["at"]))
    except (KeyError, ValueError):
        return None
    elapsed = (now - at).total_seconds()
    return None if elapsed >= COOLDOWN_SECONDS else round(COOLDOWN_SECONDS - elapsed, 3)


async def reconcile(
    db: Session,
    *,
    organization_id: int,
    session_key: str,
    task_id: int | None = None,
    reason: str = "follow",
    force: bool = False,
    now: datetime | None = None,
) -> dict:
    """Report the gap and recover pending prompts for a session we just took.

    Order matters. The gap is measured *before* the backfill writes anything,
    because a backfilled approval carries the current timestamp and would
    otherwise make the hole we are trying to measure look closed.

    Never raises. A gateway that is down, unauthorized, or answering in a
    shape we did not expect must not stop us from following the stream -- the
    live events are worth more than the recovered ones.
    """
    now = now or datetime.utcnow()
    outcome: dict = {
        "session_key": session_key,
        "task_id": task_id,
        "organization_id": organization_id,
        "reason": reason,
        "at": now.isoformat(),
        "ran": False,
        "skipped": "",
        "gap": None,
        "backfill": None,
        "error": "",
        "owner": pool.owner,
        "shared": pool.available,
    }

    if not settings.openclaw_auto_reconcile and not force:
        outcome["skipped"] = "disabled"
        _last[session_key] = outcome
        return outcome

    remaining = None if force else _cooling_down(session_key, now)
    if remaining is not None:
        outcome["skipped"] = f"cooldown:{remaining}s"
        return outcome

    # Measured first, and recorded only when it is significant. A takeover
    # that already recorded its own gap leaves that gap as the newest event
    # for the session, so this call correctly finds nothing left to report
    # rather than writing the same hole twice.
    try:
        outcome["gap"] = runtime_gap.record(
            db, organization_id=organization_id, session_key=session_key,
            task_id=task_id, reason=reason, now=now,
        )
    except Exception as exc:  # noqa: BLE001 - diagnostics must not break attach
        outcome["error"] = f"gap: {str(exc)[:200]}"

    # Imported here, not at module scope: approval_backfill imports
    # runtime_stream, runtime_stream imports this module, and a top-level
    # import would close that circle at startup.
    from app.services import approval_backfill

    try:
        outcome["backfill"] = await approval_backfill.backfill_session(
            db, organization_id=organization_id, session_key=session_key, task_id=task_id,
        )
    except Exception as exc:  # noqa: BLE001
        outcome["error"] = (outcome["error"] + " | " if outcome["error"] else "") + \
            f"backfill: {str(exc)[:200]}"

    outcome["ran"] = True
    _remember(outcome)

    try:
        emit_event(
            db, organization_id=organization_id, event_type=RECONCILE_EVENT,
            source=SOURCE, aggregate_type="session", aggregate_id=session_key,
            payload={
                "task_id": task_id,
                "reason": reason,
                "gap_seconds": (outcome["gap"] or {}).get("gap_seconds"),
                "recovered": len((outcome["backfill"] or {}).get("recorded") or []),
                "supported": (outcome["backfill"] or {}).get("supported", False),
                "error": outcome["error"],
            },
        )
    except Exception as exc:  # noqa: BLE001
        outcome["error"] = (outcome["error"] + " | " if outcome["error"] else "") + \
            f"emit: {str(exc)[:200]}"

    return outcome
