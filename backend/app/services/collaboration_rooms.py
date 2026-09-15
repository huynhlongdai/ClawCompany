"""v16 collaboration rooms.

A room is an ordered, append-only transcript shared by several members.
Turn ordering is deterministic and enforced server-side so concurrent agents
cannot silently interleave or overwrite each other.
"""
import json
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from app.models import (AgentTeam, CollaborationRoom, RoomParticipant, RoomTurn, Member)
from app.services.agent_teams import active_members
from app.services.company_event_bus import emit_event


class CollaborationError(Exception):
    pass


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


VALID_MODES = ("lead_routed", "round_robin", "free")
VALID_TURN_TYPES = ("message", "proposal", "decision", "handoff", "summary")


def open_room(db: Session, *, organization_id: int, room_key: str, topic: str = "", objective: str = "",
              company_id: int | None = None, team_id: int | None = None, project_id: int | None = None,
              mode: str = "lead_routed", max_turns: int = 200, created_by_member_id: int | None = None,
              seed_team_participants: bool = True) -> CollaborationRoom:
    if mode not in VALID_MODES:
        raise CollaborationError(f"Unsupported room mode: {mode}")
    if db.query(CollaborationRoom).filter(CollaborationRoom.organization_id == organization_id,
                                          CollaborationRoom.room_key == room_key).first():
        raise CollaborationError("Room key already exists in this organization")
    team = None
    if team_id is not None:
        team = db.get(AgentTeam, team_id)
        if not team or team.organization_id != organization_id:
            raise CollaborationError("Team does not belong to organization")
    room = CollaborationRoom(organization_id=organization_id, company_id=company_id, team_id=team_id,
                             project_id=project_id, room_key=room_key, topic=topic, objective=objective,
                             mode=mode, status="open", turn_cursor=0, max_turns=max_turns,
                             created_by_member_id=created_by_member_id)
    db.add(room); db.commit(); db.refresh(room)
    if team is not None and seed_team_participants:
        for seat, membership in enumerate(active_members(db, team), start=1):
            join_room(db, room, member_id=membership.member_id,
                      participant_role=membership.team_role,
                      can_post=membership.team_role != "observer",
                      can_decide=membership.team_role in ("lead", "reviewer"),
                      seat_order=seat, emit=False)
    elif created_by_member_id is not None:
        join_room(db, room, member_id=created_by_member_id, participant_role="lead",
                  can_post=True, can_decide=True, seat_order=1, emit=False)
    emit_event(db, organization_id=organization_id, company_id=company_id, event_type="collaboration.room.opened",
               source="collaboration_fabric", aggregate_type="collaboration_room", aggregate_id=str(room.id),
               actor_member_id=created_by_member_id,
               payload={"room_key": room_key, "mode": mode, "team_id": team_id, "topic": topic})
    return room


def join_room(db: Session, room: CollaborationRoom, *, member_id: int, participant_role: str = "contributor",
              can_post: bool = True, can_decide: bool = False, seat_order: int | None = None,
              emit: bool = True) -> RoomParticipant:
    if room.status == "closed":
        raise CollaborationError("Room is closed")
    member = db.get(Member, member_id)
    if not member or member.organization_id != room.organization_id:
        raise CollaborationError("Member does not belong to organization")
    existing = db.query(RoomParticipant).filter(RoomParticipant.room_id == room.id,
                                                RoomParticipant.member_id == member_id).first()
    if existing:
        existing.status = "active"; existing.participant_role = participant_role
        existing.can_post = can_post; existing.can_decide = can_decide
        db.add(existing); db.commit(); db.refresh(existing)
        return existing
    if seat_order is None:
        seat_order = db.query(RoomParticipant).filter(RoomParticipant.room_id == room.id).count() + 1
    item = RoomParticipant(organization_id=room.organization_id, room_id=room.id, member_id=member_id,
                           participant_role=participant_role, seat_order=seat_order, can_post=can_post,
                           can_decide=can_decide, status="active")
    db.add(item); db.commit(); db.refresh(item)
    if emit:
        emit_event(db, organization_id=room.organization_id, company_id=room.company_id,
                   event_type="collaboration.room.joined", source="collaboration_fabric",
                   aggregate_type="collaboration_room", aggregate_id=str(room.id), actor_member_id=member_id,
                   payload={"participant_role": participant_role})
    return item


