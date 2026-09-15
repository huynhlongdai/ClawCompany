"""v29: archiving the org tree, with the cascade written down before it runs.

v27 archived a project. Section 19.6 left the rest of the tree open, and the
reason was never laziness: a company holds departments, departments hold
members, members hold agents, and an agent can be inside a live OpenClaw
session right now. Archiving downward without looking at that leaf is how
you get an agent running with nobody on our side listening -- the exact
orphan state v22 through v26 exist to prevent.

So this module does three things and refuses to do a fourth:

1. ``cascade_preview`` walks the subtree and returns the *whole* blast
   radius, including which runtime sessions are live, before anything is
   written.
2. ``archive_entity`` blocks on live sessions unless ``force`` is passed,
   and when forced it reports what it left running instead of implying it
   stopped it. We cannot abort an agent from here; that is
   ``/api/v19/tasks/{id}/abort``.
3. ``restore_entity`` reads the archive event back and returns each row to
   the status it actually had, the same discipline v28 gave projects.

The fourth thing: nothing is deleted, and no new status word is invented.
Companies use ``archived`` from ``workspace_ops.COMPANY_STATUSES``, members
use ``offboarded`` from ``MEMBER_STATUSES``, and departments -- which have
no status column at all -- are locked by ``access_level`` instead of
gaining a column and a migration. That is a documented compromise, not an
oversight: see docs/architecture-v29.md.
"""

from __future__ import annotations

import json

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Agent, Company, Department, Member, Project, Task
from app.models.v10 import CompanyEvent
from app.services.board_truth import ARCHIVE_STATUS as PROJECT_ARCHIVE_STATUS
from app.services.board_truth import archive_project, live_attachments, revision
from app.services.company_event_bus import emit_event, payload_of

SOURCE = "entity_archive"

# Existing vocabularies only. See workspace_ops.COMPANY_STATUSES /
# MEMBER_STATUSES / ACCESS_LEVELS -- if a word is not already understood by
# the rest of the system, an archived row becomes a hole in every report.
COMPANY_ARCHIVED = "archived"
COMPANY_DEFAULT_RESTORE = "active"
MEMBER_ARCHIVED = "offboarded"
MEMBER_DEFAULT_RESTORE = "active"
DEPARTMENT_ARCHIVED = "archived"
DEPARTMENT_DEFAULT_RESTORE = "active"
DEPARTMENT_STATUS_WORDS = ("active", "paused", "archived")

# v29 had no status column, so it locked departments with access_level=
# "confidential". That conflated "put away" with "secret", and un-archiving
# handed out a permission level the department may never have had. v32
# archives on status and never touches access_level -- but records written by
# v29 still have to restore, so both vocabularies stay readable here. They are
# disjoint, which is what makes the recorded word self-describing.
DEPARTMENT_LOCKED = "confidential"
LEGACY_ACCESS_WORDS = ("org_public", "restricted", "confidential")
LEGACY_DEFAULT_RESTORE = "restricted"


def _dept_restore(recorded) -> dict:
    """Interpret whatever a department archive record put in "previous".

    Returns the status to restore, the access_level to restore (None when the
    record never touched permission), which era wrote it, and whether the
    value was recognised at all. An unknown value is flagged rather than
    guessed silently: a wrong guess here hands out or removes access.
    """
    if isinstance(recorded, str) and recorded in DEPARTMENT_STATUS_WORDS:
        return {"status": recorded, "access_level": None, "era": "v32", "known": True}
    if isinstance(recorded, str) and recorded in LEGACY_ACCESS_WORDS:
        return {"status": DEPARTMENT_DEFAULT_RESTORE, "access_level": recorded,
                "era": "v29", "known": True}
    return {"status": DEPARTMENT_DEFAULT_RESTORE, "access_level": None,
            "era": "unknown", "known": False}

KINDS = ("company", "department", "member")

ARCHIVE_EVENTS = {
    "company": "company.archived",
    "department": "department.archived",
    "member": "member.archived",
}
RESTORE_EVENTS = {
    "company": "company.restored",
    "department": "department.restored",
    "member": "member.restored",
}


class CascadeError(ValueError):
    """Raised for an entity kind this module does not archive."""


def kind_of(entity) -> str:
    # Test seam: stand-in rows declare their kind, so the decision logic can
    # be pinned without a live ORM. Real rows never carry this attribute.
    declared = getattr(entity, "__entity_kind__", None)
    if declared in KINDS:
        return declared
    if isinstance(entity, Company):
        return "company"
    if isinstance(entity, Department):
        return "department"
    if isinstance(entity, Member):
        return "member"
    raise CascadeError(f"entity_archive does not handle {type(entity).__name__}")


