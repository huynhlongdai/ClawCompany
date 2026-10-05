"""v19 tests: alignment with the real OpenClaw gateway contract.

These cover the things that would silently break against a live gateway:
session-key shape, the legacy-contract map, the HTTP deny list, seat binding,
and dispatch keeping the task inside the board vocabulary (the old
`services.tasks.dispatch_task` set status="running", which no board column
knows about).
"""
import asyncio

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
import app.models  # noqa: F401
from app.models import Agent, Company, CompanyEvent, Member, Organization, Project, Task
from app.runtime import openclaw_protocol as ocp
from app.runtime.openclaw_native import NativeOpenClawRuntime, OpenClawToolDenied, normalize_event
from app.services import agent_dispatch, openclaw_alignment as align
from app.services import workspace_ops as ops


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
    human = Member(organization_id=org.id, company_id=labs.id, name="Long", member_type="human",
                   role="Founder", status="active")
    db.add_all([nina, human]); db.commit(); db.refresh(nina); db.refresh(human)
    agent = Agent(member_id=nina.id, runtime_provider="openclaw", runtime_agent_id="nina", lifecycle="active")
    db.add(agent); db.commit(); db.refresh(agent)
    project = Project(company_id=labs.id, name="Launch", status="active", progress=0)
    db.add(project); db.commit(); db.refresh(project)
    task = Task(project_id=project.id, title="Draft launch plan", description="Outline the plan",
                assignee_member_id=nina.id, status="todo", priority="high")
    db.add(task); db.commit(); db.refresh(task)
    return {"org": org, "labs": labs, "nina": nina, "human": human, "agent": agent,
            "project": project, "task": task}


# --- protocol facts -------------------------------------------------------

def test_session_keys_follow_upstream_shape():
    assert ocp.main_session_key("nina") == "agent:nina:main"
    assert ocp.task_session_key("nina", 42) == "agent:nina:company-task-42"
    assert ocp.agent_id_from_session_key("agent:nina:main") == "nina"
    assert ocp.agent_id_from_session_key("global") is None


def test_legacy_contract_map_covers_every_invented_method():
    invented = {"agents.create", "agents.run", "runs.cancel", "gateway.status", "runs.subscribe"}
    assert invented == set(ocp.LEGACY_CONTRACT_MAP)
    assert ocp.LEGACY_CONTRACT_MAP["agents.run"]["upstream"].endswith(ocp.M_CHAT_SEND)


def test_agents_create_is_a_real_upstream_method():
    """WP-1.1: sửa một assertion đang ghim đúng niềm tin sai.

    Assertion cũ ở đây là ``LEGACY_CONTRACT_MAP["agents.create"]["upstream"] is
    None``, tức nó *canh giữ* mệnh đề "OpenClaw không có RPC tạo agent". Mệnh đề
    đó sai với 2026.9.4: ``docs/gateway/protocol/rpc-talk-config-and-agents.md``
    ghi "agents.create, agents.update, and agents.delete manage agent records and
    workspace wiring".

    Đây là **lỗi code, không phải lỗi test** — nhưng test cũ khiến việc sửa code
    làm suite đỏ, nên nó đã góp phần giữ lỗi sống sót. Cùng dạng với lỗi
    ``live_channel`` mà lượt tiếp nhận đã gặp: test grep/ghim niềm tin thay vì
    kiểm hành vi thì nó bảo tồn lỗi.
    """
    entry = ocp.LEGACY_CONTRACT_MAP["agents.create"]
    assert entry["upstream"] == ocp.M_AGENTS_CREATE == "agents.create"
    # Vết sửa phải đọc được, để người sau biết niềm tin nào vừa bị thay.
    assert entry["previous_claim"] == "no upstream equivalent"
    assert entry["corrected_on"] == "2026-09-16"
    # Còn agents.run thì vẫn không có thật — đừng "sửa" quá tay.
    assert not any(m == "agents.run" for m in ocp.METHOD_SCOPES)


def test_company_scopes_stay_narrow():
    assert set(ocp.COMPANY_SCOPES) <= set(ocp.OPERATOR_SCOPES)
    assert "operator.admin" not in ocp.COMPANY_SCOPES
    assert "operator.talk.secrets" not in ocp.COMPANY_SCOPES


def test_deny_list_blocks_host_mutating_tools():
    for tool in ("exec", "shell", "fs_write", "apply_patch", "gateway"):
        assert tool in ocp.HTTP_DENIED_TOOLS
    assert ocp.OWNER_ONLY_TOOLS <= ocp.HTTP_DENIED_TOOLS


def test_invoke_tool_refuses_denied_tool_before_any_network_call():
    runtime = NativeOpenClawRuntime()
    with pytest.raises(OpenClawToolDenied):
        asyncio.run(runtime.invoke_tool("exec", {"cmd": "rm -rf /"}))


