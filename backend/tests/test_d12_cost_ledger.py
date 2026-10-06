"""D1.2 — đối chiếu hai nguồn chi phí bằng frame THẬT của gateway OpenClaw 2026.9.8.

Fixture ``fixtures/d12_cost_frames.json`` là ``session.message`` ghi bằng
``OPENCLAW_FRAME_LOG`` và kết quả ``sessions.usage`` cùng phiên (task 20,
model scripted giá 3/15 USD mỗi 1M token). Xem ``_reports/cost-reconciliation.md``.

Lỗi gốc: không đường code nào ghi tiền model — ``usage_events`` chỉ có
``task_dispatch`` đơn giá 0, ``task_runs.cost_usd`` luôn 0 — nên mọi phiên lệch
100% so với gateway.
"""
import asyncio
import json
from pathlib import Path

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
from app.models import CompanyEvent, TaskRun, UsageEvent
from app.models.auth import User
from app.models.entities import Agent, Company, Member, Organization, Project, Task
from app.runtime.openclaw_native import normalize_event
from app.services import cost_ledger, runtime_stream as stream
import app.api.tasks as tasks_api

FIX = json.loads((Path(__file__).parent / "fixtures" / "d12_cost_frames.json").read_text())
SK = FIX["session_key"]
GW_COST = FIX["sessions_usage"]["sessions"][0]["usage"]["totalCost"]
GW_TOKENS = FIX["sessions_usage"]["sessions"][0]["usage"]["totalTokens"]


class GatewayStub:
    """Chỉ trả nguyên văn ``sessions.usage`` đã ghi; không tự tính gì."""

    def __init__(self, result):
        self.result, self.calls = result, []

    async def rpc(self, method, params=None):
        self.calls.append((method, params))
        assert method == "sessions.usage"
        return self.result


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
    org = Organization(name="Nova", slug="nova-d12"); db.add(org); db.commit()
    other = Organization(name="Khác", slug="other-d12"); db.add(other); db.commit()
    co = Company(organization_id=org.id, name="Nova Labs", status="active"); db.add(co); db.commit()
    boss = Member(organization_id=org.id, company_id=co.id, name="Long", member_type="human", role="CEO", status="active")
    nina = Member(organization_id=org.id, company_id=co.id, name="Nina", member_type="agent", role="CoS", status="active")
    db.add_all([boss, nina]); db.commit()
    agent = Agent(member_id=nina.id, runtime_agent_id="dev")
    db.add(agent); db.commit()
    user = User(email="long@nova.test", password_hash="x", member_id=boss.id); db.add(user); db.commit()
    proj = Project(company_id=co.id, name="P"); db.add(proj); db.commit()
    task = Task(project_id=proj.id, title="Chạy lệnh", status="in_progress", assignee_member_id=nina.id,
                runtime_session_key=SK, runtime_run_id="clawcompany:agent:dev:company-task-20:task-20:x")
    db.add(task); db.commit()
    run = TaskRun(organization_id=org.id, task_id=task.id, member_id=nina.id, status="running",
                  session_key=SK, runtime_run_id=task.runtime_run_id)
    db.add(run); db.commit()
    task.checkout_run_id = run.id; db.add(task); db.commit()
    state = stream.ConsumerState(session_key=SK, task_id=task.id, organization_id=org.id)
    gw = GatewayStub(FIX["sessions_usage"])
    monkeypatch.setattr(tasks_api, "get_runtime", lambda: gw)
    token = create_access_token(user.id, org.id, "admin")
    yield {"db": db, "org": org, "task": task, "run": run, "state": state, "gw": gw,
           "client": TestClient(app), "H": {"Authorization": f"Bearer {token}"}}
    app.dependency_overrides.pop(get_db, None)


def _feed_all(env, times=1):
    for _ in range(times):
        for frame in FIX["session_messages"]:
            stream.handle_event(env["db"], env["state"], normalize_event(frame))


def _model_rows(env):
    env["db"].expire_all()
    return env["db"].query(UsageEvent).filter(UsageEvent.event_type == cost_ledger.EVENT_TYPE).all()


