"""v16 agent-to-agent delegation contracts.

Delegation is an explicit, auditable state machine instead of an implicit
prompt instruction, so a founder can always answer: who asked whom to do what,
under which scope/budget/deadline, and what was actually delivered.
"""
import json
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from app.models import DelegationContract, CollaborationRoom, RoomParticipant, AgentTeam, Member, Task
from app.services.company_event_bus import emit_event
from app.services.agent_messaging import send_message


class DelegationError(Exception):
    pass


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


TRANSITIONS = {
    "proposed": ("accepted", "rejected", "cancelled"),
    "accepted": ("delivered", "cancelled"),
    "delivered": ("completed", "accepted"),  # returning to accepted = rework requested
    "rejected": (),
    "completed": (),
    "cancelled": (),
}


def _member(db: Session, organization_id: int, member_id: int, label: str) -> Member:
    item = db.get(Member, member_id)
    if not item or item.organization_id != organization_id:
        raise DelegationError(f"{label} member does not belong to organization")
    return item


def _check_transition(current: str, target: str):
    if target not in TRANSITIONS.get(current, ()):  # closed states have no transitions
        raise DelegationError(f"Invalid delegation transition {current} -> {target}")


def propose(db: Session, *, organization_id: int, from_member_id: int, to_member_id: int, title: str,
            objective: str = "", acceptance_criteria: str = "", company_id: int | None = None,
            room_id: int | None = None, team_id: int | None = None, task_id: int | None = None,
            scope: dict | None = None, max_cost_usd: float = 0.0,
            deadline_at: datetime | None = None) -> DelegationContract:
    if from_member_id == to_member_id:
        raise DelegationError("A member cannot delegate to itself")
    _member(db, organization_id, from_member_id, "Delegating")
    _member(db, organization_id, to_member_id, "Assignee")
    if room_id is not None:
        room = db.get(CollaborationRoom, room_id)
        if not room or room.organization_id != organization_id:
            raise DelegationError("Room does not belong to organization")
        for member_id in (from_member_id, to_member_id):
            joined = db.query(RoomParticipant).filter(RoomParticipant.room_id == room_id,
                                                      RoomParticipant.member_id == member_id,
                                                      RoomParticipant.status == "active").first()
            if not joined:
                raise DelegationError(f"Member {member_id} is not an active participant of the room")
    if team_id is not None:
        team = db.get(AgentTeam, team_id)
        if not team or team.organization_id != organization_id:
            raise DelegationError("Team does not belong to organization")
    if task_id is not None and not db.get(Task, task_id):
        raise DelegationError("Task not found")
    item = DelegationContract(organization_id=organization_id, company_id=company_id, room_id=room_id,
                              team_id=team_id, from_member_id=from_member_id, to_member_id=to_member_id,
                              task_id=task_id, title=title, objective=objective,
                              acceptance_criteria=acceptance_criteria,
                              scope_json=json.dumps(scope or {}, ensure_ascii=False, default=str),
                              max_cost_usd=float(max_cost_usd or 0.0), deadline_at=deadline_at,
                              status="proposed")
    db.add(item); db.commit(); db.refresh(item)
    send_message(db, organization_id=organization_id, company_id=company_id,
                 sender_member_id=from_member_id, recipient_member_id=to_member_id,
                 thread_key=f"delegation:{item.id}", subject=f"Delegation proposed: {title}",
                 content=objective or title, message_type="delegation", task_id=task_id,
                 context={"delegation_id": item.id, "acceptance_criteria": acceptance_criteria})
    emit_event(db, organization_id=organization_id, company_id=company_id,
               event_type="delegation.proposed", source="collaboration_fabric",
               aggregate_type="delegation_contract", aggregate_id=str(item.id),
               actor_member_id=from_member_id,
               payload={"to_member_id": to_member_id, "title": title, "max_cost_usd": item.max_cost_usd})
    return item


