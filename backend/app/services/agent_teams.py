"""v16 agent team (crew) management.

Teams are tenant-bound. Every member added to a team must belong to the same
organization, and a cross-company team must be explicitly marked as such.
"""
import json
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from app.models import AgentTeam, AgentTeamMember, Member
from app.services.company_event_bus import emit_event


class AgentTeamError(Exception):
    pass


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


VALID_MODES = ("lead_routed", "round_robin", "parallel")
VALID_TEAM_ROLES = ("lead", "contributor", "reviewer", "observer")


def create_team(db: Session, *, organization_id: int, team_key: str, name: str, mission: str = "",
                company_id: int | None = None, lead_member_id: int | None = None,
                collaboration_mode: str = "lead_routed", cross_company: bool = False) -> AgentTeam:
    if collaboration_mode not in VALID_MODES:
        raise AgentTeamError(f"Unsupported collaboration mode: {collaboration_mode}")
    existing = db.query(AgentTeam).filter(AgentTeam.organization_id == organization_id,
                                          AgentTeam.team_key == team_key).first()
    if existing:
        raise AgentTeamError("Team key already exists in this organization")
    if lead_member_id is not None:
        lead = db.get(Member, lead_member_id)
        if not lead or lead.organization_id != organization_id:
            raise AgentTeamError("Lead member does not belong to organization")
    team = AgentTeam(organization_id=organization_id, company_id=company_id, team_key=team_key, name=name,
                     mission=mission, lead_member_id=lead_member_id, collaboration_mode=collaboration_mode,
                     cross_company=bool(cross_company), status="active")
    db.add(team); db.commit(); db.refresh(team)
    if lead_member_id is not None:
        add_member(db, team, member_id=lead_member_id, team_role="lead", emit=False)
    emit_event(db, organization_id=organization_id, company_id=company_id, event_type="agent.team.created",
               source="collaboration_fabric", aggregate_type="agent_team", aggregate_id=str(team.id),
               payload={"team_key": team_key, "mode": collaboration_mode, "cross_company": bool(cross_company)})
    return team


def add_member(db: Session, team: AgentTeam, *, member_id: int, team_role: str = "contributor",
               capabilities: list[str] | None = None, allocation_percent: int = 100,
               emit: bool = True) -> AgentTeamMember:
    if team.status != "active":
        raise AgentTeamError("Team is not active")
    if team_role not in VALID_TEAM_ROLES:
        raise AgentTeamError(f"Unsupported team role: {team_role}")
    member = db.get(Member, member_id)
    if not member or member.organization_id != team.organization_id:
        raise AgentTeamError("Member does not belong to organization")
    if (not team.cross_company) and team.company_id and member.company_id and member.company_id != team.company_id:
        raise AgentTeamError("Cross-company membership requires cross_company=true on the team")
    existing = db.query(AgentTeamMember).filter(AgentTeamMember.team_id == team.id,
                                                AgentTeamMember.member_id == member_id).first()
    if existing:
        existing.team_role = team_role
        existing.status = "active"
        existing.left_at = None
        existing.allocation_percent = allocation_percent
        existing.capabilities_json = json.dumps(capabilities or [], ensure_ascii=False)
        db.add(existing); db.commit(); db.refresh(existing)
        return existing
    next_order = (db.query(AgentTeamMember).filter(AgentTeamMember.team_id == team.id).count()) + 1
    item = AgentTeamMember(organization_id=team.organization_id, team_id=team.id, member_id=member_id,
                           team_role=team_role, capabilities_json=json.dumps(capabilities or [], ensure_ascii=False),
                           turn_order=next_order, allocation_percent=allocation_percent, status="active")
    db.add(item); db.commit(); db.refresh(item)
    if emit:
        emit_event(db, organization_id=team.organization_id, company_id=team.company_id,
                   event_type="agent.team.member_added", source="collaboration_fabric",
                   aggregate_type="agent_team", aggregate_id=str(team.id),
                   payload={"member_id": member_id, "team_role": team_role})
    return item


def remove_member(db: Session, team: AgentTeam, member_id: int) -> AgentTeamMember:
    item = db.query(AgentTeamMember).filter(AgentTeamMember.team_id == team.id,
                                            AgentTeamMember.member_id == member_id,
                                            AgentTeamMember.status == "active").first()
    if not item:
        raise AgentTeamError("Active team membership not found")
    item.status = "left"; item.left_at = utcnow()
    db.add(item); db.commit(); db.refresh(item)
    return item


def active_members(db: Session, team: AgentTeam) -> list[AgentTeamMember]:
    return (db.query(AgentTeamMember)
            .filter(AgentTeamMember.team_id == team.id, AgentTeamMember.status == "active")
            .order_by(AgentTeamMember.turn_order.asc(), AgentTeamMember.id.asc()).all())


def next_turn_member(db: Session, team: AgentTeam, *, turn_index: int) -> AgentTeamMember | None:
    """Deterministic turn selection used by round_robin teams."""
    roster = [x for x in active_members(db, team) if x.team_role != "observer"]
    if not roster:
        return None
    return roster[turn_index % len(roster)]


def disband_team(db: Session, team: AgentTeam) -> AgentTeam:
    team.status = "disbanded"; team.disbanded_at = utcnow()
    db.add(team); db.commit(); db.refresh(team)
    return team
