"""v16 tests: agent collaboration fabric + shared knowledge mesh."""
from datetime import datetime, timedelta, timezone
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.db.base import Base
from app.models import *
from app.services import agent_teams as teams_service
from app.services import collaboration_rooms as rooms_service
from app.services import delegation as delegation_service
from app.services import knowledge_mesh as mesh_service


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def seed(db):
    org = Organization(name="Nova Holding", slug="nova-v16"); db.add(org); db.commit(); db.refresh(org)
    labs = Company(organization_id=org.id, name="Nova Labs", industry="AI")
    media = Company(organization_id=org.id, name="Nova Media", industry="Media")
    db.add_all([labs, media]); db.commit(); db.refresh(labs); db.refresh(media)
    nina = Member(organization_id=org.id, company_id=labs.id, name="Nina", member_type="agent", role="Chief of Staff")
    dev = Member(organization_id=org.id, company_id=labs.id, name="Dex", member_type="agent", role="Engineer")
    writer = Member(organization_id=org.id, company_id=media.id, name="Mia", member_type="agent", role="Writer")
    outsider = Member(organization_id=org.id, company_id=media.id, name="Oli", member_type="agent", role="Intern")
    db.add_all([nina, dev, writer, outsider]); db.commit()
    for x in (nina, dev, writer, outsider): db.refresh(x)
    return org, labs, media, nina, dev, writer, outsider


def build_team(db, org, labs, nina, dev, writer, mode="round_robin"):
    team = teams_service.create_team(db, organization_id=org.id, company_id=labs.id, team_key="launch-crew",
                                     name="Launch Crew", mission="Ship the launch", lead_member_id=nina.id,
                                     collaboration_mode=mode, cross_company=True)
    teams_service.add_member(db, team, member_id=dev.id, team_role="contributor", capabilities=["code"])
    teams_service.add_member(db, team, member_id=writer.id, team_role="reviewer")
    return team


# ------------------------------------------------------------------- teams
def test_team_creation_registers_lead_and_roster():
    db = session(); org, labs, media, nina, dev, writer, _ = seed(db)
    team = build_team(db, org, labs, nina, dev, writer)
    roster = teams_service.active_members(db, team)
    assert [x.member_id for x in roster] == [nina.id, dev.id, writer.id]
    assert roster[0].team_role == "lead"


def test_team_rejects_foreign_organization_member():
    db = session(); org, labs, media, nina, dev, writer, _ = seed(db)
    other = Organization(name="Other", slug="other-v16"); db.add(other); db.commit(); db.refresh(other)
    stranger = Member(organization_id=other.id, name="Stranger", member_type="agent")
    db.add(stranger); db.commit(); db.refresh(stranger)
    team = build_team(db, org, labs, nina, dev, writer)
    with pytest.raises(teams_service.AgentTeamError):
        teams_service.add_member(db, team, member_id=stranger.id)


def test_round_robin_turn_selection_is_deterministic():
    db = session(); org, labs, media, nina, dev, writer, _ = seed(db)
    team = build_team(db, org, labs, nina, dev, writer)
    picks = [teams_service.next_turn_member(db, team, turn_index=i).member_id for i in range(4)]
    assert picks == [nina.id, dev.id, writer.id, nina.id]


# ------------------------------------------------------------------- rooms
def test_room_seeds_team_participants_and_records_turns():
    db = session(); org, labs, media, nina, dev, writer, _ = seed(db)
    team = build_team(db, org, labs, nina, dev, writer)
    room = rooms_service.open_room(db, organization_id=org.id, company_id=labs.id, team_id=team.id,
                                   room_key="launch-standup", topic="Launch standup", mode="round_robin",
                                   created_by_member_id=nina.id)
    assert len(rooms_service.room_roster(db, room)) == 3
    rooms_service.post_turn(db, room, member_id=nina.id, content="Plan for today")
    rooms_service.post_turn(db, room, member_id=dev.id, content="API is ready")
    turns = rooms_service.transcript(db, room)
    assert [x.sequence for x in turns] == [1, 2]
    assert room.turn_cursor == 2


def test_round_robin_blocks_out_of_turn_posts():
    db = session(); org, labs, media, nina, dev, writer, _ = seed(db)
    team = build_team(db, org, labs, nina, dev, writer)
    room = rooms_service.open_room(db, organization_id=org.id, team_id=team.id, room_key="r1", mode="round_robin",
                                   created_by_member_id=nina.id)
    with pytest.raises(rooms_service.CollaborationError):
        rooms_service.post_turn(db, room, member_id=writer.id, content="jumping the queue")


