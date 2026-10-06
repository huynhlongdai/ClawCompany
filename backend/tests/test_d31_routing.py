"""D3.1 — trưởng phòng định tuyến. Luật thuần + ORM thật + HTTP thật (API v18,
MCP ``/api/mcp`` bằng API key của seat). Runtime giả chỉ ghi ``run_agent``."""
import asyncio
import json
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.security import create_access_token, pwd_context
from app.db.base import Base
import app.models  # noqa: F401
from app.db.session import get_db
from app.main import app
from app.models import APIKey, CompanyEvent, TaskRun, Wakeup
from app.models.auth import User
from app.models.entities import Agent, Company, Department, Member, Organization, Project, Task
from app.models.v37 import TaskJournalEntry
from app.services import routing, task_journal, wakeup
from app.services import runtime_stream as stream
from app.services.routing import HeadEvent, should_wake_head


# ------------------------------------------------------------------ 5 luật thuần


def test_rule1_member_comment_without_mention_wakes_head():
    assert should_wake_head(HeadEvent("comment", head_member_id=1, actor_member_id=2)) == (True, "comment_without_mention")


def test_rule2_comment_with_mention_does_not_wake_head():
    assert should_wake_head(HeadEvent("comment", 1, actor_member_id=2, mentions=(3,))) == (False, "mention_routes_directly")


def test_rule3_self_triggered_never_wakes_head():
    for kind in ("comment", "reference"):
        assert should_wake_head(HeadEvent(kind, 1, actor_member_id=1)) == (False, "self_triggered")


def test_rule4_reference_only_wakes_head():
    assert should_wake_head(HeadEvent("reference", 1, actor_member_id=None)) == (True, "task_reference")
    assert should_wake_head(HeadEvent("reference", 1, actor_member_id=5)) == (True, "task_reference")


def test_rule5_pending_run_dedups():
    assert should_wake_head(HeadEvent("comment", 1, actor_member_id=2, pending=True)) == (False, "dedup_pending")
    assert should_wake_head(HeadEvent("reference", 1, pending=True)) == (False, "dedup_pending")


def test_no_head_and_rule_order():
    assert should_wake_head(HeadEvent("reference", None)) == (False, "no_head")
    # tự kích hoạt đứng trước dedup và trước luật @
    assert should_wake_head(HeadEvent("comment", 1, actor_member_id=1, mentions=(2,), pending=True))[1] == "self_triggered"


# ------------------------------------------------------------------ ORM + HTTP


class FakeRuntime:
    def __init__(self):
        self.calls = []

    async def run_agent(self, runtime_agent_id, input_text, metadata=None, session_key=None):
        from app.runtime.base import RuntimeRun
        self.calls.append({"agent": runtime_agent_id, "session_key": session_key, "text": input_text,
                           "metadata": metadata or {}})
        return RuntimeRun(task_id="t", run_id=f"run-{len(self.calls)}", session_key=session_key or "",
                          status="running", raw={})

    async def rpc(self, method, params=None):
        return {"sessions": [], "cacheStatus": {"status": "fresh"}}


