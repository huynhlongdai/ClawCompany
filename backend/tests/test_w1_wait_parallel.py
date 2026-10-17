"""W1 — việc chờ người không giữ ghế + đồng thời theo ghế, trên ORM thật.

Runtime giả chỉ ghi lời gọi ``run_agent`` (không có gateway, không gọi model); mọi thứ còn lại — giao việc qua API,
drain wakeup, follower kết thúc lượt (``apply_terminal_state``), hàng duyệt của gateway (``record_approval``),
công cụ MCP, phê duyệt qua API, task_runs — là code và bảng thật. Đua giành chỗ chạy chạy trên SQLite file với
nhiều luồng thật (mỗi luồng một phiên DB)."""
import asyncio
import json
import os
import tempfile
import threading
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
from app.models import Approval, InboxItem, TaskRun, Wakeup
from app.models.auth import User
from app.models.entities import Agent, Company, Member, Organization, Project, Task
from app.models.leases import SeatLease
from app.runtime import openclaw_protocol as ocp
from app.services import company_mcp, seat_concurrency, task_wait, wakeup
from app.services import runtime_stream as stream


class FakeRuntime:
    def __init__(self):
        self.calls = []

    async def run_agent(self, runtime_agent_id, input_text, metadata=None, session_key=None):
        from app.runtime.base import RuntimeRun
        self.calls.append({"agent": runtime_agent_id, "session_key": session_key, "text": input_text})
        return RuntimeRun(task_id="t", run_id=f"run-{len(self.calls)}", session_key=session_key or "",
                          status="running", raw={})


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
    org = Organization(name="Nova", slug="nova-w1"); db.add(org); db.commit()
    co = Company(organization_id=org.id, name="Nova", status="active"); db.add(co); db.commit()
    boss = Member(organization_id=org.id, company_id=co.id, name="Long", member_type="human", role="CEO", status="active")
    db.add(boss); db.commit()

    def seat(name, rid):
        m = Member(organization_id=org.id, company_id=co.id, name=name, member_type="agent", role="AI",
                   status="active", manager_id=boss.id)
        db.add(m); db.commit()
        a = Agent(member_id=m.id, runtime_agent_id=rid, lifecycle="active"); db.add(a); db.commit()
        return m

    nina, mia = seat("Nina", "nina"), seat("Mia", "mia")
    user = User(email="long@nova.w1", password_hash="x", member_id=boss.id); db.add(user); db.commit()
    proj = Project(company_id=co.id, name="P", status="active"); db.add(proj); db.commit()
    fake = FakeRuntime()
    monkeypatch.setattr("app.services.agent_dispatch.get_runtime", lambda: fake)

    async def no_hours(agent):
        return None
    monkeypatch.setattr(wakeup, "ACTIVE_HOURS_LOOKUP", no_hours)
    token = create_access_token(user.id, org.id, "admin")
    yield {"db": db, "org": org, "co": co, "boss": boss, "nina": nina, "mia": mia, "proj": proj, "rt": fake,
           "client": TestClient(app), "H": {"Authorization": f"Bearer {token}"}}
    app.dependency_overrides.pop(get_db, None)


def _task(env, title, assignee=None, status="todo"):
    t = Task(project_id=env["proj"].id, title=title, status=status,
             assignee_member_id=assignee.id if assignee else None)
    env["db"].add(t); env["db"].commit(); env["db"].refresh(t)
    return t


def _assign(env, task, member):
    r = env["client"].post(f"/api/v18/workspace/tasks/{task.id}/assign", headers=env["H"],
                           json={"assignee_member_id": member.id})
    assert r.status_code == 200, r.text


def _drain(env, seconds=11):
    env["db"].expire_all()
    return asyncio.run(wakeup.drain(env["db"], now=datetime.utcnow() + timedelta(seconds=seconds)))


def _fresh(env, obj):
    env["db"].expire_all()
    return env["db"].get(type(obj), obj.id)


def _agent(env, member):
    return env["db"].query(Agent).filter(Agent.member_id == member.id).one()


