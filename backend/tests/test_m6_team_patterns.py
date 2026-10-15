"""M6 việc 12 — mẫu làm nhóm: reviewer ngữ cảnh sạch, cố vấn model mạnh."""
import asyncio

import pytest

from app.models import Agent, Member, Project, Task
from app.models.v10 import Artifact
from app.services import company_mcp, execution_policy
from tests.test_m3_agents import env, hire  # noqa: F401  (fixture)


def test_policy_accepts_clean_mode_and_rejects_unknown():
    p = execution_policy.normalize({"stages": [{"type": "review", "participants": [3], "mode": "clean"},
                                               {"type": "approval", "participants": [4]}]})
    assert p["stages"][0]["mode"] == "clean" and "mode" not in p["stages"][1]
    with pytest.raises(execution_policy.PolicyError):
        execution_policy.normalize({"stages": [{"type": "review", "participants": [3], "mode": "loud"}]})


def test_clean_review_sees_only_brief_and_deliverable_then_decides(env):
    doer = hire(env); rev = hire(env, name="Minh Khoa")
    d_ag = env.db.get(Agent, doer["agent_id"]); r_ag = env.db.get(Agent, rev["agent_id"])
    p = Project(company_id=env.co.id, name="P"); env.db.add(p); env.db.commit()
    t = Task(project_id=p.id, title="Viết caption bình men lam", description="Caption Facebook cho bình men lam",
             acceptance_criteria="Dưới 150 ký tự, có lời kêu gọi mua", assignee_member_id=d_ag.member_id, status="review",
             execution_policy={"stages": [{"type": "review", "participants": [r_ag.member_id], "mode": "clean"}]},
             execution_state={"status": "in_review", "stage_index": 0, "round": 1, "reviewer_member_id": r_ag.member_id,
                              "doer_member_id": d_ag.member_id})
    env.db.add(t); env.db.commit()
    env.db.add(Artifact(organization_id=env.org.id, task_id=t.id, name="caption.txt", artifact_type="text",
                        content_text="Bình men lam thủ công — đặt ngay hôm nay!", created_by_member_id=d_ag.member_id))
    env.db.commit()
    seen = {}

    async def chat_stream(agent_id, message, *, session_key=None, timeout_seconds=90):
        seen.update(agent=agent_id, msg=message, key=session_key)
        yield {"kind": "final", "text": "Đạt cả hai tiêu chí.\nQUYẾT ĐỊNH: DUYỆT"}
    env.gw.chat_stream = chat_stream
    reviewer = env.db.get(Member, r_ag.member_id)
    out = asyncio.run(execution_policy.run_agent_review(env.db, t, reviewer, env.gw))
    assert out["decision"] == "approve" and out["mode"] == "clean"
    assert seen["agent"] == r_ag.runtime_agent_id and ":clean-review-t" in seen["key"]
    assert "đặt ngay hôm nay" in seen["msg"] and "Dưới 150 ký tự" in seen["msg"]
    env.db.refresh(t)
    assert t.status == "done" and t.execution_state["history"][-1]["via"] == "clean_review"


def test_advisor_runs_on_t4_in_its_own_session(env, monkeypatch):
    out = hire(env); ag = env.db.get(Agent, out["agent_id"]); m = env.db.get(Member, ag.member_id)
    calls = []
    base = env.gw.rpc

    async def rpc(method, params=None):
        if method in ("sessions.create", "sessions.patch"):
            calls.append((method, params)); return {"ok": True}
        return await base(method, params)

    async def chat_stream(agent_id, message, *, session_key=None, timeout_seconds=90):
        calls.append(("chat", session_key, message))
        yield {"kind": "final", "text": "Khuyên: hoàn 50% kèm voucher, không hoàn toàn bộ."}
    env.gw.rpc = rpc; env.gw.chat_stream = chat_stream
    monkeypatch.setattr("app.runtime.factory.get_runtime", lambda: env.gw)
    ctx = company_mcp.ToolContext(db=env.db, member=m, agent=ag, scopes=["company.tasks:read"])
    r = company_mcp.TOOLS["company_ask_advisor"].handler(ctx, {"question": "Khách đòi hoàn 2 triệu vì giao trễ 1 ngày?"})
    assert "voucher" in r["advice"] and r["model"].endswith("claude-sonnet-5")
    patch = next(p for mth, p in calls if mth == "sessions.patch")
    key = patch["key"]
    assert ":advisor-" in key and patch["model"].endswith("claude-sonnet-5")
    assert any(c[0] == "chat" and c[1] == key and "2 triệu" in c[2] for c in calls)
