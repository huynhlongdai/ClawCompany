"""v35 delegation spend reconciliation.

Since v16 a delegation contract carries ``max_cost_usd``, but nothing ever
compared that ceiling to money actually burned: the field was decoration.
This module compares a contract's budget with the ``UsageEvent`` rows that can
be *attributed* to it, and is deliberately loud about how weak that
attribution is.

What is honest here:

- ``usage_events`` rows carry ``task_id`` / ``agent_id`` / ``runtime_run_id``
  but **no** ``delegation_id``. So a contract without ``task_id`` cannot be
  reconciled at all, and a task worked by several contracts over time is split
  only by timestamp window.
- The amounts come from our own metering (``record_usage``), not from a spend
  report returned by the OpenClaw runner. If metering under-records, this
  module under-reports with it.
- Nothing here blocks work. Exceeding the ceiling raises a flag for a human;
  enforcement would need a pre-flight check inside the dispatch path.
"""
import json
from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import CompanyEvent, DelegationContract, UsageEvent
from app.services.company_event_bus import emit_event

SOURCE = "delegation_spend"
OVERRUN_EVENT = "delegation.budget.overrun"
WARN_RATIO = 0.8
MAX_SCAN = 200
OPEN_STATUSES = ("proposed", "accepted", "delivered")


class SpendError(Exception):
    pass


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def attribution() -> dict:
    """How the numbers are derived, including what they cannot see."""
    return {
        "basis": "task_id + time window",
        "usage_rows_carry_delegation_id": False,
        "covers_contracts_without_task": False,
        "runner_reported_spend": False,
        "enforced_before_dispatch": False,
        "note": ("So s\u00e1nh ng\u00e2n s\u00e1ch v\u1edbi usage_events suy ra t\u1eeb task_id v\u00e0 kho\u1ea3ng th\u1eddi gian. "
                 "Kh\u00f4ng ph\u1ea3i chi ph\u00ed do runner b\u00e1o v\u1ec1, v\u00e0 kh\u00f4ng ch\u1eb7n c\u00f4ng vi\u1ec7c khi v\u01b0\u1ee3t."),
    }


def _window(item: DelegationContract) -> tuple[datetime, datetime]:
    start = item.accepted_at or item.created_at or utcnow()
    end = item.closed_at or utcnow()
    if end < start:
        end = start
    return start, end


def spend_for(db: Session, item: DelegationContract) -> dict:
    """Attributable spend for one contract.

    ``attributable`` is False when the contract has no ``task_id``: we return
    0.0 but refuse to call it a measurement.
    """
    start, end = _window(item)
    base = {"delegation_id": item.id, "window_start": start.isoformat(),
            "window_end": end.isoformat(), "rows": 0, "amount": 0.0}
    if not item.task_id:
        base.update({"attributable": False,
                     "reason": "contract kh\u00f4ng g\u1eafn task_id n\u00ean kh\u00f4ng th\u1ec3 quy chi ph\u00ed"})
        return base
    query = (db.query(func.count(UsageEvent.id), func.coalesce(func.sum(UsageEvent.amount), 0.0))
             .filter(UsageEvent.organization_id == item.organization_id,
                     UsageEvent.task_id == item.task_id,
                     UsageEvent.created_at >= start,
                     UsageEvent.created_at <= end))
    rows, amount = query.one()
    base.update({"attributable": True, "rows": int(rows or 0), "amount": round(float(amount or 0.0), 6)})
    return base


def _status(limit: float, amount: float, attributable: bool) -> str:
    if not attributable:
        return "unattributable"
    if limit <= 0:
        return "unbudgeted"
    if amount > limit:
        return "over"
    if amount >= limit * WARN_RATIO:
        return "warning"
    return "within"


def _row(db: Session, item: DelegationContract) -> dict:
    spend = spend_for(db, item)
    limit = float(item.max_cost_usd or 0.0)
    amount = float(spend["amount"])
    status = _status(limit, amount, bool(spend.get("attributable")))
    remaining = round(limit - amount, 6) if limit > 0 else None
    ratio = round(amount / limit, 4) if limit > 0 else None
    return {"delegation_id": item.id, "title": item.title, "contract_status": item.status,
            "company_id": item.company_id, "task_id": item.task_id,
            "from_member_id": item.from_member_id, "to_member_id": item.to_member_id,
            "max_cost_usd": limit, "spent_usd": amount, "remaining_usd": remaining,
            "used_ratio": ratio, "spend_status": status, "usage_rows": spend["rows"],
            "attributable": bool(spend.get("attributable")),
            "window_start": spend["window_start"], "window_end": spend["window_end"]}


def _contracts(db: Session, organization_id: int, *, statuses: tuple[str, ...],
               company_id: int | None = None, limit: int = MAX_SCAN) -> list[DelegationContract]:
    query = db.query(DelegationContract).filter(DelegationContract.organization_id == organization_id)
    if statuses:
        query = query.filter(DelegationContract.status.in_(tuple(statuses)))
    if company_id is not None:
        query = query.filter(DelegationContract.company_id == company_id)
    capped = max(1, min(int(limit or MAX_SCAN), MAX_SCAN))
    return query.order_by(DelegationContract.id.desc()).limit(capped).all()


