"""v21 tests: shared leases, restart resume, and the approval reply path.

These tests target the two things v20 admitted it did not solve. A lease must
refuse a second follower for the same session, and a decision made in
ClawCompany must never be reported as delivered to OpenClaw when it was only
stored locally.
"""
import asyncio
import time

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.db.base import Base
import app.models  # noqa: F401
from app.models import Agent, Approval, Company, Member, Organization, Project, Task
from app.runtime import openclaw_protocol as ocp
from app.services import approval_bridge as bridge
from app.services import runtime_stream as rs
from app.services.runtime_leases import LeaseStore


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
def leases():
    """A memory-backed store: no Redis in the test environment."""
    store = LeaseStore(ttl=30)
    store._redis = None
    return store


@pytest.fixture()
def world(db):
    org = Organization(name="Nova Holding", slug="nova-holding")
    db.add(org); db.commit(); db.refresh(org)
    labs = Company(organization_id=org.id, name="Nova Labs", industry="AI", status="active")
    db.add(labs); db.commit(); db.refresh(labs)
    nina = Member(organization_id=org.id, company_id=labs.id, name="Nina",
                  member_type="agent", role="Chief of Staff", status="active")
    db.add(nina); db.commit(); db.refresh(nina)
    db.add(Agent(member_id=nina.id, runtime_provider="openclaw",
                 runtime_agent_id="nina", lifecycle="active"))
    project = Project(company_id=labs.id, name="Launch", status="active", progress=0)
    db.add(project); db.commit(); db.refresh(project)
    running = Task(project_id=project.id, title="Draft plan", assignee_member_id=nina.id,
                   status="in_progress", priority="high",
                   runtime_session_key=ocp.task_session_key("nina", 1))
    parked = Task(project_id=project.id, title="Later", assignee_member_id=nina.id,
                  status="todo", priority="low", runtime_session_key="")
    finished = Task(project_id=project.id, title="Done thing", assignee_member_id=nina.id,
                    status="review", priority="low",
                    runtime_session_key=ocp.task_session_key("nina", 9))
    db.add_all([running, parked, finished]); db.commit()
    for t in (running, parked, finished):
        db.refresh(t)
    return {"org": org, "labs": labs, "nina": nina, "project": project,
            "running": running, "parked": parked, "finished": finished}


# --- leases ---------------------------------------------------------------

def test_lease_is_granted_once(leases):
    assert leases.acquire("agent:nina:main") is not None
    # The same owner re-claiming is a reconnect, not a conflict.
    assert leases.acquire("agent:nina:main") is not None


def test_lease_refused_when_another_process_holds_it(leases):
    leases._memory["agent:nina:main"] = ("other-host:99:abc", time.time() + 60)
    assert leases.acquire("agent:nina:main") is None
    assert leases.holder("agent:nina:main") == "other-host:99:abc"


def test_expired_lease_can_be_taken_over(leases):
    leases._memory["agent:nina:main"] = ("dead-worker:1:x", time.time() - 1)
    lease = leases.acquire("agent:nina:main")
    assert lease is not None and lease.owner == leases.owner


def test_renew_fails_after_losing_the_lease(leases):
    leases.acquire("agent:nina:main")
    leases._memory["agent:nina:main"] = ("someone-else:2:y", time.time() + 60)
    assert leases.renew("agent:nina:main") is False


def test_release_never_steals_another_owners_lease(leases):
    leases._memory["agent:nina:main"] = ("someone-else:2:y", time.time() + 60)
    assert leases.release("agent:nina:main") is False
    assert leases.holder("agent:nina:main") == "someone-else:2:y"


def test_memory_backend_admits_it_is_single_process(leases):
    status = leases.status()
    assert status["backend"] == "memory"
    assert status["single_process_only"] is True


