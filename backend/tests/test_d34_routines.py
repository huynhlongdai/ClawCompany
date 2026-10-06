"""D3.4 — routines. ORM thật + HTTP thật; runtime giả chỉ ghi ``run_agent``.
Giờ giả qua tham số ``now`` (UTC naive) — không ngủ, không đồng hồ thật."""
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
from app.models import AuditEvent, TaskRun, Wakeup
from app.models.auth import User
from app.models.entities import Agent, Company, Department, Member, Organization, Project, Task
from app.models.extended import InboxItem
from app.models.routines import Routine, RoutineRun, RoutineTrigger
from app.services import routines, wakeup
from app.services import task_lifecycle as lifecycle

DAY1 = datetime(2026, 3, 2, 1, 0)          # 08:00 giờ HCM
NINE_HCM = datetime(2026, 3, 2, 2, 0)      # 09:00 giờ HCM = 02:00 UTC


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
    org = Organization(name="Nova", slug="nova-d34"); db.add(org); db.commit()
    co = Company(organization_id=org.id, name="Nova", status="active"); db.add(co); db.commit()
    mk = Department(company_id=co.id, name="Marketing"); db.add(mk); db.commit()
    boss = Member(organization_id=org.id, company_id=co.id, name="Long", member_type="human", role="CEO",
                  status="active")
    db.add(boss); db.commit()

    def seat(name, rid, dept=None):
        m = Member(organization_id=org.id, company_id=co.id, department_id=dept.id if dept else None, name=name,
                   member_type="agent", role=name, status="active", manager_id=boss.id)
        db.add(m); db.commit()
        db.add(Agent(member_id=m.id, runtime_agent_id=rid, lifecycle="active")); db.commit()
        return m

    nina = seat("Nina", "nina")
    head = seat("Hana", "hana", mk)
    mk.head_member_id = head.id; db.commit()
    user = User(email="long@nova.test", password_hash="x", member_id=boss.id); db.add(user); db.commit()
    fake = FakeRuntime()
    monkeypatch.setattr("app.services.agent_dispatch.get_runtime", lambda: fake)
    monkeypatch.setattr("app.runtime.factory.get_runtime", lambda: fake)

    async def no_hours(agent):
        return None
    monkeypatch.setattr(wakeup, "ACTIVE_HOURS_LOOKUP", no_hours)
    token = create_access_token(user.id, org.id, "admin")
    yield {"db": db, "org": org, "co": co, "mk": mk, "boss": boss, "nina": nina, "head": head, "rt": fake,
           "client": TestClient(app), "H": {"Authorization": f"Bearer {token}"}}
    app.dependency_overrides.pop(get_db, None)


def _routine(env, **kw):
    args = dict(name="Báo cáo sáng", runbook="Viết báo cáo", assignee_member_id=env["nina"].id,
                cron="0 9 * * *", owner_member_id=env["boss"].id, now=DAY1)
    args.update(kw)
    return routines.create_routine(env["db"], env["org"].id, **args)


def _drain(env):
    env["db"].expire_all()
    return asyncio.run(wakeup.drain(env["db"], now=datetime.utcnow() + timedelta(seconds=11)))


def _runs(env, r):
    env["db"].expire_all()
    return env["db"].query(RoutineRun).filter(RoutineRun.routine_id == r.id).order_by(RoutineRun.id).all()


def _finish_task_run(env, task_id, status="completed", error=""):
    db = env["db"]; db.expire_all()
    tr = db.query(TaskRun).filter(TaskRun.task_id == task_id).order_by(TaskRun.id.desc()).first()
    lifecycle.finish_run(db, tr, status, error_reason=error)
    return tr


def test_0900_hcm_creates_task_and_run_end_to_end(env):
    db = env["db"]
    r = _routine(env)
    trig = db.query(RoutineTrigger).filter(RoutineTrigger.routine_id == r.id).one()
    assert trig.next_run_at == NINE_HCM                              # 09:00 HCM = 02:00 UTC
    assert routines.tick(db, now=NINE_HCM - timedelta(minutes=1)) == []
    out = routines.tick(db, now=NINE_HCM + timedelta(seconds=30))
    assert [o["kind"] for o in out] == ["cron"] and out[0]["created"]
    run = _runs(env, r)[0]
    assert run.idempotency_key == f"cron:t{trig.id}:20260302T0200" and run.status == "queued"
    task = db.get(Task, run.task_id)
    assert task.assignee_member_id == env["nina"].id and "02/03/2026 09:00" in task.title
    wk = db.get(Wakeup, run.wakeup_id)
    assert wk.reason == "routine" and wk.dedupe_key == f"routine:rr{run.id}"
    _drain(env)
    assert len(env["rt"].calls) == 1 and env["rt"].calls[0]["agent"] == "nina"
    tr = db.query(TaskRun).filter(TaskRun.task_id == task.id).one()
    assert tr.trigger_kind == "routine"
    routines.tick(db, now=NINE_HCM + timedelta(minutes=1))
    assert _runs(env, r)[0].status == "running"
    _finish_task_run(env, task.id)
    routines.tick(db, now=NINE_HCM + timedelta(minutes=2))
    run = _runs(env, r)[0]
    assert run.status == "succeeded" and run.task_run_id == tr.id
    # Cùng giờ hẹn không bao giờ chạy lần hai; giờ hẹn kế là 09:00 hôm sau.
    db.expire_all()
    assert db.get(RoutineTrigger, trig.id).next_run_at == NINE_HCM + timedelta(days=1)
    dup, created = routines.fire(db, db.get(Routine, r.id), kind="cron", key=run.idempotency_key)
    assert not created and dup.id == run.id
    assert db.query(Task).filter(Task.title.like("Báo cáo sáng%")).count() == 1


