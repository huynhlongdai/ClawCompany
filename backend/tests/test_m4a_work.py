"""M4a — /api/work: danh sách / bảng / side-peek, dòng thời gian lượt chạy kèm chi phí,
review chéo, chạy ngay. ORM thật (SQLite) + HTTP thật; runtime giả cho chat.send."""
import asyncio
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.security import create_access_token, hash_password
from app.db.base import Base
import app.models  # noqa: F401
from app.db.session import get_db
from app.main import app
from app.models import (Agent, Company, Department, Member, Organization, Project, Task, TaskRun, User,
                        UserOrganizationAccess, Wakeup)
from app.models.v16 import CollaborationRoom
from app.models.v37 import RoomConductorRun
from app.services import task_journal, wakeup


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
    rt = FakeRuntime()
    monkeypatch.setattr("app.services.agent_dispatch.get_runtime", lambda: rt)

    async def no_hours(agent):
        return None
    monkeypatch.setattr(wakeup, "ACTIVE_HOURS_LOOKUP", no_hours)
    org = Organization(name="Nova M4", slug="nova-m4"); other = Organization(name="Khác", slug="khac-m4")
    db.add_all([org, other]); db.commit()
    co = Company(organization_id=org.id, name="Nova Shop", status="active"); db.add(co); db.commit()
    co2 = Company(organization_id=other.id, name="Khác", status="active"); db.add(co2); db.commit()
    mkt = Department(company_id=co.id, name="Marketing", access_level="restricted"); db.add(mkt); db.commit()
    boss = Member(organization_id=org.id, company_id=co.id, name="Chị Lan", member_type="human", role="CEO")
    db.add(boss); db.commit()

    def seat(name, rid, lifecycle="active", dept=None):
        m = Member(organization_id=org.id, company_id=co.id, name=name, member_type="agent", role="AI",
                   status="active", manager_id=boss.id, department_id=dept)
        db.add(m); db.commit()
        db.add(Agent(member_id=m.id, runtime_agent_id=rid, lifecycle=lifecycle)); db.commit()
        return m

    head = seat("Hải Đăng", "hai-dang", dept=mkt.id)
    mai = seat("Mai Anh", "mai-anh", dept=mkt.id)
    nghi = seat("Tạm Nghỉ", "tam-nghi", lifecycle="paused")
    mkt.head_member_id = head.id; db.commit()
    proj = Project(company_id=co.id, name="Bộ sưu tập hè", status="active"); db.add(proj); db.commit()
    proj2 = Project(company_id=co2.id, name="Của người khác", status="active"); db.add(proj2); db.commit()
    users = {}
    for role in ("owner", "manager", "member"):
        u = User(email=f"{role}@m4.test", password_hash=hash_password("Matkhau123"), display_name=role.title(),
                 member_id=boss.id if role == "owner" else None)
        db.add(u); db.commit()
        db.add(UserOrganizationAccess(user_id=u.id, organization_id=org.id, role=role, is_default=True, status="active"))
        db.commit(); users[role] = u

    def tok(role):
        return {"Authorization": "Bearer " + create_access_token(users[role].id, org.id, role)}

    yield type("E", (), dict(db=db, org=org, co=co, mkt=mkt, boss=boss, head=head, mai=mai, nghi=nghi, proj=proj,
                             proj2=proj2, rt=rt, tok=staticmethod(tok), c=TestClient(app)))
    app.dependency_overrides.pop(get_db, None)


def create(env, role="owner", expect=201, **kw):
    body = {"title": "Viết 5 caption cho BST hè", "project_id": env.proj.id, "priority": "high",
            "assignee_member_id": env.mai.id, "reviewer_member_ids": [env.head.id],
            "acceptance_criteria": "Đủ 5 caption, có hashtag"}
    body.update(kw)
    r = env.c.post("/api/work/tasks", json=body, headers=env.tok(role))
    assert r.status_code == expect, r.text
    return r.json()


def wakes(env, **f):
    env.db.expire_all()
    q = env.db.query(Wakeup)
    for k, v in f.items():
        q = q.filter(getattr(Wakeup, k) == v)
    return q.all()


# ------------------------------------------------------------------ tạo việc