def test_follow_declines_when_lease_is_held(monkeypatch, world):
    store = LeaseStore(ttl=30)
    store._redis = None
    store._memory[world["running"].runtime_session_key] = ("other:1:z", time.time() + 60)
    monkeypatch.setattr(rs, "lease_store", store)
    state = rs.supervisor.follow(session_key=world["running"].runtime_session_key,
                                 organization_id=world["org"].id,
                                 task_id=world["running"].id)
    assert state.status == "declined"
    assert "other:1:z" in state.error
    assert not rs.supervisor.is_following(world["running"].runtime_session_key)


# --- restart resume -------------------------------------------------------

def test_resumable_only_includes_in_flight_sessions(db, world):
    ids = {t.id for t in rs.resumable_sessions(db)}
    assert world["running"].id in ids
    assert world["parked"].id not in ids     # no session key
    assert world["finished"].id not in ids   # already past in_progress


def test_resume_skips_tasks_from_another_organization(db, world, monkeypatch):
    monkeypatch.setattr(rs.supervisor, "follow",
                        lambda **kw: rs.ConsumerState(session_key=kw["session_key"],
                                                      organization_id=kw["organization_id"],
                                                      task_id=kw.get("task_id")))
    report = rs.resume_followers(db, organization_id=world["org"].id + 999)
    assert report["resumed"] == []
    assert world["running"].id in report["skipped"]


def test_resume_reports_the_lease_backend(db, world, monkeypatch):
    monkeypatch.setattr(rs.supervisor, "follow",
                        lambda **kw: rs.ConsumerState(session_key=kw["session_key"],
                                                      organization_id=kw["organization_id"],
                                                      task_id=kw.get("task_id")))
    report = rs.resume_followers(db, organization_id=world["org"].id)
    assert world["running"].id in report["resumed"]
    assert "backend" in report["lease"]


# --- approval policy keys -------------------------------------------------

def test_policy_key_survives_colons_in_session_keys():
    session_key, request_id = bridge.parse_policy_key("openclaw:agent:nina:main:req-7")
    assert session_key == "agent:nina:main"
    assert request_id == "req-7"


def test_non_openclaw_approval_is_rejected():
    with pytest.raises(bridge.ApprovalBridgeError):
        bridge.parse_policy_key("finance:invoice:12")


# --- approval replies -----------------------------------------------------

def _pending(db, world):
    row = Approval(organization_id=world["org"].id, company_id=world["labs"].id,
                   action="exec: rm -rf build", risk="high", status="pending",
                   policy_key="openclaw:agent:nina:main:req-7", evidence="{}")
    db.add(row); db.commit(); db.refresh(row)
    return row


def test_decision_is_recorded_but_not_claimed_as_delivered(db, world, monkeypatch):
    monkeypatch.setattr(settings, "openclaw_approval_reply_method", "", raising=False)
    monkeypatch.setattr(settings, "openclaw_request_approvals_scope", False, raising=False)
    row = _pending(db, world)
    result = asyncio.run(bridge.decide(db, row, decision="approved", note="ok by me"))
    assert result["recorded"] is True
    assert result["delivered"] is False
    assert "OPENCLAW_APPROVAL_REPLY_METHOD" in result["delivery_error"]
    assert row.status == "approved"
    assert "recorded locally only" in row.resolution_note


def test_decision_is_relayed_when_configured(db, world, monkeypatch):
    # v23: the method name is the documented upstream one and the payload is
    # id + three-valued decision, not a boolean.
    monkeypatch.setattr(settings, "openclaw_approval_reply_method", ocp.M_EXEC_APPROVAL_RESOLVE, raising=False)
    monkeypatch.setattr(settings, "openclaw_request_approvals_scope", True, raising=False)
    sent = {}

    class FakeRuntime:
        async def respond_approval(self, *, request_id, decision, session_key=""):
            sent.update(session_key=session_key, request_id=request_id, decision=decision)
            return {"ok": True}

    monkeypatch.setattr(bridge, "get_runtime", lambda: FakeRuntime())
    row = _pending(db, world)
    result = asyncio.run(bridge.decide(db, row, decision="denied", note="too risky"))
    assert result["delivered"] is True
    assert sent == {"session_key": "agent:nina:main", "request_id": "req-7",
                    "decision": ocp.D_DENY}
    assert "decision relayed to OpenClaw" in row.resolution_note


