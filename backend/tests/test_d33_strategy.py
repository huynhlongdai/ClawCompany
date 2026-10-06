"""D3.3 — Nina phân rã mục tiêu. HTTP thật: goal qua API v9, Nina gọi MCP
``company_plan_submit`` bằng API key của seat, người duyệt qua Hộp việc
(``/api/approvals/{id}/resolve``) và ``/api/strategy``. Runtime giả chỉ ghi ``run_agent``."""
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
from app.models import APIKey, Approval, AuditEvent, CompanyEvent, ExecutiveGoal, TaskDependency, TaskRun, Wakeup
from app.models.auth import User
from app.models.entities import Agent, Company, Department, Member, Organization, Task
from app.models.extended import InboxItem
from app.models.v37 import TaskJournalEntry
from app.services import strategy, wakeup
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
    org = Organization(name="Mây", slug="may-d33"); db.add(org); db.commit()
    co = Company(organization_id=org.id, name="Mây Fashion", status="active"); db.add(co); db.commit()
    boss = Member(organization_id=org.id, company_id=co.id, name="Long", member_type="human", role="CEO",
                  status="active")
    db.add(boss); db.commit()

    def seat(name, rid, dept=None, role=""):
        m = Member(organization_id=org.id, company_id=co.id, department_id=dept.id if dept else None, name=name,
                   member_type="agent", role=role or name, status="active", manager_id=boss.id)
        db.add(m); db.commit()
        db.add(Agent(member_id=m.id, runtime_agent_id=rid, lifecycle="active")); db.commit()
        return m

    depts, heads, staff = {}, {}, {}
    for key, name, head, worker in [("mk", "Marketing", "Hana", "An"), ("sx", "Sản xuất", "Khoa", "Chi"),
                                    ("bh", "Bán hàng", "Bảo", "Dung")]:
        d = Department(company_id=co.id, name=name); db.add(d); db.commit()
        heads[key] = seat(head, head.lower(), d, f"Trưởng phòng {name}")
        staff[key] = seat(worker, worker.lower(), d, f"Nhân viên {name}")
        d.head_member_id = heads[key].id; db.commit()
        depts[key] = d
    nina = seat("Nina", "nina", None, "Giám đốc điều hành AI")
    user = User(email="long@may.test", password_hash="x", member_id=boss.id); db.add(user); db.commit()
    fake = FakeRuntime()
    monkeypatch.setattr("app.services.agent_dispatch.get_runtime", lambda: fake)
    monkeypatch.setattr("app.runtime.factory.get_runtime", lambda: fake)

    async def no_hours(agent):
        return None
    monkeypatch.setattr(wakeup, "ACTIVE_HOURS_LOOKUP", no_hours)
    client = TestClient(app)

    def call(member, name, args, status=200):
        raw = f"cc_test_{member.id}_{datetime.utcnow().timestamp()}_" + "x" * 20
        db.add(APIKey(organization_id=org.id, member_id=member.id, name="seat", key_prefix=raw[:12],
                      key_hash=pwd_context.hash(raw), scopes=json.dumps(["*"])))
        db.commit()
        r = client.post("/api/mcp", headers={"X-API-Key": raw},
                        json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                              "params": {"name": name, "arguments": args}})
        assert r.status_code == status, r.text
        if status != 200:
            return True, r.json()["error"]
        res = r.json()["result"]
        return res["isError"], res["structuredContent"]

    token = create_access_token(user.id, org.id, "admin")
    H = {"Authorization": f"Bearer {token}"}

    def goal(budget=20.0):
        r = client.post("/api/v9/goals", headers=H, json={
            "organization_id": org.id, "company_id": co.id, "title": "Ra mắt bộ sưu tập hè",
            "objective": "Ra mắt bộ sưu tập hè trong 2 tuần", "budget_limit": budget})
        assert r.status_code == 200, r.text
        db.expire_all()
        return db.get(ExecutiveGoal, r.json()["id"])

    yield {"db": db, "org": org, "co": co, "boss": boss, "nina": nina, "depts": depts, "heads": heads,
           "staff": staff, "rt": fake, "client": client, "call": call, "H": H, "goal": goal}
    app.dependency_overrides.pop(get_db, None)


def _drain(env):
    env["db"].expire_all()
    return asyncio.run(wakeup.drain(env["db"], now=datetime.utcnow() + timedelta(seconds=11)))


