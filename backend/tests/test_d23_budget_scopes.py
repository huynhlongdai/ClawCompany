"""D2.3 — ngân sách ba nấc, chặn thật. ORM thật; runtime giả chỉ ghi lời gọi
``run_agent`` (= chat.send) và trả ``sessions.usage`` theo kịch bản."""
import asyncio
import json
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.security import create_access_token
from app.db.base import Base
import app.models  # noqa: F401
from app.db.session import get_db
from app.main import app
from app.models import AuditEvent, BudgetEnvelope, BudgetLedgerEntry, TaskRun
from app.models.auth import User
from app.models.entities import Agent, Company, Department, Member, Organization, Project, Task
from app.models.extended import InboxItem
from app.services import budget_scope as bs
from app.services import runtime_stream as stream
from app.services import wakeup, work_context


class FakeRuntime:
    def __init__(self, fail=False):
        self.calls, self.usage, self.fail = [], {}, fail

    async def run_agent(self, runtime_agent_id, input_text, metadata=None, session_key=None):
        from app.runtime.base import RuntimeRun
        if self.fail:
            raise RuntimeError("gateway down")
        self.calls.append({"agent": runtime_agent_id, "session_key": session_key})
        return RuntimeRun(task_id="t", run_id=f"run-{len(self.calls)}", session_key=session_key or "",
                          status="running", raw={})

    async def rpc(self, method, params=None):
        key = (params or {}).get("key")
        return {"sessions": [{"key": key, "usage": {"totalCost": self.usage.get(key, 0.0)}}],
                "cacheStatus": {"status": "fresh"}}


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
    org = Organization(name="Nova", slug="nova-d23"); db.add(org); db.commit()
    co = Company(organization_id=org.id, name="Nova", status="active"); db.add(co); db.commit()
    dept = Department(company_id=co.id, name="Marketing"); db.add(dept); db.commit()
    boss = Member(organization_id=org.id, company_id=co.id, name="Long", member_type="human", role="CEO", status="active")
    db.add(boss); db.commit()

    def seat(name, rid, department_id=None):
        m = Member(organization_id=org.id, company_id=co.id, department_id=department_id, name=name,
                   member_type="agent", role="AI", status="active", manager_id=boss.id)
        db.add(m); db.commit()
        db.add(Agent(member_id=m.id, runtime_agent_id=rid, lifecycle="active")); db.commit()
        return m

    nina, mia = seat("Nina", "dev", dept.id), seat("Mia", "mia")
    user = User(email="long@nova.test", password_hash="x", member_id=boss.id); db.add(user); db.commit()
    proj = Project(company_id=co.id, name="P", status="active"); db.add(proj); db.commit()
    proj2 = Project(company_id=co.id, name="Q", status="active"); db.add(proj2); db.commit()
    fake = FakeRuntime()
    monkeypatch.setattr("app.services.agent_dispatch.get_runtime", lambda: fake)

    async def no_hours(agent):
        return None
    monkeypatch.setattr(wakeup, "ACTIVE_HOURS_LOOKUP", no_hours)
    token = create_access_token(user.id, org.id, "admin")
    yield {"db": db, "org": org, "co": co, "dept": dept, "boss": boss, "nina": nina, "mia": mia, "user": user,
           "proj": proj, "proj2": proj2, "rt": fake, "client": TestClient(app),
           "H": {"Authorization": f"Bearer {token}"}}
    app.dependency_overrides.pop(get_db, None)


def _task(env, title="Viết hook", assignee="nina", project="proj", status="todo"):
    t = Task(project_id=env[project].id, title=title, status=status,
             assignee_member_id=env[assignee].id if assignee else None)
    env["db"].add(t); env["db"].commit(); env["db"].refresh(t)
    return t


def _env(env, limit=0.10, scope="member", sid=None, **kw):
    sid = env["nina"].id if sid is None and scope == "member" else sid
    e = BudgetEnvelope(organization_id=env["org"].id, company_id=env["co"].id, name=f"{scope}-{limit}",
                       amount_limit=limit, status="active", scope_type=scope, scope_id=sid, **kw)
    env["db"].add(e); env["db"].commit(); env["db"].refresh(e)
    return e


