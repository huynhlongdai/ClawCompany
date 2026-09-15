"""v17 workspace cockpit: aggregate reads that back the business UI screens.

The mockup screens (Trang chủ, Công ty, Phòng ban, Nhân sự, AI Agents, Dự án,
Nhiệm vụ, Kiến thức) used to be hardcoded demo data in the frontend. This module
turns them into real, tenant-scoped aggregate queries so the UI can drop the
fixtures without issuing a dozen round trips per screen.

Read-only by design: no writes, no new tables, no migration.
"""
from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import (Organization, Company, Department, Member, Agent, Project, Task,
                        KnowledgeDocument, Approval, Customer)

ACTIVE_PROJECT_STATUSES = ("active", "running", "in_progress")
OPEN_TASK_STATUSES = ("backlog", "todo", "in_progress", "review")


def _counts_by(db: Session, column, base_filter) -> dict[int, int]:
    rows = db.query(column, func.count()).filter(base_filter).group_by(column).all()
    return {int(key): int(value) for key, value in rows if key is not None}


def company_ids(db: Session, organization_id: int) -> list[int]:
    return [x[0] for x in db.query(Company.id).filter(Company.organization_id == organization_id).all()]


def org_overview(db: Session, organization_id: int) -> dict:
    """Header + KPI strip + holding tree for the home screen."""
    org = db.get(Organization, organization_id)
    cids = company_ids(db, organization_id)
    member_counts = _counts_by(db, Member.company_id, Member.organization_id == organization_id)
    agent_counts = _counts_by(db, Member.company_id,
                              (Member.organization_id == organization_id) & (Member.member_type == "agent"))
    project_counts = _counts_by(db, Project.company_id, Project.company_id.in_(cids)) if cids else {}

    companies = []
    for company in db.query(Company).filter(Company.organization_id == organization_id).order_by(Company.id).all():
        companies.append({
            "id": company.id,
            "name": company.name,
            "industry": company.industry,
            "status": company.status,
            "members": member_counts.get(company.id, 0),
            "agents": agent_counts.get(company.id, 0),
            "projects": project_counts.get(company.id, 0),
        })

    total_members = db.query(Member).filter(Member.organization_id == organization_id).count()
    total_agents = db.query(Member).filter(Member.organization_id == organization_id,
                                           Member.member_type == "agent").count()
    return {
        "organization": {"id": organization_id, "name": org.name if org else "", "slug": org.slug if org else ""},
        "kpis": {
            "companies": len(companies),
            "members": total_members,
            "humans": total_members - total_agents,
            "agents": total_agents,
            "projects_total": db.query(Project).filter(Project.company_id.in_(cids)).count() if cids else 0,
            "projects_active": (db.query(Project).filter(Project.company_id.in_(cids),
                                                         Project.status.in_(ACTIVE_PROJECT_STATUSES)).count()
                                if cids else 0),
            "customers": db.query(Customer).filter(Customer.organization_id == organization_id).count(),
            "approvals_pending": db.query(Approval).filter(Approval.organization_id == organization_id,
                                                           Approval.status == "pending").count(),
            "knowledge_documents": db.query(KnowledgeDocument).filter(
                KnowledgeDocument.organization_id == organization_id).count(),
        },
        "companies": companies,
    }