def _finish_open_runs(env, member):
    db = env["db"]; db.expire_all()
    for tr in db.query(TaskRun).filter(TaskRun.member_id == member.id,
                                       TaskRun.status.in_(("queued", "dispatched", "running"))):
        lifecycle.finish_run(db, tr, "completed")


def _plan(env, n=3, budget=5.0):
    d = env["depts"]
    rows = [
        {"key": "design", "title": "Thiết kế 12 mẫu", "department_id": d["sx"].id,
         "acceptance_criteria": "12 bản vẽ được duyệt", "budget_usd": budget},
        {"key": "content", "title": "Bộ ảnh + bài đăng", "department_id": d["mk"].id, "depends_on": ["design"],
         "acceptance_criteria": "20 ảnh, 5 bài", "budget_usd": budget},
        {"key": "sales", "title": "Mở bán trên sàn", "department_id": d["bh"].id, "depends_on": ["content"],
         "acceptance_criteria": "Gian hàng mở, 3 kênh", "budget_usd": budget},
        {"key": "kpi", "title": "Báo cáo doanh số tuần 1", "department_id": d["bh"].id, "depends_on": ["sales"],
         "acceptance_criteria": "Báo cáo có số đơn", "budget_usd": 1.0},
    ]
    return rows[:n]


def _events(env, kind):
    env["db"].expire_all()
    return [json.loads(e.payload_json) for e in env["db"].query(CompanyEvent)
            .filter(CompanyEvent.event_type == kind).order_by(CompanyEvent.id).all()]


def test_goal_created_wakes_nina_with_planning_protocol(env):
    db = env["db"]
    g = env["goal"]()
    pt = strategy.planning_task(db, g.id)
    assert pt.assignee_member_id == env["nina"].id and pt.goal_id == g.id and pt.status == "todo"
    wk = db.query(Wakeup).filter(Wakeup.task_id == pt.id).one()
    assert wk.reason == "goal_created" and wk.member_id == env["nina"].id
    _drain(env)
    assert [c["agent"] for c in env["rt"].calls] == ["nina"]
    text = env["rt"].calls[0]["text"]
    assert "company_plan_submit" in text and f"goal_id={g.id}" in text
    for d in env["depts"].values():
        assert f"Phòng #{d.id} {d.name}" in text
    assert "Ngân sách mục tiêu: $20.00" in text
    assert db.query(TaskRun).filter(TaskRun.task_id == pt.id).one().trigger_kind == "goal_created"


