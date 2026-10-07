"""M1.2: follower cho mọi đường dispatch, resume không 500, bắt kịp lượt đã xong,
roster agents.list + agents.create.

Mỗi lỗi ở đây đều đo được trên gateway thật 2026.9.8 (VM, e2e4/e2e5):
- giao việc qua ``/api/v19/tasks/{id}/start`` không gắn follower → task kẹt
  ``in_progress`` dù agent đã trả lời, chi phí không ghi;
- ``POST /api/v21/runtime/resume`` → 500 ``no running event loop``;
- resume xong vẫn kẹt, vì frame cuối đã trôi qua trước khi gắn.
"""
import asyncio
import inspect
import json
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.db.base import Base
import app.models  # noqa: F401
from app.models import Agent, Company, Member, Organization, Project, Task, TaskRun, UsageEvent
from app.runtime import openclaw_protocol as ocp
from app.runtime.openclaw_native import NativeOpenClawRuntime, OpenClawProtocolError
from app.services import agent_dispatch, stream_catchup
from app.services import runtime_stream as rs

RUN_ID = "clawcompany:agent:nina:company-task-1:task-1:abc"


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
    org = Organization(name="Nova", slug="nova"); db.add(org); db.commit(); db.refresh(org)
    co = Company(organization_id=org.id, name="Nova Labs", industry="AI", status="active")
    db.add(co); db.commit(); db.refresh(co)
    nina = Member(organization_id=org.id, company_id=co.id, name="Nina", member_type="agent",
                  role="Chief of Staff", status="active")
    db.add(nina); db.commit(); db.refresh(nina)
    agent = Agent(member_id=nina.id, runtime_provider="openclaw", runtime_agent_id="nina", lifecycle="active")
    db.add(agent); db.commit(); db.refresh(agent)
    project = Project(company_id=co.id, name="Launch", status="active", progress=0)
    db.add(project); db.commit(); db.refresh(project)
    task = Task(project_id=project.id, title="Plan", assignee_member_id=nina.id,
                status="in_progress", priority="high", runtime_run_id=RUN_ID,
                runtime_session_key=ocp.task_session_key("nina", 1))
    db.add(task); db.commit(); db.refresh(task)
    return {"org": org, "nina": nina, "agent": agent, "task": task}


def _state(world):
    return rs.ConsumerState(session_key=world["task"].runtime_session_key,
                            task_id=world["task"].id, organization_id=world["org"].id)


def _assistant(msg_id, run_id=RUN_ID, cost=0.005242, inp=12797, out=77):
    return {"role": "assistant", "model": "gpt-4.1-mini", "provider": "comet", "stopReason": "stop",
            "usage": {"input": inp, "output": out, "cacheRead": 0, "cacheWrite": 0,
                      "totalTokens": inp + out, "cost": {"total": cost}},
            "content": [{"type": "text", "text": "xong"}],
            "__openclaw": {"id": msg_id, "runId": run_id}}


class _Gateway:
    """Trả đúng khung đo được của sessions.describe và chat.history (2026.9.8)."""

    def __init__(self, status="done", last_run=RUN_ID, aborted=False, messages=None):
        self.session = {"key": "", "status": status, "lastRunId": last_run, "abortedLastRun": aborted}
        self.messages = messages if messages is not None else [
            {"role": "user", "content": "brief", "__openclaw": {"id": "u1"}}, _assistant("m1")]
        self.calls = []

    async def rpc(self, method, params=None):
        self.calls.append((method, params))
        assert method == ocp.M_SESSIONS_DESCRIBE and set(params) == {"key"}
        return {"session": {**self.session, "key": params["key"]}}

    async def history(self, session_key, limit=50):
        self.calls.append(("chat.history", session_key))
        return {"sessionKey": session_key, "messages": self.messages}


def _catch_up(db, world, gw):
    return asyncio.run(stream_catchup.catch_up(db, gw, _state(world), rs.apply_terminal_state))


def _model_usage(db):
    return db.query(UsageEvent).filter(UsageEvent.event_type == "model_usage").all()


# --- catch-up -------------------------------------------------------------

def test_catch_up_closes_a_run_that_finished_unobserved(db, world, monkeypatch):
    monkeypatch.setattr("app.services.execution_policy.requires_report", lambda task: False)
    out = _catch_up(db, world, _Gateway())
    db.refresh(world["task"])
    assert out["terminal"] is True and out["recorded"] == 1
    assert world["task"].status == "review"
    rows = _model_usage(db)
    assert len(rows) == 1 and abs(rows[0].amount - 0.005242) < 1e-12
    assert json.loads(rows[0].metadata_json)["message_id"] == "m1"