def _run_of(env, task):
    env["db"].expire_all()
    return env["db"].query(TaskRun).filter(TaskRun.task_id == task.id).order_by(TaskRun.id.desc()).first()


def _final(env, task):
    t = _fresh(env, task)
    st = stream.ConsumerState(session_key=t.runtime_session_key, task_id=t.id, organization_id=env["org"].id)
    stream.apply_terminal_state(env["db"], t, st, {"state": "final"})
    return _fresh(env, task)


def _exec_event(task, family, request_id="req-1", decision=None):
    raw = {"id": request_id, "request": {"command": "rm -rf build", "sessionKey": task.runtime_session_key}}
    if decision:
        raw["decision"] = decision
    return {"family": family, "raw": raw}


def _ctx(env, member, task):
    db = env["db"]
    return company_mcp.ToolContext(db=db, member=_fresh(env, member), agent=_agent(env, member), scopes=["*"],
                                   session_key=_fresh(env, task).runtime_session_key, run=_run_of(env, task))


# -- (a) chờ trong lượt: lệnh exec chờ duyệt ----------------------------------------------------


def test_exec_approval_wait_releases_the_seat_and_the_same_run_resumes(env):
    db, nina = env["db"], env["nina"]
    a, b, c = _task(env, "Việc A"), _task(env, "Việc B"), _task(env, "Việc C")
    _assign(env, a, nina); _drain(env)
    _assign(env, b, nina); _drain(env)
    assert _fresh(env, a).status == "in_progress" and len(env["rt"].calls) == 1
    (wb,) = db.query(Wakeup).filter(Wakeup.task_id == b.id).all()
    assert wb.status == "skipped" and wb.skip_reason.startswith("seat_busy")       # ghế 1 lượt đang bận

    run_a = _run_of(env, a)
    ta = _fresh(env, a)
    st = stream.ConsumerState(session_key=ta.runtime_session_key, task_id=a.id, organization_id=env["org"].id)
    ap = stream.record_approval(db, st, _exec_event(ta, ocp.E_EXEC_APPROVAL_REQUESTED), member=_fresh(env, nina))
    ta = _fresh(env, a)
    assert (ta.wait_kind, ta.wait_ref, ta.status) == ("human", f"approval:{ap.id}", "in_progress")
    assert _run_of(env, a).waiting_since is not None and _run_of(env, a).status == "running"
    # lý do của B được xếp lại ngay khi A chuyển sang chờ, và B chạy luôn — không đợi A
    again = [w for w in db.query(Wakeup).filter(Wakeup.task_id == b.id).all() if w.status == "queued"]
    assert len(again) == 1
    _drain(env, 30)
    assert len(env["rt"].calls) == 2 and env["rt"].calls[1]["session_key"].endswith(f"company-task-{b.id}")
    assert _fresh(env, b).status == "in_progress"
    # cùng một hàng chờ được gateway báo lại (backfill) → không sinh chờ/hàng thứ hai
    stream.record_approval(db, st, _exec_event(ta, ocp.E_EXEC_APPROVAL_REQUESTED), member=_fresh(env, nina))
    assert db.query(Approval).count() == 1

    # gateway báo đã duyệt → hết chờ, ĐÚNG lượt cũ chạy tiếp (không có run_agent mới, không hàng task_runs mới)
    stream.record_approval(db, st, _exec_event(ta, ocp.E_EXEC_APPROVAL_RESOLVED, decision="allow-once"))
    ta = _fresh(env, a)
    assert ta.wait_kind is None and ta.status == "in_progress"
    resumed = _run_of(env, a)
    assert resumed.id == run_a.id and resumed.waiting_since is None and resumed.status == "running"
    assert len(env["rt"].calls) == 2
    # ghế 1 lượt giờ có 2 lượt chạy (A tiếp tục không chặn được) → không nhận lượt MỚI cho tới khi về dưới giới hạn
    view = seat_concurrency.view(db, _agent(env, nina), _fresh(env, nina))
    assert view["running"] == 2 and view["over_limit"] is True
    _assign(env, c, nina); _drain(env, 40)
    assert db.query(Wakeup).filter(Wakeup.task_id == c.id).one().skip_reason.startswith("seat_busy")
    # A kết thúc bình thường → review, B vẫn chạy
    assert _final(env, a).status == "review"