def _wake_and_drain(env, t, member="nina"):
    wakeup.enqueue(env["db"], organization_id=env["org"].id, member_id=env[member].id, reason="assigned",
                   task_id=t.id, dedupe_key=f"assigned:{t.id}:{datetime.utcnow().timestamp()}")
    env["db"].expire_all()
    return asyncio.run(wakeup.drain(env["db"], now=datetime.utcnow() + timedelta(seconds=11)))


def _prior_run(env, cost, member="nina"):
    t = _task(env, title="cũ", status="done")
    env["db"].add(TaskRun(organization_id=env["org"].id, task_id=t.id, member_id=env[member].id,
                          status="succeeded", cost_usd=cost))
    env["db"].commit()


def _end(env, t, cost, state="final"):
    db = env["db"]; db.expire_all()
    t = db.get(Task, t.id)
    run = db.query(TaskRun).filter(TaskRun.task_id == t.id).order_by(TaskRun.id.desc()).first()
    run.cost_usd = cost; db.add(run); db.commit()
    st = stream.ConsumerState(session_key=run.session_key, task_id=t.id, organization_id=env["org"].id)
    stream.apply_terminal_state(db, t, st, {"state": state})
    db.expire_all()
    return db.get(TaskRun, run.id)


def _ledger(env, e):
    env["db"].expire_all()
    return [(x.entry_type, round(x.amount, 6), x.source_id)
            for x in env["db"].query(BudgetLedgerEntry).filter_by(budget_id=e.id).order_by(BudgetLedgerEntry.id)]


# ------------------------------------------------------------------ cổng: 0 chat.send


def test_seat_with_010_limit_and_real_run_history_sends_nothing(env):
    """Điều kiện 'Xong khi' của D2.3: ước tính từ run thật (0,15) > hạn mức 0,10."""
    _prior_run(env, 0.15)
    e = _env(env, 0.10)
    t = _task(env)
    out = _wake_and_drain(env, t)
    assert out[0]["decision"] == "skipped" and out[0]["reason"].startswith("budget: ")
    assert env["rt"].calls == []                                       # gateway không nhận chat.send
    assert env["db"].query(TaskRun).filter_by(task_id=t.id).count() == 0
    assert _ledger(env, e) == []


def test_dispatch_reserves_before_send_and_ties_hold_to_the_run(env):
    e = _env(env, 0.10)
    t = _task(env)
    out = _wake_and_drain(env, t)
    assert out[0]["decision"] == "dispatched" and len(env["rt"].calls) == 1
    run_id = out[0]["run_id"]
    assert _ledger(env, e) == [("reserve", 0.05, f"run:{run_id}")]
    env["db"].refresh(e)
    assert e.amount_reserved == pytest.approx(0.05) and e.amount_spent == 0


def test_settle_uses_real_cost_and_releases_the_rest(env):
    e = _env(env, 1.0)
    t = _task(env)
    rid = _wake_and_drain(env, t)[0]["run_id"]
    _end(env, t, 0.03)
    assert _ledger(env, e) == [("reserve", 0.05, f"run:{rid}"), ("spend", 0.03, f"run:{rid}"),
                               ("release", 0.02, f"run:{rid}")]
    env["db"].refresh(e)
    assert e.amount_spent == pytest.approx(0.03) and e.amount_reserved == pytest.approx(0)


def test_cost_above_hold_is_spent_beyond_reservation(env):
    e = _env(env, 1.0)
    t = _task(env)
    _wake_and_drain(env, t)
    _end(env, t, 0.08)
    env["db"].refresh(e)
    assert e.amount_spent == pytest.approx(0.08) and e.amount_reserved == pytest.approx(0)
    assert [k for k, _, _ in _ledger(env, e)] == ["reserve", "spend", "spend"]


def test_runtime_failure_releases_the_hold(env, monkeypatch):
    e = _env(env, 1.0)
    bad = FakeRuntime(fail=True)
    monkeypatch.setattr("app.services.agent_dispatch.get_runtime", lambda: bad)
    t = _task(env)
    out = _wake_and_drain(env, t)
    assert out[0]["decision"] in ("failed", "skipped")
    env["db"].refresh(e)
    assert e.amount_reserved == pytest.approx(0) and e.amount_spent == 0
    assert [k for k, _, _ in _ledger(env, e)] == ["reserve", "release"]


