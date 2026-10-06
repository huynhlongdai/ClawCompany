"""D2.1 — hàng đợi wakeup trên ORM thật. Runtime giả chỉ ghi lại lời gọi
``run_agent`` (không có gateway); mọi thứ còn lại — giao việc qua API v18,
sổ task, approval, task_runs, company_events — là code và bảng thật."""
import asyncio
import json
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.core.security import create_access_token
from app.db.base import Base
import app.models  # noqa: F401
from app.db.session import get_db
from app.main import app
from app.models import Approval, BudgetEnvelope, CompanyEvent, TaskDependency, TaskRun, Wakeup
from app.models.auth import User
from app.models.entities import Agent, Company, Member, Organization, Project, Task
from app.services import runtime_stream as stream
from app.services import task_journal, task_lifecycle, wakeup


class FakeRuntime:
    def __init__(self):
        self.calls = []

    async def run_agent(self, runtime_agent_id, input_text, metadata=None, session_key=None):
        from app.runtime.base import RuntimeRun
        self.calls.append({"agent": runtime_agent_id, "session_key": session_key})
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
    org = Organization(name="Nova", slug="nova-d21"); db.add(org); db.commit()
    co = Company(organization_id=org.id, name="Nova", status="active"); db.add(co); db.commit()
    boss = Member(organization_id=org.id, company_id=co.id, name="Long", member_type="human", role="CEO", status="active")
    db.add(boss); db.commit()

    def seat(name, rid, status="active"):
        m = Member(organization_id=org.id, company_id=co.id, name=name, member_type="agent", role="AI",
                   status=status, manager_id=boss.id)
        db.add(m); db.commit()
        db.add(Agent(member_id=m.id, runtime_agent_id=rid, lifecycle="active")); db.commit()
        return m

    nina, mia = seat("Nina", "dev"), seat("Mia", "mia")
    user = User(email="long@nova.test", password_hash="x", member_id=boss.id); db.add(user); db.commit()
    proj = Project(company_id=co.id, name="P", status="active"); db.add(proj); db.commit()
    fake = FakeRuntime()
    monkeypatch.setattr("app.services.agent_dispatch.get_runtime", lambda: fake)

    async def no_hours(agent):
        return None
    monkeypatch.setattr(wakeup, "ACTIVE_HOURS_LOOKUP", no_hours)
    token = create_access_token(user.id, org.id, "admin")
    yield {"db": db, "org": org, "co": co, "boss": boss, "nina": nina, "mia": mia, "proj": proj,
           "rt": fake, "client": TestClient(app), "H": {"Authorization": f"Bearer {token}"}}
    app.dependency_overrides.pop(get_db, None)


def _task(env, title="Viết hook", status="todo", assignee=None):
    t = Task(project_id=env["proj"].id, title=title, status=status,
             assignee_member_id=assignee.id if assignee else None)
    env["db"].add(t); env["db"].commit(); env["db"].refresh(t)
    return t


def _assign_via_api(env, task, member):
    r = env["client"].post(f"/api/v18/workspace/tasks/{task.id}/assign", headers=env["H"],
                           json={"assignee_member_id": member.id})
    assert r.status_code == 200, r.text


def _drain(env, **kw):
    env["db"].expire_all()
    return asyncio.run(wakeup.drain(env["db"], **kw))


def _later(seconds=11):
    return datetime.utcnow() + timedelta(seconds=seconds)


def _wakes(env, **filters):
    env["db"].expire_all()
    q = env["db"].query(Wakeup)
    for k, v in filters.items():
        q = q.filter(getattr(Wakeup, k) == v)
    return q.order_by(Wakeup.id).all()


def _events(env, event_type):
    env["db"].expire_all()
    return [json.loads(e.payload_json) for e in env["db"].query(CompanyEvent)
            .filter(CompanyEvent.event_type == event_type).order_by(CompanyEvent.id)]


# -- enqueue ------------------------------------------------------------------


