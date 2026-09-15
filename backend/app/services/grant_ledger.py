"""v34: a local expiry ledger for OpenClaw standing grants.

What a standing grant is here. When an approver answers ``approved_always``,
``approval_bridge.decide`` relays ``allow-always`` to the gateway. From that
moment the *gateway host* remembers the permission; our database only remembers
that somebody chose it. v23 wrote that honestly and v24-v33 never improved it.

What this module adds. An expiry ledger: when a standing grant is minted we
write down what it covers and when we think it should stop being acceptable.
Then operators can list grants that are past their date and see exactly which
session keys to revoke.

The hard limit, stated plainly: **this cannot expire anything on the gateway.**
The OpenClaw method set we verified is ``exec.approval.resolve`` and
``exec.approval.list``; there is no revoke-grant RPC we have confirmed, and a
grant already stored on the host stays there until that host is told otherwise.
So ``expires_at`` is a review deadline plus an audit record, not enforcement.
Calling it enforcement would be a lie, and a security lie is the worst kind.

Storage. Grants live on the company event bus, not in a new table -- so v34
needs no migration. The ledger is derived by folding mint and revoke events.
"""

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.models import Approval, CompanyEvent
from app.services.company_event_bus import emit_event, payload_of

SOURCE = "grant_ledger"
MINT_EVENT = "openclaw.grant.minted"
REVOKE_EVENT = "openclaw.grant.revoked"
LEDGER_EVENTS = (MINT_EVENT, REVOKE_EVENT)

# The CLI-equivalent of --expires-in-days. 30 days is short enough that a
# forgotten grant resurfaces within a month; 0 would mean "never", which we
# refuse to allow because an unexpiring standing grant is how blast radius grows.
DEFAULT_EXPIRES_IN_DAYS = 30
MAX_EXPIRES_IN_DAYS = 365
MIN_EXPIRES_IN_DAYS = 1

MAX_SCAN = 500


class GrantError(RuntimeError):
    pass


def enforcement() -> dict:
    """The capability statement. Read this before trusting an expiry date."""
    return {
        "source": SOURCE,
        "records_expiry": True,
        "enforces_expiry_upstream": False,
        "why_not": (
            "Verified gateway methods are exec.approval.resolve and exec.approval.list. "
            "Neither revokes a standing grant, so the host keeps the permission until "
            "an operator clears it there."
        ),
        "local_effect": [
            "an expired grant is reported as expired and shows up in the review list",
            "a revoke writes an audit event naming the session key to clear by hand",
        ],
        "manual_step": "Clear the grant on the gateway host, then call revoke() to close the ledger row.",
        "default_expires_in_days": DEFAULT_EXPIRES_IN_DAYS,
        "storage": "company_events (no migration in v34)",
    }


def _days(expires_in_days: int | None) -> int:
    value = DEFAULT_EXPIRES_IN_DAYS if expires_in_days is None else int(expires_in_days)
    if value < MIN_EXPIRES_IN_DAYS or value > MAX_EXPIRES_IN_DAYS:
        raise GrantError(
            f"expires_in_days must be between {MIN_EXPIRES_IN_DAYS} and {MAX_EXPIRES_IN_DAYS}; "
            "an unexpiring standing grant is not allowed"
        )
    return value


def _grant_key(session_key: str, tool: str) -> str:
    return f"{session_key}::{tool or '*'}"


def mint(db: Session, *, organization_id: int, approval: Approval, session_key: str, request_id: str,
         tool: str = "", expires_in_days: int | None = None, actor_member_id: int | None = None,
         note: str = "") -> dict:
    """Record that a standing grant was handed out, with a review deadline.

    Called after ``approval_bridge.decide`` succeeds with ``approved_always``.
    It is deliberately a separate call: if the ledger write fails, the decision
    that already reached the gateway must not be rolled back into a lie.
    """
    days = _days(expires_in_days)
    now = datetime.utcnow()
    expires_at = now + timedelta(days=days)
    payload = {
        "grant_key": _grant_key(session_key, tool),
        "approval_id": getattr(approval, "id", None),
        "session_key": session_key,
        "request_id": request_id,
        "tool": tool or "*",
        "minted_at": now.isoformat(),
        "expires_at": expires_at.isoformat(),
        "expires_in_days": days,
        "note": (note or "")[:500],
        "enforced_upstream": False,
    }
    emit_event(
        db, organization_id=organization_id,
        company_id=getattr(approval, "company_id", None),
        event_type=MINT_EVENT, source=SOURCE, aggregate_type="openclaw_grant",
        aggregate_id=payload["grant_key"], actor_member_id=actor_member_id, payload=payload,
    )
    return payload


def _ledger_rows(db: Session, organization_id: int, *, company_id: int | None = None) -> list[CompanyEvent]:
    query = db.query(CompanyEvent).filter(
        CompanyEvent.organization_id == organization_id,
        CompanyEvent.event_type.in_(list(LEDGER_EVENTS)),
    )
    if company_id is not None:
        query = query.filter(CompanyEvent.company_id == company_id)
    return query.order_by(CompanyEvent.id.asc()).limit(MAX_SCAN).all()