def test_catch_up_does_not_double_count_what_the_stream_already_recorded(db, world, monkeypatch):
    """history.__openclaw.id == session.message.messageId: một lượt, một dòng tiền."""
    monkeypatch.setattr("app.services.execution_policy.requires_report", lambda task: False)
    rs.handle_event(db, _state(world), {"type": "session.message", "family": "session.message",
                                        "raw": stream_catchup.history_usage_raw(_assistant("m1"), "k")})
    out = _catch_up(db, world, _Gateway())
    assert out["terminal"] is True and out["recorded"] == 0
    assert len(_model_usage(db)) == 1


def test_previous_run_done_never_closes_the_current_run(db, world):
    gw = _Gateway(last_run="clawcompany:older-run")
    out = _catch_up(db, world, gw)
    db.refresh(world["task"])
    assert out["terminal"] is False and world["task"].status == "in_progress"
    assert _model_usage(db) == []


def test_running_session_keeps_listening(db, world):
    out = _catch_up(db, world, _Gateway(status="running"))
    db.refresh(world["task"])
    assert out["terminal"] is False and world["task"].status == "in_progress"


def test_aborted_run_goes_back_to_todo(db, world):
    out = _catch_up(db, world, _Gateway(aborted=True))
    db.refresh(world["task"])
    assert out["terminal"] is True and world["task"].status == "todo"


def test_only_messages_of_this_run_are_billed(db, world, monkeypatch):
    monkeypatch.setattr("app.services.execution_policy.requires_report", lambda task: False)
    gw = _Gateway(messages=[_assistant("old", run_id="other-run"), _assistant("m1")])
    out = _catch_up(db, world, gw)
    assert out["recorded"] == 1
    assert [json.loads(r.metadata_json)["message_id"] for r in _model_usage(db)] == ["m1"]


def test_catch_up_never_raises(db, world):
    class Broken(_Gateway):
        async def rpc(self, method, params=None):
            raise OpenClawProtocolError("down", {"code": "UNAVAILABLE"})
    out = _catch_up(db, world, Broken())
    assert out["terminal"] is False and out["skipped"].startswith("error")


def test_task_not_waiting_is_left_alone(db, world):
    world["task"].status = "review"; db.add(world["task"]); db.commit()
    gw = _Gateway()
    out = _catch_up(db, world, gw)
    assert out["terminal"] is False and gw.calls == []


def test_consumer_stops_after_catch_up_without_subscribing(db, world, monkeypatch):
    monkeypatch.setattr("app.services.execution_policy.requires_report", lambda task: False)
    gw = _Gateway()

    async def never(_key):
        raise AssertionError("không được subscribe khi lượt đã xong")
        yield  # pragma: no cover

    gw.stream_run = never
    monkeypatch.setattr(rs, "get_runtime", lambda: gw)
    monkeypatch.setattr(rs, "SessionLocal", lambda: db)
    monkeypatch.setattr(db, "close", lambda: None)

    async def noop(*a, **k):
        return {}
    monkeypatch.setattr(rs.stream_reconcile, "reconcile", noop)
    state = _state(world)
    asyncio.run(rs._consume(state))
    assert state.status == "finished" and state.last_event_type == "catch_up"


# --- follower after every dispatch ----------------------------------------

def test_follow_after_send_attaches_in_native_mode(monkeypatch):
    seen = []
    monkeypatch.setattr(settings, "openclaw_mode", "native")
    monkeypatch.setattr(settings, "wakeup_follow", True)
    monkeypatch.setattr(rs.supervisor, "follow",
                        lambda **kw: seen.append(kw) or SimpleNamespace(status="running"))
    assert agent_dispatch.follow_after_send("agent:nina:company-task-1", 7, 1) == "running"
    assert seen == [{"session_key": "agent:nina:company-task-1", "organization_id": 7, "task_id": 1}]


@pytest.mark.parametrize("mode,follow,key", [("mock", True, "k"), ("native", False, "k"), ("native", True, "")])
def test_follow_after_send_is_off_without_gateway_or_key(monkeypatch, mode, follow, key):
    monkeypatch.setattr(settings, "openclaw_mode", mode)
    monkeypatch.setattr(settings, "wakeup_follow", follow)
    monkeypatch.setattr(rs.supervisor, "follow", lambda **kw: pytest.fail("không được follow"))
    assert agent_dispatch.follow_after_send(key, 1, 1) is None