def test_revision_loop_then_approve_creates_tasks_for_three_departments(env):
    db, c, H, call = env["db"], env["client"], env["H"], env["call"]
    g = env["goal"](); _drain(env)
    err, out = call(env["nina"], "company_plan_submit",
                    {"goal_id": g.id, "summary": "Chia theo chuỗi thiết kế → nội dung → bán", "tasks": _plan(env, 3)})
    assert not err, out
    a = db.get(Approval, out["approval_id"])
    assert (a.action, a.status, a.revision, a.approver_member_id) == ("strategy", "pending", 1, env["boss"].id)
    assert len(a.payload["tasks"]) == 3 and a.expires_at is not None
    inbox = db.query(InboxItem).filter(InboxItem.recipient_member_id == env["boss"].id).all()
    assert any("approval_pending" in (i.kinds or "") and i.status == "unread" for i in inbox)
    # Gửi trùng khi đang chờ → conflict
    err, out2 = call(env["nina"], "company_plan_submit", {"goal_id": g.id, "summary": "gửi lại lần nữa", "tasks": _plan(env)})
    assert err and out2["error"] == "conflict"
    # Yêu cầu sửa
    _finish_open_runs(env, env["nina"])
    r = c.post(f"/api/strategy/plans/{a.id}/request-revision", headers=H, json={"note": "Thêm việc báo cáo doanh số tuần 1"})
    assert r.status_code == 200, r.text
    db.expire_all()
    a = db.get(Approval, a.id)
    assert a.status == "revision_requested" and db.get(ExecutiveGoal, g.id).status == "plan_revision"
    pt = strategy.planning_task(db, g.id)
    note = db.query(TaskJournalEntry).filter(TaskJournalEntry.task_id == pt.id).order_by(TaskJournalEntry.seq.desc()).first()
    assert "báo cáo doanh số" in note.summary
    wk = db.get(Wakeup, r.json()["wakeup_id"])
    assert wk.reason == "changes_requested" and wk.member_id == env["nina"].id
    _drain(env)
    assert len(env["rt"].calls) == 2 and "báo cáo doanh số" in env["rt"].calls[1]["text"]
    # Duyệt khi đang chờ sửa → 409; gửi lại → rev 2
    assert c.post(f"/api/approvals/{a.id}/resolve", headers=H, json={"status": "approved"}).status_code == 409
    err, out = call(env["nina"], "company_plan_submit",
                    {"goal_id": g.id, "summary": "Thêm báo cáo tuần 1 theo góp ý", "tasks": _plan(env, 4)})
    assert not err, out
    db.expire_all()
    a = db.get(Approval, a.id)
    assert out["approval_id"] == a.id and (a.status, a.revision) == ("pending", 2)
    assert a.payload["history"][0]["revision"] == 1 and "báo cáo" in a.payload["history"][0]["note"]
    assert db.query(Approval).filter(Approval.action == "strategy").count() == 1
    reopened = db.query(InboxItem).filter(InboxItem.recipient_member_id == env["boss"].id,
                                          InboxItem.status == "unread").all()
    assert any("approval_pending" in (i.kinds or "") for i in reopened)     # người duyệt được báo lại
    assert a.expires_at is not None and a.expires_at > datetime.utcnow() + timedelta(hours=23)
    # Duyệt → áp kế hoạch
    r = c.post(f"/api/approvals/{a.id}/resolve", headers=H, json={"status": "approved"})
    assert r.status_code == 200, r.text
    db.expire_all()
    kids = db.query(Task).filter(Task.goal_id == g.id, Task.parent_task_id == pt.id).order_by(Task.id).all()
    assert len(kids) == 4
    by_title = {t.title: t for t in kids}
    assert by_title["Thiết kế 12 mẫu"].assignee_department_id == env["depts"]["sx"].id
    assert by_title["Bộ ảnh + bài đăng"].assignee_department_id == env["depts"]["mk"].id
    assert by_title["Mở bán trên sàn"].assignee_department_id == env["depts"]["bh"].id
    assert {t.assignee_department_id for t in kids} == {d.id for d in env["depts"].values()}
    assert all(t.acceptance_criteria for t in kids)
    deps = {(d.task_id, d.blocked_by_task_id) for d in db.query(TaskDependency).all()}
    assert (by_title["Bộ ảnh + bài đăng"].id, by_title["Thiết kế 12 mẫu"].id) in deps
    assert len(deps) == 3
    routed = db.query(Wakeup).filter(Wakeup.reason == "routed").all()
    assert {w.member_id for w in routed} == {h.id for h in env["heads"].values()}
    assert db.get(ExecutiveGoal, g.id).status == "active"
    assert db.get(Task, pt.id).status == "done"
    applied = _events(env, "goal.plan_applied")
    assert len(applied) == 1 and applied[0]["revision"] == 2
    assert db.query(AuditEvent).filter(AuditEvent.action == "strategy.plan_applied").count() == 1
    # Duyệt lại → 409, không sinh việc đôi
    assert c.post(f"/api/approvals/{a.id}/resolve", headers=H, json={"status": "approved"}).status_code == 409
    assert strategy.plan_apply(db, db.get(Approval, a.id))["already"] is True
    assert db.query(Task).filter(Task.parent_task_id == pt.id).count() == 4
    view = c.get(f"/api/strategy/goals/{g.id}", headers=H).json()
    assert view["plans"][0]["revision"] == 2 and len(view["tasks"]) == 4
    listed = c.get("/api/approvals?status=approved", headers=H).json()
    assert listed[0]["revision"] == 2 and listed[0]["payload"]["applied"]


