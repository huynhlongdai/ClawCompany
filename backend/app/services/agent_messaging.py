import json
from datetime import datetime
from sqlalchemy.orm import Session
from app.models import AgentMessage, Member
from app.services.company_event_bus import emit_event


def send_message(db: Session, *, organization_id: int, content: str, sender_member_id: int | None = None,
                 recipient_member_id: int | None = None, company_id: int | None = None, thread_key: str = "",
                 subject: str = "", message_type: str = "message", task_id: int | None = None,
                 artifact_id: int | None = None, priority: str = "normal", context: dict | None = None,
                 emit: bool = True) -> AgentMessage:
    for member_id, label in ((sender_member_id, "sender"), (recipient_member_id, "recipient")):
        if member_id is None:
            continue
        member = db.get(Member, member_id)
        if not member or member.organization_id != organization_id:
            raise ValueError(f"{label} member does not belong to organization")
    item = AgentMessage(
        organization_id=organization_id, company_id=company_id, thread_key=thread_key,
        sender_member_id=sender_member_id, recipient_member_id=recipient_member_id, task_id=task_id,
        artifact_id=artifact_id, message_type=message_type, subject=subject, content=content,
        context_json=json.dumps(context or {}, ensure_ascii=False, default=str), priority=priority, status="sent",
    )
    db.add(item); db.commit(); db.refresh(item)
    if emit:
        emit_event(
            db, organization_id=organization_id, company_id=company_id, event_type="agent.message.sent",
            source="message_bus", aggregate_type="agent_message", aggregate_id=str(item.id),
            actor_member_id=sender_member_id,
            payload={"message_id": item.id, "recipient_member_id": recipient_member_id, "task_id": task_id,
                     "artifact_id": artifact_id, "priority": priority, "subject": subject},
        )
    return item


def mark_read(db: Session, item: AgentMessage):
    item.status = "read"; item.read_at = datetime.utcnow(); db.add(item); db.commit(); db.refresh(item)
    return item