def _fold(rows: list[CompanyEvent]) -> dict[str, dict]:
    """Fold mint/revoke events into current state, last write wins per key."""
    state: dict[str, dict] = {}
    for item in rows:
        payload = payload_of(item)
        key = str(payload.get("grant_key") or "")
        if not key:
            continue
        if item.event_type == MINT_EVENT:
            state[key] = dict(payload, revoked=False, revoked_at=None, revoke_note="")
        elif key in state:
            state[key].update({
                "revoked": True,
                "revoked_at": payload.get("revoked_at") or (item.occurred_at.isoformat() if item.occurred_at else None),
                "revoke_note": payload.get("note") or "",
            })
    return state


def _parse(value) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except Exception:
        return None


def _status(row: dict, now: datetime) -> tuple[str, float | None]:
    if row.get("revoked"):
        return "revoked", None
    expires_at = _parse(row.get("expires_at"))
    if expires_at is None:
        return "unknown_expiry", None
    remaining = (expires_at - now).total_seconds() / 86400.0
    return ("expired" if remaining <= 0 else "active"), round(remaining, 2)


def ledger(db: Session, organization_id: int, *, company_id: int | None = None,
           include_revoked: bool = False) -> dict:
    """Current standing grants as this system understands them."""
    now = datetime.utcnow()
    state = _fold(_ledger_rows(db, organization_id, company_id=company_id))
    rows = []
    counts = {"active": 0, "expired": 0, "revoked": 0, "unknown_expiry": 0}
    for key, row in sorted(state.items()):
        status, remaining = _status(row, now)
        counts[status] = counts.get(status, 0) + 1
        if status == "revoked" and not include_revoked:
            continue
        rows.append({
            "grant_key": key,
            "session_key": row.get("session_key"),
            "tool": row.get("tool"),
            "approval_id": row.get("approval_id"),
            "status": status,
            "minted_at": row.get("minted_at"),
            "expires_at": row.get("expires_at"),
            "days_remaining": remaining,
            "note": row.get("note") or "",
            "revoked_at": row.get("revoked_at"),
        })
    rows.sort(key=lambda r: (r["days_remaining"] is None, r["days_remaining"] if r["days_remaining"] is not None else 0))
    return {
        "organization_id": organization_id,
        "counts": counts,
        "returned": len(rows),
        "scan_limit": MAX_SCAN,
        "rows": rows,
        "enforcement": enforcement(),
    }


def due_for_review(db: Session, organization_id: int, *, within_days: int = 7,
                   company_id: int | None = None) -> dict:
    """Grants already expired, or expiring soon, with the manual step spelled out."""
    horizon = max(0, int(within_days))
    data = ledger(db, organization_id, company_id=company_id)
    due = [
        r for r in data["rows"]
        if r["status"] == "expired"
        or (r["status"] == "active" and r["days_remaining"] is not None and r["days_remaining"] <= horizon)
        or r["status"] == "unknown_expiry"
    ]
    return {
        "organization_id": organization_id,
        "within_days": horizon,
        "count": len(due),
        "rows": due,
        "session_keys_to_clear": sorted({str(r["session_key"]) for r in due if r["status"] == "expired"}),
        "manual_step": enforcement()["manual_step"],
    }


def revoke(db: Session, organization_id: int, *, grant_key: str, note: str = "",
           actor_member_id: int | None = None, confirmed_cleared_upstream: bool = False) -> dict:
    """Close a ledger row after an operator clears the grant on the host.

    ``confirmed_cleared_upstream`` is recorded, not verified. We have no way to
    read the gateway's grant store, so the flag means "a human said so".
    """
    key = str(grant_key or "").strip()
    if not key:
        raise GrantError("grant_key is required")
    state = _fold(_ledger_rows(db, organization_id))
    row = state.get(key)
    if row is None:
        raise GrantError(f"No standing grant {key!r} in this organization's ledger")
    if row.get("revoked"):
        return {"grant_key": key, "already_revoked": True, "revoked_at": row.get("revoked_at")}
    now = datetime.utcnow()
    payload = {
        "grant_key": key,
        "session_key": row.get("session_key"),
        "tool": row.get("tool"),
        "approval_id": row.get("approval_id"),
        "revoked_at": now.isoformat(),
        "note": (note or "")[:500],
        "confirmed_cleared_upstream": bool(confirmed_cleared_upstream),
        "verified_upstream": False,
    }
    emit_event(
        db, organization_id=organization_id, event_type=REVOKE_EVENT, source=SOURCE,
        aggregate_type="openclaw_grant", aggregate_id=key, actor_member_id=actor_member_id,
        payload=payload,
    )
    return {"grant_key": key, "already_revoked": False, **payload}
