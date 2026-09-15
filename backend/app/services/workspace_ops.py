"""v18 workspace operations: the write half of the cockpit.

v17 made the business screens read real data. This module lets an operator (or
an agent with the right scope) actually change the organization from those same
screens: stand up a company, add a department, hire a human or register an agent
seat, open a project, file and move tasks.

Design rules:
- No new tables. These are guarded writes over the v1 entity model.
- Every mutation is tenant-checked by the caller (api/v18.py) before it lands
  here, and every mutation emits a company event so the audit trail and the
  realtime feed stay complete.
- Status/role vocabularies are validated here rather than in the UI, so an agent
  calling through the openclaw bridge cannot invent a status the board cannot
  render.
"""
from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Agent, Company, Department, KnowledgeDocument, Member, Project, Task
from app.services import write_trail
from app.services.company_event_bus import emit_event

SOURCE = "workspace_ops"

COMPANY_STATUSES = ("active", "paused", "archived")
MEMBER_STATUSES = ("active", "onboarding", "suspended", "offboarded")
PROJECT_STATUSES = ("planning", "active", "running", "in_progress", "blocked", "done", "cancelled")
# v20 fix: "blocked" was reachable in TASK_TRANSITIONS but missing here, so
# _check rejected it and no task could ever be blocked through the API.
TASK_STATUSES = ("backlog", "todo", "in_progress", "review", "blocked", "done", "cancelled")
TASK_PRIORITIES = ("low", "medium", "high", "urgent")
ACCESS_LEVELS = ("org_public", "restricted", "confidential")
# v31: a real status column, so "closed" stops being spelled as
# access_level="confidential". Archiving and permission are different
# questions and were sharing one field since v29.
DEPARTMENT_STATUSES = ("active", "paused", "archived")

# A task may only move along these edges. This stops an agent from silently
# flipping work from backlog straight to done without review.
TASK_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "backlog": ("todo", "cancelled"),
    "todo": ("in_progress", "backlog", "cancelled"),
    "in_progress": ("review", "todo", "blocked", "cancelled"),
    "review": ("done", "in_progress", "cancelled"),
    "blocked": ("in_progress", "todo", "cancelled"),
    "done": ("review",),
    "cancelled": ("backlog",),
}


def _check(value: str, allowed: tuple[str, ...], label: str) -> str:
    if value not in allowed:
        raise HTTPException(400, f"{label} must be one of: {', '.join(allowed)}")
    return value


def _emit(db: Session, organization_id: int, event_type: str, payload: dict,
          company_id: int | None, aggregate_type: str, aggregate_id, actor_member_id: int | None) -> None:
    emit_event(db, organization_id=organization_id, event_type=event_type, payload=payload,
               company_id=company_id, source=SOURCE, aggregate_type=aggregate_type,
               aggregate_id=str(aggregate_id), actor_member_id=actor_member_id)


# --------------------------------------------------------------------------- company

def create_company(db: Session, organization_id: int, *, name: str, industry: str = "",
                   status: str = "active", actor_member_id: int | None = None) -> Company:
    name = (name or "").strip()
    if not name:
        raise HTTPException(400, "Company name is required")
    _check(status, COMPANY_STATUSES, "status")
    exists = (db.query(Company)
              .filter(Company.organization_id == organization_id, func.lower(Company.name) == name.lower())
              .first())
    if exists:
        raise HTTPException(409, f"A company named '{name}' already exists in this organization")
    company = Company(organization_id=organization_id, name=name, industry=industry or "", status=status)
    db.add(company); db.commit(); db.refresh(company)
    _emit(db, organization_id, "company.created",
          {"company_id": company.id, "name": company.name, "industry": company.industry},
          company.id, "company", company.id, actor_member_id)
    return company


def update_company(db: Session, company: Company, *, name: str | None = None, industry: str | None = None,
                   status: str | None = None, actor_member_id: int | None = None) -> Company:
    trail = write_trail.start("company", company)
    changed: dict[str, object] = {}
    if name is not None and name.strip() and name.strip() != company.name:
        company.name = name.strip(); changed["name"] = company.name
    if industry is not None and industry != company.industry:
        company.industry = industry; changed["industry"] = industry
    if status is not None and status != company.status:
        company.status = _check(status, COMPANY_STATUSES, "status"); changed["status"] = status
    if not changed:
        return company
    db.add(company); db.commit(); db.refresh(company)
    payload = {"company_id": company.id, "changed": changed}
    payload.update(trail.finish(company))
    _emit(db, company.organization_id, "company.updated", payload,
          company.id, "company", company.id, actor_member_id)
    return company