def test_enqueue_is_idempotent_on_dedupe_key(env):
    t = _task(env, assignee=env["nina"])
    a, created_a = wakeup.enqueue(env["db"], organization_id=env["org"].id, member_id=env["nina"].id,
                                  reason="routine", task_id=t.id, dedupe_key="routine:9:00")
    b, created_b = wakeup.enqueue(env["db"], organization_id=env["org"].id, member_id=env["nina"].id,
                                  reason="routine", task_id=t.id, dedupe_key="routine:9:00")
    assert created_a and not created_b and a.id == b.id
    assert len(_wakes(env)) == 1 and len(_events(env, "wakeup.enqueued")) == 1
    with pytest.raises(ValueError):
        wakeup.enqueue(env["db"], organization_id=env["org"].id, member_id=env["nina"].id,
                       reason="because", dedupe_key="x")


# -- giao việc trên UI → run --------------------------------------------------


def test_assigning_on_the_board_wakes_the_seat_and_starts_one_run(env):
    t = _task(env)
    _assign_via_api(env, t, env["nina"])
    (wk,) = _wakes(env)
    assert (wk.reason, wk.status, wk.task_id, wk.member_id) == ("assigned", "queued", t.id, env["nina"].id)
    out = _drain(env, now=_later())
    assert out[0]["decision"] == "dispatched"
    (wk,) = _wakes(env)
    run = env["db"].get(TaskRun, wk.run_id)
    assert wk.status == "dispatched" and run.wakeup_id == wk.id and run.trigger_kind == "assigned"
    assert env["rt"].calls == [{"agent": "dev", "session_key": f"agent:dev:company-task-{t.id}"}]
    assert env["db"].get(Task, t.id).status == "in_progress"
    assert "assigned" in _events(env, "wakeup.dispatched")[0]["reason"]


def test_assigning_to_a_human_wakes_nobody(env):
    t = _task(env)
    _assign_via_api(env, t, env["boss"])
    assert _wakes(env) == []


def test_drain_inside_the_window_waits(env):
    t = _task(env)
    _assign_via_api(env, t, env["nina"])
    assert _drain(env)[0]["decision"] == "waiting"
    assert env["rt"].calls == [] and _wakes(env)[0].status == "queued"


def test_two_events_within_ten_seconds_make_one_run(env):
    t = _task(env)
    _assign_via_api(env, t, env["nina"])
    task_journal.append(env["db"], env["db"].get(Task, t.id), kind="note",
                        summary="@Nina nhớ dùng giọng thương hiệu", actor_member_id=env["boss"].id)
    first, second = _wakes(env)
    assert (first.reason, second.reason) == ("assigned", "mentioned")
    _drain(env, now=_later())
    first, second = _wakes(env)
    assert first.status == "dispatched"
    assert second.status == "coalesced" and second.coalesced_into_id == first.id and second.run_id == first.run_id
    assert len(env["rt"].calls) == 1
    assert env["db"].query(TaskRun).count() == 1


# -- luật bỏ qua ----------------------------------------------------------------


def test_exhausted_budget_skips_with_reason_budget(env):
    env["db"].add(BudgetEnvelope(organization_id=env["org"].id, company_id=env["co"].id, name="Tháng 10",
                                 amount_limit=0.10, amount_spent=0.10, status="active"))
    env["db"].commit()
    t = _task(env)
    _assign_via_api(env, t, env["nina"])
    out = _drain(env, now=_later())
    (wk,) = _wakes(env)
    assert out[0]["decision"] == "skipped" and wk.status == "skipped" and wk.skip_reason.startswith("budget")
    assert env["rt"].calls == [] and env["db"].query(TaskRun).count() == 0
    assert _events(env, "wakeup.skipped")[0]["reason"].startswith("budget")


def test_budget_of_another_company_does_not_block(env):
    other = Company(organization_id=env["org"].id, name="Khác", status="active")
    env["db"].add(other); env["db"].commit()
    env["db"].add(BudgetEnvelope(organization_id=env["org"].id, company_id=other.id, name="Khác",
                                 amount_limit=0.10, amount_spent=0.10, status="active"))
    env["db"].commit()
    t = _task(env)
    _assign_via_api(env, t, env["nina"])
    assert _drain(env, now=_later())[0]["decision"] == "dispatched"


