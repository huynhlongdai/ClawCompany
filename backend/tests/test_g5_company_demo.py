"""G5 (giả lập) — kịch bản demo ở trang kế hoạch, chạy hết đường ống với runtime giả:

Mục tiêu "Ra mắt bộ sưu tập hè, $20" → Nina lập kế hoạch → người duyệt → 3 phòng
nhận việc (trưởng phòng giao người) → làm theo thứ tự phụ thuộc → review chéo
giữa các phòng → mục tiêu hoàn thành → người chỉ nhận 2 lần ping.

Phần "chi phí khớp ±5%" cần gateway thật (giá model, usage) — không kiểm ở đây.
"""
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
from app.models import APIKey, CompanyEvent, ExecutiveGoal, TaskRun, Wakeup
from app.models.auth import User
from app.models.entities import Agent, Company, Department, Member, Organization, Task
from app.models.extended import InboxItem
from app.services import execution_policy, strategy, task_journal, wakeup
from app.services import task_lifecycle as lifecycle


class FakeRuntime:
    def __init__(self):
        self.calls = []

    async def run_agent(self, runtime_agent_id, input_text, metadata=None, session_key=None):
        from app.runtime.base import RuntimeRun
        self.calls.append({"agent": runtime_agent_id, "session_key": session_key, "text": input_text})
        return RuntimeRun(task_id="t", run_id=f"run-{len(self.calls)}", session_key=session_key or "",
                          status="running", raw={})

    async def rpc(self, method, params=None):
        return {"sessions": [], "cacheStatus": {"status": "fresh"}}


@pytest.fixture()
def world(monkeypatch):
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
    org = Organization(name="Mây", slug="may-g5"); db.add(org); db.commit()
    co = Company(organization_id=org.id, name="Mây Fashion", status="active"); db.add(co); db.commit()
    boss = Member(organization_id=org.id, company_id=co.id, name="Long", member_type="human", role="CEO", status="active")
    db.add(boss); db.commit()

    def seat(name, dept=None, manager=None):
        m = Member(organization_id=org.id, company_id=co.id, department_id=dept.id if dept else None, name=name,
                   member_type="agent", role=name, status="active", manager_id=(manager or boss).id)
        db.add(m); db.commit()
        db.add(Agent(member_id=m.id, runtime_agent_id=name.lower(), lifecycle="active")); db.commit()
        return m

    nina = seat("Nina")
    D, heads, workers = {}, {}, {}
    for k, name, h, w in [("sx", "Sản xuất", "Khoa", "Chi"), ("mk", "Marketing", "Hana", "An"), ("bh", "Bán hàng", "Bao", "Dung")]:
        d = Department(company_id=co.id, name=name); db.add(d); db.commit()
        heads[k] = seat(h, d); workers[k] = seat(w, d, heads[k])
        d.head_member_id = heads[k].id; db.commit()
        D[k] = d
    user = User(email="long@may.test", password_hash="x", member_id=boss.id); db.add(user); db.commit()
    rt = FakeRuntime()
    monkeypatch.setattr("app.services.agent_dispatch.get_runtime", lambda: rt)
    monkeypatch.setattr("app.runtime.factory.get_runtime", lambda: rt)

    async def no_hours(agent):
        return None
    monkeypatch.setattr(wakeup, "ACTIVE_HOURS_LOOKUP", no_hours)
    client = TestClient(app)

    def mcp(member, name, args):
        raw = f"cc_g5_{member.id}_{datetime.utcnow().timestamp()}_" + "x" * 20
        db.add(APIKey(organization_id=org.id, member_id=member.id, name="seat", key_prefix=raw[:12],
                      key_hash=pwd_context.hash(raw), scopes=json.dumps(["*"])))
        db.commit()
        r = client.post("/api/mcp", headers={"X-API-Key": raw}, json={
            "jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": args}})
        assert r.status_code == 200, r.text
        res = r.json()["result"]
        assert not res["isError"], res
        return res["structuredContent"]

    H = {"Authorization": f"Bearer {create_access_token(user.id, org.id, 'admin')}"}
    yield dict(db=db, org=org, co=co, boss=boss, nina=nina, D=D, heads=heads, workers=workers, rt=rt,
               client=client, mcp=mcp, H=H)
    app.dependency_overrides.pop(get_db, None)


def drain(w):
    w["db"].expire_all()
    return asyncio.run(wakeup.drain(w["db"], now=datetime.utcnow() + timedelta(seconds=11)))


def close_runs(w, member):
    db = w["db"]; db.expire_all()
    for tr in db.query(TaskRun).filter(TaskRun.member_id == member.id,
                                       TaskRun.status.in_(("queued", "dispatched", "running"))).all():
        lifecycle.finish_run(db, tr, "completed")