def _emit(db: Session, item: DelegationContract, event: str, actor_member_id: int, payload: dict):
    emit_event(db, organization_id=item.organization_id, company_id=item.company_id, event_type=event,
               source="collaboration_fabric", aggregate_type="delegation_contract", aggregate_id=str(item.id),
               actor_member_id=actor_member_id, payload=payload)


def accept(db: Session, item: DelegationContract, *, member_id: int, reason: str = "") -> DelegationContract:
    _check_transition(item.status, "accepted")
    if member_id != item.to_member_id:
        raise DelegationError("Only the assignee can accept this delegation")
    item.status = "accepted"; item.accepted_at = utcnow(); item.decision_reason = reason
    db.add(item); db.commit(); db.refresh(item)
    _emit(db, item, "delegation.accepted", member_id, {"reason": reason})
    return item


def reject(db: Session, item: DelegationContract, *, member_id: int, reason: str = "") -> DelegationContract:
    _check_transition(item.status, "rejected")
    if member_id != item.to_member_id:
        raise DelegationError("Only the assignee can reject this delegation")
    item.status = "rejected"; item.decision_reason = reason; item.closed_at = utcnow()
    db.add(item); db.commit(); db.refresh(item)
    _emit(db, item, "delegation.rejected", member_id, {"reason": reason})
    return item


def deliver(db: Session, item: DelegationContract, *, member_id: int, result_summary: str = "",
            delivery_artifact_id: int | None = None) -> DelegationContract:
    _check_transition(item.status, "delivered")
    if member_id != item.to_member_id:
        raise DelegationError("Only the assignee can deliver this delegation")
    item.status = "delivered"; item.delivered_at = utcnow(); item.result_summary = result_summary
    item.delivery_artifact_id = delivery_artifact_id
    db.add(item); db.commit(); db.refresh(item)
    send_message(db, organization_id=item.organization_id, company_id=item.company_id,
                 sender_member_id=item.to_member_id, recipient_member_id=item.from_member_id,
                 thread_key=f"delegation:{item.id}", subject=f"Delegation delivered: {item.title}",
                 content=result_summary or item.title, message_type="delegation_result",
                 artifact_id=delivery_artifact_id, context={"delegation_id": item.id})
    _emit(db, item, "delegation.delivered", member_id, {"artifact_id": delivery_artifact_id})
    return item


def close(db: Session, item: DelegationContract, *, member_id: int, accepted: bool = True,
          reason: str = "") -> DelegationContract:
    """Delegator reviews the delivery: complete it, or send it back for rework."""
    if member_id != item.from_member_id:
        raise DelegationError("Only the delegating member can close this delegation")
    target = "completed" if accepted else "accepted"
    _check_transition(item.status, target)
    item.status = target
    item.decision_reason = reason
    if accepted:
        item.closed_at = utcnow()
    else:
        item.delivered_at = None
    db.add(item); db.commit(); db.refresh(item)
    _emit(db, item, "delegation.completed" if accepted else "delegation.rework_requested",
          member_id, {"reason": reason})
    return item


def cancel(db: Session, item: DelegationContract, *, member_id: int, reason: str = "") -> DelegationContract:
    _check_transition(item.status, "cancelled")
    if member_id != item.from_member_id:
        raise DelegationError("Only the delegating member can cancel this delegation")
    item.status = "cancelled"; item.decision_reason = reason; item.closed_at = utcnow()
    db.add(item); db.commit(); db.refresh(item)
    _emit(db, item, "delegation.cancelled", member_id, {"reason": reason})
    return item


def overdue_contracts(db: Session, organization_id: int, now: datetime | None = None) -> list[DelegationContract]:
    moment = now or utcnow()
    return (db.query(DelegationContract)
            .filter(DelegationContract.organization_id == organization_id,
                    DelegationContract.status.in_(("proposed", "accepted")),
                    DelegationContract.deadline_at.isnot(None),
                    DelegationContract.deadline_at < moment)
            .order_by(DelegationContract.deadline_at.asc()).all())