def test_inactive_seat_is_skipped(env):
    t = _task(env)
    _assign_via_api(env, t, env["nina"])
    env["db"].get(Member, env["nina"].id).status = "paused"; env["db"].commit()
    _drain(env, now=_later())
    assert _wakes(env)[0].skip_reason == "seat_inactive" and env["rt"].calls == []


def test_outside_active_hours_is_skipped(env, monkeypatch):
    async def hours(agent):
        return {"start": "08:00", "end": "18:00", "timezone": "Asia/Ho_Chi_Minh"}
    monkeypatch.setattr(wakeup, "ACTIVE_HOURS_LOOKUP", hours)
    t = _task(env)
    _assign_via_api(env, t, env["nina"])
    night = datetime(2026, 10, 6, 16, 0)  # 23:00 giờ Việt Nam
    _drain(env, now=night, force=True)
    assert _wakes(env)[0].skip_reason == "outside_active_hours" and env["rt"].calls == []


def test_active_hours_window_is_local_time_and_wraps_midnight():
    vn = {"start": "08:00", "end": "18:00", "timezone": "Asia/Ho_Chi_Minh"}
    assert wakeup.within_active_hours(vn, datetime(2026, 10, 6, 2, 0))       # 09:00 VN
    assert not wakeup.within_active_hours(vn, datetime(2026, 10, 6, 12, 0))  # 19:00 VN
    night = {"start": "22:00", "end": "06:00"}
    assert wakeup.within_active_hours(night, datetime(2026, 10, 6, 23, 30))
    assert not wakeup.within_active_hours(night, datetime(2026, 10, 6, 12, 0))
    assert wakeup.within_active_hours(None, datetime(2026, 10, 6, 12, 0))


def test_busy_seat_is_skipped_then_requeued_when_the_run_ends(env):
    a, b = _task(env, "Việc A"), _task(env, "Việc B")
    _assign_via_api(env, a, env["nina"])
    _drain(env, now=_later())
    _assign_via_api(env, b, env["nina"])
    _drain(env, now=_later())
    wb = _wakes(env, task_id=b.id)[0]
    assert wb.status == "skipped" and wb.skip_reason.startswith("seat_busy")
    assert len(env["rt"].calls) == 1

    # Lượt của A kết thúc (frame chat state=final) → lý do của B được xếp lại.
    db = env["db"]
    task_a = db.get(Task, a.id)
    state = stream.ConsumerState(session_key=task_a.runtime_session_key, task_id=a.id,
                                 organization_id=env["org"].id)
    stream.apply_terminal_state(db, task_a, state, {"state": "final"})
    again = [w for w in _wakes(env, task_id=b.id) if w.status == "queued"]
    assert len(again) == 1 and json.loads(again[0].payload)["requeued_from"] == wb.id
    _drain(env, now=_later(30))
    assert len(env["rt"].calls) == 2 and env["rt"].calls[1]["session_key"].endswith(f"-{b.id}")


def test_stale_open_run_does_not_block_forever(env):
    t0 = _task(env, "Cũ", status="in_progress", assignee=env["nina"])
    env["db"].add(TaskRun(organization_id=env["org"].id, task_id=t0.id, member_id=env["nina"].id,
                          status="running", started_at=datetime.utcnow() - timedelta(hours=2)))
    env["db"].commit()
    t = _task(env)
    _assign_via_api(env, t, env["nina"])
    assert _drain(env, now=_later())[0]["decision"] == "dispatched"


# -- các nguồn phát khác ----------------------------------------------------------


def test_closing_the_last_blocker_wakes_the_waiting_seat(env):
    first = _task(env, "Viết brief", status="review", assignee=env["mia"])
    waiting = _task(env, "Dựng video", status="todo", assignee=env["nina"])
    env["db"].add(TaskDependency(task_id=waiting.id, blocked_by_task_id=first.id)); env["db"].commit()
    task_lifecycle.transition(env["db"], env["db"].get(Task, first.id), "done", reason="duyệt xong")
    (wk,) = _wakes(env)
    assert (wk.reason, wk.task_id, wk.member_id) == ("blocker_cleared", waiting.id, env["nina"].id)