def test_webhook_requires_key_and_never_duplicates(env):
    db, c = env["db"], env["client"]
    r = _routine(env, cron="", webhook=True)
    t = db.query(RoutineTrigger).filter(RoutineTrigger.routine_id == r.id).one()
    url = f"/api/routines/hooks/{t.id}"
    assert c.post(url, json={"x": 1}, headers={"X-Routine-Secret": t.secret}).status_code == 400
    assert c.post(url, json={}, headers={"X-Routine-Secret": "sai", "Idempotency-Key": "a"}).status_code == 403
    h = {"X-Routine-Secret": t.secret, "Idempotency-Key": "order-42"}
    first = c.post(url, json={"order": 42}, headers=h)
    assert first.status_code == 200 and first.json()["duplicate"] is False
    again = c.post(url, json={"order": 42}, headers=h)
    assert again.status_code == 200 and again.json()["duplicate"] is True
    assert again.json()["task_id"] == first.json()["task_id"] == again.json()["task_id"]
    db.expire_all()
    assert db.query(Task).count() == 1 and len(_runs(env, r)) == 1
    assert '"order": 42' in db.get(Task, first.json()["task_id"]).description
    other = c.post(url, json={}, headers={**h, "Idempotency-Key": "order-43"})
    assert other.json()["duplicate"] is False and other.json()["status"] == "skipped"   # lần trước chưa xong
    assert "concurrent" in other.json()["error"]


def test_consecutive_failures_pause_routine_with_audit_and_inbox(env):
    db = env["db"]
    r = _routine(env, max_consecutive_failures=2)
    ag = db.query(Agent).filter(Agent.member_id == env["nina"].id).one()
    ag.lifecycle = "retired"; db.commit()                          # runtime của seat hỏng → wakeup bị bỏ, lỗi thật
    routines.tick(db, now=NINE_HCM)
    _drain(env)
    routines.tick(db, now=NINE_HCM + timedelta(minutes=1))
    db.expire_all()
    first = _runs(env, r)[0]
    assert first.status == "failed" and "seat_inactive" in first.error
    assert db.get(Routine, r.id).consecutive_failures == 1 and db.get(Routine, r.id).enabled
    routines.tick(db, now=NINE_HCM + timedelta(days=1))
    _drain(env)
    routines.tick(db, now=NINE_HCM + timedelta(days=1, minutes=1))
    db.expire_all()
    r = db.get(Routine, r.id)
    assert [x.status for x in _runs(env, r)] == ["failed", "failed"]
    assert r.enabled is False and "2 lần lỗi" in r.paused_reason
    audit = db.query(AuditEvent).filter(AuditEvent.action == "routine.paused").one()
    assert json.loads(audit.payload_json)["consecutive_failures"] == 2
    item = db.query(InboxItem).filter(InboxItem.recipient_member_id == env["boss"].id).one()
    assert "routine_paused" in item.kinds and item.priority == "high"
    assert routines.tick(db, now=NINE_HCM + timedelta(days=2)) == []          # đã dừng: không chạy nữa
    # Bật lại: xoá chuỗi lỗi, giờ hẹn tính từ bây giờ (không chạy bù thời gian dừng).
    routines.set_enabled(db, r, True, now=NINE_HCM + timedelta(days=5, hours=3))
    db.expire_all()
    assert db.get(Routine, r.id).consecutive_failures == 0
    assert db.query(RoutineTrigger).filter(RoutineTrigger.routine_id == r.id).one().next_run_at \
        == NINE_HCM + timedelta(days=6)


def test_success_resets_failure_streak(env):
    db = env["db"]
    r = _routine(env, max_consecutive_failures=3)
    r.consecutive_failures = 2; db.commit()
    routines.tick(db, now=NINE_HCM); _drain(env)
    _finish_task_run(env, _runs(env, r)[0].task_id)
    routines.tick(db, now=NINE_HCM + timedelta(minutes=1))
    db.expire_all()
    assert db.get(Routine, r.id).consecutive_failures == 0 and db.get(Routine, r.id).enabled


