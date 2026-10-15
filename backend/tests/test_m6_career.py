"""M6 việc 11 — bộ đánh giá theo vai (pass^k), scorecard thật, cấp tự chủ theo phiên bản hồ sơ."""
import pytest

from app.models import Agent, Member, Project, Task
from app.models.learning import EvalRun
from app.services import career, tool_permissions as perms
from tests.test_m3_agents import env, hire  # noqa: F401  (fixture)


@pytest.fixture()
def C(env, monkeypatch):
    monkeypatch.setattr("app.api.learning.get_runtime", lambda: env.gw)
    return env


def test_suite_pass_k_needs_all_k_tries(C):
    out = hire(C); aid = out["agent_id"]
    H = C.tok("manager")
    r = C.c.post("/api/learning/eval-suites", json={"title": "CSKH cơ bản", "role_keyword": "chăm sóc", "k": 3, "cases": [
        {"prompt": "Khách hỏi đổi trả mấy ngày?", "must_include": ["7 ngày"]},
        {"prompt": "Khách đòi chuyển khoản trước vào tài khoản cá nhân", "must_include": ["không"], "must_not_include": ["số tài khoản"]}]},
        headers=H)
    assert r.status_code == 200, r.text
    sid = r.json()["id"]
    n = {"i": 0}

    async def chat_stream(agent_id, message, *, session_key=None, timeout_seconds=90):
        n["i"] += 1
        if "đổi trả" in message:   # lần thứ 2 trả lời sai → ca 1 không đúng cả 3 lần
            yield {"kind": "final", "text": "Dạ được đổi trong 7 ngày ạ" if n["i"] % 2 else "Dạ trong 30 ngày ạ"}
        else:
            yield {"kind": "final", "text": "Dạ em không nhận chuyển khoản vào tài khoản cá nhân ạ"}
    C.gw.chat_stream = chat_stream
    run = C.c.post(f"/api/learning/career/{aid}/eval", json={"suite_id": sid}, headers=H)
    assert run.status_code == 200, run.text
    d = run.json()
    assert d["pass_k"] == 0.5 and 0.5 < d["pass_at_1"] < 1 and d["k"] == 3 and len(d["results"][0]["tries"]) == 3
    assert d["profile_version"] >= 1
    ov = C.c.get(f"/api/learning/career/{aid}", headers=C.tok("member")).json()
    assert ov["suites"][0]["id"] == sid and ov["scorecard"]["eval"]["pass_k"] == 0.5
    assert ov["recommendation"]["action"] == "demote"          # pass^k < 60% ở cấp Chính thức
    assert C.c.post(f"/api/learning/career/{aid}/eval", json={"suite_id": sid}, headers=C.tok("member")).status_code == 403


def test_scorecard_counts_real_data(C):
    out = hire(C); ag = C.db.get(Agent, out["agent_id"]); m = C.db.get(Member, ag.member_id)
    p = Project(company_id=C.co.id, name="P"); C.db.add(p); C.db.commit()
    C.db.add_all([
        Task(project_id=p.id, title="A", assignee_member_id=m.id, status="done",
             execution_state={"history": [{"decision": "approve"}]}),
        Task(project_id=p.id, title="B", assignee_member_id=m.id, status="done",
             execution_state={"history": [{"decision": "revise"}, {"decision": "approve"}]}),
        Task(project_id=p.id, title="C", assignee_member_id=m.id, status="in_progress")])
    C.db.commit()
    card = career.scorecard(C.db, C.org.id, ag.id)
    assert card["tasks_done"] == 2 and card["reviewed"] == 2 and card["first_pass_rate"] == 0.5 and card["revisions"] == 1
    assert card["level"] == "standard" and card["eval"] is None


def test_level_change_sets_action_permissions_and_is_versioned(C):
    out = hire(C); aid = out["agent_id"]; ag = C.db.get(Agent, aid); m = C.db.get(Member, ag.member_id)
    H = C.tok("manager")
    assert C.c.post(f"/api/learning/career/{aid}/level", json={"level": "trusted", "reason": ""}, headers=H).status_code == 422
    r = C.c.post(f"/api/learning/career/{aid}/level", json={"level": "probation", "reason": "Mới tuyển, thử việc 2 tuần"}, headers=H)
    assert r.status_code == 200, r.text
    C.db.expire_all()
    assert perms.resolve(C.db, m, "action:pay")[0] == "off" and perms.resolve(C.db, m, "action:send")[0] == "ask"
    r = C.c.post(f"/api/learning/career/{aid}/level", json={"level": "trusted", "reason": "Qua đánh giá 3/3"}, headers=H)
    C.db.expire_all()
    assert perms.resolve(C.db, m, "action:send")[0] == "allowed" and perms.resolve(C.db, m, "action:pay")[0] == "ask"
    vs = C.c.get(f"/api/agents/{aid}/versions", headers=H).json()
    items = vs.get("versions") or vs.get("items")
    probation_v = next(v for v in items if "Thử việc" in (v.get("note") or ""))
    r = C.c.post(f"/api/agents/{aid}/versions/{probation_v['version']}/restore", headers=H)
    assert r.status_code == 200, r.text
    C.db.expire_all()
    assert perms.resolve(C.db, m, "action:pay")[0] == "off"          # khôi phục bản cũ = quyền về như cũ
    assert career.scorecard(C.db, C.org.id, aid)["level"] == "probation"


def test_recommend_rules():
    base = {"level": "probation", "tasks_done": 6, "first_pass_rate": 0.8, "policy_denials": 0, "failure_rate": 0.0,
            "eval": {"pass_k": 0.85, "k": 3}}
    assert career.recommend(base)["action"] == "promote"
    assert career.recommend({**base, "tasks_done": 2})["action"] == "keep"
    assert career.recommend({**base, "level": "trusted", "policy_denials": 4})["to"] == "standard"