def test_follow_failure_does_not_break_the_dispatch(monkeypatch):
    monkeypatch.setattr(settings, "openclaw_mode", "native")
    monkeypatch.setattr(settings, "wakeup_follow", True)

    def boom(**kw):
        raise RuntimeError("no running event loop")
    monkeypatch.setattr(rs.supervisor, "follow", boom)
    assert agent_dispatch.follow_after_send("k", 1, 1).startswith("error")


def test_dispatch_task_follows_the_session_it_just_sent(db, world, monkeypatch):
    task = world["task"]
    task.status = "todo"; task.runtime_run_id = None; task.runtime_session_key = None
    db.add(task); db.commit()
    calls = []

    async def fake_run(runtime, agent, task, member, pack, session_key):
        return SimpleNamespace(run_id="run-1", session_key=session_key, task_id=str(task.id))
    monkeypatch.setattr(agent_dispatch, "_run_agent", fake_run)
    monkeypatch.setattr(agent_dispatch, "follow_after_send",
                        lambda key, org, tid: calls.append((key, org, tid)))
    asyncio.run(agent_dispatch.dispatch_task(db, task))
    assert calls == [(ocp.task_session_key("nina", task.id), world["org"].id, task.id)]


# --- resume must run on the event loop ------------------------------------

def test_resume_endpoint_and_boot_hook_are_async():
    """``supervisor.follow`` gọi asyncio.create_task: ``def`` → 500 trong threadpool."""
    from app.api import v21
    from app import main
    assert inspect.iscoroutinefunction(v21.resume)
    assert inspect.iscoroutinefunction(main.resume_openclaw_followers)


def test_follow_outside_a_loop_is_what_used_to_500():
    with pytest.raises(RuntimeError, match="no running event loop"):
        rs.StreamSupervisor().follow(session_key="k-sync", organization_id=1, task_id=None)


# --- roster: agents.list + agents.create ----------------------------------

def _native(responses):
    rt = NativeOpenClawRuntime()
    sent = []

    async def fake_rpc(method, params=None):
        sent.append((method, params))
        value = responses.get(method, {})
        if isinstance(value, Exception):
            raise value
        return value
    rt._rpc = fake_rpc
    return rt, sent


def test_list_agents_includes_agents_without_sessions():
    rt, _ = _native({
        ocp.M_AGENTS_LIST: {"agents": [{"id": "main", "model": {"primary": "comet/gpt-4.1-mini"}},
                                       {"id": "mia-content", "name": "Mia"}]},
        ocp.M_SESSIONS_LIST: {"sessions": [{"key": "agent:main:main", "hasActiveRun": True},
                                           {"key": "agent:ghost:x"}]},
    })
    roster = {a["id"]: a for a in asyncio.run(rt.list_agents())}
    assert set(roster) == {"main", "mia-content", "ghost"}
    assert roster["mia-content"]["sessions"] == 0 and roster["mia-content"]["name"] == "Mia"
    assert roster["main"]["active"] is True and roster["main"]["model"] == "comet/gpt-4.1-mini"


def test_list_agents_falls_back_to_sessions_when_agents_list_is_refused():
    rt, _ = _native({ocp.M_AGENTS_LIST: OpenClawProtocolError("scope", {"code": "FORBIDDEN"}),
                     ocp.M_SESSIONS_LIST: {"sessions": [{"key": "agent:nina:main"}]}})
    assert [a["id"] for a in asyncio.run(rt.list_agents())] == ["nina"]


def test_create_agent_binds_existing_without_creating():
    rt, sent = _native({ocp.M_AGENTS_LIST: {"agents": [{"id": "nina"}]}})
    out = asyncio.run(rt.create_agent("nina", {}))
    assert out["status"] == "bound" and ocp.M_AGENTS_CREATE not in [m for m, _ in sent]


def test_create_agent_creates_and_checks_the_returned_id():
    rt, sent = _native({ocp.M_AGENTS_CREATE: {"ok": True, "agentId": "mia-content", "workspace": "/w"}})
    out = asyncio.run(rt.create_agent("mia-content", {"model": "comet/gpt-4.1-mini"}))
    assert out["status"] == "created" and out["bound"] is True
    assert (ocp.M_AGENTS_CREATE, {"name": "mia-content", "model": "comet/gpt-4.1-mini"}) in sent


def test_create_agent_reports_mismatch_and_missing_scope():
    rt, _ = _native({ocp.M_AGENTS_CREATE: {"ok": True, "agentId": "mia_content"}})
    assert asyncio.run(rt.create_agent("Mia Content", {}))["status"] == "mismatch"
    rt, _ = _native({ocp.M_AGENTS_CREATE: OpenClawProtocolError("x", {"code": "FORBIDDEN"})})
    out = asyncio.run(rt.create_agent("mia", {"model": "gpt"}))
    assert out["status"] == "missing" and out["bound"] is False and "OPENCLAW_REQUEST_ADMIN_SCOPE" in out["hint"]