def test_blocker_still_open_does_not_wake(env):
    a = _task(env, "A", status="review", assignee=env["mia"])
    b = _task(env, "B", status="todo", assignee=env["mia"])
    waiting = _task(env, "C", status="todo", assignee=env["nina"])
    env["db"].add_all([TaskDependency(task_id=waiting.id, blocked_by_task_id=a.id),
                       TaskDependency(task_id=waiting.id, blocked_by_task_id=b.id)])
    env["db"].commit()
    task_lifecycle.transition(env["db"], env["db"].get(Task, a.id), "done", reason="xong")
    assert _wakes(env) == []


def test_mention_of_a_seat_that_is_not_the_assignee_is_skipped_with_reason(env):
    t = _task(env, assignee=env["mia"])
    task_journal.append(env["db"], t, kind="note", summary="@Nina xem giúp", actor_member_id=env["boss"].id)
    (wk,) = _wakes(env)
    assert wk.member_id == env["nina"].id
    _drain(env, now=_later())
    assert _wakes(env)[0].skip_reason == "not_assignee"


def test_self_mention_and_plain_text_do_not_wake(env):
    t = _task(env, assignee=env["nina"])
    task_journal.append(env["db"], t, kind="note", summary="@Nina tự ghi chú", actor_member_id=env["nina"].id)
    task_journal.append(env["db"], t, kind="note", summary="Nina làm tốt", actor_member_id=env["boss"].id)
    assert _wakes(env) == []


def test_resolved_tool_approval_wakes_the_requester_on_its_task(env):
    t = _task(env)
    _assign_via_api(env, t, env["nina"])
    _drain(env, now=_later())
    run = env["db"].query(TaskRun).one()
    run.status = "completed"; env["db"].commit()
    ap = Approval(organization_id=env["org"].id, requester_member_id=env["nina"].id, action="tool:company_budget_check",
                  policy_key="tool:company_budget_check", status="pending")
    env["db"].add(ap); env["db"].commit()
    r = env["client"].post(f"/api/approvals/{ap.id}/resolve", headers=env["H"],
                           json={"status": "approved", "resolution_note": "ok"})
    assert r.status_code == 200, r.text
    wk = _wakes(env, reason="approval_resolved")
    assert len(wk) == 1 and wk[0].task_id == t.id


def test_wakeups_endpoint_is_scoped_to_the_org(env):
    t = _task(env)
    _assign_via_api(env, t, env["nina"])
    other = Organization(name="Khác", slug="other-d21"); env["db"].add(other); env["db"].commit()
    oco = Company(organization_id=other.id, name="X", status="active"); env["db"].add(oco); env["db"].commit()
    om = Member(organization_id=other.id, company_id=oco.id, name="Zed", member_type="agent", role="AI", status="active")
    env["db"].add(om); env["db"].commit()
    wakeup.enqueue(env["db"], organization_id=other.id, member_id=om.id, reason="routine", dedupe_key="other")
    rows = env["client"].get("/api/tasks/wakeups", headers=env["H"]).json()
    assert [r["reason"] for r in rows] == ["assigned"]


def test_dispatch_from_a_wakeup_attaches_the_follower_to_the_new_session(env, monkeypatch):
    """E2E lần đầu: drain gọi ``registry.follow`` (không tồn tại) → lượt chạy
    không bao giờ được nghe tới cuối, seat kẹt seat_busy. Test thẳng vào
    supervisor thật để tên/đối số sai là đỏ."""
    from app.services import runtime_stream
    seen = []

    def fake_follow(*, session_key, organization_id, task_id=None):
        seen.append((session_key, organization_id, task_id))
        return runtime_stream.ConsumerState(session_key=session_key, task_id=task_id,
                                            organization_id=organization_id)

    monkeypatch.setattr(runtime_stream.supervisor, "follow", fake_follow)
    t = _task(env)
    _assign_via_api(env, t, env["nina"])
    out = _drain(env, now=_later(), follow=True)
    assert out[0]["decision"] == "dispatched", out
    assert not str(out[0]["followed"]).startswith("error")
    assert seen == [(f"agent:dev:company-task-{t.id}", env["org"].id, t.id)]