def room_roster(db: Session, room: CollaborationRoom) -> list[RoomParticipant]:
    return (db.query(RoomParticipant)
            .filter(RoomParticipant.room_id == room.id, RoomParticipant.status == "active")
            .order_by(RoomParticipant.seat_order.asc(), RoomParticipant.id.asc()).all())


def expected_speaker(db: Session, room: CollaborationRoom) -> RoomParticipant | None:
    """Who is allowed to post the next turn, for ordered modes."""
    roster = [x for x in room_roster(db, room) if x.can_post]
    if not roster:
        return None
    if room.mode == "round_robin":
        return roster[room.turn_cursor % len(roster)]
    return None  # lead_routed and free modes are validated by role instead of position


def post_turn(db: Session, room: CollaborationRoom, *, member_id: int, content: str,
              turn_type: str = "message", references: dict | None = None,
              knowledge_entry_ids: list[int] | None = None) -> RoomTurn:
    if room.status != "open":
        raise CollaborationError(f"Room is {room.status}")
    if turn_type not in VALID_TURN_TYPES:
        raise CollaborationError(f"Unsupported turn type: {turn_type}")
    if not content.strip():
        raise CollaborationError("Turn content must not be empty")
    participant = db.query(RoomParticipant).filter(RoomParticipant.room_id == room.id,
                                                   RoomParticipant.member_id == member_id,
                                                   RoomParticipant.status == "active").first()
    if not participant:
        raise CollaborationError("Member is not an active participant of this room")
    if not participant.can_post:
        raise CollaborationError("Participant has no posting permission in this room")
    if turn_type == "decision" and not participant.can_decide:
        raise CollaborationError("Participant is not allowed to record a decision")
    if room.mode == "round_robin":
        turn_owner = expected_speaker(db, room)
        if turn_owner and turn_owner.member_id != member_id:
            raise CollaborationError(f"Out of turn: member {turn_owner.member_id} is expected to speak next")
    sequence = room.turn_cursor + 1
    if sequence > room.max_turns:
        raise CollaborationError("Room turn limit reached")
    turn = RoomTurn(organization_id=room.organization_id, room_id=room.id, sequence=sequence, member_id=member_id,
                    turn_type=turn_type, content=content,
                    references_json=json.dumps(references or {}, ensure_ascii=False, default=str),
                    knowledge_entry_ids_json=json.dumps(knowledge_entry_ids or []))
    db.add(turn)
    room.turn_cursor = sequence
    db.add(room)
    db.commit(); db.refresh(turn); db.refresh(room)
    emit_event(db, organization_id=room.organization_id, company_id=room.company_id,
               event_type=f"collaboration.turn.{turn_type}", source="collaboration_fabric",
               aggregate_type="collaboration_room", aggregate_id=str(room.id), actor_member_id=member_id,
               payload={"turn_id": turn.id, "sequence": sequence, "turn_type": turn_type})
    return turn


def transcript(db: Session, room: CollaborationRoom, limit: int = 200) -> list[RoomTurn]:
    return (db.query(RoomTurn).filter(RoomTurn.room_id == room.id)
            .order_by(RoomTurn.sequence.asc()).limit(max(1, min(limit, 1000))).all())


def close_room(db: Session, room: CollaborationRoom, *, summary: str = "",
               member_id: int | None = None) -> CollaborationRoom:
    if room.status == "closed":
        raise CollaborationError("Room is already closed")
    room.status = "closed"; room.summary = summary; room.closed_at = utcnow()
    db.add(room); db.commit(); db.refresh(room)
    emit_event(db, organization_id=room.organization_id, company_id=room.company_id,
               event_type="collaboration.room.closed", source="collaboration_fabric",
               aggregate_type="collaboration_room", aggregate_id=str(room.id), actor_member_id=member_id,
               payload={"summary": summary, "turns": room.turn_cursor})
    return room
