import json, uuid
from sqlalchemy.orm import Session
from app.models import AuditEvent

def log_event(db: Session, organization_id: int, action: str, object_type: str = "", object_id: str = "",
              actor_member_id: int | None = None, actor_name: str = "system", result: str = "success",
              risk: str = "low", payload: dict | None = None):
    event = AuditEvent(
        organization_id=organization_id,
        actor_member_id=actor_member_id,
        actor_name=actor_name,
        action=action,
        object_type=object_type,
        object_id=str(object_id),
        result=result,
        risk=risk,
        trace_id=f"tr_{uuid.uuid4().hex[:12]}",
        payload_json=json.dumps(payload or {}, ensure_ascii=False),
    )
    db.add(event); db.commit(); db.refresh(event)
    return event