# ------------------------------------------------------------------------ department

def create_department(db: Session, company: Company, *, name: str, head_member_id: int | None = None,
                      access_level: str = "restricted", actor_member_id: int | None = None) -> Department:
    name = (name or "").strip()
    if not name:
        raise HTTPException(400, "Department name is required")
    _check(access_level, ACCESS_LEVELS, "access_level")
    if head_member_id is not None:
        head = db.get(Member, head_member_id)
        if not head or head.organization_id != company.organization_id:
            raise HTTPException(404, "Head member not found in this organization")
        if head.company_id is not None and head.company_id != company.id:
            raise HTTPException(400, "Department head must belong to the same company")
    # v31: names are unique per company at the database level (migration
    # 0014). Checking here too turns a 500 from the index into a 409 that
    # names the conflicting department.
    existing = db.query(Department).filter(Department.company_id == company.id,
                                           Department.name == name).first()
    if existing is not None:
        raise HTTPException(409, detail={
            "error": "A department with this name already exists in this company",
            "department_id": existing.id,
            "name": name,
        })
    dept = Department(company_id=company.id, name=name, head_member_id=head_member_id,
                      access_level=access_level, status="active")
    db.add(dept); db.commit(); db.refresh(dept)
    _emit(db, company.organization_id, "department.created",
          {"department_id": dept.id, "company_id": company.id, "name": dept.name},
          company.id, "department", dept.id, actor_member_id)
    return dept


def update_department(db: Session, dept: Department, organization_id: int, *,
                      name: str | None = None, head_member_id: int | None = None,
                      access_level: str | None = None, status: str | None = None,
                      clear_head: bool = False,
                      actor_member_id: int | None = None) -> Department:
    """v31: the department update path that never existed.

    Departments could be created and cascade-archived but never edited, so
    fixing a typo in a name meant a guarded write through v28's generic
    endpoint, which skipped the uniqueness check entirely.
    """
    trail = write_trail.start("department", dept)
    changed: dict[str, object] = {}
    if name is not None:
        name = name.strip()
        if not name:
            raise HTTPException(400, "Department name is required")
        if name != dept.name:
            clash = db.query(Department).filter(Department.company_id == dept.company_id,
                                                Department.name == name,
                                                Department.id != dept.id).first()
            if clash is not None:
                raise HTTPException(409, detail={
                    "error": "A department with this name already exists in this company",
                    "department_id": clash.id, "name": name})
            dept.name = name
            changed["name"] = name
    if access_level is not None and access_level != dept.access_level:
        dept.access_level = _check(access_level, ACCESS_LEVELS, "access_level")
        changed["access_level"] = access_level
    if status is not None and status != dept.status:
        dept.status = _check(status, DEPARTMENT_STATUSES, "status")
        changed["status"] = status
    if clear_head:
        # Explicit, because None in a request body means "leave alone".
        if dept.head_member_id is not None:
            dept.head_member_id = None
            changed["head_member_id"] = None
    elif head_member_id is not None and head_member_id != dept.head_member_id:
        head = db.get(Member, head_member_id)
        if not head or head.organization_id != organization_id:
            raise HTTPException(404, "Head member not found in this organization")
        if head.company_id is not None and head.company_id != dept.company_id:
            raise HTTPException(400, "Department head must belong to the same company")
        dept.head_member_id = head_member_id
        changed["head_member_id"] = head_member_id
    if not changed:
        return dept
    db.add(dept); db.commit(); db.refresh(dept)
    payload = {"department_id": dept.id, "changed": changed}
    payload.update(trail.finish(dept))
    _emit(db, organization_id, "department.updated", payload,
          dept.company_id, "department", dept.id, actor_member_id)
    return dept