@pytest.fixture()
def env(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    Maker = sessionmaker(bind=engine, autoflush=False)
    db = Maker()

    def override():
        s = Maker()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = override
    org = Organization(name="Nova", slug="nova-d31"); db.add(org); db.commit()
    co = Company(organization_id=org.id, name="Nova", status="active"); db.add(co); db.commit()
    mk = Department(company_id=co.id, name="Marketing", guide="Bài SEO giao cho người viết.\nQuảng cáo giao Bình.")
    eng = Department(company_id=co.id, name="Kỹ thuật")
    db.add_all([mk, eng]); db.commit()
    boss = Member(organization_id=org.id, company_id=co.id, name="Long", member_type="human", role="CEO", status="active")
    db.add(boss); db.commit()

    def seat(name, rid, dept, role):
        m = Member(organization_id=org.id, company_id=co.id, department_id=dept.id, name=name,
                   member_type="agent", role=role, status="active", manager_id=boss.id)
        db.add(m); db.commit()
        db.add(Agent(member_id=m.id, runtime_agent_id=rid, lifecycle="active")); db.commit()
        return m

    head = seat("Hana", "hana", mk, "Trưởng phòng Marketing")
    an = seat("An", "an", mk, "Người viết nội dung SEO")
    binh = seat("Bình", "binh", mk, "Chạy quảng cáo")
    chi = seat("Chi", "chi", eng, "Kỹ sư backend")
    mk.head_member_id = head.id; db.commit()
    user = User(email="long@nova.test", password_hash="x", member_id=boss.id); db.add(user); db.commit()
    proj = Project(company_id=co.id, name="Ra mắt", status="active"); db.add(proj); db.commit()
    fake = FakeRuntime()
    monkeypatch.setattr("app.services.agent_dispatch.get_runtime", lambda: fake)
    monkeypatch.setattr("app.runtime.factory.get_runtime", lambda: fake)

    async def no_hours(agent):
        return None
    monkeypatch.setattr(wakeup, "ACTIVE_HOURS_LOOKUP", no_hours)
    keys = {}

    def key(member):
        raw = f"cc_test_{member.id}_{len(keys)}_" + "x" * 20
        db.add(APIKey(organization_id=org.id, member_id=member.id, name="seat", key_prefix=raw[:12],
                      key_hash=pwd_context.hash(raw), scopes=json.dumps(["*"])))
        db.commit(); keys[raw] = member
        return raw

    client = TestClient(app)

    def call(member, name, args, session_key="", status=200):
        r = client.post("/api/mcp", headers={"X-API-Key": key(member), **({"X-OpenClaw-Session-Key": session_key} if session_key else {})},
                        json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                              "params": {"name": name, "arguments": args}})
        assert r.status_code == status, r.text
        if status != 200:
            return True, r.json()["error"]
        res = r.json()["result"]
        return res["isError"], res["structuredContent"]

    token = create_access_token(user.id, org.id, "admin")
    yield {"db": db, "org": org, "co": co, "mk": mk, "eng": eng, "boss": boss, "head": head, "an": an,
           "binh": binh, "chi": chi, "proj": proj, "rt": fake, "client": client, "call": call,
           "H": {"Authorization": f"Bearer {token}"}}
    app.dependency_overrides.pop(get_db, None)


def _task(env, title="Viết bài SEO ra mắt", status="todo"):
    t = Task(project_id=env["proj"].id, title=title, status=status)
    env["db"].add(t); env["db"].commit(); env["db"].refresh(t)
    return t


def _route(env, t, reason="việc nội dung"):
    r = env["client"].post(f"/api/v18/workspace/tasks/{t.id}/route", headers=env["H"],
                           json={"department_id": env["mk"].id, "reason": reason})
    assert r.status_code == 200, r.text
    env["db"].expire_all()
    return r.json()


def _drain(env):
    env["db"].expire_all()
    return asyncio.run(wakeup.drain(env["db"], now=datetime.utcnow() + timedelta(seconds=11)))


def _events(env, kind):
    env["db"].expire_all()
    return [json.loads(e.payload_json) for e in env["db"].query(CompanyEvent)
            .filter(CompanyEvent.event_type == kind).order_by(CompanyEvent.id).all()]


def _routed_wakeups(env, t):
    env["db"].expire_all()
    return env["db"].query(Wakeup).filter(Wakeup.reason == "routed", Wakeup.task_id == t.id).all()


def test_route_to_department_wakes_head_with_routed_reason(env):
    t = _task(env)
    out = _route(env, t)
    db = env["db"]; db.refresh(t)
    assert t.assignee_department_id == env["mk"].id and t.assignee_member_id is None
    assert out["task"]["assignee_department_id"] == env["mk"].id
    wks = _routed_wakeups(env, t)
    assert len(wks) == 1 and wks[0].member_id == env["head"].id and wks[0].status == "queued"
    ev = _events(env, "task.routed_to_department")[-1]
    assert ev["department_id"] == env["mk"].id and ev["head_member_id"] == env["head"].id
    assert _events(env, "routing.head_wake")[-1]["rule"] == "task_reference"


def test_routing_run_uses_routing_pack_and_does_not_hold_or_move_task(env):
    t = _task(env)
    _route(env, t)
    res = _drain(env)
    assert any(r["decision"] == "routed" for r in res["results"]) if isinstance(res, dict) else True
    call = env["rt"].calls[-1]
    assert call["agent"] == "hana" and call["session_key"] == f"agent:hana:company-route-{t.id}"
    text = call["text"]
    assert "Giao thức định tuyến" in text and "company_task_assign" in text and "DỪNG" in text
    assert "Nhân sự phòng" in text and "An" in text and "Người viết nội dung SEO" in text
    assert "Chi" not in text.split("Nhân sự phòng")[1].split("##")[0]      # người phòng khác không có
    assert "Hướng dẫn phòng" in text and "Quảng cáo giao Bình" in text
    db = env["db"]; db.expire_all(); db.refresh(t)
    run = db.query(TaskRun).filter(TaskRun.task_id == t.id).one()
    assert run.trigger_kind == "routed" and run.member_id == env["head"].id and run.status == "running"
    assert t.checkout_run_id is None and t.status == "todo" and t.runtime_session_key is None


