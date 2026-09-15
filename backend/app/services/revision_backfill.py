"""v32 revision adoption service.

Migration 0013 added row_revision as a nullable column, and v30 kept it that
way on purpose: a row whose count is unknown must not claim to be version 1,
because a client may hold a timestamp token for it. What v30 lacked was any
path forward, so those rows stay on the weaker timestamp guard forever.

backfill() sets NULL counters to 1 only for rows whose updated_at is older
than a quiet period. That quiet period is what makes adoption safe rather
than merely bounded: a row written seconds ago may have a writer mid-flight
holding a timestamp token.

Two invariants:

* A row that already has a counter is never renumbered. Renumbering is
  indistinguishable from a lost update to anyone holding the old token.
* updated_at is never bumped, for the same reason: it is the fallback guard
  value, and moving it would invalidate the tokens we are preserving.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models.entities import Company, Department, Member, Project, Task
from app.services.company_event_bus import emit_event

SOURCE = "revision_backfill"
BACKFILL_EVENT = "company.revisions.backfilled"

QUIET_SECONDS = 60
START_AT = 1

MODELS = {
    "company": Company,
    "department": Department,
    "member": Member,
    "project": Project,
    "task": Task,
}


def _org_filter(kind: str, model, organization_id: int):
    """Tenant scoping, reaching through parents where needed.

    Departments, projects and tasks carry no organization_id. A backfill that
    skipped this would renumber another tenant rows, and unlike a read there
    is no way to notice afterwards.
    """
    if hasattr(model, "organization_id"):
        return model.organization_id == organization_id
    if kind in ("department", "project"):
        return model.company_id.in_(
            select(Company.id).where(Company.organization_id == organization_id)
        )
    if kind == "task":
        return model.project_id.in_(
            select(Project.id).where(
                Project.company_id.in_(
                    select(Company.id).where(Company.organization_id == organization_id)
                )
            )
        )
    return None


def preview(db: Session, organization_id: int, *, quiet_seconds: int = QUIET_SECONDS,
            now: datetime | None = None) -> dict:
    now = now or datetime.utcnow()
    cutoff = now - timedelta(seconds=max(0, int(quiet_seconds)))

    kinds = []
    timestamp_total = 0
    ready_total = 0

    for kind, model in MODELS.items():
        scope = _org_filter(kind, model, organization_id)

        def count(condition, model=model, scope=scope):
            stmt = select(func.count(model.id)).where(condition)
            if scope is not None:
                stmt = stmt.where(scope)
            return db.execute(stmt).scalar() or 0

        exact = count(model.row_revision.is_not(None))
        pending = count(model.row_revision.is_(None))
        ready = count(model.row_revision.is_(None) & (model.updated_at < cutoff))
        kinds.append({
            "kind": kind,
            "exact_guard": exact,
            "timestamp_guard": pending,
            "ready_to_adopt": ready,
            "too_recent": max(0, pending - ready),
        })
        timestamp_total += pending
        ready_total += ready

    return {
        "organization_id": organization_id,
        "kinds": kinds,
        "timestamp_guard_total": timestamp_total,
        "ready_total": ready_total,
        "quiet_seconds": int(quiet_seconds),
        "cutoff": cutoff.isoformat(),
        "start_at": START_AT,
        "counted_kinds": list(MODELS),
        "note": ("Rows written inside the quiet period are skipped: a writer may "
                 "still hold a timestamp token for them."),
    }


def backfill(db: Session, organization_id: int, *, kinds: list[str] | None = None,
             dry_run: bool = True, quiet_seconds: int = QUIET_SECONDS,
             now: datetime | None = None,
             actor_member_id: int | None = None) -> dict:
    now = now or datetime.utcnow()
    cutoff = now - timedelta(seconds=max(0, int(quiet_seconds)))
    requested = [k for k in (kinds or list(MODELS)) if k in MODELS]

    plan = preview(db, organization_id, quiet_seconds=quiet_seconds, now=now)
    plan["requested_kinds"] = requested
    plan["dry_run"] = bool(dry_run)
    plan["updated"] = {}
    plan["updated_total"] = 0

    if dry_run:
        return plan

    updated: dict[str, int] = {}
    for kind in requested:
        model = MODELS[kind]
        scope = _org_filter(kind, model, organization_id)
        stmt = (
            update(model)
            .where(model.row_revision.is_(None))
            .where(model.updated_at < cutoff)
        )
        if scope is not None:
            stmt = stmt.where(scope)
        result = db.execute(stmt.values(row_revision=START_AT))
        updated[kind] = int(result.rowcount or 0)

    total = sum(updated.values())
    emit_event(
        db,
        organization_id=organization_id,
        event_type=BACKFILL_EVENT,
        source=SOURCE,
        aggregate_type="organization",
        aggregate_id=str(organization_id),
        actor_member_id=actor_member_id,
        payload={
            "updated": updated,
            "updated_total": total,
            "start_at": START_AT,
            "quiet_seconds": int(quiet_seconds),
            "cutoff": cutoff.isoformat(),
        },
    )
    db.commit()

    plan["updated"] = updated
    plan["updated_total"] = total
    return plan
