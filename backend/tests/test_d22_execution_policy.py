"""D2.2 — execution policy (ORM thật, TestClient, runtime giả).

"Xong khi": không đường API nào đưa task có policy sang done trước khi qua đủ
chặng; vòng sửa → làm lại → duyệt chạy được; run không có comment bị chặn.
"""
from __future__ import annotations

import asyncio
import json

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
from app.models import Approval, CompanyEvent, TaskJournalEntry, TaskRun, Wakeup
from app.models.auth import User
from app.models.entities import Agent, Company, Member, Organization, Project, Task
from app.services import execution_policy as ep
from app.services import runtime_stream as stream
from app.services import task_journal, task_lifecycle, wakeup


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
    org = Organization(name="Nova", slug="nova-d22"); db.add(org); db.commit()
    co = Company(organization_id=org.id, name="Nova", status="active"); db.add(co); db.commit()

    def human(name, email, role):
        m = Member(organization_id=org.id, company_id=co.id, name=name, member_type="human", role=role, status="active")
        db.add(m); db.commit()
        u = User(email=email, password_hash="x", member_id=m.id); db.add(u); db.commit()
        return m, {"Authorization": f"Bearer {create_access_token(u.id, org.id, 'admin')}"}

    boss, H = human("Long", "long@nova.test", "CEO")
    rev, HR = human("Hà", "ha@nova.test", "QA")

    def seat(name, rid):
        m = Member(organization_id=org.id, company_id=co.id, name=name, member_type="agent", role="AI",
                   status="active", manager_id=boss.id)
        db.add(m); db.commit()
        db.add(Agent(member_id=m.id, runtime_agent_id=rid, lifecycle="active")); db.commit()
        return m

    nina, sophia = seat("Nina", "dev"), seat("Sophia", "sophia")
    proj = Project(company_id=co.id, name="P", status="active"); db.add(proj); db.commit()

    async def no_hours(agent):
        return None
    monkeypatch.setattr(wakeup, "ACTIVE_HOURS_LOOKUP", no_hours)
    yield {"db": db, "org": org, "boss": boss, "rev": rev, "nina": nina, "sophia": sophia, "proj": proj,
           "client": TestClient(app), "H": H, "HR": HR}
    app.dependency_overrides.pop(get_db, None)


def _task(env, status="in_progress", stages=None, assignee="nina"):
    t = Task(project_id=env["proj"].id, title="Viết báo cáo", status=status,
             assignee_member_id=env[assignee].id)
    env["db"].add(t); env["db"].commit(); env["db"].refresh(t)
    if stages is not None:
        r = env["client"].put(f"/api/tasks/{t.id}/execution-policy", headers=env["H"], json={"stages": stages})
        assert r.status_code == 200, r.text
    env["db"].expire_all()
    return env["db"].get(Task, t.id)


def _fresh(env, t):
    env["db"].expire_all()
    return env["db"].get(Task, t.id)


def _review_stage(env, who="rev"):
    return [{"type": "review", "participants": [env[who].id]}]


# ------------------------------------------------------------------ chốt done


def test_no_endpoint_can_finish_a_task_whose_stages_are_pending(env):
    t = _task(env, status="review", stages=_review_stage(env))
    c, H = env["client"], env["H"]
    tries = {
        "v18": c.post(f"/api/v18/workspace/tasks/{t.id}/move", headers=H, json={"status": "done"}),
        "v20": c.post(f"/api/v20/board/tasks/{t.id}/move", headers=H, json={"status": "done", "dispatch": False}),
        "v27": c.post(f"/api/v27/tasks/{t.id}/move", headers=H, json={"status": "done"}),
    }
    for name, r in tries.items():
        assert r.status_code == 409, (name, r.status_code, r.text)
        assert "execution_policy_pending" in r.text, (name, r.text)
    # đường hệ thống (system=True) cũng không vượt được
    with pytest.raises(Exception) as exc:
        task_lifecycle.transition(env["db"], _fresh(env, t), "done", system=True, reason="thử vượt")
    assert "execution_policy_pending" in str(exc.value.detail)
    assert _fresh(env, t).status == "review"


def test_agent_tool_cannot_finish_either(env):
    from app.services import company_mcp
    t = _task(env, status="review", stages=_review_stage(env))
    with pytest.raises(Exception) as exc:
        task_lifecycle.transition(env["db"], _fresh(env, t), "done", via="mcp", actor_member_id=env["nina"].id)
    assert "execution_policy_pending" in str(exc.value.detail)
    assert company_mcp  # tool đi qua cùng lifecycle.transition (company_mcp.py dòng company_task_status)