def test_head_assigns_via_mcp_reason_in_company_events_and_no_self_loop(env):
    t = _task(env)
    _route(env, t)
    _drain(env)
    sk = f"agent:hana:company-route-{t.id}"
    err, out = env["call"](env["head"], "company_task_assign",
                           {"task_id": t.id, "member_id": env["an"].id, "reason": "An viết SEO, đang rảnh"},
                           session_key=sk)
    assert not err, out
    db = env["db"]; db.expire_all(); db.refresh(t)
    assert t.assignee_member_id == env["an"].id and t.assignee_department_id == env["mk"].id
    ev = _events(env, "task.routed")[-1]
    assert ev["to_member_id"] == env["an"].id and ev["reason"] == "An viết SEO, đang rảnh"
    assert ev["by_member_id"] == env["head"].id and ev["run_id"] is not None
    entry = db.query(TaskJournalEntry).filter(TaskJournalEntry.task_id == t.id, TaskJournalEntry.kind == "decision").one()
    assert entry.actor_member_id == env["head"].id and "An viết SEO" in entry.summary
    # không vòng tự gọi: chỉ đúng 1 wakeup routed (lúc giao cho phòng)
    assert len(_routed_wakeups(env, t)) == 1
    assigned = db.query(Wakeup).filter(Wakeup.reason == "assigned", Wakeup.task_id == t.id).all()
    assert [w.member_id for w in assigned] == [env["an"].id]
    # lượt định tuyến kết thúc: run đóng, task giữ nguyên trạng thái
    run = db.query(TaskRun).filter(TaskRun.trigger_kind == "routed").one()
    state = stream.ConsumerState(session_key=sk, task_id=t.id, organization_id=env["org"].id)
    stream.handle_event(db, state, {"type": "chat", "family": "chat", "state": "final", "terminal": True})
    db.expire_all(); db.refresh(t); db.refresh(run)
    assert run.status == "succeeded" and t.status == "todo"
    assert _events(env, "routing.run_finished")[-1]["assigned"] is True
    # người được giao chạy lượt thường; trưởng phòng không bị gọi lại
    _drain(env)
    agents = [c["agent"] for c in env["rt"].calls]
    assert agents == ["hana", "an"]
    assert len(_routed_wakeups(env, t)) == 1


def test_comment_rules_on_department_task(env):
    t = _task(env)
    db = env["db"]
    t.assignee_department_id = env["mk"].id; db.commit()
    # luật 1: comment không @ của người khác → đánh thức
    task_journal.append(db, t, kind="note", summary="Cần làm gấp", actor_member_id=env["boss"].id)
    assert len(_routed_wakeups(env, t)) == 1
    # luật 5: đang có lý do chờ → dedup
    task_journal.append(db, t, kind="note", summary="Nhắc lại", actor_member_id=env["boss"].id)
    assert len(_routed_wakeups(env, t)) == 1
    assert _events(env, "routing.head_wake")[-1]["rule"] == "dedup_pending"
    for w in _routed_wakeups(env, t):
        w.status = "skipped"
    db.commit()
    # luật 2: có @ → không đánh thức trưởng phòng, người được @ dậy
    task_journal.append(db, t, kind="note", summary="@Bình xem giúp", actor_member_id=env["boss"].id)
    assert len([w for w in _routed_wakeups(env, t) if w.status == "queued"]) == 0
    assert db.query(Wakeup).filter(Wakeup.reason == "mentioned", Wakeup.member_id == env["binh"].id).count() == 1
    # luật 3: trưởng phòng tự comment → không
    task_journal.append(db, t, kind="note", summary="Để tôi xem", actor_member_id=env["head"].id)
    assert len([w for w in _routed_wakeups(env, t) if w.status == "queued"]) == 0
    assert _events(env, "routing.head_wake")[-1]["rule"] == "self_triggered"