def test_non_participant_cannot_post():
    db = session(); org, labs, media, nina, dev, writer, outsider = seed(db)
    room = rooms_service.open_room(db, organization_id=org.id, room_key="r2", mode="free",
                                   created_by_member_id=nina.id)
    with pytest.raises(rooms_service.CollaborationError):
        rooms_service.post_turn(db, room, member_id=outsider.id, content="hello")


def test_decision_requires_decide_permission_and_closed_room_rejects_turns():
    db = session(); org, labs, media, nina, dev, writer, _ = seed(db)
    room = rooms_service.open_room(db, organization_id=org.id, room_key="r3", mode="free",
                                   created_by_member_id=nina.id)
    rooms_service.join_room(db, room, member_id=dev.id, can_post=True, can_decide=False)
    with pytest.raises(rooms_service.CollaborationError):
        rooms_service.post_turn(db, room, member_id=dev.id, content="we ship", turn_type="decision")
    rooms_service.post_turn(db, room, member_id=nina.id, content="we ship", turn_type="decision")
    rooms_service.close_room(db, room, summary="Shipped", member_id=nina.id)
    with pytest.raises(rooms_service.CollaborationError):
        rooms_service.post_turn(db, room, member_id=nina.id, content="late note")


# -------------------------------------------------------------- delegation
def test_delegation_happy_path():
    db = session(); org, labs, media, nina, dev, writer, _ = seed(db)
    item = delegation_service.propose(db, organization_id=org.id, company_id=labs.id, from_member_id=nina.id,
                                      to_member_id=dev.id, title="Build landing API",
                                      objective="Expose /v16/rooms", acceptance_criteria="tests pass",
                                      max_cost_usd=12.5)
    assert item.status == "proposed"
    delegation_service.accept(db, item, member_id=dev.id)
    delegation_service.deliver(db, item, member_id=dev.id, result_summary="done")
    delegation_service.close(db, item, member_id=nina.id, accepted=True)
    assert item.status == "completed" and item.closed_at is not None
    messages = db.query(AgentMessage).filter(AgentMessage.thread_key == f"delegation:{item.id}").all()
    assert len(messages) == 2


def test_delegation_rework_and_invalid_transitions():
    db = session(); org, labs, media, nina, dev, writer, _ = seed(db)
    item = delegation_service.propose(db, organization_id=org.id, from_member_id=nina.id, to_member_id=dev.id,
                                      title="Draft copy")
    with pytest.raises(delegation_service.DelegationError):
        delegation_service.deliver(db, item, member_id=dev.id)  # not accepted yet
    delegation_service.accept(db, item, member_id=dev.id)
    delegation_service.deliver(db, item, member_id=dev.id, result_summary="v1")
    delegation_service.close(db, item, member_id=nina.id, accepted=False, reason="needs rework")
    assert item.status == "accepted"
    with pytest.raises(delegation_service.DelegationError):
        delegation_service.close(db, item, member_id=dev.id, accepted=True)  # only delegator may close


def test_delegation_requires_room_membership_and_overdue_detection():
    db = session(); org, labs, media, nina, dev, writer, outsider = seed(db)
    room = rooms_service.open_room(db, organization_id=org.id, room_key="r4", mode="free",
                                   created_by_member_id=nina.id)
    with pytest.raises(delegation_service.DelegationError):
        delegation_service.propose(db, organization_id=org.id, from_member_id=nina.id, to_member_id=outsider.id,
                                   title="x", room_id=room.id)
    late = delegation_service.propose(db, organization_id=org.id, from_member_id=nina.id, to_member_id=dev.id,
                                      title="late task", deadline_at=utcnow() - timedelta(hours=3))
    overdue = delegation_service.overdue_contracts(db, org.id)
    assert [x.id for x in overdue] == [late.id]


# ---------------------------------------------------------- knowledge mesh
def test_knowledge_permission_is_deny_by_default_and_grant_driven():
    db = session(); org, labs, media, nina, dev, writer, outsider = seed(db)
    space = mesh_service.create_space(db, organization_id=org.id, owner_company_id=labs.id, slug="labs-playbook",
                                      name="Labs Playbook", classification="restricted")
    assert mesh_service.effective_permission(db, space, nina.id) == "contribute"  # owner company
    assert mesh_service.effective_permission(db, space, writer.id) == "none"
    mesh_service.grant_access(db, space, grantee_type="company", grantee_id=media.id, permission="read")
    assert mesh_service.effective_permission(db, space, writer.id) == "read"
    with pytest.raises(mesh_service.KnowledgeMeshError):
        mesh_service.contribute_entry(db, space, member_id=writer.id, title="x", content="y")
    denied = db.query(KnowledgeAccessLog).filter(KnowledgeAccessLog.action == "denied").count()
    assert denied == 1


