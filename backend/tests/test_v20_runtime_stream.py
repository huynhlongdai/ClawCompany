"""v20 tests: long-lived session streams, approval bridge, auto-dispatch.

The interesting failures here are not "does the code run" but "does a run that
outlives its HTTP request still land in the database": terminal states must
move the task inside the board vocabulary, gateway permission prompts must
become approval rows exactly once, and a resolution must update the existing
row instead of creating a second one.
"""
import asyncio
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
import app.models  # noqa: F401
from app.models import Agent, Approval, Company, CompanyEvent, Member, Organization, Project, Task
from app.runtime import openclaw_protocol as ocp
from app.services import runtime_stream as rs


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def world(db):
    org = Organization(name="Nova Holding", slug="nova-holding")
    db.add(org); db.commit(); db.refresh(org)
    labs = Company(organization_id=org.id, name="Nova Labs", industry="AI Products", status="active")
    db.add(labs); db.commit(); db.refresh(labs)
    nina = Member(organization_id=org.id, company_id=labs.id, name="Nina", member_type="agent",
                  role="Chief of Staff", status="active")
    db.add(nina); db.commit(); db.refresh(nina)
    agent = Agent(member_id=nina.id, runtime_provider="openclaw", runtime_agent_id="nina", lifecycle="active")
    db.add(agent); db.commit(); db.refresh(agent)
    project = Project(company_id=labs.id, name="Launch", status="active", progress=0)
    db.add(project); db.commit(); db.refresh(project)
    task = Task(project_id=project.id, title="Draft launch plan", assignee_member_id=nina.id,
                status="in_progress", priority="high",
                runtime_session_key=ocp.task_session_key("nina", 1))
    db.add(task); db.commit(); db.refresh(task)
    return {"org": org, "labs": labs, "nina": nina, "agent": agent, "project": project, "task": task}


def _state(world):
    return rs.ConsumerState(session_key=world["task"].runtime_session_key,
                            task_id=world["task"].id,
                            organization_id=world["org"].id)


def _event(family, state="", **payload):
    return {"type": f"{family}.{state}" if state else family, "family": family, "state": state,
            "terminal": state in ocp.TERMINAL_STATES, "error": state in ocp.ERROR_STATES,
            "sessionKey": "agent:nina:company-task-1", "raw": payload}


# --- terminal states ------------------------------------------------------

def test_completed_run_moves_task_to_review_not_done(db, world):
    """The agent finishing is not the company accepting the work."""
    rs.handle_event(db, _state(world), _event(ocp.E_CHAT, "complete"))
    db.refresh(world["task"])
    assert world["task"].status == "review"


def test_failed_run_blocks_the_task(db, world):
    rs.handle_event(db, _state(world), _event(ocp.E_CHAT, "error", errorMessage="model timeout"))
    db.refresh(world["task"])
    assert world["task"].status == "blocked"


def test_aborted_run_parks_the_task_back_on_the_board(db, world):
    rs.handle_event(db, _state(world), _event(ocp.E_CHAT, "aborted"))
    db.refresh(world["task"])
    assert world["task"].status == "todo"


def test_terminal_status_map_only_uses_board_vocabulary(db):
    from app.services.workspace_ops import TASK_STATUSES
    allowed = set(TASK_STATUSES) | {"blocked"}
    assert set(rs.TERMINAL_STATUS.values()) <= allowed


def test_non_terminal_event_leaves_status_alone(db, world):
    rs.handle_event(db, _state(world), _event(ocp.E_SESSION_MESSAGE, "delta", deltaText="thinking"))
    db.refresh(world["task"])
    assert world["task"].status == "in_progress"


# --- persistence ----------------------------------------------------------

def test_every_event_is_persisted_with_task_and_session(db, world):
    from app.models import RuntimeEvent
    state = _state(world)
    rs.handle_event(db, state, _event(ocp.E_SESSION_TOOL, "start", tool="read_file"))
    row = db.query(RuntimeEvent).one()
    assert row.task_id == world["task"].id
    assert row.runtime_session_key == state.session_key
    assert row.agent_id == world["agent"].id


# --- approval bridge ------------------------------------------------------

def test_permission_prompt_becomes_a_pending_approval(db, world):
    state = _state(world)
    rs.handle_event(db, state, _event(ocp.E_SESSION_APPROVAL, "", id="req-1", tool="fs_write"))
    approval = db.query(Approval).one()
    assert approval.status == "pending"
    assert approval.policy_key.startswith("openclaw:")
    assert approval.company_id == world["labs"].id
    assert state.approvals == 1


def test_denied_tool_prompt_is_marked_high_risk(db, world):
    rs.handle_event(db, _state(world), _event(ocp.E_SESSION_APPROVAL, "", id="req-1", tool="exec"))
    assert db.query(Approval).one().risk == "high"


def test_repeated_prompt_does_not_duplicate_the_queue(db, world):
    state = _state(world)
    for _ in range(3):
        rs.handle_event(db, state, _event(ocp.E_SESSION_APPROVAL, "", id="req-1", tool="fs_write"))
    assert db.query(Approval).count() == 1


def test_resolution_in_openclaw_updates_the_existing_row(db, world):
    state = _state(world)
    rs.handle_event(db, state, _event(ocp.E_SESSION_APPROVAL, "", id="req-1", tool="fs_write"))
    rs.handle_event(db, state, _event(ocp.E_SESSION_APPROVAL, "", id="req-1", decision="approved"))
    approvals = db.query(Approval).all()
    assert len(approvals) == 1
    assert approvals[0].status == "approved"
    assert "OpenClaw" in approvals[0].resolution_note


def test_resolution_without_a_known_request_is_ignored(db, world):
    rs.handle_event(db, _state(world), _event(ocp.E_SESSION_APPROVAL, "", id="ghost", decision="denied"))
    assert db.query(Approval).count() == 0


def test_approval_evidence_keeps_the_raw_prompt(db, world):
    rs.handle_event(db, _state(world), _event(ocp.E_SESSION_APPROVAL, "", id="req-1", tool="fs_write"))
    evidence = json.loads(db.query(Approval).one().evidence)
    assert evidence["session_key"] == world["task"].runtime_session_key
    assert evidence["event"]["tool"] == "fs_write"


# --- supervisor bookkeeping ----------------------------------------------

def test_supervisor_deduplicates_followers_per_session():
    async def scenario():
        sup = rs.StreamSupervisor()

        async def never_ends():
            await asyncio.sleep(3600)

        sup._tasks["agent:nina:main"] = asyncio.create_task(never_ends())
        sup._state["agent:nina:main"] = rs.ConsumerState("agent:nina:main", None, 1)
        assert sup.is_following("agent:nina:main")
        first = sup.follow(session_key="agent:nina:main", organization_id=1)
        assert first is sup._state["agent:nina:main"]
        assert sup.stop("agent:nina:main") is True
        assert sup._state["agent:nina:main"].status == "stopped"

    asyncio.run(scenario())


def test_snapshot_is_scoped_to_one_organization():
    sup = rs.StreamSupervisor()
    sup._state["a"] = rs.ConsumerState("a", None, 1)
    sup._state["b"] = rs.ConsumerState("b", None, 2)
    assert [r["session_key"] for r in sup.snapshot(1)] == ["a"]
    assert len(sup.snapshot()) == 2


def test_stream_state_never_exposes_the_gateway_token():
    state = rs.ConsumerState("agent:nina:main", 1, 1)
    assert "token" not in json.dumps(state.public()).lower()