def test_failed_run_keeps_real_spend_and_releases_hold(env):
    e = _env(env, 1.0)
    t = _task(env)
    _wake_and_drain(env, t)
    run = _end(env, t, 0.01, state="error")
    env["db"].refresh(e)
    assert run.status not in ("running", "queued")
    assert e.amount_spent == pytest.approx(0.01) and e.amount_reserved == pytest.approx(0)


# ------------------------------------------------------------------ nấc 80% / 100%


def test_80_percent_warns_inbox_and_puts_critical_rule_in_block_6(env):
    e = _env(env, 0.10)
    t = _task(env)
    _wake_and_drain(env, t)
    _end(env, t, 0.085)
    env["db"].refresh(e)
    assert e.threshold_state == "warned"
    inbox = env["db"].query(InboxItem).filter_by(related_type="budget_envelope", related_id=str(e.id)).all()
    assert [i.recipient_member_id for i in inbox] == [env["boss"].id]
    t2 = _task(env, title="việc tiếp")
    pack = work_context.build_pack(env["db"], t2, organization_id=env["org"].id)
    block6 = pack["text"].split("Luật áp dụng cho việc này", 1)[1]
    assert "CHỈ làm việc critical" in block6
    t3 = _task(env, title="của Mia", assignee="mia")                 # seat khác không bị luật này
    assert "critical" not in work_context.build_pack(env["db"], t3, organization_id=env["org"].id)["text"]


def test_100_percent_pauses_seat_blocks_its_tasks_and_audits(env):
    e = _env(env, 0.10)
    t = _task(env)
    other = _task(env, title="chờ làm")
    mias = _task(env, title="việc Mia", assignee="mia")
    _wake_and_drain(env, t)
    _end(env, t, 0.12)
    db = env["db"]; db.expire_all()
    e = db.get(BudgetEnvelope, e.id)
    assert e.threshold_state == "exhausted"
    assert db.get(Member, env["nina"].id).status == "paused"
    o = db.get(Task, other.id)
    assert o.status == "blocked" and o.execution_state["budget_block"]["budget_id"] == e.id
    assert db.get(Task, mias.id).status == "todo" and db.get(Member, env["mia"].id).status == "active"
    audit = db.query(AuditEvent).filter_by(action="budget.exhausted", object_id=str(e.id)).one()
    assert json.loads(audit.payload_json)["paused_members"] == [env["nina"].id]
    n = len(env["rt"].calls)
    t4 = _task(env, title="việc mới")
    out = _wake_and_drain(env, t4)
    assert out[0]["decision"] == "skipped" and out[0]["reason"].startswith("budget")
    assert len(env["rt"].calls) == n