def company_detail(db: Session, company: Company) -> dict:
    """Company screen: departments, headcount split, projects."""
    departments = []
    dept_members = _counts_by(db, Member.department_id, Member.company_id == company.id)
    for dept in db.query(Department).filter(Department.company_id == company.id).order_by(Department.id).all():
        head = db.get(Member, dept.head_member_id) if dept.head_member_id else None
        departments.append({
            "id": dept.id, "name": dept.name, "access_level": dept.access_level,
            "head_member_id": dept.head_member_id, "head_name": head.name if head else None,
            "members": dept_members.get(dept.id, 0),
        })
    projects = [{"id": p.id, "name": p.name, "status": p.status, "progress": p.progress,
                 "owner_member_id": p.owner_member_id}
                for p in db.query(Project).filter(Project.company_id == company.id).order_by(Project.id.desc()).all()]
    humans = db.query(Member).filter(Member.company_id == company.id, Member.member_type == "human").count()
    agents = db.query(Member).filter(Member.company_id == company.id, Member.member_type == "agent").count()
    return {
        "company": {"id": company.id, "name": company.name, "industry": company.industry, "status": company.status},
        "headcount": {"humans": humans, "agents": agents, "total": humans + agents},
        "departments": departments,
        "projects": projects,
    }


def people_directory(db: Session, organization_id: int, *, member_type: str | None = None,
                     company_id: int | None = None, limit: int = 300) -> list[dict]:
    """Nhân sự / AI Agents screens share one directory shape."""
    query = db.query(Member).filter(Member.organization_id == organization_id)
    if member_type:
        query = query.filter(Member.member_type == member_type)
    if company_id:
        query = query.filter(Member.company_id == company_id)
    members = query.order_by(Member.id).limit(limit).all()

    companies = {c.id: c.name for c in db.query(Company).filter(Company.organization_id == organization_id).all()}
    departments = {d.id: d.name for d in db.query(Department).filter(
        Department.company_id.in_(list(companies) or [0])).all()}
    agents = {a.member_id: a for a in db.query(Agent).filter(
        Agent.member_id.in_([m.id for m in members] or [0])).all()}

    directory = []
    for member in members:
        agent = agents.get(member.id)
        directory.append({
            "id": member.id, "name": member.name, "member_type": member.member_type,
            "role": member.role, "status": member.status,
            "company_id": member.company_id, "company_name": companies.get(member.company_id),
            "department_id": member.department_id, "department_name": departments.get(member.department_id),
            "manager_id": member.manager_id,
            "agent": None if agent is None else {
                "runtime_provider": agent.runtime_provider, "runtime_agent_id": agent.runtime_agent_id,
                "lifecycle": agent.lifecycle, "model": agent.model,
                "success_rate": agent.success_rate, "cost_30d": agent.cost_30d, "risk": agent.risk,
            },
        })
    return directory


def project_board(db: Session, organization_id: int, *, company_id: int | None = None, limit: int = 200) -> list[dict]:
    """Dự án screen: each project with its task rollup."""
    cids = [company_id] if company_id else company_ids(db, organization_id)
    if not cids:
        return []
    projects = db.query(Project).filter(Project.company_id.in_(cids)).order_by(Project.id.desc()).limit(limit).all()
    pids = [p.id for p in projects] or [0]
    rows = db.query(Task.project_id, Task.status, func.count()).filter(
        Task.project_id.in_(pids)).group_by(Task.project_id, Task.status).all()
    rollup: dict[int, dict[str, int]] = {}
    for project_id, status, count in rows:
        rollup.setdefault(int(project_id), {})[status] = int(count)
    companies = {c.id: c.name for c in db.query(Company).filter(Company.id.in_(cids)).all()}

    board = []
    for project in projects:
        by_status = rollup.get(project.id, {})
        board.append({
            "id": project.id, "name": project.name, "status": project.status, "progress": project.progress,
            "company_id": project.company_id, "company_name": companies.get(project.company_id),
            "owner_member_id": project.owner_member_id,
            "tasks_total": sum(by_status.values()),
            "tasks_open": sum(v for k, v in by_status.items() if k in OPEN_TASK_STATUSES),
            "tasks_done": by_status.get("done", 0) + by_status.get("completed", 0),
            "tasks_by_status": by_status,
        })
    return board