def test_submit_validation(env):
    g = env["goal"](budget=10.0)
    call, nina, d = env["call"], env["nina"], env["depts"]

    def bad(tasks, code="invalid_argument", who=None, summary="kế hoạch thử nghiệm"):
        err, out = call(who or nina, "company_plan_submit", {"goal_id": g.id, "summary": summary, "tasks": tasks})
        assert err and out["error"] == code, out
        return out["message"]
    assert "ngân sách" in bad(_plan(env, 3, budget=5.0)).lower()
    assert "acceptance_criteria" in bad([{"title": "x", "department_id": d["mk"].id}])
    assert "phòng" in bad([{"title": "x", "department_id": 9999, "acceptance_criteria": "ok"}])
    assert "vòng" in bad([{"key": "a", "title": "a", "acceptance_criteria": "ok", "depends_on": ["b"]},
                          {"key": "b", "title": "b", "acceptance_criteria": "ok", "depends_on": ["a"]}])
    assert "không thuộc phòng" in bad([{"title": "x", "department_id": d["mk"].id,
                                        "member_id": env["staff"]["bh"].id, "acceptance_criteria": "ok"}])
    assert "summary" in bad(_plan(env, 1), summary="ngắn")
    bad(_plan(env, 1), code="forbidden", who=env["heads"]["mk"])           # trưởng phòng không lập kế hoạch
    assert env["db"].query(Approval).count() == 0


def test_member_tasks_auto_pick_and_blocked_tasks_wait(env):
    db, c, H, call = env["db"], env["client"], env["H"], env["call"]
    g = env["goal"](); _drain(env)
    an = env["staff"]["mk"]
    tasks = [{"key": "a", "title": "Viết brief", "member_id": an.id, "acceptance_criteria": "1 trang"},
             {"key": "b", "title": "Duyệt brief", "member_id": an.id, "depends_on": ["a"], "acceptance_criteria": "ok"},
             {"key": "c", "title": "Việc chung", "acceptance_criteria": "ok"}]
    err, out = call(env["nina"], "company_plan_submit", {"goal_id": g.id, "summary": "giao thẳng cho An", "tasks": tasks})
    assert not err, out
    assert c.post(f"/api/approvals/{out['approval_id']}/resolve", headers=H, json={"status": "approved"}).status_code == 200
    db.expire_all()
    t = {x.title: x for x in db.query(Task).filter(Task.goal_id == g.id, Task.parent_task_id.isnot(None))}
    assert t["Viết brief"].assignee_member_id == an.id
    woken = {w.task_id for w in db.query(Wakeup).filter(Wakeup.reason == "assigned")}
    assert t["Viết brief"].id in woken and t["Duyệt brief"].id not in woken      # bị chặn: chờ blocker_cleared
    assert t["Việc chung"].assignee_member_id is not None                         # D3.2 chọn theo tải
    assert _events(env, "task.dispatch_decided")[-1]["task_id"] == t["Việc chung"].id


def test_reject_marks_goal_and_creates_nothing(env):
    db, c, H = env["db"], env["client"], env["H"]
    g = env["goal"](); _drain(env)
    err, out = env["call"](env["nina"], "company_plan_submit", {"goal_id": g.id, "summary": "kế hoạch đầu tiên", "tasks": _plan(env)})
    r = c.post(f"/api/approvals/{out['approval_id']}/resolve", headers=H, json={"status": "rejected", "resolution_note": "không"})
    assert r.status_code == 200
    db.expire_all()
    assert db.get(ExecutiveGoal, g.id).status == "plan_rejected"
    assert db.query(Task).filter(Task.parent_task_id.isnot(None)).count() == 0
    assert _events(env, "goal.plan_rejected")[0]["approval_id"] == out["approval_id"]


def test_only_named_approver_decides_and_executor_has_no_tool(env):
    db, c = env["db"], env["client"]
    g = env["goal"](); _drain(env)
    err, out = env["call"](env["nina"], "company_plan_submit", {"goal_id": g.id, "summary": "kế hoạch đầu tiên", "tasks": _plan(env)})
    other = Member(organization_id=env["org"].id, company_id=env["co"].id, name="Minh", member_type="human",
                   role="COO", status="active")
    db.add(other); db.commit()
    u = User(email="minh@may.test", password_hash="x", member_id=other.id); db.add(u); db.commit()
    H2 = {"Authorization": f"Bearer {create_access_token(u.id, env['org'].id, 'admin')}"}
    assert c.post(f"/api/approvals/{out['approval_id']}/resolve", headers=H2, json={"status": "approved"}).status_code == 403
    assert c.post(f"/api/strategy/plans/{out['approval_id']}/request-revision", headers=H2,
                  json={"note": "sửa đi nhé"}).status_code == 403
    err, res = env["call"](env["staff"]["mk"], "company_plan_submit",
                           {"goal_id": g.id, "summary": "x" * 20, "tasks": _plan(env)}, status=403)
    assert res["data"]["source"] == "default:executor"            # thừa hành: tool tắt mặc định