def test_task_without_policy_is_unchanged(env):
    t = _task(env, status="review")
    r = env["client"].post(f"/api/v18/workspace/tasks/{t.id}/move", headers=env["H"], json={"status": "done"})
    assert r.status_code == 200, r.text


# ------------------------------------------------------- sửa → làm lại → duyệt


def test_revise_then_redo_then_approve_with_a_human_reviewer(env):
    t = _task(env, stages=_review_stage(env))
    c = env["client"]
    # người làm báo xong
    r = c.post(f"/api/v18/workspace/tasks/{t.id}/move", headers=env["H"], json={"status": "review"})
    assert r.status_code == 200, r.text
    st = _fresh(env, t).execution_state
    assert (st["status"], st["round"], st["reviewer_member_id"]) == ("in_review", 1, env["rev"].id)
    # người làm không tự duyệt; người ngoài không duyệt
    assert c.post(f"/api/tasks/{t.id}/review", headers=env["H"], json={"decision": "approve"}).status_code == 403
    # reviewer yêu cầu sửa
    r = c.post(f"/api/tasks/{t.id}/review", headers=env["HR"], json={"decision": "revise", "note": "Thiếu số liệu tuần"})
    assert r.status_code == 200, r.text
    t1 = _fresh(env, t)
    assert t1.status == "in_progress" and t1.execution_state["status"] == "changes_requested"
    rv = env["db"].query(TaskJournalEntry).filter_by(task_id=t.id, kind="review").all()
    assert len(rv) == 1 and "SỬA" in rv[0].summary and "Thiếu số liệu" in rv[0].detail
    (wk,) = env["db"].query(Wakeup).filter_by(task_id=t.id, reason="changes_requested").all()
    assert wk.member_id == env["nina"].id and json.loads(wk.payload)["note"] == "Thiếu số liệu tuần"
    # làm lại → vòng 2
    c.post(f"/api/v18/workspace/tasks/{t.id}/move", headers=env["H"], json={"status": "review"})
    assert _fresh(env, t).execution_state["round"] == 2
    r = c.post(f"/api/tasks/{t.id}/review", headers=env["HR"], json={"decision": "approve", "note": "OK"})
    assert r.status_code == 200, r.text
    t2 = _fresh(env, t)
    assert t2.status == "done" and t2.execution_state["status"] == "approved"
    assert [h["decision"] for h in t2.execution_state["history"]] == ["revise", "approve"]


def test_two_stages_review_then_approval_row(env):
    stages = [{"type": "review", "participants": [env["rev"].id]},
              {"type": "approval", "participants": [env["boss"].id]}]
    t = _task(env, stages=stages)
    c = env["client"]
    c.post(f"/api/v18/workspace/tasks/{t.id}/move", headers=env["H"], json={"status": "review"})
    c.post(f"/api/tasks/{t.id}/review", headers=env["HR"], json={"decision": "approve"})
    t1 = _fresh(env, t)
    assert t1.status == "review" and t1.execution_state["stage_index"] == 1
    ap = env["db"].get(Approval, t1.execution_state["approval_id"])
    assert ap.status == "pending" and ap.approver_member_id == env["boss"].id
    assert ap.requester_member_id == env["nina"].id and ap.policy_key.startswith(f"task_stage:t{t.id}:")
    # người khác không duyệt thay được
    r = c.post(f"/api/approvals/{ap.id}/resolve", headers=env["HR"], json={"status": "approved"})
    assert r.status_code == 403, r.text
    r = c.post(f"/api/approvals/{ap.id}/resolve", headers=env["H"], json={"status": "approved", "resolution_note": "ok"})
    assert r.status_code == 200, r.text
    assert _fresh(env, t).status == "done"


def test_rejected_approval_sends_the_work_back(env):
    t = _task(env, stages=[{"type": "approval", "participants": [env["boss"].id]}])
    c = env["client"]
    c.post(f"/api/v18/workspace/tasks/{t.id}/move", headers=env["H"], json={"status": "review"})
    ap_id = _fresh(env, t).execution_state["approval_id"]
    c.post(f"/api/approvals/{ap_id}/resolve", headers=env["H"], json={"status": "rejected", "resolution_note": "làm lại"})
    t1 = _fresh(env, t)
    assert t1.status == "in_progress" and t1.execution_state["status"] == "changes_requested"


def test_reviewer_list_excludes_the_doer(env):
    t = _task(env, stages=[{"type": "review", "participants": [env["nina"].id, env["sophia"].id]}])
    task_lifecycle.transition(env["db"], t, "review", actor_member_id=env["nina"].id)
    st = _fresh(env, t).execution_state
    assert st["reviewer_member_id"] == env["sophia"].id
    (wk,) = env["db"].query(Wakeup).filter_by(task_id=t.id, reason="review_requested").all()
    assert wk.member_id == env["sophia"].id