def task_queue(db: Session, organization_id: int, *, status: str | None = None,
               assignee_member_id: int | None = None, limit: int = 200) -> list[dict]:
    """Nhiệm vụ screen: tasks joined with project, company and assignee names."""
    cids = company_ids(db, organization_id)
    if not cids:
        return []
    pids = [x[0] for x in db.query(Project.id).filter(Project.company_id.in_(cids)).all()]
    if not pids:
        return []
    query = db.query(Task).filter(Task.project_id.in_(pids))
    if status:
        query = query.filter(Task.status == status)
    if assignee_member_id:
        query = query.filter(Task.assignee_member_id == assignee_member_id)
    tasks = query.order_by(Task.id.desc()).limit(limit).all()

    projects = {p.id: p for p in db.query(Project).filter(Project.id.in_(pids)).all()}
    companies = {c.id: c.name for c in db.query(Company).filter(Company.id.in_(cids)).all()}
    assignees = {m.id: m for m in db.query(Member).filter(
        Member.id.in_([t.assignee_member_id for t in tasks if t.assignee_member_id] or [0])).all()}

    queue = []
    for task in tasks:
        project = projects.get(task.project_id)
        assignee = assignees.get(task.assignee_member_id) if task.assignee_member_id else None
        queue.append({
            "id": task.id, "title": task.title, "status": task.status, "priority": task.priority,
            "project_id": task.project_id, "project_name": project.name if project else None,
            "company_name": companies.get(project.company_id) if project else None,
            "assignee_member_id": task.assignee_member_id,
            "assignee_name": assignee.name if assignee else None,
            "assignee_type": assignee.member_type if assignee else None,
            "runtime_run_id": task.runtime_run_id,
        })
    return queue


def knowledge_library(db: Session, organization_id: int, *, company_id: int | None = None,
                      limit: int = 200) -> list[dict]:
    """Kiến thức screen: classic documents (the v16 mesh has its own console)."""
    query = db.query(KnowledgeDocument).filter(KnowledgeDocument.organization_id == organization_id)
    if company_id:
        query = query.filter(KnowledgeDocument.company_id == company_id)
    documents = query.order_by(KnowledgeDocument.id.desc()).limit(limit).all()
    companies = {c.id: c.name for c in db.query(Company).filter(Company.organization_id == organization_id).all()}
    return [{"id": d.id, "title": d.title, "source_type": d.source_type, "access_level": d.access_level,
             "indexed": bool(d.indexed), "company_id": d.company_id,
             "company_name": companies.get(d.company_id), "project_id": d.project_id}
            for d in documents]


def org_chart(db: Session, organization_id: int) -> dict:
    """Holding → company → department → member tree for the org chart canvas."""
    org = db.get(Organization, organization_id)
    members = db.query(Member).filter(Member.organization_id == organization_id).order_by(Member.id).all()
    by_department: dict[int | None, list[Member]] = {}
    unassigned_by_company: dict[int | None, list[Member]] = {}
    for member in members:
        if member.department_id:
            by_department.setdefault(member.department_id, []).append(member)
        else:
            unassigned_by_company.setdefault(member.company_id, []).append(member)

    def shape(member: Member) -> dict:
        return {"id": member.id, "name": member.name, "member_type": member.member_type,
                "role": member.role, "status": member.status}

    companies = []
    for company in db.query(Company).filter(Company.organization_id == organization_id).order_by(Company.id).all():
        departments = []
        for dept in db.query(Department).filter(Department.company_id == company.id).order_by(Department.id).all():
            departments.append({"id": dept.id, "name": dept.name, "access_level": dept.access_level,
                                "members": [shape(m) for m in by_department.get(dept.id, [])]})
        companies.append({"id": company.id, "name": company.name, "industry": company.industry,
                          "status": company.status, "departments": departments,
                          "unassigned_members": [shape(m) for m in unassigned_by_company.get(company.id, [])]})
    return {"organization": {"id": organization_id, "name": org.name if org else ""},
            "companies": companies,
            "floating_members": [shape(m) for m in unassigned_by_company.get(None, [])]}