def report(db: Session, organization_id: int, *, statuses: tuple[str, ...] = OPEN_STATUSES,
           company_id: int | None = None, limit: int = MAX_SCAN) -> dict:
    items = _contracts(db, organization_id, statuses=statuses, company_id=company_id, limit=limit)
    rows = [_row(db, item) for item in items]
    buckets: dict[str, int] = {}
    for row in rows:
        buckets[row["spend_status"]] = buckets.get(row["spend_status"], 0) + 1
    return {"scanned": len(rows), "scan_cap": MAX_SCAN, "warn_ratio": WARN_RATIO,
            "by_status": buckets, "contracts": rows, "attribution": attribution()}


def overruns(db: Session, organization_id: int, *, company_id: int | None = None,
             include_warnings: bool = False, limit: int = MAX_SCAN) -> list[dict]:
    wanted = {"over", "warning"} if include_warnings else {"over"}
    data = report(db, organization_id, company_id=company_id, limit=limit)
    return [row for row in data["contracts"] if row["spend_status"] in wanted]


def _already_flagged(db: Session, organization_id: int, delegation_id: int) -> bool:
    return db.query(CompanyEvent.id).filter(
        CompanyEvent.organization_id == organization_id,
        CompanyEvent.event_type == OVERRUN_EVENT,
        CompanyEvent.aggregate_type == "delegation_contract",
        CompanyEvent.aggregate_id == str(delegation_id)).first() is not None


def flag_overruns(db: Session, organization_id: int, *, company_id: int | None = None,
                  dry_run: bool = True, limit: int = MAX_SCAN) -> dict:
    """Raise one event per contract that burned past its ceiling.

    Flagged once and only once: a second pass finds the existing event and
    reports it as ``already_flagged`` instead of spamming the bus.
    """
    candidates = overruns(db, organization_id, company_id=company_id, limit=limit)
    flagged: list[dict] = []
    skipped: list[dict] = []
    for row in candidates:
        if _already_flagged(db, organization_id, row["delegation_id"]):
            skipped.append({"delegation_id": row["delegation_id"], "reason": "already_flagged"})
            continue
        if dry_run:
            flagged.append(row)
            continue
        emit_event(db, organization_id=organization_id, company_id=row["company_id"],
                   event_type=OVERRUN_EVENT, source=SOURCE,
                   aggregate_type="delegation_contract", aggregate_id=str(row["delegation_id"]),
                   payload={"max_cost_usd": row["max_cost_usd"], "spent_usd": row["spent_usd"],
                            "task_id": row["task_id"], "basis": attribution()["basis"],
                            "enforced": False})
        flagged.append(row)
    return {"dry_run": dry_run, "candidates": len(candidates), "flagged": flagged,
            "skipped": skipped, "enforced": False, "attribution": attribution()}


def rollup(db: Session, organization_id: int, *, company_id: int | None = None,
           limit: int = MAX_SCAN) -> dict:
    data = report(db, organization_id, statuses=(), company_id=company_id, limit=limit)
    rows = data["contracts"]
    budgeted = [row for row in rows if row["max_cost_usd"] > 0]
    measured = [row for row in rows if row["attributable"]]
    return {"contracts": len(rows), "with_budget": len(budgeted),
            "without_budget": len(rows) - len(budgeted),
            "unattributable": len(rows) - len(measured),
            "budget_total_usd": round(sum(row["max_cost_usd"] for row in budgeted), 6),
            "spent_total_usd": round(sum(row["spent_usd"] for row in measured), 6),
            "over_count": sum(1 for row in rows if row["spend_status"] == "over"),
            "warning_count": sum(1 for row in rows if row["spend_status"] == "warning"),
            "by_status": data["by_status"], "attribution": attribution()}


def explain(db: Session, organization_id: int, delegation_id: int) -> dict:
    """Per-contract detail, including the usage rows behind the number."""
    item = db.get(DelegationContract, delegation_id)
    if not item or item.organization_id != organization_id:
        raise SpendError("Delegation contract not found in this organization")
    row = _row(db, item)
    detail: list[dict] = []
    if item.task_id:
        start, end = _window(item)
        events = (db.query(UsageEvent)
                  .filter(UsageEvent.organization_id == organization_id,
                          UsageEvent.task_id == item.task_id,
                          UsageEvent.created_at >= start,
                          UsageEvent.created_at <= end)
                  .order_by(UsageEvent.id.desc()).limit(50).all())
        for event in events:
            try:
                meta = json.loads(event.metadata_json or "{}")
            except (TypeError, ValueError):
                meta = {}
            detail.append({"usage_event_id": event.id, "event_type": event.event_type,
                           "quantity": float(event.quantity or 0), "unit": event.unit,
                           "amount": float(event.amount or 0), "agent_id": event.agent_id,
                           "runtime_run_id": event.runtime_run_id,
                           "created_at": event.created_at.isoformat() if event.created_at else None,
                           "metadata": meta})
    return {"contract": row, "usage_events": detail, "usage_events_capped_at": 50,
            "attribution": attribution()}