# -- (a) chờ ngoài lượt: xin duyệt nghiệp vụ qua MCP ---------------------------------------------


def test_business_approval_wait_frees_seat_then_resumes_in_the_same_session(env, monkeypatch):
    db, nina = env["db"], env["nina"]
    a, b = _task(env, "Hoàn tiền đơn #77"), _task(env, "Trả lời khách")
    _assign(env, a, nina); _drain(env)
    ap = Approval(organization_id=env["org"].id, company_id=env["co"].id, requester_member_id=nina.id,
                  approver_member_id=env["boss"].id, action="Hoàn tiền 80 USD", policy_key="authority:refund",
                  status="pending")
    db.add(ap); db.commit()
    from app.services.policy import PolicyDecision
    monkeypatch.setattr("app.services.policy.authorize",
                        lambda *a_, **k: PolicyDecision("approval_required", "vượt ngưỡng", "authority:refund", ap.id))
    out = company_mcp.TOOLS["company_approval_request"].handler(_ctx(env, nina, a), {"action": "refund",
                                                                                   "amount_usd": 80})
    assert out["decision"] == "approval_required" and out["waiting"]["ref"] == f"approval:{ap.id}"
    session_a = _fresh(env, a).runtime_session_key

    # agent kết thúc lượt (frame final) → việc CHỜ (blocked + wait_kind), không review, không thẻ "run lỗi"
    ta = _final(env, a)
    assert (ta.status, ta.wait_kind, ta.wait_ref) == ("blocked", "human", f"approval:{ap.id}")
    assert _run_of(env, a).status == "completed"
    assert db.query(InboxItem).filter(InboxItem.item_type == "run_failed").count() == 0
    # ghế rảnh: việc B chạy ngay
    _assign(env, b, nina); _drain(env, 20)
    assert len(env["rt"].calls) == 2 and _fresh(env, b).status == "in_progress"
    # một lý do lạc (nhắc tên) không đánh thức việc đang chờ
    wakeup.enqueue_for_task(db, _fresh(env, a), "mentioned", dedupe_key="stray")
    _drain(env, 25)
    assert db.query(Wakeup).filter(Wakeup.dedupe_key == "stray").one().skip_reason.startswith(("task_waiting", "seat_busy"))
    _final(env, b)   # B xong → ghế rảnh

    # người duyệt qua API → việc về Cần làm + wakeup mang "resume" → đúng phiên của A, tin ngắn "tiếp tục"
    r = env["client"].post(f"/api/approvals/{ap.id}/resolve", headers=env["H"],
                           json={"status": "approved", "resolution_note": "ok, hoàn đủ"})
    assert r.status_code == 200, r.text
    ta = _fresh(env, a)
    assert ta.wait_kind is None and ta.status == "todo"
    (wk,) = db.query(Wakeup).filter(Wakeup.task_id == a.id, Wakeup.reason == "approval_resolved").all()
    assert json.loads(wk.payload)["resume"]["decision"] == "approved"
    _drain(env, 40)
    last = env["rt"].calls[-1]
    assert last["session_key"] == session_a                      # cùng phiên = tiếp tục từ điểm dừng
    assert last["text"].startswith(f"[Tiếp tục việc #{a.id}") and "ĐÃ ĐƯỢC DUYỆT" in last["text"]
    assert "ok, hoàn đủ" in last["text"] and len(last["text"]) < 600   # không gửi lại gói 7 khối
    assert _fresh(env, a).status == "in_progress"