def test_gateway_failure_still_records_the_human_decision(db, world, monkeypatch):
    monkeypatch.setattr(settings, "openclaw_approval_reply_method", ocp.M_EXEC_APPROVAL_RESOLVE, raising=False)
    monkeypatch.setattr(settings, "openclaw_request_approvals_scope", True, raising=False)

    class BrokenRuntime:
        async def respond_approval(self, **kwargs):
            raise RuntimeError("gateway unreachable")

    monkeypatch.setattr(bridge, "get_runtime", lambda: BrokenRuntime())
    row = _pending(db, world)
    result = asyncio.run(bridge.decide(db, row, decision="approved"))
    assert result["recorded"] is True and result["delivered"] is False
    assert "gateway unreachable" in result["delivery_error"]
    assert row.status == "approved"


def test_already_decided_approval_cannot_be_decided_again(db, world):
    row = _pending(db, world)
    row.status = "approved"
    db.add(row); db.commit()
    with pytest.raises(bridge.ApprovalBridgeError):
        asyncio.run(bridge.decide(db, row, decision="denied"))


def test_unknown_decision_is_rejected(db, world):
    row = _pending(db, world)
    with pytest.raises(bridge.ApprovalBridgeError):
        asyncio.run(bridge.decide(db, row, decision="maybe"))


def test_readiness_lists_every_missing_setting(monkeypatch):
    monkeypatch.setattr(settings, "openclaw_approval_reply_method", "", raising=False)
    monkeypatch.setattr(settings, "openclaw_request_approvals_scope", False, raising=False)
    readiness = bridge.upstream_readiness()
    assert readiness["ready"] is False
    assert set(readiness["missing"]) == {"OPENCLAW_APPROVAL_REPLY_METHOD",
                                        "OPENCLAW_REQUEST_APPROVALS_SCOPE"}


# --- scope hygiene and the legacy shim -----------------------------------

def test_approvals_scope_is_opt_in(monkeypatch):
    from app.runtime.openclaw_native import NativeOpenClawRuntime

    runtime = NativeOpenClawRuntime()
    monkeypatch.setattr(settings, "openclaw_request_approvals_scope", False, raising=False)
    assert ocp.SCOPE_APPROVALS not in runtime.scopes()
    monkeypatch.setattr(settings, "openclaw_request_approvals_scope", True, raising=False)
    assert ocp.SCOPE_APPROVALS in runtime.scopes()
    # Admin and secrets are never requested, in either mode.
    assert "operator.admin" not in runtime.scopes()
    assert "operator.talk.secrets" not in runtime.scopes()


def test_reply_refuses_to_guess_the_rpc_name(monkeypatch):
    from app.runtime.openclaw_native import NativeOpenClawRuntime, OpenClawProtocolError

    monkeypatch.setattr(settings, "openclaw_approval_reply_method", "", raising=False)
    monkeypatch.setattr(settings, "openclaw_request_approvals_scope", True, raising=False)
    runtime = NativeOpenClawRuntime()
    with pytest.raises(OpenClawProtocolError):
        asyncio.run(runtime.respond_approval(request_id="req-7",
                                             decision=ocp.D_ALLOW_ONCE,
                                             session_key="agent:nina:main"))


def test_legacy_dispatch_delegates_and_warns(monkeypatch):
    from app.services import agent_dispatch, tasks as legacy

    calls = []

    async def fake(db, task):
        calls.append(task)
        return task

    monkeypatch.setattr(legacy, "_dispatch_task", fake)
    with pytest.warns(DeprecationWarning):
        asyncio.run(legacy.dispatch_task(None, "task-object"))
    assert calls == ["task-object"]
    # Old callers caught ValueError; the new error type must stay compatible.
    assert issubclass(agent_dispatch.DispatchError, ValueError)
