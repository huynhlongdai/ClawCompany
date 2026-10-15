"""Phase B việc 6 — lưới quyền theo hành động, trần chi USD theo ghế, model theo loại việc."""
from datetime import datetime, timedelta

import pytest

from app.models import Member, Project, Task
from app.models.work_graph import TaskRun
from app.runtime import openclaw_protocol as ocp
from app.services import model_routing, seat_limits, seat_provision, tool_permissions as perms
from tests.test_m3_agents import env, hire  # noqa: F401  (fixture)


def seat_member(env, out) -> Member:
    env.db.expire_all()
    return env.db.get(Member, out["member_id"])


# ------------------------------------------------------------------ lưới quyền theo hành động

def test_action_classes_default_and_combine_with_tool_level(env):
    out = hire(env); m = seat_member(env, out)
    assert perms.seat_tier(env.db, m) == "executor"
    assert perms.resolve(env.db, m, "action:pay") == ("off", "default:executor")
    assert perms.resolve(env.db, m, "action:send")[0] == "ask"
    assert perms.action_of("company_task_comment") == "draft"
    assert perms.action_of("company_tasks_list") == "read"
    assert perms.resolve(env.db, m, "company_task_comment")[0] == "allowed"
    # Tắt cả loại "Ghi nội bộ" cho thừa hành → mọi tool ghi nội bộ thành off, kể cả ở gateway.
    r = env.c.put("/api/mcp/permissions", json={"tool": "action:draft", "level": "off", "role": "executor"},
                  headers=env.tok("owner"))
    assert r.status_code == 200, r.text
    assert any(t["name"] == "action:draft" and t["group"] == "action" for t in r.json()["tools"])
    level, source = perms.resolve(env.db, m, "company_task_comment")
    assert level == "off" and source.startswith("action:draft/")
    assert perms.resolve(env.db, m, "company_tasks_list")[0] == "allowed"     # đọc không bị ảnh hưởng
    deny = seat_provision.seat_deny(env.db, m, out["runtime_agent_id"], [], [])
    assert f"cc-{out['runtime_agent_id']}__company_task_comment" in deny
    # Riêng ghế này được ghi nội bộ lại: hàng theo ghế thắng hàng theo bậc.
    env.c.put("/api/mcp/permissions", json={"tool": "action:draft", "level": "allowed",
                                            "member_id": m.id}, headers=env.tok("owner"))
    assert perms.resolve(env.db, m, "company_task_comment")[0] == "allowed"
    # Hàng tool chặt hơn loại hành động thì tool thắng.
    env.c.put("/api/mcp/permissions", json={"tool": "company_task_comment", "level": "ask",
                                            "member_id": m.id}, headers=env.tok("owner"))
    assert perms.resolve(env.db, m, "company_task_comment") == ("ask", "member")


def test_seat_tools_lists_action_rows(env):
    out = hire(env)
    r = env.c.get(f"/api/agents/{out['agent_id']}/tools", headers=env.tok("member"))
    rows = {t["name"]: t for t in r.json()["tools"]}
    assert rows["action:pay"]["level"] == "off" and rows["action:pay"]["label"] == "Trả tiền"
    assert rows["company_task_comment"]["action"] == "draft"


# ------------------------------------------------------------------ trần chi USD

def _run(env, m, usd, when=None):
    p = Project(company_id=env.co.id, name="P"); env.db.add(p); env.db.commit()
    t = Task(project_id=p.id, title="Việc", status="todo", assignee_member_id=m.id)
    env.db.add(t); env.db.commit()
    env.db.add(TaskRun(organization_id=env.org.id, task_id=t.id, member_id=m.id, status="succeeded",
                       cost_usd=usd, created_at=when or datetime.utcnow()))
    env.db.commit()
    return t


def test_daily_cap_blocks_new_runs_but_ignores_yesterday(env):
    out = hire(env, daily_cap_usd=0.5); m = seat_member(env, out)
    _run(env, m, 3.0, when=datetime.utcnow() - timedelta(days=2))
    assert seat_limits.check(env.db, m) == ""
    _run(env, m, 0.6)
    why = seat_limits.check(env.db, m)
    assert "trần chi ngày" in why and "$0.60 / $0.50" in why
    from app.services import budget_scope
    assert budget_scope.gate(env.db, m, None)[0] == why
    t = _run(env, m, 0.0)
    r = env.c.post(f"/api/tasks/{t.id}/dispatch", headers=env.tok("manager"))
    assert r.status_code in (409, 422), r.text
    assert "trần chi ngày" in r.text