def test_override_needs_reason_restores_seat_tasks_and_is_audited(env):
    e = _env(env, 0.10)
    t = _task(env)
    other = _task(env, title="chờ làm")
    _wake_and_drain(env, t)
    _end(env, t, 0.12)
    t4 = _task(env, title="việc mới")
    _wake_and_drain(env, t4)                                       # bị bỏ vì budget
    c, H = env["client"], env["H"]
    assert c.post(f"/api/v9/budgets/{e.id}/override", headers=H, json={"add_usd": 1}).status_code == 422
    r = c.post(f"/api/v9/budgets/{e.id}/override", headers=H, json={"add_usd": 1, "reason": "duyệt thêm quý 4"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["budget"]["threshold_state"] == "ok" and env["nina"].id in body["restored_members"]
    assert other.id in body["restored_tasks"] and body["requeued_wakeups"]
    db = env["db"]; db.expire_all()
    assert db.get(Member, env["nina"].id).status == "active" and db.get(Task, other.id).status == "todo"
    a = db.query(AuditEvent).filter_by(action="budget.override", object_id=str(e.id)).one()
    assert json.loads(a.payload_json)["reason"] == "duyệt thêm quý 4"
    out = asyncio.run(wakeup.drain(db, now=datetime.utcnow() + timedelta(seconds=11)))
    assert any(o["decision"] == "dispatched" for o in out)


def test_override_requires_manager_role(env):
    e = _env(env, 0.10)
    tok = create_access_token(env["user"].id, env["org"].id, "member")
    r = env["client"].post(f"/api/v9/budgets/{e.id}/override", headers={"Authorization": f"Bearer {tok}"},
                           json={"add_usd": 1, "reason": "tự mở"})
    assert r.status_code in (401, 403)


# ------------------------------------------------------------------ phạm vi


@pytest.mark.parametrize("scope,sid_key,blocks_nina", [
    ("member", "mia", False), ("department", "dept", True), ("company", "co", True),
    ("project", "proj", True), ("project", "proj2", False),
])
def test_scope_coverage(env, scope, sid_key, blocks_nina):
    e = _env(env, 0.10, scope=scope, sid=env[sid_key].id)
    e.amount_spent = 0.10; env["db"].add(e); env["db"].commit()
    t = _task(env)
    out = _wake_and_drain(env, t)
    assert (out[0]["decision"] == "skipped") is blocks_nina, out


def test_goal_scope_and_legacy_goal_envelope(env):
    from app.models import ExecutiveGoal
    g = ExecutiveGoal(organization_id=env["org"].id, title="G", objective="o")
    env["db"].add(g); env["db"].commit()
    env["db"].add(BudgetEnvelope(organization_id=env["org"].id, goal_id=g.id, name="v9 goal", amount_limit=0.1,
                                 amount_spent=0.1, status="active"))
    env["db"].commit()
    free = _task(env, title="không mục tiêu")
    assert _wake_and_drain(env, free)[0]["decision"] == "dispatched"
    tied = _task(env, title="thuộc mục tiêu", assignee="mia")
    tied.goal_id = g.id; env["db"].add(tied); env["db"].commit()
    out = _wake_and_drain(env, tied, member="mia")
    assert out[0]["decision"] == "skipped" and "v9 goal" in out[0]["reason"]


# ------------------------------------------------------------------ đối chiếu gateway


def test_true_up_follows_gateway_sessions_usage_and_is_idempotent(env):
    e = _env(env, 5.0)
    t = _task(env)
    _wake_and_drain(env, t)
    run = _end(env, t, 0.05)                      # local (session.message) = 0,05
    env["rt"].usage[run.session_key] = 0.07       # gateway = 0,07
    out = asyncio.run(bs.true_up_run(env["db"], run, env["rt"]))
    assert out["actual_usd"] == pytest.approx(0.07)
    env["db"].refresh(e)
    assert e.amount_spent == pytest.approx(0.07)
    n = len(_ledger(env, e))
    asyncio.run(bs.true_up_run(env["db"], run, env["rt"]))
    assert len(_ledger(env, e)) == n               # luỹ đẳng
    db = env["db"]
    run2 = TaskRun(organization_id=env["org"].id, task_id=t.id, member_id=env["nina"].id, status="succeeded",
                   session_key=run.session_key, cost_usd=0.02)
    db.add(run2); db.commit()
    env["rt"].usage[run.session_key] = 0.10       # run thứ hai cùng phiên chỉ nhận phần của nó
    out2 = asyncio.run(bs.true_up_run(db, run2, env["rt"]))
    assert out2["actual_usd"] == pytest.approx(0.03)
    db.refresh(e)
    assert e.amount_spent == pytest.approx(0.10)
    env["rt"].usage[run.session_key] = 0.09       # gateway thấp hơn → điều chỉnh giảm
    asyncio.run(bs.true_up_run(db, run2, env["rt"]))
    db.refresh(e)
    assert e.amount_spent == pytest.approx(0.09)


# ------------------------------------------------------------------ API


def test_create_validates_scope_and_overview_breaks_down_spend(env):
    c, H = env["client"], env["H"]
    r = c.post("/api/v9/budgets", headers=H, json={"organization_id": env["org"].id, "name": "x",
                                                    "amount_limit": 1, "scope_type": "member"})
    assert r.status_code == 422
    r = c.post("/api/v9/budgets", headers=H, json={"organization_id": env["org"].id, "name": "Nina T10",
                                                    "amount_limit": 1, "scope_type": "member",
                                                    "scope_id": env["nina"].id})
    assert r.status_code == 200, r.text
    t = _task(env)
    _wake_and_drain(env, t)
    _end(env, t, 0.04)
    ov = c.get("/api/v9/budgets-overview", headers=H).json()
    b = next(x for x in ov["budgets"] if x["name"] == "Nina T10")
    assert b["scope_type"] == "member" and b["amount_spent"] == pytest.approx(0.04)
    assert b["spend"]["by_seat"] == [{"name": "Nina", "spent_usd": 0.04}]
    assert b["spend"]["by_project"] == [{"name": "P", "spent_usd": 0.04}]
    assert b["spend"]["by_task"][0]["name"].startswith(f"#{t.id}")