def duplicate_department_names(db: Session, company_id: int) -> list[dict]:
    """Name collisions that would block migration 0014 for one company."""
    rows = db.query(Department).filter(Department.company_id == company_id).all()
    seen: dict[str, list[int]] = {}
    for row in rows:
        seen.setdefault(row.name, []).append(row.id)
    return [{"name": name, "department_ids": sorted(ids)}
            for name, ids in sorted(seen.items()) if len(ids) > 1]


# ---------------------------------------------------------------------------- member

def create_member(db: Session, organization_id: int, *, name: str, member_type: str,
                  company_id: int | None = None, department_id: int | None = None, role: str = "",
                  manager_id: int | None = None, status: str = "active",
                  runtime_agent_id: str | None = None, model: str = "", risk: str = "low",
                  actor_member_id: int | None = None) -> tuple[Member, Agent | None]:
    """Create a human seat, or an agent seat plus its Agent runtime record.

    Agent seats are the interesting case: a Member row alone is just a name on an
    org chart. Without the Agent row the seat has no runtime binding, so the
    cockpit would show an 'agent' that no openclaw runtime can ever execute. We
    therefore create both in one transaction.
    """
    name = (name or "").strip()
    if not name:
        raise HTTPException(400, "Member name is required")
    if member_type not in ("human", "agent"):
        raise HTTPException(400, "member_type must be human or agent")
    _check(status, MEMBER_STATUSES, "status")
    if member_type == "agent" and not (runtime_agent_id or "").strip():
        raise HTTPException(400, "runtime_agent_id is required for an agent seat")

    if department_id is not None:
        dept = db.get(Department, department_id)
        if not dept:
            raise HTTPException(404, "Department not found")
        if company_id is not None and dept.company_id != company_id:
            raise HTTPException(400, "Department does not belong to the given company")
        company_id = company_id if company_id is not None else dept.company_id
    if manager_id is not None:
        manager = db.get(Member, manager_id)
        if not manager or manager.organization_id != organization_id:
            raise HTTPException(404, "Manager not found in this organization")

    member = Member(organization_id=organization_id, company_id=company_id, department_id=department_id,
                    name=name, member_type=member_type, role=role or "", manager_id=manager_id,
                    status=status)
    db.add(member); db.commit(); db.refresh(member)

    agent: Agent | None = None
    if member_type == "agent":
        runtime_id = runtime_agent_id.strip()
        clash = (db.query(Agent).join(Member, Member.id == Agent.member_id)
                 .filter(Member.organization_id == organization_id,
                         Agent.runtime_agent_id == runtime_id).first())
        if clash:
            db.delete(member); db.commit()
            raise HTTPException(409, f"runtime_agent_id '{runtime_id}' is already bound to another seat")
        agent = Agent(member_id=member.id, runtime_provider="openclaw", runtime_agent_id=runtime_id,
                      lifecycle="active", model=model or "", success_rate=0, cost_30d=0, risk=risk)
        db.add(agent); db.commit(); db.refresh(agent)

    _emit(db, organization_id, "member.created",
          {"member_id": member.id, "name": member.name, "member_type": member.member_type,
           "company_id": company_id, "runtime_agent_id": agent.runtime_agent_id if agent else None},
          company_id, "member", member.id, actor_member_id)
    return member, agent


def move_member(db: Session, member: Member, *, company_id: int | None = None,
                department_id: int | None = None, role: str | None = None,
                manager_id: int | None = None, status: str | None = None,
                actor_member_id: int | None = None) -> Member:
    """Reassign a seat. Used by the org-chart screen for drag-and-drop moves."""
    trail = write_trail.start("member", member)
    changed: dict[str, object] = {}
    if department_id is not None:
        dept = db.get(Department, department_id)
        if not dept:
            raise HTTPException(404, "Department not found")
        target_company = company_id if company_id is not None else dept.company_id
        if dept.company_id != target_company:
            raise HTTPException(400, "Department does not belong to the target company")
        member.department_id = department_id; changed["department_id"] = department_id
        company_id = target_company
    if company_id is not None and company_id != member.company_id:
        member.company_id = company_id; changed["company_id"] = company_id
        if department_id is None:
            # A seat cannot keep a department that belongs to the old company.
            member.department_id = None; changed["department_id"] = None
    if manager_id is not None:
        if manager_id == member.id:
            raise HTTPException(400, "A member cannot manage themselves")
        manager = db.get(Member, manager_id)
        if not manager or manager.organization_id != member.organization_id:
            raise HTTPException(404, "Manager not found in this organization")
        if _creates_cycle(db, member.id, manager_id):
            raise HTTPException(400, "That manager change would create a reporting cycle")
        member.manager_id = manager_id; changed["manager_id"] = manager_id
    if role is not None and role != member.role:
        member.role = role; changed["role"] = role
    if status is not None and status != member.status:
        member.status = _check(status, MEMBER_STATUSES, "status"); changed["status"] = status
    if not changed:
        return member
    db.add(member); db.commit(); db.refresh(member)
    payload = {"member_id": member.id, "changed": changed}
    payload.update(trail.finish(member))
    _emit(db, member.organization_id, "member.updated", payload,
          member.company_id, "member", member.id, actor_member_id)
    return member