def test_create_with_agent_and_cross_review_wakes_agent(env):
    t = create(env)
    assert t["status"] == "todo" and t["assignee"]["name"] == "Mai Anh" and t["priority_vi"] == "Cao"
    assert t["review"]["needed"] and [r["name"] for r in t["review"]["reviewers"]] == ["Hải Đăng"]
    assert t["acceptance_criteria"] == "Đủ 5 caption, có hashtag"
    assert [w.reason for w in wakes(env, task_id=t["id"], member_id=env.mai.id)] == ["assigned"]
    labels = [e["label"] for e in t["timeline"] if e["type"] == "event"]
    assert "Tạo việc" in labels and any(l.startswith("Giao việc cho Mai Anh") for l in labels)


def test_create_rejects_self_review_paused_agent_and_member_setting_reviewers(env):
    r = create(env, expect=422, reviewer_member_ids=[env.mai.id])
    assert r["detail"]["error"] == "self_review" and "không tự review" in r["detail"]["message"]
    r = create(env, expect=409, assignee_member_id=env.nghi.id, reviewer_member_ids=[])
    assert r["detail"]["error"] == "agent_inactive" and "tạm dừng" in r["detail"]["message"]
    r = create(env, role="member", expect=403)
    assert r["detail"]["error"] == "manager_required"
    t = create(env, role="member", reviewer_member_ids=[])
    assert t["status"] == "todo"


def test_create_draft_does_not_wake(env):
    t = create(env, start=False, reviewer_member_ids=[])
    assert t["status"] == "backlog" and t["assignee"]["id"] == env.mai.id
    assert wakes(env, task_id=t["id"]) == []


def test_create_routed_to_department_wakes_head(env):
    t = create(env, assignee_member_id=None, department_id=env.mkt.id, reviewer_member_ids=[])
    assert t["routed_to_department"] and t["department"]["name"] == "Marketing" and t["assignee"] is None
    assert [w.reason for w in wakes(env, task_id=t["id"], member_id=env.head.id)] == ["routed"]


# ------------------------------------------------------------------ danh sách / bảng

def _run(env, task_id, member, status="completed", cost=0.01, ti=100, to=50, rid=None, err=""):
    now = datetime.utcnow()
    r = TaskRun(organization_id=env.org.id, task_id=task_id, member_id=member.id, trigger_kind="assigned",
                status=status, session_key=f"agent:x:company-task-{task_id}", runtime_run_id=rid or "",
                started_at=now - timedelta(seconds=30), ended_at=now if status != "running" else None,
                cost_usd=cost, tokens_in=ti, tokens_out=to, error_reason=err)
    env.db.add(r); env.db.commit()
    return r


def test_list_counts_runs_cost_review_room_and_filters(env):
    a = create(env)
    b = create(env, title="Đặt lịch chụp", assignee_member_id=None, reviewer_member_ids=[], priority="low")
    _run(env, a["id"], env.mai, cost=0.004, rid="r1")
    _run(env, a["id"], env.mai, status="failed", cost=0.001, err="timeout waiting for gateway")
    room = CollaborationRoom(organization_id=env.org.id, room_key=f"review-t{a['id']}-r1-s0", topic="x")
    env.db.add(room); env.db.commit()
    env.db.add(RoomConductorRun(organization_id=env.org.id, room_id=room.id, speaker_member_id=env.head.id,
                                cost_usd=0.002)); env.db.commit()
    other = Task(project_id=env.proj2.id, title="Không được thấy", status="todo"); env.db.add(other); env.db.commit()

    r = env.c.get("/api/work/tasks", headers=env.tok("member")).json()
    ids = [i["id"] for i in r["items"]]
    assert other.id not in ids and set(ids) == {a["id"], b["id"]}
    assert r["counts"]["todo"] == 2 and r["total"] == 2
    ia = next(i for i in r["items"] if i["id"] == a["id"])
    assert ia["runs"]["count"] == 2 and ia["runs"]["failed"] == 1 and ia["runs"]["last_status"] == "failed"
    assert ia["runs"]["cost_usd"] == pytest.approx(0.007)          # 2 lượt + phòng review
    assert ia["department"]["name"] == "Marketing" and ia["assignee"]["lifecycle"] == "active"
    assert ia["review"]["reviewers"][0]["name"] == "Hải Đăng"
    assert ia["revision"].startswith("task:")

    q = lambda s: [i["id"] for i in env.c.get(f"/api/work/tasks?{s}", headers=env.tok("member")).json()["items"]]
    assert q("assignee=none") == [b["id"]]
    assert q(f"assignee={env.mai.id}") == [a["id"]]
    assert q("priority=low") == [b["id"]]
    assert q(f"q=%23{a['id']}") == [a["id"]]
    assert q("q=lịch") == [b["id"]]
    assert q(f"department_id={env.mkt.id}") == [a["id"]]
    assert q("status=done") == [] and env.c.get("/api/work/tasks?status=done", headers=env.tok("member")).json()["counts"]["todo"] == 2