def _members_of(db: Session, kind: str, entity) -> list:
    if kind == "member":
        return [entity]
    if kind == "department":
        return list(db.execute(select(Member).where(Member.department_id == entity.id)).scalars().all())
    return list(db.execute(select(Member).where(Member.company_id == entity.id)).scalars().all())


def _departments_of(db: Session, kind: str, entity) -> list:
    if kind == "department":
        return [entity]
    if kind == "company":
        return list(db.execute(select(Department).where(Department.company_id == entity.id)).scalars().all())
    return []


def _agents_of(db: Session, members: list) -> list:
    ids = [m.id for m in members]
    if not ids:
        return []
    return list(db.execute(select(Agent).where(Agent.member_id.in_(ids))).scalars().all())


def _projects_of(db: Session, kind: str, entity) -> list:
    """Projects hang off the company, never off a department or a member.

    A member who owns projects is therefore *not* a reason to cascade into
    them -- ownership is reassigned, not archived. Only a company archive
    reaches the board.
    """
    if kind != "company":
        return []
    return list(db.execute(select(Project).where(Project.company_id == entity.id)).scalars().all())


def _live_sessions(db: Session, kind: str, entity, members: list, projects: list) -> list[dict]:
    if kind == "company":
        out: list[dict] = []
        for project in projects:
            for item in live_attachments(db, project.id):
                out.append({**item, "project_id": project.id, "project": project.name})
        return out
    member_ids = [m.id for m in members]
    if not member_ids:
        return []
    rows = db.execute(
        select(Task).where(Task.assignee_member_id.in_(member_ids),
                           Task.status == "in_progress",
                           Task.runtime_session_key.isnot(None))
    ).scalars().all()
    return [{"task_id": t.id, "title": t.title, "session_key": t.runtime_session_key or "",
             "project_id": t.project_id, "assignee_member_id": t.assignee_member_id} for t in rows]


def _already_archived(kind: str, entity) -> bool:
    if kind == "company":
        return entity.status == COMPANY_ARCHIVED
    if kind == "member":
        return entity.status == MEMBER_ARCHIVED
    # Both eras count as archived: v32 sets status, v29 set access_level.
    return (getattr(entity, "status", None) == DEPARTMENT_ARCHIVED
            or getattr(entity, "access_level", None) == DEPARTMENT_LOCKED)


def _subtree(db: Session, entity) -> dict:
    kind = kind_of(entity)
    departments = _departments_of(db, kind, entity)
    members = _members_of(db, kind, entity)
    agents = _agents_of(db, members)
    projects = _projects_of(db, kind, entity)
    return {"kind": kind, "departments": departments, "members": members,
            "agents": agents, "projects": projects}


def cascade_preview(db: Session, entity, organization_id: int | None = None) -> dict:
    """What an archive would touch, computed before anything is written."""
    tree = _subtree(db, entity)
    kind = tree["kind"]
    live = _live_sessions(db, kind, entity, tree["members"], tree["projects"])
    open_projects = [p for p in tree["projects"] if p.status != PROJECT_ARCHIVE_STATUS]
    affected_members = [m for m in tree["members"] if m.status != MEMBER_ARCHIVED]
    return {
        "kind": kind,
        "id": entity.id,
        "name": entity.name,
        "already_archived": _already_archived(kind, entity),
        "will_archive": {
            "departments": [{"id": d.id, "name": d.name, "access_level": d.access_level}
                            for d in tree["departments"] if kind == "company"],
            "members": [{"id": m.id, "name": m.name, "status": m.status,
                         "member_type": m.member_type} for m in affected_members],
            "projects": [{"id": p.id, "name": p.name, "status": p.status} for p in open_projects],
        },
        "counts": {
            "departments": len(tree["departments"]) if kind == "company" else 0,
            "members": len(affected_members),
            "agents": len(tree["agents"]),
            "projects": len(open_projects),
        },
        # Agent rows are never touched. Their lifecycle belongs to the
        # runtime, and flipping it from here would lie to OpenClaw about
        # what we control.
        "agents_left_registered": [{"id": a.id, "member_id": a.member_id,
                                    "runtime_agent_id": a.runtime_agent_id,
                                    "lifecycle": a.lifecycle} for a in tree["agents"]],
        "live_runtime_sessions": live,
        "blocked": bool(live),
        "blocked_reason": "members in this subtree own tasks attached to live OpenClaw sessions" if live else "",
        "destructive": False,
        "revision": revision(entity),
    }