def test_assigned_task_only_blocker_comments_wake_head(env):
    t = _task(env)
    db = env["db"]
    t.assignee_department_id, t.assignee_member_id = env["mk"].id, env["an"].id; db.commit()
    task_journal.append(db, t, kind="result", summary="Đã xong bản nháp", actor_member_id=env["an"].id)
    assert _routed_wakeups(env, t) == []
    task_journal.append(db, t, kind="blocker", summary="Thiếu brief sản phẩm", actor_member_id=env["an"].id)
    assert len(_routed_wakeups(env, t)) == 1


def test_assign_guards(env):
    t = _task(env)
    _route(env, t)
    err, out = env["call"](env["an"], "company_task_assign", {"task_id": t.id, "member_id": env["binh"].id,
                                                              "reason": "tôi muốn giao"}, status=403)
    assert err and out["data"]["level"] == "off"                             # thừa hành: tool off (D1.6)
    # kể cả khi được bật tool, người không phải trưởng phòng vẫn bị chặn ở service
    with pytest.raises(routing.RoutingError) as exc:
        routing.assign(env["db"], t, actor=env["an"], member_id=env["binh"].id, reason="tôi muốn giao")
    assert exc.value.code == "forbidden"
    err, out = env["call"](env["head"], "company_task_assign", {"task_id": t.id, "member_id": env["chi"].id,
                                                                "reason": "Chi rảnh"})
    assert err and "không thuộc phòng" in json.dumps(out, ensure_ascii=False)
    err, out = env["call"](env["head"], "company_task_assign", {"task_id": t.id, "member_id": env["an"].id,
                                                                "reason": ""})
    assert err
    env["db"].expire_all(); env["db"].refresh(t)
    assert t.assignee_member_id is None


def test_assign_without_member_picks_by_load_and_records_why(env):
    db = env["db"]
    busy = _task(env, "việc cũ", status="in_progress")
    db.add_all([TaskRun(organization_id=env["org"].id, task_id=busy.id, member_id=env["an"].id, status="running"),
                TaskRun(organization_id=env["org"].id, task_id=busy.id, member_id=env["an"].id, status="queued")])
    db.commit()
    t = _task(env)
    t.assignee_department_id = env["mk"].id; db.commit()
    out = routing.assign(db, t, actor=env["head"], member_id=None, reason="chọn theo tải trong phòng")
    assert out["assignee_member_id"] in (env["head"].id, env["binh"].id)
    assert out["assignee_member_id"] != env["an"].id                         # An đầy 2/2
    assert _events(env, "task.dispatch_decided")[-1]["member_id"] == out["assignee_member_id"]
    assert _events(env, "task.routed")[-1]["auto_pick"].startswith("Chọn ")


def test_routing_session_cost_goes_to_routing_run(env):
    t = _task(env)
    _route(env, t)
    _drain(env)
    db = env["db"]
    sk = f"agent:hana:company-route-{t.id}"
    state = stream.ConsumerState(session_key=sk, task_id=t.id, organization_id=env["org"].id)
    raw = {"sessionKey": sk, "messageId": "m1", "message": {"role": "assistant", "usage": {"input": 100, "output": 20,
                                                                                     "cost": {"total": 0.0123}}}}
    stream.handle_event(db, state, {"type": "session.message", "family": "session.message", "raw": raw})
    db.expire_all()
    run = db.query(TaskRun).filter(TaskRun.trigger_kind == "routed").one()
    assert run.cost_usd == pytest.approx(0.0123)


def test_department_routing_api_and_guide(env):
    t = _task(env)
    _route(env, t)
    c, H = env["client"], env["H"]
    r = c.put(f"/api/v18/workspace/departments/{env['mk'].id}/guide", headers=H, json={"guide": "SEO → An"})
    assert r.status_code == 200 and r.json()["guide"] == "SEO → An"
    r = c.get(f"/api/v18/workspace/departments/{env['mk'].id}/routing", headers=H)
    assert r.status_code == 200
    body = r.json()
    assert body["department"]["head"]["name"] == "Hana" and body["department"]["guide"] == "SEO → An"
    assert {m["name"] for m in body["roster"]} == {"Hana", "An", "Bình"}
    assert body["tasks"][0]["id"] == t.id and body["tasks"][0]["unassigned"] is True
    assert {e["type"] for e in body["events"]} >= {"task.routed_to_department", "routing.head_wake"}
    # task đang chạy thì không giao lại cho phòng được
    t2 = _task(env, "đang chạy", status="in_progress")
    r = c.post(f"/api/v18/workspace/tasks/{t2.id}/route", headers=H, json={"department_id": env["mk"].id})
    assert r.status_code == 409
