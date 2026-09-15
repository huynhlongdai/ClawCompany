from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.core.authz import Principal, enforce_org, require_role, require_scope
from app.core.tenancy import active_org
from app.models import (AgentTeam, AgentTeamMember, CollaborationRoom, RoomParticipant, RoomTurn,
                        DelegationContract, SharedKnowledgeSpace, KnowledgeGrant, SharedKnowledgeEntry,
                        KnowledgeAccessLog)
from app.schemas.v16 import *
from app.services import agent_teams as teams_service
from app.services import collaboration_rooms as rooms_service
from app.services import delegation as delegation_service
from app.services import knowledge_mesh as mesh_service

router = APIRouter(prefix="/v16", tags=["v16-agent-collaboration-mesh"])


def _team(db, team_id, p) -> AgentTeam:
    x = db.get(AgentTeam, team_id)
    if not x: raise HTTPException(404, "Agent team not found")
    enforce_org(x.organization_id, p); return x


def _room(db, room_id, p) -> CollaborationRoom:
    x = db.get(CollaborationRoom, room_id)
    if not x: raise HTTPException(404, "Collaboration room not found")
    enforce_org(x.organization_id, p); return x


def _contract(db, contract_id, p) -> DelegationContract:
    x = db.get(DelegationContract, contract_id)
    if not x: raise HTTPException(404, "Delegation contract not found")
    enforce_org(x.organization_id, p); return x


def _space(db, space_id, p) -> SharedKnowledgeSpace:
    x = db.get(SharedKnowledgeSpace, space_id)
    if not x: raise HTTPException(404, "Knowledge space not found")
    enforce_org(x.organization_id, p); return x