@pytest.mark.parametrize("policy", ["skip_missed", "run_once"])
def test_catch_up_policies_after_downtime(env, policy):
    db = env["db"]
    r = _routine(env, catch_up=policy)
    late = NINE_HCM + timedelta(days=2, hours=3)                    # lỡ 3 giờ hẹn (ngày 1, 2, 3)
    out = routines.tick(db, now=late)
    runs = _runs(env, r)
    if policy == "skip_missed":
        assert [x.status for x in runs] == ["skipped"] * 3 and db.query(Task).count() == 0
        assert all("missed" in x.error for x in runs)
    else:
        kinds = sorted((x.trigger_kind, x.status) for x in runs)
        assert kinds == [("catch_up", "queued"), ("cron", "skipped"), ("cron", "skipped")]
        cu = next(x for x in runs if x.trigger_kind == "catch_up")
        assert cu.scheduled_for == NINE_HCM + timedelta(days=2) and json.loads(cu.payload_json)["missed_slots"] == 3
        assert db.query(Task).count() == 1
    assert any(o["kind"] == "missed" for o in out)
    db.expire_all()
    assert db.query(RoutineTrigger).filter(RoutineTrigger.routine_id == r.id).one().next_run_at \
        == NINE_HCM + timedelta(days=3)
    assert routines.tick(db, now=late + timedelta(minutes=1)) == []            # không ghi lại lần hai


def test_late_within_grace_still_runs_on_time(env):
    r = _routine(env, catch_up="skip_missed")
    out = routines.tick(env["db"], now=NINE_HCM + timedelta(minutes=4))
    assert [o["kind"] for o in out] == ["cron"] and _runs(env, r)[0].status == "queued"


def test_seat_busy_waits_instead_of_failing(env):
    db = env["db"]
    r = _routine(env)
    busy = Task(project_id=routines._standing_project(db, env["co"].id).id, title="việc khác",
                assignee_member_id=env["nina"].id, status="in_progress")
    db.add(busy); db.commit()
    db.add(TaskRun(organization_id=env["org"].id, task_id=busy.id, member_id=env["nina"].id, status="running"))
    db.commit()
    routines.tick(db, now=NINE_HCM); _drain(env)
    routines.tick(db, now=NINE_HCM + timedelta(minutes=1))
    run = _runs(env, r)[0]
    assert run.status == "queued"                                   # seat bận không tính là lỗi
    assert db.get(Wakeup, run.wakeup_id).skip_reason.startswith("seat_busy")


def test_department_routine_routes_to_head(env):
    db = env["db"]
    r = _routine(env, assignee_member_id=None, department_id=env["mk"].id)
    routines.tick(db, now=NINE_HCM)
    run = _runs(env, r)[0]
    task = db.get(Task, run.task_id)
    assert task.assignee_department_id == env["mk"].id and task.assignee_member_id is None
    wk = db.get(Wakeup, run.wakeup_id)
    assert wk.reason == "routed" and wk.member_id == env["head"].id


def test_run_only_reuses_and_reopens_standing_task(env):
    db = env["db"]
    r = _routine(env, mode="run_only")
    run1 = routines.run_now(db, r)
    _drain(env); _finish_task_run(env, run1.task_id)
    t = db.get(Task, run1.task_id); t.status = "done"; db.commit()
    routines.reconcile_open(db)
    run2 = routines.run_now(db, db.get(Routine, r.id))
    db.expire_all()
    assert run2.task_id == run1.task_id and db.get(Task, run1.task_id).status == "todo"
    assert db.query(Task).count() == 1


def test_template_snapshot_and_api(env):
    db, c, H = env["db"], env["client"], env["H"]
    assert {t["key"] for t in c.get("/api/routines/templates", headers=H).json()["templates"]} == \
        {"nina_morning_report", "sla_review", "weekly_cost_review"}
    made = c.post("/api/routines/from-template", headers=H, json={"key": "nina_morning_report"})
    assert made.status_code == 200, made.text
    body = made.json()
    assert body["assignee_member_id"] == env["nina"].id and body["triggers"][0]["cron"] == "30 8 * * *"
    assert body["timezone"] == "Asia/Ho_Chi_Minh"
    run = c.post(f"/api/routines/{body['id']}/run", headers=H).json()
    desc = db.get(Task, run["task_id"]).description
    assert "## Số liệu lúc" in desc and "Phê duyệt chờ: 0" in desc
    assert c.post("/api/routines", headers=H, json={"name": "x", "assignee_member_id": env["nina"].id,
                                                    "cron": "99 * * * *"}).status_code == 422
    assert c.post("/api/routines", headers=H, json={"name": "x", "assignee_member_id": env["nina"].id,
                                                    "cron": "0 9 * * *", "timezone": "Mars/Base"}).status_code == 422
    assert c.post("/api/routines", headers=H, json={"name": "x", "cron": "0 9 * * *"}).status_code == 422
    off = c.patch(f"/api/routines/{body['id']}", headers=H, json={"enabled": False}).json()
    assert off["enabled"] is False
    assert c.post(f"/api/routines/{body['id']}/run", headers=H).status_code == 409
    runs = c.get(f"/api/routines/{body['id']}/runs", headers=H).json()
    assert len(runs["runs"]) == 1 and runs["runs"][0]["kind"] == "manual"
    assert "secret" not in json.dumps(c.get("/api/routines", headers=H).json())