def _creates_cycle(db: Session, member_id: int, manager_id: int) -> bool:
    """Walk up the proposed chain; if we meet ourselves, the edge is illegal."""
    seen: set[int] = set()
    cursor: int | None = manager_id
    while cursor is not None and cursor not in seen:
        if cursor == member_id:
            return True
        seen.add(cursor)
        parent = db.get(Member, cursor)
        cursor = parent.manager_id if parent else None
    return False


# --------------------------------------------------------------------------- project

def create_project(db: Session, company: Company, *, name: str, description: str = "",
                   owner_member_id: int | None = None, status: str = "planning",
                   actor_member_id: int | None = None) -> Project:
    name = (name or "").strip()
    if not name:
        raise HTTPException(400, "Project name is required")
    _check(status, PROJECT_STATUSES, "status")
    # v31 bugfix: the clear_owner flag belongs to update_project only. The
    # patch that added it also landed this condition here, where the name
    # does not exist, so creating a project with an owner raised NameError
    # -> 500 on the most ordinary call in the module.
    if owner_member_id is not None:
        owner = db.get(Member, owner_member_id)
        if not owner or owner.organization_id != company.organization_id:
            raise HTTPException(404, "Owner not found in this organization")
    project = Project(company_id=company.id, name=name, description=description or "",
                      owner_member_id=owner_member_id, status=status, progress=0)
    db.add(project); db.commit(); db.refresh(project)
    _emit(db, company.organization_id, "project.created",
          {"project_id": project.id, "company_id": company.id, "name": project.name},
          company.id, "project", project.id, actor_member_id)
    return project


def update_project(db: Session, project: Project, organization_id: int, *, status: str | None = None,
                   progress: int | None = None, owner_member_id: int | None = None,
                   description: str | None = None, clear_owner: bool = False,
                   actor_member_id: int | None = None) -> Project:
    """v31 adds ``clear_owner``: a project can finally lose its owner.

    None still means "leave alone", so unassigning needed a separate flag
    rather than a meaning change that would silently clear owners for
    every client that omits the field.
    """
    trail = write_trail.start("project", project)
    changed: dict[str, object] = {}
    if clear_owner and project.owner_member_id is not None:
        project.owner_member_id = None
        changed["owner_member_id"] = None
    if status is not None and status != project.status:
        project.status = _check(status, PROJECT_STATUSES, "status"); changed["status"] = status
    if progress is not None:
        if not 0 <= int(progress) <= 100:
            raise HTTPException(400, "progress must be between 0 and 100")
        project.progress = int(progress); changed["progress"] = project.progress
    # clear_owner wins over an owner_member_id sent in the same body:
    # a request that says both "unassign" and "assign to 7" is ambiguous,
    # and clearing is the destructive one, so it must not be silently
    # cancelled by a field the client may have left in place.
    if owner_member_id is not None and not clear_owner:
        owner = db.get(Member, owner_member_id)
        if not owner or owner.organization_id != organization_id:
            raise HTTPException(404, "Owner not found in this organization")
        project.owner_member_id = owner_member_id; changed["owner_member_id"] = owner_member_id
    if description is not None and description != project.description:
        project.description = description; changed["description"] = description
    if not changed:
        return project
    db.add(project); db.commit(); db.refresh(project)
    payload = {"project_id": project.id, "changed": changed}
    payload.update(trail.finish(project))
    _emit(db, organization_id, "project.updated", payload,
          project.company_id, "project", project.id, actor_member_id)
    return project