# ------------------------------------------------------------------ side-peek

def test_detail_timeline_runs_with_cost_entries_and_errors(env):
    t = create(env)
    task = env.db.get(Task, t["id"])
    _run(env, t["id"], env.mai, cost=0.0052, ti=1200, to=300, rid="run-a")
    task_journal.append(env.db, task, kind="result", summary="Đã viết 5 caption", actor_member_id=env.mai.id,
                        runtime_run_id="run-a")
    task_journal.append(env.db, task, kind="note", summary="Ghi chú rời", actor_member_id=env.boss.id)
    _run(env, t["id"], env.mai, status="failed", cost=0, err="websocket closed")
    d = env.c.get(f"/api/work/tasks/{t['id']}", headers=env.tok("member")).json()
    runs = [e for e in d["timeline"] if e["type"] == "run"]
    assert len(runs) == 2 and runs[0]["cost_usd"] == 0.0052 and runs[0]["tokens_in"] == 1200
    assert runs[0]["duration_s"] == pytest.approx(30, abs=1) and runs[0]["trigger_vi"] == "Được giao việc"
    assert [e["summary"] for e in runs[0]["entries"]] == ["Đã viết 5 caption"]
    assert runs[1]["status_vi"] == "Lỗi" and "Mất kết nối gateway" in runs[1]["error_vi"]
    assert any(e["type"] == "entry" and e["summary"] == "Ghi chú rời" for e in d["timeline"])
    # mỗi mục sổ hiện đúng một lần, không kèm thẻ sự kiện thô "task.journal.*"
    labels = [e["label"] for e in d["timeline"] if e["type"] == "event"]
    assert labels and not [x for x in labels if x.startswith("task.")]
    assert d["totals"]["runs"] == 2 and d["totals"]["failed"] == 1 and d["totals"]["cost_usd"] == pytest.approx(0.0052)
    assert d["suggested_reviewer"]["name"] == "Hải Đăng"        # trưởng phòng của người làm
    assert [n["key"] for n in d["next"]] == ["in_progress", "backlog", "cancelled"]


# ------------------------------------------------------------------ kéo thẻ / sửa

def test_move_stale_revision_invalid_transition_and_policy_guard(env):
    t = create(env)
    r = env.c.post(f"/api/work/tasks/{t['id']}/move", json={"status": "in_progress", "expected_revision": "task:1:old"},
                   headers=env.tok("member"))
    assert r.status_code == 409 and r.json()["detail"]["error"] == "stale_revision"
    assert "người khác sửa" in r.json()["detail"]["message"] and r.json()["detail"]["current_revision"] == t["revision"]
    r = env.c.post(f"/api/work/tasks/{t['id']}/move", json={"status": "done"}, headers=env.tok("member"))
    assert r.status_code == 409 and r.json()["detail"]["error"] == "invalid_transition"
    assert "Cần làm" in r.json()["detail"]["message"] and "Xong" in r.json()["detail"]["message"]
    r = env.c.post(f"/api/work/tasks/{t['id']}/move", json={"status": "in_progress", "expected_revision": t["revision"]},
                   headers=env.tok("member"))
    assert r.status_code == 200 and r.json()["status"] == "in_progress"
    r = env.c.post(f"/api/work/tasks/{t['id']}/move", json={"status": "review"}, headers=env.tok("member"))
    assert r.json()["review"]["state"] == "in_review" and r.json()["review"]["reviewer"]["name"] == "Hải Đăng"
    # agent reviewer được đánh thức
    assert [w.reason for w in wakes(env, task_id=t["id"], member_id=env.head.id)] == ["review_requested"]
    r = env.c.post(f"/api/work/tasks/{t['id']}/move", json={"status": "done"}, headers=env.tok("member"))
    assert r.status_code == 409 and r.json()["detail"]["error"] == "execution_policy_pending"
    assert "Chờ duyệt" in r.json()["detail"]["message"]


def test_needs_assignee_message_is_vietnamese(env):
    t = create(env, assignee_member_id=None, reviewer_member_ids=[])
    r = env.c.post(f"/api/work/tasks/{t['id']}/move", json={"status": "in_progress"}, headers=env.tok("member"))
    assert r.status_code == 400 and r.json()["detail"]["error"] == "needs_assignee"