def test_summer_collection_demo_two_pings(world):
    w = world; db, c, H, mcp = w["db"], w["client"], w["H"], w["mcp"]
    D, heads, workers = w["D"], w["heads"], w["workers"]

    # 1. Người đặt mục tiêu (không phải ping: người tự làm).
    r = c.post("/api/v9/goals", headers=H, json={"organization_id": w["org"].id, "company_id": w["co"].id,
                                                 "title": "Ra mắt bộ sưu tập hè", "objective": "Ra mắt bộ sưu tập hè trong 2 tuần",
                                                 "budget_limit": 20})
    goal_id = r.json()["id"]
    drain(w)                                                   # Nina lập kế hoạch
    plan = [
        {"key": "design", "title": "Thiết kế 12 mẫu", "department_id": D["sx"].id, "budget_usd": 6,
         "acceptance_criteria": "12 bản vẽ được duyệt", "reviewer_member_id": heads["mk"].id},
        {"key": "content", "title": "Bộ ảnh + bài đăng", "department_id": D["mk"].id, "budget_usd": 7,
         "depends_on": ["design"], "acceptance_criteria": "20 ảnh, 5 bài", "reviewer_member_id": heads["bh"].id},
        {"key": "sales", "title": "Mở bán trên sàn", "department_id": D["bh"].id, "budget_usd": 7,
         "depends_on": ["content"], "acceptance_criteria": "Gian hàng mở trên 3 kênh", "reviewer_member_id": heads["sx"].id},
    ]
    out = mcp(w["nina"], "company_plan_submit", {"goal_id": goal_id, "summary": "Thiết kế → nội dung → bán, mỗi phòng một khâu",
                                                 "tasks": plan})
    close_runs(w, w["nina"])

    # 2. Ping #1: duyệt kế hoạch.
    assert c.post(f"/api/approvals/{out['approval_id']}/resolve", headers=H, json={"status": "approved"}).status_code == 200
    db.expire_all()
    kids = {t.title: t for t in strategy.goal_tasks(db, goal_id)}
    order = [("Thiết kế 12 mẫu", "sx", "mk"), ("Bộ ảnh + bài đăng", "mk", "bh"), ("Mở bán trên sàn", "bh", "sx")]

    # 3. Ba trưởng phòng được đánh thức, mỗi người giao việc cho nhân viên của phòng.
    drain(w)
    for title, dk, _ in order:
        mcp(heads[dk], "company_task_assign", {"task_id": kids[title].id, "member_id": workers[dk].id,
                                               "reason": f"{workers[dk].name} làm khâu này của phòng"})
        close_runs(w, heads[dk])

    # 4. Làm theo thứ tự phụ thuộc; mỗi việc được trưởng phòng KHÁC review chéo rồi mới done.
    for title, dk, rk in order:
        drain(w)
        db.expire_all()
        t = db.get(Task, kids[title].id)
        assert t.assignee_member_id == workers[dk].id and t.status == "in_progress", (title, t.status)
        task_journal.append(db, t, kind="result", summary=f"Xong: {title}", actor_member_id=workers[dk].id)
        close_runs(w, workers[dk])
        lifecycle.transition(db, t, "review", via="mcp", actor_member_id=workers[dk].id)
        db.expire_all()
        t = db.get(Task, t.id)
        assert execution_policy.is_current_reviewer(t, heads[rk].id)
        rq = db.query(Wakeup).filter(Wakeup.reason == "review_requested", Wakeup.task_id == t.id).one()
        assert rq.member_id == heads[rk].id                    # agent review chéo được đánh thức
        execution_policy.decide(db, t, member_id=heads[rk].id, decision="approve", note="đạt tiêu chí")
        db.expire_all()
        assert db.get(Task, t.id).status == "done"

    # 5. Mục tiêu hoàn thành → ping #2.
    db.expire_all()
    goal = db.get(ExecutiveGoal, goal_id)
    assert goal.status == "completed" and goal.progress == 100
    pings = db.query(InboxItem).filter(InboxItem.recipient_member_id == w["boss"].id).order_by(InboxItem.id).all()
    assert [p.item_type for p in pings] == ["approval_pending", "goal_completed"], [(p.item_type, p.title) for p in pings]
    assert sum(p.count for p in pings) == 2
    # Ai đã chạy: Nina 1 lượt, 3 trưởng phòng định tuyến, 3 nhân viên làm.
    agents = [x["agent"] for x in w["rt"].calls]
    assert agents.count("nina") == 1
    assert sorted(a for a in agents if a in ("khoa", "hana", "bao")) == ["bao", "hana", "khoa"]
    assert sorted(a for a in agents if a in ("chi", "an", "dung")) == ["an", "chi", "dung"]
    ev = [e.event_type for e in db.query(CompanyEvent).order_by(CompanyEvent.id)]
    for kind in ("goal.planning_started", "goal.plan_submitted", "goal.plan_applied", "task.routed",
                 "task.review.approved", "goal.completed"):
        assert kind in ev, kind