def test_monthly_budget_now_enforced_editable_and_versioned(env):
    out = hire(env, monthly_budget=1); aid = out["agent_id"]; m = seat_member(env, out)
    _run(env, m, 1.2)
    assert "hạn mức tháng" in seat_limits.check(env.db, m)
    lim = env.c.get(f"/api/agents/{aid}/limits", headers=env.tok("member")).json()
    assert lim["spent_month_usd"] == 1.2 and lim["blocked"] and lim["options"]["thinking_levels"][0] == "off"
    r = env.c.patch(f"/api/agents/{aid}/hr", json={"monthly_budget": 50, "daily_cap_usd": 2},
                    headers=env.tok("manager"))
    assert r.status_code == 200, r.text
    agents_md = env.gw.files[(out["runtime_agent_id"], "AGENTS.md")]
    assert "50 USD/tháng" in agents_md and "Trần chi mỗi ngày: 2 USD" in agents_md
    assert seat_limits.check(env.db, seat_member(env, out)) == ""
    v = env.c.get(f"/api/agents/{aid}/versions", headers=env.tok("member")).json()["versions"][0]
    assert set(v["changed"]) == {"monthly_budget", "daily_cap_usd"} and "trần chi ngày" in v["changed_vi"]
    # Khôi phục bản 1 → trần ngày bỏ, hạn mức tháng về 1.
    r = env.c.post(f"/api/agents/{aid}/versions/1/restore", headers=env.tok("manager"))
    assert r.status_code == 200, r.text
    st = seat_limits.state(env.db, seat_member(env, out))
    assert st["monthly_budget"] == 1 and st["daily_cap_usd"] is None and st["currency"] == "USD"
    assert env.c.patch(f"/api/agents/{aid}/hr", json={"daily_cap_usd": -1},
                       headers=env.tok("manager")).status_code == 422


# ------------------------------------------------------------------ model theo loại việc

def test_seat_policy_overrides_kind_tier_but_keeps_safety_floors():
    p = {"tiers": {"default": "T1", "planning": "T2"}, "thinking": {"default": "low", "planning": "high"}}
    d = model_routing.decide(title="Soạn bài giới thiệu", seat_policy=p)
    assert (d.kind, d.tier, d.thinking) == ("default", "T1", "low")
    d = model_routing.decide(title="Lập kế hoạch quý", seat_policy=p)
    assert (d.kind, d.tier, d.thinking) == ("planning", "T2", "high")
    d = model_routing.decide(title="Gửi email cho khách", seat_policy=p)
    assert d.tier == "T3" and d.thinking is None          # sàn an toàn; gemini không có thinking
    assert any("không có thinking" in r for r in d.reasons)
    assert model_routing.decide(title="Soạn bài", seat_policy=p, pinned_tier="T4").tier == "T4"


def test_model_policy_validated_versioned_and_feeds_router(env):
    out = hire(env, model_policy={"tiers": {"default": "T1"}}); aid = out["agent_id"]
    m = seat_member(env, out)
    assert model_routing.seat_policy(env.db, m) == {"tiers": {"default": "T1"}}
    r = env.c.patch(f"/api/agents/{aid}/hr", json={"model_policy": {
        "tiers": {"default": "T2", "decision": "T3"}, "thinking": {"default": "minimal"},
        "fallback": "gpt-5-nano"}}, headers=env.tok("manager"))
    assert r.status_code == 200, r.text
    assert any("Model dự phòng" in w for w in r.json()["warnings"])
    assert model_routing.seat_policy(env.db, seat_member(env, out))["fallback"] == "gpt-5-nano"
    assert model_routing.seat_model_config("x", fallback="gpt-5-nano")["model"]["fallbacks"] == ["custom/gpt-5-nano"]
    for bad in ({"tiers": {"default": "T9"}}, {"thinking": {"default": "max"}}, {"fallback": "gpt-2"}):
        assert env.c.patch(f"/api/agents/{aid}/hr", json={"model_policy": bad},
                           headers=env.tok("manager")).status_code == 422
    opts = env.c.get("/api/agents/hire/options", headers=env.tok("manager")).json()["model_policy_options"]
    assert [k["key"] for k in opts["kinds"]] == list(seat_limits.KINDS)


@pytest.mark.asyncio
async def test_native_run_agent_sends_thinking_level_with_model():
    from app.runtime.openclaw_native import NativeOpenClawRuntime
    rt = NativeOpenClawRuntime.__new__(NativeOpenClawRuntime)
    calls = []

    async def _rpc(method, params=None):
        calls.append((method, params))
        return {"runId": "r1"} if method == ocp.M_CHAT_SEND else {}

    rt._rpc = _rpc
    await rt.run_agent("cskh", "việc", metadata={"company_task_id": 8, "model": "custom/gpt-5-mini",
                                                "thinking": "low"}, session_key="agent:cskh:company-task-8")
    assert calls[1] == (ocp.M_SESSIONS_PATCH, {"key": "agent:cskh:company-task-8",
                                               "model": "custom/gpt-5-mini", "thinkingLevel": "low"})