def test_patch_fields_and_assignee_guard(env):
    t = create(env)
    r = env.c.patch(f"/api/work/tasks/{t['id']}", headers=env.tok("member"),
                    json={"expected_revision": t["revision"], "title": "Viết 6 caption", "priority": "urgent",
                          "due_at": "2026-10-20"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["title"] == "Viết 6 caption" and d["priority_vi"] == "Khẩn" and d["due_at"].startswith("2026-10-20")
    r = env.c.patch(f"/api/work/tasks/{t['id']}", headers=env.tok("member"),
                    json={"expected_revision": t["revision"], "title": "Ghi đè mù"})
    assert r.status_code == 409 and r.json()["detail"]["error"] == "stale_revision"
    r = env.c.patch(f"/api/work/tasks/{t['id']}", headers=env.tok("member"), json={"assignee_member_id": env.head.id})
    assert r.status_code == 422 and r.json()["detail"]["error"] == "self_review"
    r = env.c.patch(f"/api/work/tasks/{t['id']}", headers=env.tok("member"), json={"due_at": "mai"})
    assert r.status_code == 422 and r.json()["detail"]["error"] == "invalid_due"


# ------------------------------------------------------------------ review chéo

def test_set_reviewers_and_human_review_decisions(env):
    t = create(env, reviewer_member_ids=[])
    r = env.c.put(f"/api/work/tasks/{t['id']}/reviewers", json={"reviewer_member_ids": [env.mai.id]},
                  headers=env.tok("manager"))
    assert r.status_code == 422 and r.json()["detail"]["error"] == "self_review"
    r = env.c.put(f"/api/work/tasks/{t['id']}/reviewers", json={"reviewer_member_ids": [env.boss.id]},
                  headers=env.tok("member"))
    assert r.status_code == 403
    r = env.c.put(f"/api/work/tasks/{t['id']}/reviewers", json={"reviewer_member_ids": [env.boss.id]},
                  headers=env.tok("manager"))
    assert r.status_code == 200 and r.json()["review"]["reviewers"][0]["name"] == "Chị Lan"
    for s in ("in_progress", "review"):
        assert env.c.post(f"/api/work/tasks/{t['id']}/move", json={"status": s}, headers=env.tok("member")).status_code == 200
    r = env.c.put(f"/api/work/tasks/{t['id']}/reviewers", json={"reviewer_member_ids": []}, headers=env.tok("manager"))
    assert r.status_code == 409 and r.json()["detail"]["error"] == "review_in_progress"
    assert "đợi reviewer quyết xong" in r.json()["detail"]["message"]
    # Chị Lan (owner, member_id=boss) yêu cầu sửa → về Đang làm, Mai Anh được đánh thức
    r = env.c.post(f"/api/work/tasks/{t['id']}/review", json={"decision": "revise", "note": "Thiếu hashtag"},
                   headers=env.tok("owner"))
    assert r.status_code == 200 and r.json()["status"] == "in_progress"
    assert "changes_requested" in [w.reason for w in wakes(env, task_id=t["id"], member_id=env.mai.id)]
    assert r.json()["review"]["history"][0]["decision_vi"] == "Yêu cầu sửa"
    env.c.post(f"/api/work/tasks/{t['id']}/move", json={"status": "review"}, headers=env.tok("member"))
    r = env.c.post(f"/api/work/tasks/{t['id']}/review", json={"decision": "approve"}, headers=env.tok("owner"))
    assert r.json()["status"] == "done" and r.json()["review"]["state"] == "approved" and r.json()["review"]["round"] == 2


# ------------------------------------------------------------------ chạy ngay

def test_run_now_dispatches_through_wakeup_and_explains_skips(env):
    t = create(env, start=False, reviewer_member_ids=[])
    r = env.c.post(f"/api/work/tasks/{t['id']}/run", headers=env.tok("member"))
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["decision"] == "dispatched" and out["run_id"] and env.rt.calls[0]["agent"] == "mai-anh"
    assert out["task"]["totals"]["runs"] == 1 and out["task"]["totals"]["running"]
    # seat đang bận lượt này → việc thứ hai bị hoãn kèm câu giải thích
    t2 = create(env, title="Việc thứ hai", start=False, reviewer_member_ids=[])
    out2 = env.c.post(f"/api/work/tasks/{t2['id']}/run", headers=env.tok("member")).json()
    assert out2["decision"] == "skipped" and "đang bận" in out2["message"]


def test_run_now_refusals(env):
    t = create(env, assignee_member_id=None, reviewer_member_ids=[])
    r = env.c.post(f"/api/work/tasks/{t['id']}/run", headers=env.tok("member"))
    assert r.status_code == 409 and r.json()["detail"]["error"] == "no_assignee"
    h = create(env, assignee_member_id=env.boss.id, reviewer_member_ids=[])
    r = env.c.post(f"/api/work/tasks/{h['id']}/run", headers=env.tok("member"))
    assert r.json()["detail"]["error"] == "not_agent"
    env.c.post(f"/api/work/tasks/{h['id']}/move", json={"status": "cancelled"}, headers=env.tok("member"))
    r = env.c.post(f"/api/work/tasks/{h['id']}/run", headers=env.tok("member"))
    assert r.json()["detail"]["error"] in ("not_agent", "not_runnable")


# ------------------------------------------------------------------ đường cũ

def test_legacy_routes_carry_deprecation_header(env):
    t = create(env)
    r = env.c.get("/api/v17/workspace/tasks", headers=env.tok("owner"))
    assert r.headers.get("Deprecation") == "true" and "/api/work/tasks" in r.headers.get("Link", "")
    r = env.c.get(f"/api/tasks/{t['id']}/runs", headers=env.tok("owner"))
    assert r.status_code == 200 and f"/api/work/tasks/{t['id']}" in r.headers["Link"]
    r = env.c.get("/api/work/tasks", headers=env.tok("owner"))
    assert "Deprecation" not in r.headers


def test_meta_lists_assignable_members_and_caps(env):
    m = env.c.get("/api/work/meta", headers=env.tok("member")).json()
    by = {x["name"]: x for x in m["members"]}
    assert by["Tạm Nghỉ"]["assignable"] is False and by["Mai Anh"]["assignable"] is True
    assert [p["name"] for p in m["projects"]] == ["Bộ sưu tập hè"] and m["caps"] == {"create": True, "set_reviewers": False}
    assert env.c.get("/api/work/meta", headers=env.tok("manager")).json()["caps"]["set_reviewers"] is True


# ------------------------------------------------------------------ báo cáo = câu trả lời cuối

def _ending_run(env, t):
    run = TaskRun(organization_id=env.org.id, task_id=t.id, member_id=env.mai.id, status="running",
                  session_key=f"agent:mai-anh:company-task-{t.id}", runtime_run_id="run-x",
                  started_at=datetime.utcnow() - timedelta(seconds=5))
    env.db.add(run); env.db.commit()
    t.checkout_run_id = run.id; t.status = "in_progress"; env.db.add(t); env.db.commit()
    return run


def test_final_reply_becomes_the_doers_report_and_review_starts(env):
    from app.services import runtime_stream as stream
    d = create(env, start=False)
    t = env.db.get(Task, d["id"])
    run = _ending_run(env, t)
    st = stream.ConsumerState(session_key=run.session_key, task_id=t.id, organization_id=env.org.id)
    stream.handle_event(env.db, st, {"type": "session.message", "family": "session.message", "raw": {
        "sessionKey": run.session_key, "messageId": "m1",
        "message": {"role": "assistant", "content": [{"type": "text", "text": "1. Nắng hè rực rỡ #BSTHe\n2. ..."}]}}})
    assert st.last_reply.startswith("1. Nắng hè")
    stream.handle_event(env.db, st, {"type": "chat", "family": "chat", "state": "final", "terminal": True})
    env.db.expire_all()
    t = env.db.get(Task, d["id"])
    assert t.status == "review" and t.execution_state["status"] == "in_review"
    detail = env.c.get(f"/api/work/tasks/{t.id}", headers=env.tok("member")).json()
    run_card = next(e for e in detail["timeline"] if e["type"] == "run")
    assert [x["kind"] for x in run_card["entries"]] == ["result"]
    assert run_card["entries"][0]["detail"].startswith("1. Nắng hè rực rỡ")


def test_empty_final_reply_is_still_missing_report(env):
    from app.services import runtime_stream as stream
    d = create(env, start=False)
    t = env.db.get(Task, d["id"])
    run = _ending_run(env, t)
    st = stream.ConsumerState(session_key=run.session_key, task_id=t.id, organization_id=env.org.id)
    stream.apply_terminal_state(env.db, t, st, {"state": "final"})
    env.db.expire_all()
    assert env.db.get(Task, d["id"]).status == "blocked"


def test_review_room_prompt_anchors_the_reviewed_task_and_shows_result(env):
    from app.services import collaboration_rooms as rooms, room_conductor
    other = create(env, title="Việc khẩn khác trong cùng dự án", priority="urgent", reviewer_member_ids=[])
    d = create(env, start=False)
    t = env.db.get(Task, d["id"])
    task_journal.append(env.db, t, kind="result", summary="Kết quả: 5 caption", detail="CAPTION-NGUYEN-VAN-123",
                        actor_member_id=env.mai.id)
    room = rooms.open_room(env.db, organization_id=env.org.id, room_key=f"review-t{t.id}-r1-s0", max_turns=4,
                           topic="Review", objective="Chấm", project_id=t.project_id, created_by_member_id=None,
                           seed_team_participants=False)
    p = rooms.join_room(env.db, room, member_id=env.head.id, participant_role="lead", can_post=True, can_decide=True,
                        seat_order=1, emit=False)
    text = room_conductor.build_turn_prompt(env.db, room, p, chair=p)
    assert "## Việc đang review" in text and "CAPTION-NGUYEN-VAN-123" in text
    assert f"#{other['id']}" not in text.split("## Việc đang review", 1)[1][:400]


# ------------------------------------------------------------------ drain đôi (gate thật, việc #26)

def _review_wakeup(env):
    t = create(env)
    for s in ("in_progress", "review"):
        assert env.c.post(f"/api/work/tasks/{t['id']}/move", json={"status": s}, headers=env.tok("member")).status_code == 200
    [wk] = wakes(env, task_id=t["id"], member_id=env.head.id, reason="review_requested")
    return t, wk


def test_two_drains_never_run_the_same_review_twice(env, monkeypatch):
    """Celery 4 tiến trình + beat 5 giây: review ~40 giây, wakeup còn 'queued' → drain thứ hai
    bốc lại đúng wakeup ấy (gate M4a lần 8: hai drain cùng chốt, một cái 409)."""
    from app.services import execution_policy
    t, wk = _review_wakeup(env)
    calls = []

    async def slow_review(db, task, member, runtime):
        calls.append(task.id)
        await asyncio.sleep(0.05)
        return {"decision": "approve", "room_id": 0}
    monkeypatch.setattr(execution_policy, "run_agent_review", slow_review)
    Maker = sessionmaker(bind=env.db.get_bind(), autoflush=False)

    async def both():
        a, b = Maker(), Maker()
        try:
            return await asyncio.gather(wakeup.drain(a, member_id=env.head.id, force=True),
                                        wakeup.drain(b, member_id=env.head.id, force=True))
        finally:
            a.close(); b.close()
    outs = asyncio.run(both())
    assert calls == [t["id"]]
    assert sorted(o["decision"] for out in outs for o in out) == ["reviewed"]
    env.db.expire_all()
    assert env.db.get(Wakeup, wk.id).status == "dispatched"


def test_claim_is_released_for_wakeups_left_queued_and_expires_when_a_drain_dies(env):
    a = create(env, start=False, reviewer_member_ids=[])
    b = create(env, title="Việc thứ hai", start=False, reviewer_member_ids=[])
    for t in (a, b):
        wakeup.enqueue(env.db, organization_id=env.org.id, member_id=env.mai.id, reason="assigned", task_id=t["id"],
                       dedupe_key=f"claim-test:{t['id']}")
    asyncio.run(wakeup.drain(env.db, member_id=env.mai.id, force=True))
    left = [w for w in wakes(env, member_id=env.mai.id) if w.status == "queued"]
    # seat chỉ chạy một việc mỗi drain: wakeup còn lại phải được trả chỗ, không bị giữ 15 phút
    assert left and all(w.processed_at is None for w in left)
    # tiến trình giữ chỗ rồi chết: chưa hết hạn thì không ai bốc, hết hạn thì bốc lại
    now = datetime.utcnow()
    for w in left:
        w.processed_at = now - timedelta(seconds=60)
    env.db.commit()
    assert asyncio.run(wakeup.drain(env.db, member_id=env.mai.id, force=True, now=now)) == []
    for w in left:
        w.processed_at = now - timedelta(seconds=wakeup.CLAIM_TTL_SECONDS + 5)
    env.db.commit()
    assert asyncio.run(wakeup.drain(env.db, member_id=env.mai.id, force=True, now=now))