def test_rejected_business_approval_resumes_with_rejection(env, monkeypatch):
    db, nina = env["db"], env["nina"]
    a = _task(env, "Chi quảng cáo")
    _assign(env, a, nina); _drain(env)
    ap = Approval(organization_id=env["org"].id, company_id=env["co"].id, requester_member_id=nina.id,
                  action="Chi 200 USD", policy_key="authority:spend", status="pending")
    db.add(ap); db.commit()
    from app.services.policy import PolicyDecision
    monkeypatch.setattr("app.services.policy.authorize",
                        lambda *a_, **k: PolicyDecision("approval_required", "", "authority:spend", ap.id))
    company_mcp.TOOLS["company_approval_request"].handler(_ctx(env, nina, a), {"action": "spend"})
    _final(env, a)
    r = env["client"].post(f"/api/approvals/{ap.id}/resolve", headers=env["H"],
                           json={"status": "rejected", "resolution_note": "để quý sau"})
    assert r.status_code == 200, r.text
    _drain(env, 40)
    assert "BỊ TỪ CHỐI" in env["rt"].calls[-1]["text"] and "Không thực hiện" in env["rt"].calls[-1]["text"]


def test_approval_decided_while_agent_still_in_its_turn_does_not_strand_the_task(env, monkeypatch):
    db, nina = env["db"], env["nina"]
    a = _task(env, "Việc nhanh")
    _assign(env, a, nina); _drain(env)
    ap = Approval(organization_id=env["org"].id, requester_member_id=nina.id, action="x", policy_key="authority:x",
                  status="pending")
    db.add(ap); db.commit()
    from app.services.policy import PolicyDecision
    monkeypatch.setattr("app.services.policy.authorize",
                        lambda *a_, **k: PolicyDecision("approval_required", "", "authority:x", ap.id))
    company_mcp.TOOLS["company_approval_request"].handler(_ctx(env, nina, a), {"action": "x"})
    env["client"].post(f"/api/approvals/{ap.id}/resolve", headers=env["H"], json={"status": "approved"})
    assert _fresh(env, a).wait_kind is None                      # hết chờ ngay, agent còn trong lượt
    assert _final(env, a).status == "review"                     # lượt kết thúc bình thường


# -- (a) chờ người trả lời ----------------------------------------------------------------------


def test_agent_question_waits_for_human_answer_and_resumes_with_it(env):
    db, nina = env["db"], env["nina"]
    a = _task(env, "Viết mô tả sản phẩm")
    _assign(env, a, nina); _drain(env)
    out = company_mcp.TOOLS["company_task_status"].handler(_ctx(env, nina, a), {
        "task_id": a.id, "status": "blocked", "reason": "Màu men chính xác là gì?", "wait_for": "human"})
    item = db.query(InboxItem).filter(InboxItem.item_type == "agent_question").one()
    assert item.recipient_member_id == env["boss"].id and out["waiting"]["wait_ref"] == f"question:{item.id}"
    ta = _final(env, a)
    assert (ta.status, ta.wait_kind) == ("blocked", "human")
    # bảng việc hiện "đang chờ"
    rows = env["client"].get("/api/work/tasks", headers=env["H"]).json()["items"]
    row = next(r for r in rows if r["id"] == a.id)
    assert row["waiting"]["kind"] == "human" and row["waiting"]["on"] == "question"
    # wait_for sai cách dùng → lỗi rõ
    with pytest.raises(company_mcp.ToolError):
        company_mcp.TOOLS["company_task_status"].handler(_ctx(env, nina, a), {
            "task_id": a.id, "status": "review", "reason": "x", "wait_for": "human"})
    r = env["client"].post(f"/api/work/tasks/{a.id}/answer", headers=env["H"], json={"answer": "Men xanh lam ngọc"})
    assert r.status_code == 200, r.text
    assert r.json()["task"]["waiting"] is None
    assert _fresh(env, item).status == "done"
    _drain(env, 30)
    last = env["rt"].calls[-1]
    assert last["session_key"].endswith(f"company-task-{a.id}") and "Men xanh lam ngọc" in last["text"]
    assert env["client"].post(f"/api/work/tasks/{a.id}/answer", headers=env["H"],
                              json={"answer": "lần hai"}).status_code == 409


