"""v33: stop making a human retype project progress.

v27 gave the board a *derived* progress number (``board_truth.derive``) and a
one-project ``sync_progress`` writer. What it never had was a way to run that
over a whole company, so in practice ``Project.progress`` stayed whatever a
human typed months ago while the task board moved underneath it.

This module is the missing batch pass. Three rules it will not break:

1. A project with no tasks has *no* derived progress. It is reported as
   unknown and skipped -- never silently written down to 0.
2. Drift below ``MIN_DRIFT`` is noise, not news. It is not written.
3. Every call defaults to a dry run and is bounded, exactly like the v32
   retention pass.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import Project
from app.services import board_truth
from app.services.company_event_bus import emit_event

SOURCE = "progress_autosync"
BATCH_EVENT = "company.progress.synced"

# Below this, the stored number and the board disagree by an amount nobody
# would notice, and rewriting it would only add audit noise.
MIN_DRIFT = 2

MAX_SYNC = 300

# Projects that are finished or abandoned are left alone: their progress is a
# historical record, not a live measurement.
FROZEN_STATUSES = ("done", "cancelled")


def policy() -> dict:
    return {
        "min_drift": MIN_DRIFT,
        "max_sync_per_call": MAX_SYNC,
        "dry_run_default": True,
        "frozen_statuses": list(FROZEN_STATUSES),
        "unknown_is_skipped": True,
        "source_of_truth": "board_truth.derive",
    }


def _projects(db: Session, organization_id: int, company_id: int | None) -> list[Project]:
    stmt = select(Project).where(Project.organization_id == organization_id)
    if company_id is not None:
        stmt = stmt.where(Project.company_id == company_id)
    return list(db.execute(stmt).scalars().all())


def _row(db: Session, project: Project) -> dict:
    truth = board_truth.derive(db, project)
    derived = truth.get("derived_progress")
    stored = int(project.progress or 0)
    frozen = project.status in FROZEN_STATUSES
    if derived is None:
        reason = "no tasks to measure"
    elif frozen:
        reason = "status is final"
    elif abs(int(derived) - stored) < MIN_DRIFT:
        reason = "within noise threshold"
    else:
        reason = None
    return {
        "project_id": project.id,
        "name": project.name,
        "status": project.status,
        "stored_progress": stored,
        "derived_progress": derived,
        "drift": None if derived is None else int(derived) - stored,
        "frozen": frozen,
        "eligible": reason is None,
        "skip_reason": reason,
    }


def drift_report(db: Session, *, organization_id: int, company_id: int | None = None) -> dict:
    """Where the typed number and the task board disagree."""
    rows = [_row(db, p) for p in _projects(db, organization_id, company_id)]
    eligible = [r for r in rows if r["eligible"]]
    unknown = [r for r in rows if r["derived_progress"] is None]
    eligible.sort(key=lambda r: abs(r["drift"] or 0), reverse=True)
    return {
        "company_id": company_id,
        "projects_checked": len(rows),
        "eligible_count": len(eligible),
        "unknown_count": len(unknown),
        "frozen_count": len([r for r in rows if r["frozen"]]),
        "worst_drift": (abs(eligible[0]["drift"]) if eligible else 0),
        "eligible": eligible[:MAX_SYNC],
        "unknown_project_ids": [r["project_id"] for r in unknown],
        "policy": policy(),
    }


def sync(db: Session, *, organization_id: int, company_id: int | None = None,
         dry_run: bool = True, limit: int | None = None,
         actor_member_id: int | None = None) -> dict:
    """Write the derived progress onto every project that has drifted."""
    plan = drift_report(db, organization_id=organization_id, company_id=company_id)
    cap = MAX_SYNC if limit is None else max(1, min(int(limit), MAX_SYNC))
    targets = plan["eligible"][:cap]

    if dry_run:
        return {**plan, "dry_run": True, "synced": 0,
                "would_sync_project_ids": [r["project_id"] for r in targets]}

    synced: list[dict] = []
    failed: list[dict] = []
    for row in targets:
        project = db.get(Project, row["project_id"])
        if project is None:
            continue
        try:
            # sync_progress emits its own per-project event and is the single
            # writer for this column. This pass never assigns progress itself.
            out = board_truth.sync_progress(db, project, organization_id,
                                            actor_member_id=actor_member_id)
            synced.append({"project_id": project.id,
                           "from": out.get("previous_progress", row["stored_progress"]),
                           "to": out.get("stored_progress", row["derived_progress"])})
        except Exception as exc:
            failed.append({"project_id": row["project_id"], "error": str(exc)})

    result = {**plan, "dry_run": False, "synced": len(synced),
              "synced_projects": synced, "failed": failed}
    try:
        emit_event(db, organization_id=organization_id, event_type=BATCH_EVENT,
                   source=SOURCE, company_id=company_id, aggregate_type="company",
                   aggregate_id=str(company_id or ""), actor_member_id=actor_member_id,
                   payload={"synced": len(synced), "failed": len(failed),
                            "project_ids": [x["project_id"] for x in synced],
                            "min_drift": MIN_DRIFT})
    except Exception as exc:  # pragma: no cover - the writes already landed
        result["event_error"] = str(exc)
    return result