def test_invalid_policy_is_rejected(env):
    t = _task(env)
    r = env["client"].put(f"/api/tasks/{t.id}/execution-policy", headers=env["H"],
                          json={"stages": [{"type": "vote", "participants": [1]}]})
    assert r.status_code == 422
    r = env["client"].put(f"/api/tasks/{t.id}/execution-policy", headers=env["H"],
                          json={"stages": [{"type": "review", "participants": [99999]}]})
    assert r.status_code == 422


# ---------------------------------------------------------- reviewer là agent


class RoomRuntime:
    """Giả gateway cho phòng họp: chat.send rồi chat.history trả lời theo kịch bản."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.sent = []
        self.hist = {}

    async def rpc(self, method, params=None):
        params = params or {}
        key = params.get("sessionKey")
        if method == "chat.send":
            self.sent.append(key)
            reply = self.replies.pop(0) if self.replies else "..."
            self.hist.setdefault(key, []).append({"role": "user", "content": params.get("message", "")})
            self.hist[key].append({"role": "assistant", "content": [{"type": "text", "text": reply}]})
            return {"runId": f"r{len(self.sent)}", "status": "started"}
        if method == "chat.history":
            return {"messages": self.hist.get(key, [])}
        return {}

    async def run_agent(self, runtime_agent_id, input_text, metadata=None, session_key=None):
        from app.runtime.base import RuntimeRun
        await self.rpc("chat.send", {"sessionKey": session_key, "message": input_text})
        return RuntimeRun(task_id="t", run_id=f"r{len(self.sent)}", session_key=session_key or "",
                          status="running", raw={})

    async def history(self, session_key, limit=20):
        return {"messages": self.hist.get(session_key, [])}


def test_agent_reviewer_decides_in_a_two_person_room(env, monkeypatch):
    t = _task(env, stages=[{"type": "review", "participants": [env["sophia"].id]}])
    task_lifecycle.transition(env["db"], t, "review", actor_member_id=env["nina"].id)
    rt = RoomRuntime(["Đã xem.\nQUYẾT ĐỊNH: SỬA — thiếu nguồn số liệu"])
    monkeypatch.setattr("app.runtime.factory.get_runtime", lambda: rt)
    from app.services import room_conductor
    monkeypatch.setattr(room_conductor, "POLL_SECONDS", 0.01)
    from datetime import datetime, timedelta
    out = asyncio.run(wakeup.drain(env["db"], now=datetime.utcnow() + timedelta(seconds=11)))
    assert out[0]["decision"] == "reviewed", out
    assert out[0]["review"]["decision"] == "revise"
    t1 = _fresh(env, t)
    assert t1.status == "in_progress" and t1.execution_state["history"][0]["via"] == "room"
    assert len(rt.sent) == 1 and f"review-t{t.id}" in rt.sent[0]  # 1 lượt: chủ toạ chốt ngay


def test_parse_decision_takes_the_last_marker():
    assert ep.parse_decision("QUYẾT ĐỊNH: SỬA\n...\nQUYẾT ĐỊNH: DUYỆT") == "approve"
    assert ep.parse_decision("tôi quyết định duyệt") is None


# ------------------------------------------------------------ báo cáo bắt buộc


def _run_ends(env, t, *, comment: bool):
    db = env["db"]
    run = TaskRun(organization_id=env["org"].id, task_id=t.id, member_id=env["nina"].id, status="running",
                  session_key=f"agent:dev:company-task-{t.id}")
    from datetime import datetime, timedelta
    run.started_at = datetime.utcnow() - timedelta(seconds=5)
    db.add(run); db.commit()
    t.checkout_run_id = run.id; db.add(t); db.commit()
    if comment:
        task_journal.append(db, t, kind="result", summary="Đã xong, file ở /out/report.md",
                            actor_member_id=env["nina"].id)
    state = stream.ConsumerState(session_key=run.session_key, task_id=t.id, organization_id=env["org"].id)
    stream.apply_terminal_state(db, _fresh(env, t), state, {"state": "final"})
    return _fresh(env, t)


def test_run_without_a_comment_is_flagged_and_does_not_move_on(env):
    t = _task(env, stages=_review_stage(env))
    t1 = _run_ends(env, t, comment=False)
    assert t1.status == "blocked" and t1.execution_state["missing_report"]
    assert env["db"].query(CompanyEvent).filter_by(event_type="task.report.missing").count() == 1


def test_run_with_a_comment_goes_to_review_and_starts_the_stage(env):
    t = _task(env, stages=_review_stage(env))
    t1 = _run_ends(env, t, comment=True)
    assert t1.status == "review" and t1.execution_state["status"] == "in_review"