def test_expired_grant_is_ignored_and_team_grant_applies():
    db = session(); org, labs, media, nina, dev, writer, outsider = seed(db)
    team = build_team(db, org, labs, nina, dev, writer)
    space = mesh_service.create_space(db, organization_id=org.id, owner_company_id=labs.id, slug="s2", name="S2")
    mesh_service.grant_access(db, space, grantee_type="member", grantee_id=outsider.id, permission="read",
                              expires_at=utcnow() - timedelta(minutes=1))
    assert mesh_service.effective_permission(db, space, outsider.id) == "none"
    mesh_service.grant_access(db, space, grantee_type="team", grantee_id=team.id, permission="contribute")
    assert mesh_service.effective_permission(db, space, writer.id) == "contribute"


def test_search_only_returns_readable_spaces_and_logs_access():
    db = session(); org, labs, media, nina, dev, writer, outsider = seed(db)
    open_space = mesh_service.create_space(db, organization_id=org.id, owner_company_id=labs.id, slug="open",
                                           name="Open", classification="org_public", default_permission="read")
    secret = mesh_service.create_space(db, organization_id=org.id, owner_company_id=labs.id, slug="secret",
                                       name="Secret", classification="confidential")
    mesh_service.contribute_entry(db, open_space, member_id=nina.id, title="Launch checklist",
                                  content="Ship the launch checklist", tags=["launch"])
    mesh_service.contribute_entry(db, secret, member_id=nina.id, title="Salary launch plan", content="launch secret")
    results = mesh_service.search(db, organization_id=org.id, member_id=outsider.id, query="launch")
    assert [x["space_slug"] for x in results] == ["open"]
    logs = db.query(KnowledgeAccessLog).filter(KnowledgeAccessLog.member_id == outsider.id,
                                               KnowledgeAccessLog.action == "search").count()
    assert logs == 1


def test_entry_versioning_supersedes_previous():
    db = session(); org, labs, media, nina, dev, writer, _ = seed(db)
    space = mesh_service.create_space(db, organization_id=org.id, owner_company_id=labs.id, slug="sop", name="SOP")
    first = mesh_service.contribute_entry(db, space, member_id=nina.id, title="SOP", content="v1",
                                          mirror_to_org_memory=True)
    second = mesh_service.contribute_entry(db, space, member_id=nina.id, title="SOP", content="v2",
                                           supersedes_entry_id=first.id)
    db.refresh(first)
    assert first.status == "superseded" and second.version == 2
    assert first.memory_id is not None


def test_room_summary_publishes_into_knowledge_mesh():
    db = session(); org, labs, media, nina, dev, writer, _ = seed(db)
    space = mesh_service.create_space(db, organization_id=org.id, owner_company_id=labs.id, slug="decisions",
                                      name="Decisions")
    room = rooms_service.open_room(db, organization_id=org.id, company_id=labs.id, room_key="r5", mode="free",
                                   topic="Pricing", created_by_member_id=nina.id)
    rooms_service.post_turn(db, room, member_id=nina.id, content="We pick tiered pricing", turn_type="decision")
    rooms_service.close_room(db, room, summary="Chose tiered pricing", member_id=nina.id)
    entry = mesh_service.publish_room_summary(db, space, member_id=nina.id, room_id=room.id,
                                              title="Room summary: Pricing", summary="Chose tiered pricing")
    assert entry.room_id == room.id and entry.entry_type == "decision"


def test_collaboration_events_are_emitted():
    db = session(); org, labs, media, nina, dev, writer, _ = seed(db)
    team = build_team(db, org, labs, nina, dev, writer)
    room = rooms_service.open_room(db, organization_id=org.id, team_id=team.id, room_key="r6", mode="round_robin",
                                   created_by_member_id=nina.id)
    rooms_service.post_turn(db, room, member_id=nina.id, content="kickoff")
    types = {x.event_type for x in db.query(CompanyEvent).all()}
    assert "agent.team.created" in types
    assert "collaboration.room.opened" in types
    assert "collaboration.turn.message" in types