def _apply_archive(db: Session, kind: str, entity, tree: dict, organization_id: int,
                   *, force: bool, actor_member_id: int | None) -> dict:
    previous: dict = {"self": None, "members": {}, "departments": {}}
    archived_projects: list[dict] = []

    if kind == "company":
        for project in tree["projects"]:
            if project.status == PROJECT_ARCHIVE_STATUS:
                continue
            result = archive_project(db, project, organization_id, force=True,
                                     actor_member_id=actor_member_id)
            archived_projects.append({"project_id": project.id, "previous_status": result["previous_status"],
                                      "cancelled_task_ids": result["cancelled_task_ids"]})
        for dept in tree["departments"]:
            previous["departments"][str(dept.id)] = dept.status
            dept.status = DEPARTMENT_ARCHIVED
            db.add(dept)
    elif kind == "department":
        previous["self"] = entity.status
        entity.status = DEPARTMENT_ARCHIVED
        db.add(entity)

    for member in tree["members"]:
        if member.status == MEMBER_ARCHIVED:
            continue
        previous["members"][str(member.id)] = member.status
        member.status = MEMBER_ARCHIVED
        db.add(member)

    if kind == "company":
        previous["self"] = entity.status
        entity.status = COMPANY_ARCHIVED
        db.add(entity)
    elif kind == "member":
        # The member row is in tree["members"], so its prior status is
        # already recorded above; "self" mirrors it for symmetry.
        previous["self"] = previous["members"].get(str(entity.id), entity.status)

    db.commit()
    db.refresh(entity)
    return {"previous": previous, "archived_projects": archived_projects}


def archive_entity(db: Session, entity, organization_id: int, *, force: bool = False,
                   actor_member_id: int | None = None) -> dict:
    kind = kind_of(entity)
    preview = cascade_preview(db, entity, organization_id)
    if preview["already_archived"]:
        raise HTTPException(409, detail={
            "error": f"This {kind} is already archived",
            "kind": kind, "id": entity.id,
        })
    if preview["blocked"] and not force:
        raise HTTPException(409, detail={
            "error": f"Archiving this {kind} would orphan live OpenClaw sessions",
            "live_runtime_sessions": preview["live_runtime_sessions"],
            "hint": "Abort them via /api/v19/tasks/{id}/abort, or pass force=true to "
                    "archive and leave those sessions running",
        })

    tree = _subtree(db, entity)
    applied = _apply_archive(db, kind, entity, tree, organization_id,
                             force=force, actor_member_id=actor_member_id)

    result = {
        "kind": kind,
        "id": entity.id,
        "name": entity.name,
        "archived": True,
        "previous": applied["previous"],
        "archived_members": sorted(int(k) for k in applied["previous"]["members"]),
        "archived_departments": sorted(int(k) for k in applied["previous"]["departments"]),
        "archived_projects": applied["archived_projects"],
        "agents_left_registered": preview["agents_left_registered"],
        "forced": bool(force and preview["blocked"]),
        "left_running": preview["live_runtime_sessions"] if force else [],
        "deleted": False,
        "revision": revision(entity),
    }
    try:
        emit_event(db, organization_id=organization_id, event_type=ARCHIVE_EVENTS[kind],
                   source=SOURCE,
                   company_id=entity.id if kind == "company" else getattr(entity, "company_id", None),
                   aggregate_type=kind, aggregate_id=str(entity.id),
                   payload={**result, "actor_member_id": actor_member_id})
    except Exception:  # noqa: BLE001
        pass
    return result


def last_archive_event(db: Session, entity, organization_id: int):
    kind = kind_of(entity)
    return db.execute(
        select(CompanyEvent).where(CompanyEvent.organization_id == organization_id,
                                   CompanyEvent.event_type == ARCHIVE_EVENTS[kind],
                                   CompanyEvent.aggregate_id == str(entity.id))
        .order_by(CompanyEvent.id.desc())
    ).scalars().first()


def _recorded(payload: dict, section: str) -> dict[int, str]:
    raw = (payload.get("previous") or {}).get(section)
    out: dict[int, str] = {}
    if isinstance(raw, dict):
        for key, value in raw.items():
            if isinstance(value, str) and str(key).isdigit():
                out[int(key)] = value
    return out