def test_normalize_event_marks_terminal_and_error_states():
    running = normalize_event({"event": "chat", "payload": {"state": "delta", "deltaText": "hi", "runId": "r1"}})
    assert running["terminal"] is False and running["content"] == "hi"
    done = normalize_event({"event": "chat", "payload": {"state": "complete", "runId": "r1"}})
    assert done["terminal"] is True and done["error"] is False
    failed = normalize_event({"event": "chat", "payload": {"state": "error", "errorKind": "model",
                                                          "errorMessage": "boom"}})
    assert failed["terminal"] is True and failed["error"] is True and failed["errorKind"] == "model"
    assert normalize_event({"payload": {}}) is None


# --- roster ---------------------------------------------------------------

def test_reconcile_detaches_orphans_and_reports_unbound(db, world):
    result = align.reconcile(db, world["org"].id, [{"id": "researcher", "sessions": 2}])
    assert result["counts"]["orphaned"] == 1  # nina is not on the gateway
    assert result["counts"]["unbound"] == 1  # researcher has no company seat
    db.refresh(world["agent"])
    assert world["agent"].lifecycle == "detached"

    # The agent reappears on the gateway: the seat comes back to life.
    again = align.reconcile(db, world["org"].id, [{"id": "nina"}])
    assert again["counts"]["matched"] == 1
    db.refresh(world["agent"])
    assert world["agent"].lifecycle == "active"


def test_reconcile_is_idempotent(db, world):
    first = align.reconcile(db, world["org"].id, [{"id": "nina"}])
    second = align.reconcile(db, world["org"].id, [{"id": "nina"}])
    assert first["counts"]["matched"] == second["counts"]["matched"] == 1
    assert second["counts"]["updated"] == 0


def test_bind_seat_rejects_humans_and_duplicates(db, world):
    with pytest.raises(ValueError):
        align.bind_seat(db, world["org"].id, world["human"].id, "writer")
    second_seat = Member(organization_id=world["org"].id, company_id=world["labs"].id, name="Dex",
                         member_type="agent", role="Researcher", status="active")
    db.add(second_seat); db.commit(); db.refresh(second_seat)
    with pytest.raises(ValueError):
        align.bind_seat(db, world["org"].id, second_seat.id, "nina")  # already taken
    bound = align.bind_seat(db, world["org"].id, second_seat.id, "researcher")
    assert bound.runtime_agent_id == "researcher" and bound.runtime_provider == "openclaw"


# --- dispatch -------------------------------------------------------------

def test_resolve_seat_requires_bound_agent(db, world):
    unbound = Member(organization_id=world["org"].id, company_id=world["labs"].id, name="Ghost",
                     member_type="agent", role="Analyst", status="active")
    db.add(unbound); db.commit(); db.refresh(unbound)
    db.add(Agent(member_id=unbound.id, runtime_provider="openclaw", runtime_agent_id="", lifecycle="active"))
    db.commit()
    task = Task(project_id=world["project"].id, title="Orphan work", assignee_member_id=unbound.id,
                status="todo", priority="low")
    db.add(task); db.commit(); db.refresh(task)
    with pytest.raises(agent_dispatch.DispatchError):
        agent_dispatch.resolve_seat(db, task)


def test_dispatch_uses_task_session_and_board_status(db, world):
    task = asyncio.run(agent_dispatch.dispatch_task(db, world["task"]))
    # The old implementation set "running", which is not a board status.
    assert task.status == "in_progress"
    assert task.status in ops.TASK_STATUSES
    assert task.runtime_run_id
    # Mock runtime echoes the session key we asked for.
    assert task.runtime_session_key == ocp.task_session_key("nina", task.id)
    types = {e.event_type for e in db.query(CompanyEvent).all()}
    assert "openclaw.task.dispatched" in types


def test_dispatch_refuses_human_assignee(db, world):
    task = Task(project_id=world["project"].id, title="Human work", assignee_member_id=world["human"].id,
                status="todo", priority="low")
    db.add(task); db.commit(); db.refresh(task)
    with pytest.raises(agent_dispatch.DispatchError):
        asyncio.run(agent_dispatch.dispatch_task(db, task))


def test_abort_parks_task_back_on_the_board(db, world):
    task = asyncio.run(agent_dispatch.dispatch_task(db, world["task"]))
    result = asyncio.run(agent_dispatch.abort_task(db, task, back_to="todo"))
    assert result["status"] == "todo"
    with pytest.raises(agent_dispatch.DispatchError):
        asyncio.run(agent_dispatch.abort_task(db, task, back_to="done"))


def test_task_brief_states_the_approval_boundary(db, world):
    brief = align.task_brief(db, world["task"])
    assert "Draft launch plan" in brief
    assert "without human approval" in brief


def test_runtime_descriptor_never_leaks_the_token():
    descriptor = align.runtime_descriptor()
    assert "token_configured" in descriptor
    assert all("token" not in str(v).lower() or k == "token_configured" for k, v in descriptor.items()
               if isinstance(v, str))
