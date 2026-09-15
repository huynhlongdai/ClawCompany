from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from app.models import Company, SLAIncident, SLAProfile, Task, Project
from app.services.agent_messaging import send_message
from app.services.company_event_bus import emit_event


def _task_org_company(db: Session, task: Task):
    project = db.get(Project, task.project_id)
    company = db.get(Company, project.company_id) if project else None
    return (company.organization_id if company else None, company.id if company else None)


def monitor_sla(db: Session, organization_id: int | None = None) -> list[SLAIncident]:
    q = db.query(SLAProfile).filter(SLAProfile.enabled == True, SLAProfile.resource_type == "task")  # noqa: E712
    if organization_id is not None:
        q = q.filter(SLAProfile.organization_id == organization_id)
    profiles = q.all()
    created: list[SLAIncident] = []
    now = datetime.utcnow()
    for profile in profiles:
        tq = db.query(Task).join(Project, Task.project_id == Project.id).join(Company, Project.company_id == Company.id).filter(
            Company.organization_id == profile.organization_id,
            Task.status.notin_(["done", "completed", "cancelled"]),
        )
        if profile.company_id is not None:
            tq = tq.filter(Company.id == profile.company_id)
        if profile.priority != "*":
            tq = tq.filter(Task.priority == profile.priority)
        for task in tq.limit(500).all():
            age = now - task.created_at
            if age < timedelta(minutes=profile.completion_minutes):
                continue
            existing = db.query(SLAIncident).filter(
                SLAIncident.profile_id == profile.id, SLAIncident.resource_type == "task",
                SLAIncident.resource_id == str(task.id), SLAIncident.status.in_(["open", "escalated"]),
            ).first()
            if existing:
                continue
            item = SLAIncident(
                organization_id=profile.organization_id, profile_id=profile.id, resource_type="task",
                resource_id=str(task.id), breach_type="completion", severity="high" if task.priority == "critical" else "medium",
                status="open", summary=f"Task #{task.id} exceeded {profile.completion_minutes} minute completion SLA.",
                breached_at=now,
            )
            db.add(item); db.commit(); db.refresh(item); created.append(item)
            if profile.escalation_target_member_id:
                send_message(
                    db, organization_id=profile.organization_id, company_id=profile.company_id,
                    recipient_member_id=profile.escalation_target_member_id, task_id=task.id,
                    message_type="sla_escalation", priority="critical",
                    subject=f"SLA breach · {task.title}", content=item.summary, emit=False,
                    context={"sla_incident_id": item.id, "profile_id": profile.id},
                )
                item.status = "escalated"; item.escalated_at = now; db.add(item); db.commit(); db.refresh(item)
            emit_event(
                db, organization_id=profile.organization_id, company_id=profile.company_id,
                event_type="sla.breached", source="sla_monitor", aggregate_type="task", aggregate_id=str(task.id),
                payload={"sla_incident_id": item.id, "profile_id": profile.id, "task_id": task.id,
                         "priority": task.priority, "completion_minutes": profile.completion_minutes},
            )
    return created