# ---------------------------------------------------------------- agent teams
@router.post("/teams")
def create_team(payload: AgentTeamCreate, principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    enforce_org(payload.organization_id, principal)
    try: return teams_service.create_team(db, **payload.model_dump())
    except teams_service.AgentTeamError as exc: raise HTTPException(409, str(exc))


@router.get("/teams")
def list_teams(principal: Principal = Depends(require_scope("company.collaboration:read")), db: Session = Depends(get_db)):
    return db.query(AgentTeam).filter(AgentTeam.organization_id == active_org(principal)).order_by(AgentTeam.id.desc()).limit(500).all()


@router.get("/teams/{team_id}")
def get_team(team_id: int, principal: Principal = Depends(require_scope("company.collaboration:read")), db: Session = Depends(get_db)):
    team = _team(db, team_id, principal)
    return {"team": team, "members": teams_service.active_members(db, team)}


@router.post("/teams/{team_id}/members")
def add_team_member(team_id: int, payload: AgentTeamMemberAdd, principal: Principal = Depends(require_scope("company.collaboration:write")), db: Session = Depends(get_db)):
    team = _team(db, team_id, principal)
    try: return teams_service.add_member(db, team, **payload.model_dump())
    except teams_service.AgentTeamError as exc: raise HTTPException(409, str(exc))


@router.delete("/teams/{team_id}/members/{member_id}")
def remove_team_member(team_id: int, member_id: int, principal: Principal = Depends(require_scope("company.collaboration:write")), db: Session = Depends(get_db)):
    team = _team(db, team_id, principal)
    try: return teams_service.remove_member(db, team, member_id)
    except teams_service.AgentTeamError as exc: raise HTTPException(409, str(exc))


# --------------------------------------------------------- collaboration rooms
@router.post("/rooms")
def open_room(payload: CollaborationRoomCreate, principal: Principal = Depends(require_scope("company.collaboration:write")), db: Session = Depends(get_db)):
    enforce_org(payload.organization_id, principal)
    try: return rooms_service.open_room(db, **payload.model_dump())
    except rooms_service.CollaborationError as exc: raise HTTPException(409, str(exc))


@router.get("/rooms")
def list_rooms(status: str | None = None, principal: Principal = Depends(require_scope("company.collaboration:read")), db: Session = Depends(get_db)):
    q = db.query(CollaborationRoom).filter(CollaborationRoom.organization_id == active_org(principal))
    if status: q = q.filter(CollaborationRoom.status == status)
    return q.order_by(CollaborationRoom.id.desc()).limit(500).all()


@router.get("/rooms/{room_id}")
def get_room(room_id: int, principal: Principal = Depends(require_scope("company.collaboration:read")), db: Session = Depends(get_db)):
    room = _room(db, room_id, principal)
    speaker = rooms_service.expected_speaker(db, room)
    return {"room": room, "participants": rooms_service.room_roster(db, room),
            "turns": rooms_service.transcript(db, room),
            "expected_speaker_member_id": speaker.member_id if speaker else None}


@router.post("/rooms/{room_id}/participants")
def join_room(room_id: int, payload: RoomParticipantAdd, principal: Principal = Depends(require_scope("company.collaboration:write")), db: Session = Depends(get_db)):
    room = _room(db, room_id, principal)
    try: return rooms_service.join_room(db, room, **payload.model_dump())
    except rooms_service.CollaborationError as exc: raise HTTPException(409, str(exc))


@router.post("/rooms/{room_id}/turns")
def post_turn(room_id: int, payload: RoomTurnCreate, principal: Principal = Depends(require_scope("company.collaboration:write")), db: Session = Depends(get_db)):
    room = _room(db, room_id, principal)
    if principal.auth_type == "api_key" and principal.member_id and principal.member_id != payload.member_id:
        raise HTTPException(403, "API key is bound to a different member identity")
    try: return rooms_service.post_turn(db, room, **payload.model_dump())
    except rooms_service.CollaborationError as exc: raise HTTPException(409, str(exc))


@router.post("/rooms/{room_id}/close")
def close_room(room_id: int, payload: RoomCloseRequest, principal: Principal = Depends(require_scope("company.collaboration:write")), db: Session = Depends(get_db)):
    room = _room(db, room_id, principal)
    try:
        closed = rooms_service.close_room(db, room, summary=payload.summary, member_id=payload.member_id)
    except rooms_service.CollaborationError as exc:
        raise HTTPException(409, str(exc))
    published = None
    if payload.publish_to_space_id and payload.member_id:
        space = _space(db, payload.publish_to_space_id, principal)
        try:
            published = mesh_service.publish_room_summary(db, space, member_id=payload.member_id, room_id=room.id,
                                                          title=f"Room summary: {room.topic or room.room_key}",
                                                          summary=payload.summary)
        except mesh_service.KnowledgeMeshError as exc:
            raise HTTPException(403, str(exc))
    return {"room": closed, "published_entry": published}


# -------------------------------------------------------- delegation contracts
@router.post("/delegations")
def propose_delegation(payload: DelegationProposeRequest, principal: Principal = Depends(require_scope("company.delegation:write")), db: Session = Depends(get_db)):
    enforce_org(payload.organization_id, principal)
    if principal.auth_type == "api_key" and principal.member_id and principal.member_id != payload.from_member_id:
        raise HTTPException(403, "API key is bound to a different member identity")
    try: return delegation_service.propose(db, **payload.model_dump())
    except delegation_service.DelegationError as exc: raise HTTPException(409, str(exc))


@router.get("/delegations")
def list_delegations(status: str | None = None, member_id: int | None = None,
                     principal: Principal = Depends(require_scope("company.delegation:read")), db: Session = Depends(get_db)):
    q = db.query(DelegationContract).filter(DelegationContract.organization_id == active_org(principal))
    if status: q = q.filter(DelegationContract.status == status)
    if member_id: q = q.filter((DelegationContract.from_member_id == member_id) | (DelegationContract.to_member_id == member_id))
    return q.order_by(DelegationContract.id.desc()).limit(500).all()


def _delegation_action(db, contract_id, principal, action, **kwargs):
    item = _contract(db, contract_id, principal)
    try: return action(db, item, **kwargs)
    except delegation_service.DelegationError as exc: raise HTTPException(409, str(exc))


@router.post("/delegations/{contract_id}/accept")
def accept_delegation(contract_id: int, payload: DelegationDecisionRequest, principal: Principal = Depends(require_scope("company.delegation:write")), db: Session = Depends(get_db)):
    return _delegation_action(db, contract_id, principal, delegation_service.accept, member_id=payload.member_id, reason=payload.reason)


@router.post("/delegations/{contract_id}/reject")
def reject_delegation(contract_id: int, payload: DelegationDecisionRequest, principal: Principal = Depends(require_scope("company.delegation:write")), db: Session = Depends(get_db)):
    return _delegation_action(db, contract_id, principal, delegation_service.reject, member_id=payload.member_id, reason=payload.reason)


@router.post("/delegations/{contract_id}/deliver")
def deliver_delegation(contract_id: int, payload: DelegationDeliverRequest, principal: Principal = Depends(require_scope("company.delegation:write")), db: Session = Depends(get_db)):
    return _delegation_action(db, contract_id, principal, delegation_service.deliver, member_id=payload.member_id,
                              result_summary=payload.result_summary, delivery_artifact_id=payload.delivery_artifact_id)


@router.post("/delegations/{contract_id}/close")
def close_delegation(contract_id: int, payload: DelegationCompleteRequest, principal: Principal = Depends(require_scope("company.delegation:write")), db: Session = Depends(get_db)):
    return _delegation_action(db, contract_id, principal, delegation_service.close, member_id=payload.member_id,
                              accepted=payload.accepted, reason=payload.reason)


@router.get("/delegations/overdue")
def overdue_delegations(principal: Principal = Depends(require_scope("company.delegation:read")), db: Session = Depends(get_db)):
    return delegation_service.overdue_contracts(db, active_org(principal))


# ------------------------------------------------------------- knowledge mesh
@router.post("/knowledge-spaces")
def create_space(payload: KnowledgeSpaceCreate, principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    enforce_org(payload.organization_id, principal)
    try: return mesh_service.create_space(db, **payload.model_dump())
    except mesh_service.KnowledgeMeshError as exc: raise HTTPException(409, str(exc))


@router.get("/knowledge-spaces")
def list_spaces(principal: Principal = Depends(require_scope("company.knowledge_mesh:read")), db: Session = Depends(get_db)):
    return db.query(SharedKnowledgeSpace).filter(SharedKnowledgeSpace.organization_id == active_org(principal)).order_by(SharedKnowledgeSpace.id.desc()).all()


@router.post("/knowledge-spaces/{space_id}/grants")
def create_grant(space_id: int, payload: KnowledgeGrantCreate, principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    space = _space(db, space_id, principal)
    try: return mesh_service.grant_access(db, space, **payload.model_dump())
    except mesh_service.KnowledgeMeshError as exc: raise HTTPException(409, str(exc))


@router.get("/knowledge-spaces/{space_id}/grants")
def list_grants(space_id: int, principal: Principal = Depends(require_scope("company.knowledge_mesh:read")), db: Session = Depends(get_db)):
    space = _space(db, space_id, principal)
    return db.query(KnowledgeGrant).filter(KnowledgeGrant.space_id == space.id).order_by(KnowledgeGrant.id.desc()).all()


@router.delete("/knowledge-grants/{grant_id}")
def revoke_grant(grant_id: int, principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    item = db.get(KnowledgeGrant, grant_id)
    if not item: raise HTTPException(404, "Knowledge grant not found")
    enforce_org(item.organization_id, principal)
    return mesh_service.revoke_grant(db, item)


@router.get("/knowledge-spaces/{space_id}/permission")
def check_permission(space_id: int, member_id: int, principal: Principal = Depends(require_scope("company.knowledge_mesh:read")), db: Session = Depends(get_db)):
    space = _space(db, space_id, principal)
    return {"space_id": space.id, "member_id": member_id,
            "permission": mesh_service.effective_permission(db, space, member_id)}


@router.post("/knowledge-spaces/{space_id}/entries")
def contribute_entry(space_id: int, payload: KnowledgeEntryCreate, principal: Principal = Depends(require_scope("company.knowledge_mesh:write")), db: Session = Depends(get_db)):
    space = _space(db, space_id, principal)
    if principal.auth_type == "api_key" and principal.member_id and principal.member_id != payload.member_id:
        raise HTTPException(403, "API key is bound to a different member identity")
    try: return mesh_service.contribute_entry(db, space, **payload.model_dump())
    except mesh_service.KnowledgeMeshError as exc: raise HTTPException(403, str(exc))


@router.post("/knowledge-mesh/search")
def search_mesh(payload: KnowledgeSearchRequest, principal: Principal = Depends(require_scope("company.knowledge_mesh:read")), db: Session = Depends(get_db)):
    if principal.auth_type == "api_key" and principal.member_id and principal.member_id != payload.member_id:
        raise HTTPException(403, "API key is bound to a different member identity")
    return {"results": mesh_service.search(db, organization_id=active_org(principal), member_id=payload.member_id,
                                            query=payload.query, space_ids=payload.space_ids, limit=payload.limit)}


@router.get("/knowledge-mesh/access-logs")
def access_logs(space_id: int | None = None, principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    q = db.query(KnowledgeAccessLog).filter(KnowledgeAccessLog.organization_id == active_org(principal))
    if space_id: q = q.filter(KnowledgeAccessLog.space_id == space_id)
    return q.order_by(KnowledgeAccessLog.id.desc()).limit(300).all()


# ------------------------------------------------------------------- overview
@router.get("/collaboration/summary")
def collaboration_summary(principal: Principal = Depends(require_scope("company.collaboration:read")), db: Session = Depends(get_db)):
    org = active_org(principal)
    def count(model, *filters):
        return db.query(model).filter(model.organization_id == org, *filters).count()
    return {
        "teams_active": count(AgentTeam, AgentTeam.status == "active"),
        "rooms_open": count(CollaborationRoom, CollaborationRoom.status == "open"),
        "turns_total": count(RoomTurn),
        "delegations_open": count(DelegationContract, DelegationContract.status.in_(("proposed", "accepted", "delivered"))),
        "delegations_completed": count(DelegationContract, DelegationContract.status == "completed"),
        "knowledge_spaces": count(SharedKnowledgeSpace, SharedKnowledgeSpace.status == "active"),
        "knowledge_entries": count(SharedKnowledgeEntry, SharedKnowledgeEntry.status == "active"),
        "knowledge_denials": count(KnowledgeAccessLog, KnowledgeAccessLog.action == "denied"),
        "team_memberships": count(AgentTeamMember, AgentTeamMember.status == "active"),
        "room_participants": count(RoomParticipant, RoomParticipant.status == "active"),
    }
