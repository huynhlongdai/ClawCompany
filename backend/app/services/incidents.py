import json
from datetime import datetime
from sqlalchemy.orm import Session
from app.models import Incident, IncidentEvent
from app.services.company_event_bus import emit_event


class IncidentError(RuntimeError):
    pass


def create_incident(db: Session, **kwargs) -> Incident:
    item = Incident(**kwargs)
    db.add(item); db.commit(); db.refresh(item)
    db.add(IncidentEvent(organization_id=item.organization_id, incident_id=item.id, event_type="opened",
                         message=item.summary, data_json="{}")); db.commit()
    emit_event(db, organization_id=item.organization_id, company_id=item.company_id, event_type="incident.opened",
               source="incident_response", aggregate_type="incident", aggregate_id=str(item.id),
               payload={"incident_id": item.id, "severity": item.severity, "title": item.title})
    try:
        from app.services.incident_paging import queue_incident_notifications
        queue_incident_notifications(db, item, event_type="opened")
    except Exception:
        # Paging is auxiliary; incident persistence/event emission must not be lost if no route is configured.
        pass
    return item


def add_incident_event(db: Session, incident: Incident, *, event_type: str, message: str = "", data: dict | None = None,
                       actor_member_id: int | None = None, actor_agent_id: int | None = None) -> IncidentEvent:
    item = IncidentEvent(organization_id=incident.organization_id, incident_id=incident.id, actor_member_id=actor_member_id,
                         actor_agent_id=actor_agent_id, event_type=event_type, message=message,
                         data_json=json.dumps(data or {}, ensure_ascii=False, default=str))
    db.add(item); db.commit(); db.refresh(item)
    return item


def update_incident_status(db: Session, incident: Incident, status: str, *, message: str = "",
                           actor_member_id: int | None = None) -> Incident:
    if status not in {"open", "acknowledged", "mitigating", "resolved"}:
        raise IncidentError("Unsupported incident status")
    incident.status = status
    now = datetime.utcnow()
    if status == "acknowledged" and not incident.acknowledged_at: incident.acknowledged_at = now
    if status == "resolved": incident.resolved_at = now
    db.add(incident); db.commit(); db.refresh(incident)
    add_incident_event(db, incident, event_type=status, message=message, actor_member_id=actor_member_id)
    emit_event(db, organization_id=incident.organization_id, company_id=incident.company_id,
               event_type=f"incident.{status}", source="incident_response", aggregate_type="incident", aggregate_id=str(incident.id),
               actor_member_id=actor_member_id, payload={"incident_id": incident.id, "status": status})
    try:
        from app.services.incident_paging import queue_incident_notifications
        queue_incident_notifications(db, incident, event_type=status)
    except Exception:
        pass
    return incident