# --- M1.3: gateway restart giữa lượt → OpenClaw tự chạy tiếp bằng runId mới ---

def _user(text, key=""):
    return {"role": "user", "content": text, "idempotencyKey": key, "__openclaw": {"id": "u-" + text[:5]}}


RESUME = "[System] Your previous turn was interrupted by a gateway restart while OpenClaw was working."


def _restart_history(extra_user=None):
    msgs = [_user("brief", RUN_ID + ":user"),
            {**_assistant("m1"), "stopReason": "toolUse"},
            _user(RESUME)]
    if extra_user:
        msgs.append(_user(extra_user))
    msgs.append(_assistant("m2", run_id="resumed-run", cost=0.001))
    return msgs


def test_resumed_turn_after_gateway_restart_closes_the_task(db, world, monkeypatch):
    """Khung đo được trong chaos test (task 4, 2026.9.8)."""
    monkeypatch.setattr("app.services.execution_policy.requires_report", lambda task: False)
    out = _catch_up(db, world, _Gateway(last_run="resumed-run", messages=_restart_history()))
    db.refresh(world["task"])
    assert out["terminal"] is True and world["task"].status == "review"
    assert out["recorded"] == 2 and sorted(out["chain"]) == sorted([RUN_ID, "resumed-run"])
    assert abs(sum(r.amount for r in _model_usage(db)) - 0.006242) < 1e-12


def test_a_real_user_message_after_our_run_is_someone_elses_turn(db, world):
    out = _catch_up(db, world, _Gateway(last_run="resumed-run",
                                        messages=_restart_history(extra_user="Làm việc khác giúp tôi")))
    db.refresh(world["task"])
    assert out["terminal"] is False and world["task"].status == "in_progress"


def test_resume_notice_must_be_a_system_message():
    assert stream_catchup.is_resume_notice(_user(RESUME))
    assert not stream_catchup.is_resume_notice(_user("interrupted by a gateway restart"))
    assert not stream_catchup.is_resume_notice({"role": "assistant", "content": RESUME})
    assert stream_catchup.run_chain([_user("x")], RUN_ID) is None


# --- M4a: lượt xong trước khi follower nghe kịp → báo cáo lấy từ chat.history ---

def _texted(msg_id, text, run_id=RUN_ID):
    return {**_assistant(msg_id, run_id=run_id), "content": [{"type": "text", "text": text}]}


def test_catch_up_records_the_final_reply_as_the_report(db, world):
    """Gate thật M4a (việc #12): không có session.message nào trên stream, việc kẹt
    'thiếu báo cáo'. Câu trả lời cuối trong chat.history của lượt là báo cáo."""
    from app.models import TaskJournalEntry
    db.add(TaskRun(organization_id=world["org"].id, task_id=world["task"].id, member_id=world["nina"].id, runtime_run_id=RUN_ID,
                   status="running"))
    db.commit()
    msgs = [_texted("old", "câu trả lời lượt trước", run_id="older-run"),
            _user("brief", RUN_ID + ":user"),
            {**_texted("m1", "đang làm"), "stopReason": "toolUse"},
            _texted("m2", "Đã xong: kế hoạch 3 bước")]
    out = _catch_up(db, world, _Gateway(messages=msgs))
    db.refresh(world["task"])
    assert out["terminal"] is True and out["reply"] is True
    assert world["task"].status == "review"
    rows = db.query(TaskJournalEntry).filter(TaskJournalEntry.task_id == world["task"].id,
                                             TaskJournalEntry.kind == "result").all()
    assert len(rows) == 1 and rows[0].detail == "Đã xong: kế hoạch 3 bước"


def test_chain_reply_ignores_other_turns_in_the_same_session():
    msgs = [_texted("a", "của lượt khác", run_id="older-run"),
            _user("brief", RUN_ID + ":user"),
            _texted("b", "của lượt này"),
            _texted("c", "lượt khác chen vào", run_id="other-run"),
            _user("Làm việc khác giúp tôi"),
            {"role": "assistant", "content": "trả lời người khác"}]
    assert stream_catchup.chain_reply(msgs, {RUN_ID}, RUN_ID) == "của lượt này"
    assert stream_catchup.chain_reply([_texted("a", "x", run_id="older-run")], {RUN_ID}, RUN_ID) == ""