# ------------------------------------------------------------------------------ task

def create_task(db: Session, project: Project, organization_id: int, *, title: str, description: str = "",
                assignee_member_id: int | None = None, priority: str = "medium",
                actor_member_id: int | None = None) -> Task:
    title = (title or "").strip()
    if not title:
        raise HTTPException(400, "Task title is required")
    _check(priority, TASK_PRIORITIES, "priority")
    if assignee_member_id is not None:
        _assignable(db, assignee_member_id, organization_id)
    task = Task(project_id=project.id, title=title, description=description or "",
                assignee_member_id=assignee_member_id, status="backlog", priority=priority)
    db.add(task); db.commit(); db.refresh(task)
    _emit(db, organization_id, "task.created",
          {"task_id": task.id, "project_id": project.id, "title": task.title,
           "assignee_member_id": assignee_member_id, "priority": priority},
          project.company_id, "task", task.id, actor_member_id)
    return task


def _assignable(db: Session, member_id: int, organization_id: int) -> Member:
    member = db.get(Member, member_id)
    if not member or member.organization_id != organization_id:
        raise HTTPException(404, "Assignee not found in this organization")
    if member.status not in ("active", "onboarding"):
        raise HTTPException(400, f"Cannot assign work to a member whose status is '{member.status}'")
    return member


def move_task(db: Session, task: Task, project: Project, organization_id: int, *, status: str,
              actor_member_id: int | None = None) -> Task:
    _check(status, TASK_STATUSES, "status")
    current = task.status or "backlog"
    if status == current:
        return task
    allowed = TASK_TRANSITIONS.get(current, ())
    if status not in allowed:
        raise HTTPException(409, f"Cannot move a task from '{current}' to '{status}'. "
                                 f"Allowed: {', '.join(allowed) or 'none'}")
    if status in ("in_progress", "review") and task.assignee_member_id is None:
        raise HTTPException(400, "Assign the task before moving it into progress")
    trail = write_trail.start("task", task)
    task.status = status
    db.add(task); db.commit(); db.refresh(task)
    payload = {"task_id": task.id, "project_id": task.project_id,
               "from": current, "to": status}
    payload.update(trail.finish(task))
    _emit(db, organization_id, f"task.{status}", payload,
          project.company_id, "task", task.id, actor_member_id)
    return task


def assign_task(db: Session, task: Task, project: Project, organization_id: int, *,
                assignee_member_id: int | None, actor_member_id: int | None = None) -> Task:
    if assignee_member_id is not None:
        _assignable(db, assignee_member_id, organization_id)
    elif task.status in ("in_progress", "review"):
        raise HTTPException(400, "Cannot unassign a task that is in progress or review")
    previous = task.assignee_member_id
    if previous == assignee_member_id:
        return task
    trail = write_trail.start("task", task)
    task.assignee_member_id = assignee_member_id
    db.add(task); db.commit(); db.refresh(task)
    payload = {"task_id": task.id, "from": previous, "to": assignee_member_id}
    payload.update(trail.finish(task))
    _emit(db, organization_id, "task.assigned", payload,
          project.company_id, "task", task.id, actor_member_id)
    return task


# ------------------------------------------------------------------------- knowledge

def create_knowledge_document(db: Session, organization_id: int, *, title: str, content: str,
                              company_id: int | None = None, department_id: int | None = None,
                              project_id: int | None = None, access_level: str = "restricted",
                              source_type: str = "manual",
                              actor_member_id: int | None = None) -> KnowledgeDocument:
    title = (title or "").strip()
    if not title:
        raise HTTPException(400, "Document title is required")
    _check(access_level, ACCESS_LEVELS, "access_level")
    doc = KnowledgeDocument(organization_id=organization_id, company_id=company_id,
                            department_id=department_id, project_id=project_id, title=title,
                            source_type=source_type, access_level=access_level, content=content or "",
                            indexed=False)
    db.add(doc); db.commit(); db.refresh(doc)
    _emit(db, organization_id, "knowledge.document.created",
          {"document_id": doc.id, "title": doc.title, "access_level": access_level},
          company_id, "knowledge_document", doc.id, actor_member_id)
    return doc
