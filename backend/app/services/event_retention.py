"""v32: retention for company_events.

Nothing has ever deleted a row from company_events. Every guarded write,
every stream gap, every reconcile has been appended since v10. v31 made it
worse by storing two copies of every changed column. An event store nothing
prunes is a disk-full incident with a long fuse.

Three tiers, chosen to be explainable rather than clever:

  evidence (400d) - guarded writes, conflicts, archive/restore records
  default   (90d) - ordinary lifecycle events
  runtime   (14d) - stream gaps, reconciles, session churn (highest volume)

Two safety properties matter more than the numbers:

* Reachability, not only age. board_restore and entity_archive *read archive
  events back* to undo an operation. If a row is still archived, its record
  is retained regardless of age. Age alone would quietly expire the undo.
* Fail closed. If the "which rows are still archived" query fails,
  protected_aggregates raises instead of returning an empty set, because an
  empty set would authorise deleting exactly the records we must keep.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.entities import Company, Department, Member, Project
from app.models.v10 import CompanyEvent
from app.services.company_event_bus import emit_event

SOURCE = "event_retention"
PRUNE_EVENT = "company.events.pruned"

EVIDENCE_DAYS = 400
DEFAULT_DAYS = 90
RUNTIME_DAYS = 14

# A single call is bounded so a prune can never become an unbounded DELETE
# holding a lock on the busiest table in the system.
MAX_DELETE = 5000

# Records that answer "who changed this, and what was it before" or that an
# undo path reads back. entity_archive and board_restore both parse these.
EVIDENCE_TYPES = (
    "board.write.guarded",
    "board.write.conflict",
    "company.archived",
    "company.restored",
    "department.archived",
    "department.restored",
    "member.archived",
    "member.restored",
    "project.archived",
    "project.restored",
    "company.projects.restored",
)

# High-volume machine chatter. Useful for a few days of debugging, not for a
# year of audit.
RUNTIME_PREFIXES = ("openclaw.", "runtime.", "session.", "stream.")


class RetentionError(RuntimeError):
    """Raised when a prune cannot prove what is safe to delete."""


def tier_of(event_type: str) -> str:
    if event_type in EVIDENCE_TYPES:
        return "evidence"
    if event_type.startswith(RUNTIME_PREFIXES):
        return "runtime"
    return "default"


def tier_days(tier: str) -> int:
    return {
        "evidence": EVIDENCE_DAYS,
        "default": DEFAULT_DAYS,
        "runtime": RUNTIME_DAYS,
    }.get(tier, DEFAULT_DAYS)


def policy() -> dict:
    return {
        "tiers": [
            {"tier": "evidence", "days": EVIDENCE_DAYS,
             "note": "guarded writes, conflicts, archive/restore records"},
            {"tier": "default", "days": DEFAULT_DAYS,
             "note": "ordinary lifecycle events"},
            {"tier": "runtime", "days": RUNTIME_DAYS,
             "note": "stream gaps, reconciles, session churn"},
        ],
        "evidence_types": list(EVIDENCE_TYPES),
        "runtime_prefixes": list(RUNTIME_PREFIXES),
        "max_delete_per_call": MAX_DELETE,
        "dry_run_default": True,
        "protection": "archive records are kept while their row is still archived",
    }


def _cutoffs(now: datetime) -> dict[str, datetime]:
    return {
        "evidence": now - timedelta(days=EVIDENCE_DAYS),
        "default": now - timedelta(days=DEFAULT_DAYS),
        "runtime": now - timedelta(days=RUNTIME_DAYS),
    }


def protected_aggregates(db: Session, organization_id: int) -> set[tuple[str, str]]:
    """(aggregate_type, aggregate_id) pairs whose undo record must survive.

    Fails closed: a query error raises rather than returning an empty set.
    """
    protected: set[tuple[str, str]] = set()
    plans = (
        ("company", Company, Company.status == "archived", None),
        ("member", Member, Member.status == "offboarded", Member.organization_id),
        ("department", Department, Department.status == "archived", None),
        ("project", Project, Project.status == "cancelled", None),
    )
    try:
        for kind, model, condition, org_column in plans:
            stmt = select(model.id).where(condition)
            if org_column is not None:
                stmt = stmt.where(org_column == organization_id)
            elif hasattr(model, "organization_id"):
                stmt = stmt.where(model.organization_id == organization_id)
            for row_id in db.execute(stmt).scalars().all():
                protected.add((kind, str(row_id)))
    except Exception as exc:  # noqa: BLE001
        raise RetentionError(
            "Could not determine which rows are still archived; refusing to prune"
        ) from exc
    return protected


def _candidate_query(organization_id: int, cutoffs: dict[str, datetime]):
    """Events past the cutoff of their own tier, oldest first."""
    return (
        select(CompanyEvent)
        .where(CompanyEvent.organization_id == organization_id)
        .where(CompanyEvent.occurred_at < cutoffs["default"])
        .order_by(CompanyEvent.occurred_at.asc())
    )


def preview(db: Session, organization_id: int, *, limit: int = MAX_DELETE,
            now: datetime | None = None) -> dict:
    now = now or datetime.utcnow()
    cutoffs = _cutoffs(now)
    protected = protected_aggregates(db, organization_id)
    limit = max(1, min(int(limit), MAX_DELETE))

    total = db.execute(
        select(func.count(CompanyEvent.id))
        .where(CompanyEvent.organization_id == organization_id)
    ).scalar() or 0

    # The evidence cutoff is the oldest, so scanning from the default cutoff
    # covers every tier; each row is then judged against its own tier.
    rows = db.execute(_candidate_query(organization_id, cutoffs)).scalars().all()

    deletable: list[CompanyEvent] = []
    by_tier: dict[str, int] = {"evidence": 0, "default": 0, "runtime": 0}
    by_type: dict[str, int] = {}
    kept_protected = 0

    for row in rows:
        tier = tier_of(row.event_type or "")
        if (row.occurred_at or now) >= cutoffs[tier]:
            continue
        key = (row.aggregate_type or "", str(row.aggregate_id or ""))
        if tier == "evidence" and key in protected:
            kept_protected += 1
            continue
        deletable.append(row)
        by_tier[tier] = by_tier.get(tier, 0) + 1
        by_type[row.event_type or ""] = by_type.get(row.event_type or "", 0) + 1
        if len(deletable) >= limit:
            break

    return {
        "organization_id": organization_id,
        "total_events": total,
        "scanned": len(rows),
        "deletable": len(deletable),
        "event_ids": [row.id for row in deletable],
        "by_tier": by_tier,
        "by_event_type": dict(sorted(by_type.items(), key=lambda kv: -kv[1])),
        "kept_protected": kept_protected,
        "protected_aggregates": len(protected),
        "oldest_deletable": (deletable[0].occurred_at.isoformat()
                             if deletable and deletable[0].occurred_at else ""),
        "newest_deletable": (deletable[-1].occurred_at.isoformat()
                             if deletable and deletable[-1].occurred_at else ""),
        "cutoffs": {tier: value.isoformat() for tier, value in cutoffs.items()},
        "limit": limit,
        "has_more": len(deletable) >= limit,
        "policy": policy(),
    }


def prune(db: Session, organization_id: int, *, dry_run: bool = True,
          limit: int = MAX_DELETE, now: datetime | None = None,
          actor_member_id: int | None = None) -> dict:
    """Delete expired events. dry_run defaults to true on purpose."""
    plan = preview(db, organization_id, limit=limit, now=now)
    ids = list(plan["event_ids"])
    plan["dry_run"] = bool(dry_run)
    plan["deleted"] = 0

    if dry_run or not ids:
        # Keep the id list out of the response once it is large; the caller
        # only needs counts to decide.
        plan["sample_event_ids"] = ids[:20]
        plan.pop("event_ids", None)
        return plan

    deleted = 0
    for row in db.execute(
        select(CompanyEvent).where(CompanyEvent.id.in_(ids))
    ).scalars().all():
        db.delete(row)
        deleted += 1

    # Emitted before the commit so the prune and its record land together.
    # Counts only: listing deleted ids would recreate the volume just removed.
    emit_event(
        db,
        organization_id=organization_id,
        event_type=PRUNE_EVENT,
        source=SOURCE,
        aggregate_type="organization",
        aggregate_id=str(organization_id),
        actor_member_id=actor_member_id,
        payload={
            "deleted": deleted,
            "by_tier": plan["by_tier"],
            "kept_protected": plan["kept_protected"],
            "cutoffs": plan["cutoffs"],
        },
    )
    db.commit()

    plan["deleted"] = deleted
    plan["sample_event_ids"] = ids[:20]
    plan.pop("event_ids", None)
    return plan