def test_review_does_not_hold_the_seat(env):
    nina = env["nina"]
    a, b = _task(env, "A"), _task(env, "B")
    _assign(env, a, nina); _drain(env)
    assert _final(env, a).status == "review"
    _assign(env, b, nina); _drain(env, 20)
    assert len(env["rt"].calls) == 2


def test_cancelling_a_waiting_task_drops_the_wait(env):
    db, nina = env["db"], env["nina"]
    a = _task(env, "A")
    _assign(env, a, nina); _drain(env)
    task_wait.begin(db, _fresh(env, a), kind="human", ref="question:t1")
    _final(env, a)
    r = env["client"].post(f"/api/work/tasks/{a.id}/move", headers=env["H"], json={"status": "cancelled"})
    assert r.status_code == 200, r.text
    assert _fresh(env, a).wait_kind is None


# -- (b) đồng thời theo ghế ---------------------------------------------------------------------


def test_parallel_limit_two_runs_two_sessions_third_is_busy(env):
    db, nina = env["db"], env["nina"]
    ag = _agent(env, nina)
    c = env["client"]
    g = c.get(f"/api/agents/{ag.id}/concurrency", headers=env["H"]).json()
    assert (g["max_parallel_runs"], g["default"], g["max_allowed"], g["settled"]) == (1, 1, 3, False)
    for bad in (0, 4, "x"):
        assert c.put(f"/api/agents/{ag.id}/concurrency", headers=env["H"],
                     json={"max_parallel_runs": bad}).status_code == 422
    r = c.put(f"/api/agents/{ag.id}/concurrency", headers=env["H"], json={"max_parallel_runs": 2})
    assert r.status_code == 200 and r.json()["effective_limit"] == 2
    ts = [_task(env, f"Việc {i}") for i in range(3)]
    for t in ts:
        _assign(env, t, nina)
    out = _drain(env)
    assert [o["decision"] for o in out] == ["dispatched", "dispatched"]   # một drain lấp đủ 2 chỗ
    keys = {call["session_key"] for call in env["rt"].calls}
    assert len(env["rt"].calls) == 2 and len(keys) == 2         # hai việc, hai phiên riêng
    third = db.query(Wakeup).filter(Wakeup.task_id == ts[2].id).one()
    assert third.status == "queued"                             # hết chỗ: giữ hàng đợi như trước W1
    _drain(env, 15)
    third = _fresh(env, third)
    assert third.status == "skipped" and third.skip_reason.startswith("seat_busy: 2/2")
    # một lượt xong → việc thứ ba được xếp lại và chạy
    done = next(t for t in ts if _fresh(env, t).status == "in_progress")
    _final(env, done)
    _drain(env, 30)
    assert len(env["rt"].calls) == 3 and _fresh(env, ts[2]).status == "in_progress"


def test_atomic_claim_beats_the_non_atomic_precheck(env):
    """Hai worker cùng đọc 'còn chỗ' rồi cùng giành: chỉ một thắng (trước W1 cả hai cùng gửi)."""
    db, nina = env["db"], env["nina"]
    a, b = _task(env, "A", assignee=nina), _task(env, "B", assignee=nina)
    assert seat_concurrency.busy_reason(db, nina.id) == "" and seat_concurrency.busy_reason(db, nina.id) == ""
    seat_concurrency.open_run(db, a, organization_id=env["org"].id, member_id=nina.id)
    with pytest.raises(seat_concurrency.SeatBusy):
        seat_concurrency.open_run(db, b, organization_id=env["org"].id, member_id=nina.id)
    assert db.query(TaskRun).filter(TaskRun.member_id == nina.id).count() == 1


