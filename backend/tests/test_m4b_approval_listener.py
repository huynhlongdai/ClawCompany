"""Gate M4b (gateway thật): thẻ duyệt exec tới socket thường trực phải thành hàng approvals gắn đúng việc."""
from app.models import Agent, Approval, Project, Task
from app.models.work_graph import TaskRun
from app.services import approval_listener
from tests.test_m3_agents import env, hire  # noqa: F401  (fixture)


def _requested(key: str, rid: str = "ap-1") -> dict:
    return {"family": "exec.approval.requested", "type": "exec.approval.requested",
            "raw": {"id": rid, "request": {"command": "date +%Y", "host": "gateway", "sessionKey": key,
                                           "agentId": key.split(":")[1]}, "expiresAtMs": 9_999_999_999_999}}


def test_listener_records_exec_approval_for_the_running_task_once(env):
    out = hire(env); ag = env.db.get(Agent, out["agent_id"])
    p = Project(company_id=env.co.id, name="P"); env.db.add(p); env.db.commit()
    t = Task(project_id=p.id, title="Kiểm tra năm", assignee_member_id=ag.member_id, status="in_progress")
    env.db.add(t); env.db.commit()
    key = f"agent:{ag.runtime_agent_id}:company-task-{t.id}"
    env.db.add(TaskRun(organization_id=env.org.id, task_id=t.id, member_id=ag.member_id, status="running", session_key=key))
    env.db.commit()
    assert approval_listener.record(env.db, _requested(key)) is True
    assert approval_listener.record(env.db, _requested(key)) is True        # follower/listener cùng thấy → không trùng
    rows = env.db.query(Approval).filter(Approval.policy_key.like("openclaw:%")).all()
    assert len(rows) == 1 and rows[0].status == "pending" and rows[0].requester_member_id == ag.member_id
    import json
    ev = json.loads(rows[0].evidence)
    assert "date +%Y" in rows[0].action and ev["task_id"] == t.id and ev["session_key"] == key


def test_listener_ignores_sessions_that_are_not_company_agents(env):
    assert approval_listener.record(env.db, _requested("agent:la-hoan-toan:main")) is False
    assert approval_listener.record(env.db, _requested("cron:x")) is False
