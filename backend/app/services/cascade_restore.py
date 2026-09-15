"""v30: put a company's board back after a cascade archive.

v29 archived a company by cascading into its departments, members and open
projects, then restored everything *except* the projects. Section 20.2 gave
the reason and it was a real one: silently reopening a whole board is a
bigger decision than un-archiving one company, so the restore listed the
project ids under ``projects_restored_separately`` and stopped.

Listing them was right. Making a human reopen twelve projects one endpoint
call at a time was not. This module does it as one reviewed batch:

* the project list comes from the company's own archive event, so it covers
  what *that* archive cancelled -- never projects archived before it or by
  somebody else;
* every project goes through v28's ``board_restore.restore_project``, so
  task-level fidelity (v29's ``task_statuses``) and the "leave tasks a human
  moved on" rule are inherited rather than re-implemented;
* one project failing does not abort the batch, and the response separates
  ``restored`` from ``skipped`` with a reason for each skip. A partial
  restore reported honestly is more useful than an all-or-nothing rollback
  that leaves the operator guessing which half landed.
"""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import Project
from app.services import board_restore
from app.services.company_event_bus import emit_event, payload_of
from app.services.entity_archive import kind_of, last_archive_event

SOURCE = "cascade_restore"
BATCH_EVENT = "company.projects.restored"


def _recorded_projects(db: Session, company, organization_id: int) -> tuple[list[int], object]:
    """Project ids the company's most recent archive cancelled."""
    event = last_archive_event(db, company, organization_id)
    payload = payload_of(event) if event else {}
    if not isinstance(payload, dict):
        payload = {}
    ids: list[int] = []
    for item in payload.get("archived_projects") or []:
        if isinstance(item, dict) and str(item.get("project_id")).isdigit():
            ids.append(int(item["project_id"]))
    return ids, event


def preview(db: Session, company, organization_id: int) -> dict:
    """What a batch restore would reopen, computed without writing."""
    if kind_of(company) != "company":
        raise HTTPException(400, detail={"error": "Batch project restore is company-scoped"})
    ids, event = _recorded_projects(db, company, organization_id)
    rows = {p.id: p for p in (db.execute(
        select(Project).where(Project.company_id == company.id, Project.id.in_(ids))
    ).scalars().all() if ids else [])}

    will: list[dict] = []
    skip: list[dict] = []
    for project_id in ids:
        project = rows.get(project_id)
        if project is None:
            skip.append({"project_id": project_id, "reason": "project no longer exists"})
            continue
        if project.status != board_restore.ARCHIVE_STATUS:
            # Somebody already reopened it. The archive record is a log of
            # what we cancelled, not a claim of ownership over the row.
            skip.append({"project_id": project_id, "name": project.name,
                         "status": project.status,
                         "reason": "already reopened by someone else"})
            continue
        plan = board_restore.restore_preview(db, project, organization_id)
        will.append({"project_id": project_id, "name": project.name,
                     "restore_to": plan["previous_status"],
                     "previous_status_known": plan["previous_status_known"],
                     "tasks_to_restore": len(plan["will_restore_tasks"]),
                     "tasks_left_alone": len(plan["will_skip_tasks"])})

    return {
        "company_id": company.id,
        "company_name": company.name,
        "company_status": company.status,
        "archive_event_id": event.id if event else None,
        "has_archive_record": event is not None,
        "recorded_projects": len(ids),
        "will_restore": will,
        "will_skip": skip,
        # A company still archived can have its board restored, but saying so
        # up front stops an operator from reading a reopened board as a
        # reopened company.
        "company_still_archived": company.status == "archived",
    }


def restore_projects(db: Session, company, organization_id: int, *,
                     actor_member_id: int | None = None) -> dict:
    plan = preview(db, company, organization_id)
    if not plan["has_archive_record"]:
        raise HTTPException(409, detail={
            "error": "No company archive record found, so there is no project list "
                     "to restore from",
            "hint": "Restore projects individually through /api/v28/projects/{id}/restore",
        })

    restored: list[dict] = []
    failed: list[dict] = []
    for entry in plan["will_restore"]:
        project = db.get(Project, entry["project_id"])
        if project is None:
            failed.append({"project_id": entry["project_id"], "reason": "project disappeared"})
            continue
        try:
            result = board_restore.restore_project(db, project, organization_id,
                                                   actor_member_id=actor_member_id)
        except HTTPException as exc:  # one bad row must not abort the batch
            db.rollback()
            detail = exc.detail
            reason = detail.get("error") if isinstance(detail, dict) else str(detail)
            failed.append({"project_id": entry["project_id"], "reason": reason})
            continue
        restored.append({"project_id": result["project_id"], "status": result["status"],
                         "previous_status_known": result["previous_status_known"],
                         "restored_tasks": len(result["restored_tasks"]),
                         "skipped_tasks": len(result["skipped_tasks"])})

    out = {
        "company_id": company.id,
        "archive_event_id": plan["archive_event_id"],
        "recorded_projects": plan["recorded_projects"],
        "restored": restored,
        "restored_count": len(restored),
        "skipped": plan["will_skip"],
        "failed": failed,
        # Partial success is the normal outcome, not an error state.
        "complete": not failed,
        "company_still_archived": company.status == "archived",
    }
    try:
        emit_event(db, organization_id=organization_id, event_type=BATCH_EVENT,
                   source=SOURCE, company_id=company.id,
                   aggregate_type="company", aggregate_id=str(company.id),
                   payload={**out, "actor_member_id": actor_member_id})
    except Exception:  # noqa: BLE001 - a failed event never becomes a 500
        pass
    return out