def restore_preview(db: Session, entity, organization_id: int) -> dict:
    kind = kind_of(entity)
    event = last_archive_event(db, entity, organization_id)
    payload = payload_of(event) if event else {}
    if isinstance(payload, str):  # defensive: payload_of already decodes
        try:
            payload = json.loads(payload)
        except Exception:  # noqa: BLE001
            payload = {}
    member_statuses = _recorded(payload, "members")
    dept_levels = _recorded(payload, "departments")
    self_prior = (payload.get("previous") or {}).get("self")
    tree = _subtree(db, entity)
    default_self = COMPANY_DEFAULT_RESTORE if kind == "company" else (
        MEMBER_DEFAULT_RESTORE if kind == "member" else DEPARTMENT_DEFAULT_RESTORE)
    return {
        "kind": kind,
        "id": entity.id,
        "archived": _already_archived(kind, entity),
        "has_archive_record": event is not None,
        "archived_at": event.occurred_at.isoformat() if event is not None and event.occurred_at else "",
        "restore_to": self_prior if isinstance(self_prior, str) else default_self,
        "prior_state_known": isinstance(self_prior, str),
        "will_restore_members": [
            {"member_id": m.id, "name": m.name,
             "restore_to": member_statuses.get(m.id, MEMBER_DEFAULT_RESTORE),
             "prior_status_known": m.id in member_statuses}
            for m in tree["members"] if m.status == MEMBER_ARCHIVED
        ],
        "will_restore_departments": [
            {"department_id": d.id, "name": d.name,
             "restore_to": _dept_restore(dept_levels.get(d.id))["status"],
             "status": _dept_restore(dept_levels.get(d.id))["status"],
             "restore_access_level": _dept_restore(dept_levels.get(d.id))["access_level"],
             "archive_era": _dept_restore(dept_levels.get(d.id))["era"],
             "prior_level_known": d.id in dept_levels}
            for d in tree["departments"]
            if kind == "company" and _already_archived("department", d)
        ],
        # Projects cancelled by a company archive are restored one at a time
        # through /api/v28/projects/{id}/restore. Reopening a whole board
        # implicitly is a bigger decision than un-archiving a company.
        "projects_restored_separately": [
            item.get("project_id") for item in (payload.get("archived_projects") or [])
            if isinstance(item, dict)
        ],
    }


def restore_entity(db: Session, entity, organization_id: int, *,
                   actor_member_id: int | None = None) -> dict:
    kind = kind_of(entity)
    if not _already_archived(kind, entity):
        raise HTTPException(409, detail={
            "error": f"This {kind} is not archived",
            "kind": kind, "id": entity.id,
        })
    plan = restore_preview(db, entity, organization_id)
    tree = _subtree(db, entity)
    by_member = {item["member_id"]: item for item in plan["will_restore_members"]}
    by_dept = {item["department_id"]: item for item in plan["will_restore_departments"]}

    restored_members: list[dict] = []
    for member in tree["members"]:
        entry = by_member.get(member.id)
        if entry is None:
            continue
        member.status = entry["restore_to"]
        db.add(member)
        restored_members.append({"member_id": member.id, "status": member.status,
                                 "prior_status_known": entry["prior_status_known"]})

    restored_departments: list[dict] = []
    for dept in tree["departments"]:
        entry = by_dept.get(dept.id)
        if entry is None:
            continue
        dept.status = entry.get("status") or DEPARTMENT_DEFAULT_RESTORE
        if entry.get("restore_access_level"):
            # A v29 record: put back the permission it took away.
            dept.access_level = entry["restore_access_level"]
        db.add(dept)
        restored_departments.append({"department_id": dept.id, "status": dept.status,
                                     "access_level": dept.access_level,
                                     "archive_era": entry.get("archive_era", "unknown"),
                                     "prior_level_known": entry["prior_level_known"]})

    if kind == "company":
        entity.status = plan["restore_to"]
    elif kind == "member":
        entity.status = plan["restore_to"]
    else:
        recorded = plan["restore_to"] if plan["prior_state_known"] else None
        plan_dept = _dept_restore(recorded)
        entity.status = plan_dept["status"]
        if plan_dept["access_level"]:
            entity.access_level = plan_dept["access_level"]
    db.add(entity); db.commit(); db.refresh(entity)

    result = {
        "kind": kind,
        "id": entity.id,
        "name": entity.name,
        "restored": True,
        "restored_to": plan["restore_to"],
        "prior_state_known": plan["prior_state_known"],
        "has_archive_record": plan["has_archive_record"],
        "restored_members": restored_members,
        "restored_departments": restored_departments,
        "projects_restored_separately": plan["projects_restored_separately"],
        "revision": revision(entity),
    }
    try:
        emit_event(db, organization_id=organization_id, event_type=RESTORE_EVENTS[kind],
                   source=SOURCE,
                   company_id=entity.id if kind == "company" else getattr(entity, "company_id", None),
                   aggregate_type=kind, aggregate_id=str(entity.id),
                   payload={**result, "actor_member_id": actor_member_id})
    except Exception:  # noqa: BLE001
        pass
    return result
