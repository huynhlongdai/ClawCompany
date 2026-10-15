"""M2e.2 — luật cứng cưỡng chế lúc chạy: CRUD + kiểm hợp lệ, cổng MCP chặn tool cấm / đòi duyệt / che dữ liệu cá nhân
khi gửi ra ngoài, vi phạm → nhật ký + Hộp việc + tỷ lệ tuân thủ của ghế, biên dịch cho guard plugin (cùng regex chạy
đúng trong JavaScript), AGENTS.md có phần Luật cứng, config.patch lên gateway. ORM thật trên SQLite, gateway giả."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from app.models import Agent, Approval, Member
from app.models.agent_native import RuleViolation
from app.models.extended import InboxItem
from app.services import runtime_rules as rr
from tests.test_m2b_company_foundation import E, mkpos  # noqa: F401  (fixture)
from tests.test_m3_agents import env, hire  # noqa: F401  (fixture)

PLUGIN = Path(__file__).resolve().parents[2] / "openclaw-plugins" / "clawcompany-guard"


def mkrule(E, role="manager", **body):
    return E.c.post("/api/team/rules", json={"company_id": E.co.id, **body}, headers=E.tok(role))


def _seat(E):
    pos = mkpos(E, title="CSKH online", department_id=E.sales.id, headcount=2)
    a = hire(E, position_id=pos["id"], role="")
    ag = E.db.get(Agent, a["agent_id"]); m = E.db.get(Member, ag.member_id)
    return pos, a, ag, m


def _mcp(E, m, name, args):
    """Gọi tools/call qua đúng endpoint MCP với API key (scope *) của seat."""
    from app.core.security import pwd_context
    from app.models import APIKey
    raw = f"cc_test_{m.id}_rules_" + "x" * 20
    E.db.add(APIKey(organization_id=E.org.id, member_id=m.id, name="k", key_prefix=raw[:12],
                    key_hash=pwd_context.hash(raw), scopes=json.dumps(["*"])))
    E.db.commit()
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": args}}
    r = E.c.post("/api/mcp", json=body, headers={"X-API-Key": raw})
    assert r.status_code == 200, r.text
    return r.json()["result"]


def test_rule_crud_validation_and_templates(E):
    pos, *_ = _seat(E)
    assert mkrule(E, role="member", name="x", kind="phrase", pattern="y").status_code == 403
    assert mkrule(E, name="x", kind="nope", pattern="y").status_code == 422
    assert mkrule(E, name="x", kind="regex", pattern="(unclosed").status_code == 422
    assert mkrule(E, name="x", kind="regex", pattern="(?i)abc").status_code == 422          # cờ nội tuyến Python
    assert mkrule(E, name="x", kind="tool", pattern="company_khong_co").status_code == 422
    assert mkrule(E, name="x", kind="tool", pattern="company_event_emit", action="scrub").status_code == 422
    assert mkrule(E, name="x", kind="pii", pattern="phone,ssn").status_code == 422
    r = mkrule(E, template="pii_external")
    assert r.status_code == 200, r.text
    assert r.json()["kind"] == "pii" and r.json()["external_only"] is True and r.json()["source"] == "template"
    r = mkrule(E, template="no_refund_promise", position_id=pos["id"], source_ref="0")
    assert r.json()["source"] == "charter" and r.json()["position"] == "CSKH online"
    E.c.put("/api/team/company-profile", json={"company_id": E.co.id, "prohibitions": ["Không hứa hoàn tiền ngoài chính sách",
                                                                                      "Không chê đối thủ"]}, headers=E.tok("owner"))
    lst = E.c.get(f"/api/team/rules?company_id={E.co.id}", headers=E.tok("member")).json()
    assert [p["enforced"] for p in lst["prohibitions"]] == [True, False]       # điều cấm #2 mới chỉ là chữ
    rid = lst["rules"][1]["id"]
    assert E.c.patch(f"/api/team/rules/{rid}", json={"enabled": False}, headers=E.tok("manager")).json()["enabled"] is False
    assert E.c.delete(f"/api/team/rules/{rid}", headers=E.tok("manager")).status_code == 200
    assert E.c.patch(f"/api/team/rules/{rid}", json={"enabled": True}, headers=E.tok("other")).status_code == 404


def test_rules_test_endpoint_matches_and_scrubs(E):
    mkrule(E, template="pii_external"); mkrule(E, template="no_refund_promise")
    r = E.c.post("/api/team/rules/test", json={"company_id": E.co.id, "text": "Em cam kết hoàn tiền 100%, gọi 0912345678",
                                               "tool": "company_event_emit"}, headers=E.tok("member")).json()
    assert {h["action"] for h in r["hits"]} == {"revise", "scrub"}
    assert "0912345678" not in r["scrubbed"] and "[đã ẩn]" in r["scrubbed"]
    assert r["tool"] is None
    internal = E.c.post("/api/team/rules/test", json={"company_id": E.co.id, "text": "gọi 0912345678", "external": False},
                        headers=E.tok("member")).json()
    assert internal["hits"] == []                        # luật PII chỉ áp khi ra ngoài


def test_mcp_gate_blocks_forbidden_tool_and_logs_violation_to_inbox(E):
    pos, a, ag, m = _seat(E)
    mkrule(E, name="Không phát sự kiện", kind="tool", pattern="company_event_emit", action="block",
           message="Không được xoá dữ liệu công ty", position_id=pos["id"])
    ok, d, _ = rr.check_mcp_call(E.db, m, "company_event_emit", {"event_type": "x"})
    assert ok == "block" and d["message"] == "Không được xoá dữ liệu công ty"
    v = E.db.query(RuleViolation).one()
    assert v.member_id == m.id and v.hook == "mcp" and v.action_taken == "block" and v.company_id == E.co.id
    item = E.db.query(InboxItem).filter(InboxItem.item_type == "rule_violation").one()
    assert item.recipient_member_id == m.manager_id and item.company_id == E.co.id
    # an unrelated seat (other position) is not bound by a position rule
    other = hire(E, name="Bé Kho", role="Kho", department_id=E.mkt.id)
    m2 = E.db.get(Member, E.db.get(Agent, other["agent_id"]).member_id)
    assert rr.check_mcp_call(E.db, m2, "company_event_emit", {"event_type": "x"})[0] == "allow"
    # second violation groups into the same inbox row (count 2), not a new card per hit
    rr.check_mcp_call(E.db, m, "company_event_emit", {"event_type": "y"})
    assert E.db.query(InboxItem).filter(InboxItem.item_type == "rule_violation").one().count == 2
    c = rr.compliance(E.db, m)
    assert c["violations"] == 2 and c["rate"] == 0.0


def test_mcp_endpoint_enforces_rules_end_to_end(E):
    pos, a, ag, m = _seat(E)
    assert _mcp(E, m, "company_context", {})["isError"] is False
    mkrule(E, name="Không phát", kind="tool", pattern="company_context", action="block", message="Không đọc ngữ cảnh")
    res = _mcp(E, m, "company_context", {})
    assert res["isError"] is True and res["structuredContent"]["error"] == "rule_blocked"
    assert "Không đọc ngữ cảnh" in res["structuredContent"]["message"]
    assert E.db.query(RuleViolation).filter(RuleViolation.hook == "mcp").count() == 1


def test_approval_rule_routes_tool_to_human_and_pii_is_scrubbed_for_external_tools(E):
    pos, a, ag, m = _seat(E)
    mkrule(E, name="Agent ngoài cần duyệt", kind="approval", pattern="company_budget_check", action="approve")
    assert rr.check_mcp_call(E.db, m, "company_budget_check", {})[0] == "approve"
    mkrule(E, template="pii_external")
    d, hit, args = rr.check_mcp_call(E.db, m, "company_delegate_external",
                                     {"external_agent_id": 1, "message": "Khách Lan 0912 345 678 muốn đổi bình"})
    assert d == "allow" and hit["action"] == "scrub"
    assert args["message"] == "Khách Lan [đã ẩn] muốn đổi bình" and args["external_agent_id"] == 1
    assert E.db.query(RuleViolation).filter(RuleViolation.action_taken == "scrub").count() == 1
    assert "0912" not in E.db.query(RuleViolation).first().excerpt          # nhật ký cũng che
    mkrule(E, name="Không chê đối thủ", kind="phrase", pattern="gốm Bát Tràng dỏm", action="block")
    d, hit, _ = rr.check_mcp_call(E.db, m, "company_delegate_external", {"external_agent_id": 1, "message": "gốm  Bát Tràng dỏm"})
    assert d == "block"


def test_plugin_report_endpoint_requires_token_and_records(E):
    pos, a, ag, m = _seat(E)
    rid = mkrule(E, template="no_refund_promise").json()["id"]
    body = {"agentId": ag.runtime_agent_id, "ruleId": rid, "hook": "before_agent_finalize", "action": "revise",
            "excerpt": "Em cam kết hoàn tiền 100% — sđt 0912345678", "sessionKey": f"agent:{ag.runtime_agent_id}:task-1",
            "runId": "run-1"}
    assert E.c.post("/api/guard/violations", json=body).status_code == 401
    assert E.c.post("/api/guard/violations", json=body, headers={"x-guard-token": "sai"}).status_code == 401
    r = E.c.post("/api/guard/violations", json=body, headers={"x-guard-token": rr.report_token()})
    assert r.status_code == 200, r.text
    v = E.db.get(RuleViolation, r.json()["id"])
    assert v.rule_id == rid and v.run_id == "run-1" and "[đã ẩn]" in v.excerpt
    assert E.c.post("/api/guard/violations", json={**body, "agentId": "khong-co"},
                    headers={"x-guard-token": rr.report_token()}).status_code == 404
    seats = E.c.get(f"/api/team/rules?company_id={E.co.id}", headers=E.tok("member")).json()["seats"]
    row = next(s for s in seats if s["member_id"] == m.id)
    assert row["violations"] == 1 and row["rules"] == 1


def test_compiled_rules_reach_agents_md_and_gateway_config(E):
    pos, a, ag, m = _seat(E)
    E.c.patch(f"/api/team/positions/{pos['id']}", json={"allowed_tools": ["company_context", "company_knowledge_search"]},
              headers=E.tok("manager"))
    mkrule(E, template="pii_external"); mkrule(E, template="no_refund_promise", position_id=pos["id"])
    md = E.gw.files[(ag.runtime_agent_id, "AGENTS.md")]      # resync chạy nền sau response
    assert "## Luật cứng" in md and "Không hứa hoàn tiền ngoài chính sách" in md and "số điện thoại" in md
    data = rr.compile_all(E.db, E.org.id)
    seat = data["agents"][ag.runtime_agent_id]
    assert seat["allowedCompanyTools"] == ["company_context", "company_knowledge_search"]
    assert {r["kind"] for r in seat["rules"]} == {"pii", "regex"} and all(r["regex"] for r in seat["rules"])
    patched = {}

    class Reg:
        def __init__(self, runtime): pass
        async def snapshot(self): return {"hash": "h1", "config": {}}
        async def patch(self, values, **kw): patched.update(values); patched["_kw"] = kw

    import asyncio
    import app.services.openclaw_config as oc
    orig = oc.ConfigRegistry
    oc.ConfigRegistry = Reg
    try:
        from app.services import agent_hr
        real = agent_hr._has_rpc
        agent_hr._has_rpc = lambda rt: True
        out = asyncio.run(rr.push(E.db, object()))
    finally:
        oc.ConfigRegistry = orig; agent_hr._has_rpc = real
    assert out["pushed"] is True and out["agents"] >= 1
    raw = patched[rr.PLUGIN_CFG + ("rulesJson",)]
    assert json.loads(raw)["agents"][ag.runtime_agent_id]["seat"] == m.id
    assert patched[rr.PLUGIN_CFG + ("reportToken",)] == rr.report_token()
    assert patched[rr.PLUGIN_CFG + ("reportUrl",)].endswith("/api/guard/violations")
    assert patched["_kw"]["base_hash"] == "h1"


@pytest.mark.skipif(shutil.which("node") is None, reason="cần node để chạy lõi plugin")
def test_python_compiled_regex_behaves_the_same_in_the_javascript_plugin(E, tmp_path):
    """Luật biên dịch phía Python phải chạy đúng y hệt trong plugin JS (cờ iu): cùng câu → cùng luật bắt."""
    pos, a, ag, m = _seat(E)
    mkrule(E, template="pii_external"); mkrule(E, template="no_refund_promise")
    mkrule(E, name="Không chê", kind="phrase", pattern="gốm Bát-Tràng dỏm # rẻ", action="block")
    data = rr.compile_all(E.db, E.org.id)
    cases = ["Em cam kết hoàn tiền 100% nhé", "gọi 0912 345 678 hoặc lan@gmail.com", "gốm   Bát-Tràng dỏm # rẻ quá",
             "Dạ em báo quản lý duyệt theo chính sách"]
    py = [[h["rule_id"] for h in rr.check_text(rr.rules_for(E.db, m), c, external=True)] for c in cases]
    script = tmp_path / "x.mjs"
    script.write_text(
        f'import {{parseRules, checkText}} from "{(PLUGIN / "rules.mjs").as_posix()}";\n'
        f'const R = parseRules({json.dumps(json.dumps(data, ensure_ascii=False), ensure_ascii=False)});\n'
        f'const S = R.agents[{json.dumps(ag.runtime_agent_id)}];\n'
        f'console.log(JSON.stringify({json.dumps(cases, ensure_ascii=False)}.map(c => checkText(S, c, true).map(h => h.ruleId))));\n')
    out = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout) == py
    assert py[0] and py[1] and py[2] and py[3] == []