def test_real_session_message_frames_become_model_usage_rows_once(env):
    _feed_all(env, times=2)  # gateway gửi lại / hai lần subscribe → không đếm đôi
    rows = _model_rows(env)
    assert len(rows) == 2, "một dòng cho mỗi tin assistant có usage, tin user bỏ qua"
    assert round(sum(r.amount for r in rows), 6) == round(GW_COST, 6)
    meta = [json.loads(r.metadata_json) for r in rows]
    assert sum(m["total_tokens"] for m in meta) == GW_TOKENS
    assert {m["model"] for m in meta} == {"approval-e2e"}
    assert all(r.task_id == env["task"].id and r.agent_id is not None for r in rows)


def test_task_run_carries_tokens_and_cost(env):
    _feed_all(env)
    env["db"].expire_all()
    run = env["db"].get(TaskRun, env["run"].id)
    u = FIX["sessions_usage"]["sessions"][0]["usage"]
    assert run.tokens_in == u["input"] + u["cacheRead"] + u["cacheWrite"]
    assert run.tokens_out == u["output"]
    assert round(run.cost_usd, 6) == round(GW_COST, 6)


def test_reconcile_matches_gateway_after_fix(env):
    _feed_all(env)
    report = asyncio.run(cost_ledger.reconcile(env["db"], env["gw"], organization_id=env["org"].id))
    row = report["rows"][0]
    assert row["status"] == "match" and row["cost_delta_pct"] == 0.0 and row["missing_model_calls"] == 0
    s = report["summary"]
    assert s["delta_pct"] == 0.0
    assert s["conclusion"].startswith("Nguồn sự thật là gateway sessions.usage")
    assert "độ lệch 0.00%" in s["conclusion"]
    assert env["gw"].calls == [("sessions.usage", {"key": SK})]
    ev = env["db"].query(CompanyEvent).filter(CompanyEvent.event_type == "cost.reconciled").one()
    assert json.loads(ev.payload_json)["reason"] == s["conclusion"]


def test_missed_frames_show_up_as_drift_and_gateway_wins(env):
    # Follower bám muộn (đo thật: task 24) → không có dòng nào phía ClawCompany.
    report = asyncio.run(cost_ledger.reconcile(env["db"], env["gw"], organization_id=env["org"].id))
    row = report["rows"][0]
    assert row["status"] == "drift" and row["cost_delta_pct"] == 100.0 and row["missing_model_calls"] == 2
    assert "Lệch > 10%" in report["summary"]["conclusion"]


def test_endpoint_is_admin_only_and_scoped_to_org(env):
    _feed_all(env)
    db = env["db"]
    other = db.query(Organization).filter(Organization.slug == "other-d12").one()
    oco = Company(organization_id=other.id, name="Khác", status="active"); db.add(oco); db.commit()
    op = Project(company_id=oco.id, name="Q"); db.add(op); db.commit()
    db.add(Task(project_id=op.id, title="Việc tổ chức khác", runtime_session_key="agent:x:company-task-99")); db.commit()
    r = env["client"].get("/api/tasks/cost-reconciliation", headers=env["H"])
    assert r.status_code == 200, r.text
    assert [x["task_id"] for x in r.json()["rows"]] == [env["task"].id]
    assert r.json()["summary"]["delta_pct"] == 0.0
    assert env["client"].get("/api/tasks/cost-reconciliation").status_code in (401, 403)


def test_pure_compare_and_message_parser():
    assert cost_ledger.message_usage({"message": {"role": "user", "usage": {"input": 5}}}) is None
    assert cost_ledger.compare({"cost_usd": 0, "total_tokens": 0, "model_calls": 0}, None)["status"] == "gateway_missing"
    near = cost_ledger.compare({"cost_usd": 0.0098, "total_tokens": 98, "model_calls": 1},
                               {"cost_usd": 0.01, "total_tokens": 100, "assistant_messages": 1})
    assert near["status"] == "within_tolerance" and near["cost_delta_pct"] == 2.0