def test_concurrent_workers_never_exceed_the_seat_limit():
    """Đua thật: 8 luồng, mỗi luồng một phiên DB, cùng giành chỗ cho một ghế giới hạn 2 → đúng 2 lượt."""
    path = os.path.join(tempfile.mkdtemp(), "w1_race.db")
    engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False, "timeout": 30})
    Base.metadata.create_all(bind=engine)
    Maker = sessionmaker(bind=engine, autoflush=False)
    db = Maker()
    org = Organization(name="R", slug="race-w1"); db.add(org); db.commit()
    co = Company(organization_id=org.id, name="R", status="active"); db.add(co); db.commit()
    m = Member(organization_id=org.id, company_id=co.id, name="Seat", member_type="agent", role="AI", status="active")
    db.add(m); db.commit()
    db.add(Agent(member_id=m.id, runtime_agent_id="race", lifecycle="active", max_parallel_runs=2)); db.commit()
    proj = Project(company_id=co.id, name="P", status="active"); db.add(proj); db.commit()
    tasks = [Task(project_id=proj.id, title=f"T{i}", status="todo", assignee_member_id=m.id) for i in range(8)]
    db.add_all(tasks); db.commit()
    ids = [t.id for t in tasks]
    org_id, mid = org.id, m.id
    barrier = threading.Barrier(len(ids))
    won, busy, errors = [], [], []

    def worker(tid):
        s = Maker()
        try:
            t = s.get(Task, tid)
            barrier.wait()
            r = seat_concurrency.open_run(s, t, organization_id=org_id, member_id=mid)
            won.append(r.id)
        except seat_concurrency.SeatBusy:
            busy.append(tid)
        except Exception as exc:  # noqa: BLE001
            errors.append(repr(exc))
        finally:
            s.close()

    threads = [threading.Thread(target=worker, args=(i,)) for i in ids]
    for th in threads:
        th.start()
    for th in threads:
        th.join(60)
    assert errors == []
    assert len(won) == 2 and len(busy) == 6
    db.expire_all()
    assert db.query(TaskRun).filter(TaskRun.member_id == mid).count() == 2
    db.close(); engine.dispose()


def test_leased_seat_cannot_go_above_the_provider_floor(env):
    db, nina, mia = env["db"], env["nina"], env["mia"]
    ag = _agent(env, nina)
    ls = SeatLease(offer_code="W1FLOOR", status="active", provider_org_id=env["org"].id,
                   provider_company_id=env["co"].id, provider_member_id=mia.id, provider_agent_id=_agent(env, mia).id,
                   renter_org_id=env["org"].id, renter_company_id=env["co"].id, renter_member_id=nina.id,
                   renter_agent_id=ag.id, max_parallel_runs=2)
    db.add(ls); db.commit()
    c = env["client"]
    r = c.put(f"/api/agents/{ag.id}/concurrency", headers=env["H"], json={"max_parallel_runs": 3})
    assert r.status_code == 422 and r.json()["detail"]["error"] == "above_lease_floor"
    assert c.put(f"/api/agents/{ag.id}/concurrency", headers=env["H"], json={"max_parallel_runs": 2}).status_code == 200
    assert c.get(f"/api/agents/{ag.id}/concurrency", headers=env["H"]).json()["max_allowed"] == 2
    # bên cho thuê hạ sàn → giới hạn hiệu dụng hạ theo, kể cả khi ghế đang đặt 2
    from app.services import seat_leases
    from fastapi import HTTPException
    seat_leases._apply_terms(db, ls, {"max_parallel_runs": 1}); db.commit()
    assert seat_concurrency.limit_of(db, nina.id) == 1
    with pytest.raises(HTTPException):
        seat_leases._apply_terms(db, ls, {"max_parallel_runs": 5})


def test_routing_load_counts_capacity_and_skips_waiting_tasks(env):
    db, nina, mia = env["db"], env["nina"], env["mia"]
    _task(env, "n1", assignee=nina); _task(env, "m1", assignee=mia)
    w = _task(env, "m-wait", assignee=mia, status="blocked")
    w.wait_kind, w.wait_ref = "human", "question:t9"; db.commit()
    assert seat_concurrency.routing_load(db, mia.id) == 1.0       # việc đang chờ người không tính tải
    ag = _agent(env, nina); ag.max_parallel_runs = 2; db.commit()
    assert seat_concurrency.routing_load(db, nina.id) == 0.5      # ghế 2 lượt: cùng số việc, tải bằng nửa
