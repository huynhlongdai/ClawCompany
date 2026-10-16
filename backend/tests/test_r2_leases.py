"""R2 — cho thuê agent (seat_leases). Spec: docs/r-rental-and-multi-company.md §R2.

Bên cho thuê = tổ chức Nova (E.org / E.co) có ghế CSKH; bên thuê = tổ chức khác "Renter" có công ty + chức danh riêng.
Kiểm hành vi qua API thật + ORM SQLite + gateway giả: chào thuê → nhận lời (ghế mới ở bên thuê), AGENTS.md sàn đứng
trước lớp bên thuê, phạm vi tri thức, luật cứng + công cụ = giao hai bên, cổng công cụ trên cả quyền riêng của ghế,
bên thuê không nới được, đo đếm chi phí thật × (1+markup) + phí việc/giờ, trần → tạm dừng + Hộp việc hai bên, yêu cầu
thay đổi, đo phiên A2A (sessions.usage), tick hết hạn dọn ghế nhưng giữ dòng đo đếm, bên cho thuê không thấy dữ liệu
ghế của bên thuê."""
import asyncio
import json
from datetime import datetime, timedelta

import pytest

from app.core.security import create_access_token, hash_password, pwd_context
from app.models import (Agent, APIKey, Company, Department, KnowledgeDocument, Member, Organization, Project, Task,
                        User, UserOrganizationAccess)
from app.models.agent_hr import AgentFileSnapshot
from app.models.extended import InboxItem
from app.models.leases import LeaseUsage, SeatLease
from app.services import cost_ledger, knowledge_hub, runtime_rules, seat_leases, task_lifecycle, tool_permissions
from tests.test_m2b_company_foundation import E, mkpos  # noqa: F401  (fixture)
from tests.test_m3_agents import FakeGateway, env, hire  # noqa: F401  (fixture)

PROHIBITION = "Không hứa hoàn tiền ngoài chính sách"


def ok(r, what=""):
    assert r.status_code == 200, (what, r.status_code, r.text[:400])
    return r.json()


class UsageGateway(FakeGateway):
    """Gateway giả có sessions.usage (tổng chi phí theo phiên) và chat_stream (trả lời A2A)."""
    session_cost: dict

    async def rpc(self, method, params=None):
        if method == "sessions.usage":
            key = (params or {}).get("key")
            c = self.session_cost.get(key)
            sess = [] if c is None else [{"key": key, "usage": {"input": 300, "output": 120, "totalCost": c,
                                                                 "messageCounts": {"assistant": 1}}}]
            return {"sessions": sess, "cacheStatus": {"status": "fresh"}}
        return await super().rpc(method, params)

    async def chat_stream(self, agent_id, message, *, session_key=None, timeout_seconds=90):
        self.session_cost[session_key] = round(self.session_cost.get(session_key, 0.0) + 0.05, 6)
        yield {"kind": "final", "text": "Dạ em kiểm tra đơn cho anh/chị ngay ạ."}


@pytest.fixture()
def L(E, monkeypatch):
    X = E
    monkeypatch.setattr("app.api.leases.get_runtime", lambda: X.gw)
    X.gw.__class__ = UsageGateway
    X.gw.session_cost = {}
    # --- bên cho thuê: hiến chương có điều cấm, chức danh CSKH giới hạn công cụ, luật cứng, ghế nguồn, 2 tài liệu
    ok(X.c.put("/api/team/company-profile", json={"company_id": X.co.id, "prohibitions": [PROHIBITION]},
               headers=X.tok("owner")), "charter")
    ppos = mkpos(X, title="CSKH Nova", department_id=X.sales.id, headcount=2,
                 allowed_tools=["company_context", "company_knowledge_search", "company_knowledge_get",
                                "company_budget_check"])
    src = hire(X, name="Thu Trang", position_id=ppos["id"], role="")
    ok(X.c.post("/api/team/rules", json={"company_id": X.co.id, "name": "Sàn: không phát sự kiện", "kind": "tool",
                                         "pattern": "company_event_emit", "action": "block",
                                         "message": "Agent CSKH không phát sự kiện"}, headers=X.tok("manager")), "rule")
    d_in = ok(X.c.post("/api/learning/docs", json={"title": "Chính sách đổi trả Nova", "scope": "company",
                                                   "company_id": X.co.id,
                                                   "content": "SCOPE-DOC đổi trả trong 7 ngày, giữ hoá đơn."},
                       headers=X.tok("manager")), "doc-in")
    d_out = ok(X.c.post("/api/learning/docs", json={"title": "Bảng giá nhập nội bộ", "scope": "company",
                                                    "company_id": X.co.id, "content": "SECRET-DOC giá nhập 12k."},
                        headers=X.tok("manager")), "doc-out")
    X.doc_in = d_in.get("id") or d_in.get("doc", {}).get("id")
    X.doc_out = d_out.get("id") or d_out.get("doc", {}).get("id")
    X.src, X.ppos = src, ppos
    # --- bên thuê: tổ chức khác, công ty + phòng + chức danh rộng hơn sàn
    ro = Organization(name="Renter Org", slug="renter-r2"); X.db.add(ro); X.db.commit()
    rco = Company(organization_id=ro.id, name="Renter Shop", status="active"); X.db.add(rco); X.db.commit()
    rd = Department(company_id=rco.id, name="CSKH thuê", access_level="restricted"); X.db.add(rd); X.db.commit()
    boss = Member(organization_id=ro.id, company_id=rco.id, name="Chủ thuê", member_type="human", role="CEO")
    X.db.add(boss); X.db.commit()
    ru = User(email="owner@renter.test", password_hash=hash_password("Matkhau123"), member_id=boss.id)
    X.db.add(ru); X.db.commit()
    X.db.add(UserOrganizationAccess(user_id=ru.id, organization_id=ro.id, role="owner", is_default=True,
                                    status="active"))
    X.db.commit()
    X.tR = {"Authorization": "Bearer " + create_access_token(ru.id, ro.id, "owner")}
    X.ro, X.rco, X.rd = ro, rco, rd
    rpos = ok(X.c.post("/api/team/positions", json={"company_id": rco.id, "title": "CSKH thuê", "department_id": rd.id,
                                                    "headcount": 2,
                                                    "allowed_tools": ["company_context", "company_knowledge_search",
                                                                      "company_event_emit", "company_knowledge_get"]},
                       headers=X.tR), "rpos")
    X.rpos = rpos
    return X


def offer(X, **kw):
    body = {"provider_agent_id": X.src["agent_id"], "markup_pct": 20, "price_per_task_usd": 0.5,
            "price_per_hour_usd": 2.0, "monthly_cost_cap_usd": 10, "knowledge_doc_ids": [X.doc_in],
            "data_handling": "Xoá hội thoại khách sau 30 ngày.",
            "ends_at": (datetime.utcnow() + timedelta(days=30)).isoformat()}
    body.update(kw)
    return ok(X.c.post("/api/leases", json=body, headers=X.tok("owner")), "offer")


def accept(X, code):
    return ok(X.c.post("/api/leases/accept", json={"offer_code": code, "company_id": X.rco.id,
                                                   "position_id": X.rpos["id"]}, headers=X.tR), "accept")


def leased(X, **kw):
    o = offer(X, **kw)
    a = accept(X, o["offer_code"])
    ls = X.db.get(SeatLease, o["id"]); X.db.refresh(ls)
    ag = X.db.get(Agent, ls.renter_agent_id); m = X.db.get(Member, ls.renter_member_id)
    return o, a, ls, ag, m


def _frame(mid, cost, key):
    return {"messageId": mid, "sessionKey": key,
            "message": {"role": "assistant", "model": "gpt-4.1-mini", "provider": "comet",
                        "usage": {"input": 1000, "output": 200, "cacheRead": 0, "cacheWrite": 0, "cost": {"total": cost}}}}


def _mcp(X, m, org_id, name, args, status=200):
    raw = f"cc_test_{m.id}_lease_" + "x" * 20
    X.db.add(APIKey(organization_id=org_id, member_id=m.id, name="k", key_prefix=raw[:12],
                    key_hash=pwd_context.hash(raw), scopes=json.dumps(["*"])))
    X.db.commit()
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": args}}
    r = X.c.post("/api/mcp", json=body, headers={"X-API-Key": raw})
    assert r.status_code == status, r.text
    return r.json().get("result") or r.json()


# ------------------------------------------------------------------ 1. chào thuê → nhận lời

def test_offer_accept_hires_a_new_seat_in_the_renter_company(L):
    X = L
    o = offer(X)
    assert o["status"] == "draft" and o["side"] == "provider" and o["offer_code"]
    pv = ok(X.c.get(f"/api/leases/offer/{o['offer_code']}", headers=X.tR), "preview")
    assert pv["agent_name"] == "Thu Trang" and "20%" in pv["terms"] and pv["approval_policy"]["payer"] == "renter"
    # chính tổ chức cho thuê không tự nhận
    r = X.c.post("/api/leases/accept", json={"offer_code": o["offer_code"], "company_id": X.co.id,
                                             "position_id": X.ppos["id"]}, headers=X.tok("owner"))
    assert r.status_code == 422
    a = accept(X, o["offer_code"])
    assert a["status"] == "active" and a["side"] == "renter" and a["renter"]["company"] == "Renter Shop"
    ls = X.db.get(SeatLease, o["id"]); X.db.refresh(ls)
    m = X.db.get(Member, ls.renter_member_id)
    assert m.organization_id == X.ro.id and m.company_id == X.rco.id and m.position_id == X.rpos["id"]
    assert ls.renter_agent_id != X.src["agent_id"] and ls.provider_member_id != m.id
    # mã chỉ dùng một lần
    assert X.c.post("/api/leases/accept", json={"offer_code": o["offer_code"], "company_id": X.rco.id,
                                                "position_id": X.rpos["id"]}, headers=X.tR).status_code == 404
    # không cho thuê lại một ghế đi thuê
    r = X.c.post("/api/leases", json={"provider_agent_id": ls.renter_agent_id}, headers=X.tR)
    assert r.status_code == 422
    # Hộp việc hai bên có thẻ bắt đầu
    orgs = {i.organization_id for i in X.db.query(InboxItem).filter(InboxItem.related_type == "seat_lease").all()}
    assert orgs == {X.org.id, X.ro.id}


# ------------------------------------------------------------------ 2. AGENTS.md: sàn trước lớp bên thuê

def test_agents_md_puts_provider_floor_before_renter_layer(L):
    X = L
    ok(X.c.put("/api/team/company-profile", json={"company_id": X.rco.id, "prohibitions": ["RENTER-RULE không chửi khách"]},
               headers=X.tR), "renter-charter")
    o, a, ls, ag, m = leased(X)
    md = X.gw.files[(ag.runtime_agent_id, "AGENTS.md")]
    floor_at = md.index(seat_leases.FLOOR_HEADING)
    assert PROHIBITION in md and "Sàn: không phát sự kiện" in md
    # sàn đứng ngay sau tiêu đề, trước cả vai trò/nhiệm vụ do bên thuê đặt
    assert floor_at < md.index("## Lớp của bên thuê") < md.index("## Vai trò")
    # danh sách công cụ của chức danh trong file là công cụ hiệu lực (sàn ∩ chức danh bên thuê)
    tools_line = next(x for x in md.splitlines() if x.startswith("- Công cụ công ty được dùng:"))
    assert "company_event_emit" not in tools_line and "company_budget_check" not in tools_line
    assert "Xoá hội thoại khách sau 30 ngày." in md
    assert "SCOPE-DOC" in md and "SECRET-DOC" not in md
    assert "## Lớp của bên thuê" in md
    assert floor_at < md.index("## Lớp của bên thuê") < md.index("RENTER-RULE không chửi khách")
    # bên thuê ghi AGENTS.md bỏ mục sàn → 422; giữ nguyên sàn + thêm dòng → được
    r = X.c.put(f"/api/agents/{ag.id}/files/AGENTS.md", json={"content": "# chỉ lớp bên thuê"}, headers=X.tR)
    assert r.status_code == 422 and "Sàn của bên cho thuê" in r.text
    floor = seat_leases.floor_section(X.db, ls)
    r = X.c.put(f"/api/agents/{ag.id}/files/AGENTS.md", json={"content": floor + "\n\n- Chào khách bằng tên shop."},
                headers=X.tR)
    assert r.status_code != 422, r.text


# ------------------------------------------------------------------ 3. phạm vi tri thức

def test_knowledge_scope_exposes_only_granted_provider_docs(L):
    X = L
    o, a, ls, ag, m = leased(X)
    ids = {d.id for d in knowledge_hub.visible_docs_query(X.db, X.ro.id, m, ag).all()}
    assert X.doc_in in ids and X.doc_out not in ids
    got = _mcp(X, m, X.ro.id, "company_knowledge_get", {"document_id": X.doc_in})
    assert got["isError"] is False and "SCOPE-DOC" in json.dumps(got, ensure_ascii=False)
    got = _mcp(X, m, X.ro.id, "company_knowledge_get", {"document_id": X.doc_out})
    assert "SECRET-DOC" not in json.dumps(got, ensure_ascii=False)
    # ghế thường của bên thuê không thấy tài liệu bên cho thuê
    other = ok(X.c.post("/api/agents/hire", json={"name": "Ghế riêng", "company_id": X.rco.id,
                                                  "department_id": X.rd.id}, headers=X.tR), "own-hire")
    om = X.db.get(Member, X.db.get(Agent, other["agent_id"]).member_id)
    ids2 = {d.id for d in knowledge_hub.visible_docs_query(X.db, X.ro.id, om, X.db.get(Agent, other["agent_id"])).all()}
    assert X.doc_in not in ids2
    # hợp đồng tạm dừng → mất phạm vi
    ok(X.c.post(f"/api/leases/{ls.id}/status", json={"action": "suspend"}, headers=X.tok("owner")), "suspend")
    X.db.expire_all()
    assert X.doc_in not in {d.id for d in knowledge_hub.visible_docs_query(X.db, X.ro.id, m, ag).all()}


# ------------------------------------------------------------------ 4. luật cứng + công cụ = giao hai bên

def test_guard_rules_and_tool_allowlist_intersect(L):
    X = L
    ok(X.c.post("/api/team/rules", json={"company_id": X.rco.id, "name": "Bên thuê: che sđt", "template": "pii_external"},
                headers=X.tR), "renter-rule")
    o, a, ls, ag, m = leased(X)
    c = runtime_rules.compile_agent(X.db, m, ag)
    names = [r["name"] for r in c["rules"]]
    assert names.index("Sàn: không phát sự kiện") < names.index("Bên thuê: che sđt")
    assert c["lease"] == ls.id
    # sàn (chức danh nguồn) ∩ chức danh bên thuê: event_emit (bên thuê cho) và budget_check (chỉ sàn) đều không có
    tools = set(c["allowedCompanyTools"]) - set(tool_permissions.ALWAYS_ALLOWED)
    assert tools == {"company_context", "company_knowledge_search", "company_knowledge_get"}
    # cổng MCP: luật sàn chặn dù bên thuê cho chức danh dùng
    d, hit, _ = runtime_rules.check_mcp_call(X.db, m, "company_event_emit", {"event_type": "x"})
    floor_id = next(r["id"] for r in seat_leases.provider_rules(X.db, ls))
    assert d == "block" and hit["rule_id"] == floor_id and hit["message"] == "Agent CSKH không phát sự kiện"
    # cấu hình guard plugin của ghế mang cả hai lớp
    seat = runtime_rules.compile_all(X.db, X.ro.id)["agents"][ag.runtime_agent_id]
    assert {"Sàn: không phát sự kiện", "Bên thuê: che sđt"} <= {r["name"] for r in seat["rules"]}


# ------------------------------------------------------------------ 5. cổng công cụ trên quyền riêng của ghế

def test_lease_tool_gate_overrides_member_permissions(L):
    X = L
    o, a, ls, ag, m = leased(X, allowed_tools=["company_context", "company_knowledge_search"])
    from app.models import ToolPermission
    X.db.add(ToolPermission(organization_id=X.ro.id, member_id=m.id, tool="company_budget_check", level="auto"))
    X.db.commit()
    level, source = tool_permissions.resolve(X.db, m, "company_budget_check")
    assert level == "off" and source == f"lease:{ls.id}"
    assert tool_permissions.resolve(X.db, m, "company_context")[0] != "off"
    res = _mcp(X, m, X.ro.id, "company_budget_check", {}, status=403)
    assert res["error"]["data"]["source"] == f"lease:{ls.id}"
    # tạm dừng → mọi công cụ công ty tắt
    ok(X.c.post(f"/api/leases/{ls.id}/status", json={"action": "suspend"}, headers=X.tok("owner")), "suspend")
    X.db.expire_all()
    assert tool_permissions.resolve(X.db, m, "company_context") == ("off", f"lease:{ls.id}:suspended")


# ------------------------------------------------------------------ 6. bên thuê không nới được

def test_renter_cannot_loosen_the_floor(L):
    X = L
    o, a, ls, ag, m = leased(X)
    floor_rule = next(r for r in seat_leases.provider_rules(X.db, ls))
    # luật sàn nằm ở công ty bên cho thuê: bên thuê không sửa / tắt / xoá được
    assert X.c.patch(f"/api/team/rules/{floor_rule['id']}",
                     json={"enabled": False}, headers=X.tR).status_code in (403, 404)
    assert X.c.delete(f"/api/team/rules/{floor_rule['id']}",
                      headers=X.tR).status_code in (403, 404)
    # đổi model / cấu hình nền tảng → 403 (bên cho thuê duyệt)
    r = X.c.patch(f"/api/agents/{ag.id}/hr", json={"model": "comet/gpt-5"}, headers=X.tR)
    assert r.status_code == 403 and "bên cho thuê" in r.text
    r = X.c.patch(f"/api/agents/{ag.id}/config", json={"tab": "permission", "values": {}}, headers=X.tR)
    assert r.status_code == 403
    # hạn mức ghế vượt trần hợp đồng → 422; siết thì được
    r = X.c.patch(f"/api/agents/{ag.id}/hr", json={"monthly_budget": 50}, headers=X.tR)
    assert r.status_code == 422 and "trần hợp đồng" in r.text
    assert X.c.patch(f"/api/agents/{ag.id}/hr", json={"monthly_budget": 5}, headers=X.tR).status_code == 200
    # điều khoản: chỉ bên cho thuê sửa; bên thuê không duyệt / tự tiếp tục
    assert X.c.patch(f"/api/leases/{ls.id}", json={"monthly_cost_cap_usd": 999}, headers=X.tR).status_code == 403
    assert X.c.post(f"/api/leases/{ls.id}/status", json={"action": "suspend"}, headers=X.tR).status_code == 409
    # giá không đổi sau khi chạy
    assert X.c.patch(f"/api/leases/{ls.id}", json={"markup_pct": 0}, headers=X.tok("owner")).status_code == 422
    # chính sách duyệt không hỗ trợ đảo vai
    r = X.c.post("/api/leases", json={"provider_agent_id": X.src["agent_id"], "approval_policy": {"policy": "renter"}},
                 headers=X.tok("owner"))
    assert r.status_code == 422


# ------------------------------------------------------------------ 7. đo đếm

def _task_run(X, m, minutes=30):
    p = Project(company_id=X.rco.id, name="P thuê"); X.db.add(p); X.db.commit()
    t = Task(project_id=p.id, title="Trả lời khách", assignee_member_id=m.id, status="in_progress")
    X.db.add(t); X.db.commit()
    run = task_lifecycle.open_run(X.db, t, organization_id=X.ro.id, member_id=m.id)
    run.status = "running"; run.started_at = datetime.utcnow() - timedelta(minutes=minutes)
    X.db.add(run); X.db.commit()
    return t, run


def test_metering_real_cost_times_markup_plus_task_and_hour_fees(L):
    X = L
    o, a, ls, ag, m = leased(X, monthly_cost_cap_usd=None)
    t, run = _task_run(X, m, minutes=30)
    ev = cost_ledger.record_message_usage(X.db, organization_id=X.ro.id, task=t, agent_id=ag.id,
                                          session_key=f"agent:{ag.runtime_agent_id}:task-{t.id}",
                                          raw=_frame("msg-1", 0.10, "k"), run=run)
    assert ev is not None
    row = X.db.query(LeaseUsage).filter_by(lease_id=ls.id, kind="model").one()
    assert row.cost_usd == pytest.approx(0.10) and row.billed_usd == pytest.approx(0.12)
    assert row.tokens_in == 1000 and row.tokens_out == 200 and row.task_run_id == run.id and row.channel == "task"
    # cùng messageId không tính hai lần
    cost_ledger.record_message_usage(X.db, organization_id=X.ro.id, task=t, agent_id=ag.id, session_key="k",
                                     raw=_frame("msg-1", 0.10, "k"), run=run)
    assert X.db.query(LeaseUsage).filter_by(lease_id=ls.id, kind="model").count() == 1
    task_lifecycle.finish_run(X.db, run, "succeeded")
    fees = {r.kind: r for r in X.db.query(LeaseUsage).filter_by(lease_id=ls.id).all()}
    assert fees["task_fee"].billed_usd == pytest.approx(0.5)
    assert fees["hour_fee"].quantity == pytest.approx(0.5, abs=0.01)
    assert fees["hour_fee"].billed_usd == pytest.approx(1.0, abs=0.02)
    X.db.refresh(run)
    assert run.lease_id == ls.id and run.billed_usd == pytest.approx(0.12 + 0.5 + fees["hour_fee"].billed_usd)
    # lượt chạy kết thúc lại / sự kiện muộn → không thu phí hai lần
    seat_leases.on_run_end(X.db, run)
    assert X.db.query(LeaseUsage).filter_by(lease_id=ls.id, kind="task_fee").count() == 1
    v = ok(X.c.get(f"/api/leases/{ls.id}", headers=X.tok("owner")))
    assert v["usage"]["cost_usd"] == pytest.approx(0.10) and v["usage"]["margin_usd"] == pytest.approx(
        v["usage"]["billed_usd"] - 0.10)
    # ghế không thuê thì không có dòng đo đếm
    own = hire(X, name="Ghế thường")
    cost_ledger.record_message_usage(X.db, organization_id=X.org.id, task=None, agent_id=own["agent_id"],
                                     session_key="x", raw=_frame("msg-own", 1.0, "x"))
    assert X.db.query(LeaseUsage).count() == 3


# ------------------------------------------------------------------ 8. trần → tạm dừng + Hộp việc hai bên

def test_cap_suspends_and_notifies_both_sides(L):
    X = L
    o, a, ls, ag, m = leased(X, monthly_cost_cap_usd=1.0, markup_pct=0)
    from app.services import seat_limits
    assert seat_limits.check(X.db, m) == ""
    cost_ledger.record_message_usage(X.db, organization_id=X.ro.id, task=None, agent_id=ag.id, session_key="s",
                                     raw=_frame("m-a", 0.6, "s"))
    X.db.refresh(ls); assert ls.status == "active"
    cost_ledger.record_message_usage(X.db, organization_id=X.ro.id, task=None, agent_id=ag.id, session_key="s",
                                     raw=_frame("m-b", 0.6, "s"))
    X.db.refresh(ls)
    assert ls.status == "suspended" and "Chạm trần" in ls.status_reason
    assert "tạm dừng" in seat_limits.check(X.db, m)
    cards = X.db.query(InboxItem).filter(InboxItem.item_type == "budget_exhausted",
                                         InboxItem.related_type == "seat_lease").all()
    assert {c.organization_id for c in cards} == {X.org.id, X.ro.id}
    # tiếp tục khi vẫn chạm trần → 409; nâng trần rồi tiếp tục → chạy
    assert X.c.post(f"/api/leases/{ls.id}/status", json={"action": "resume"}, headers=X.tok("owner")).status_code == 409
    ok(X.c.patch(f"/api/leases/{ls.id}", json={"monthly_cost_cap_usd": 5}, headers=X.tok("owner")))
    ok(X.c.post(f"/api/leases/{ls.id}/status", json={"action": "resume"}, headers=X.tok("owner")))
    X.db.expire_all()
    assert seat_limits.check(X.db, m) == ""


# ------------------------------------------------------------------ 9. yêu cầu thay đổi

def test_change_request_flow(L):
    X = L
    o, a, ls, ag, m = leased(X)
    r = X.c.post(f"/api/leases/{ls.id}/change-requests", json={"changes": {"markup_pct": 0}}, headers=X.tR)
    assert r.status_code == 422           # giá không phải thứ bên thuê xin đổi
    cr = ok(X.c.post(f"/api/leases/{ls.id}/change-requests",
                     json={"changes": {"monthly_cost_cap_usd": 25}, "note": "mùa sale"}, headers=X.tR))
    assert cr["status"] == "pending"
    assert X.db.query(InboxItem).filter(InboxItem.item_type == "approval_pending", InboxItem.organization_id == X.org.id,
                                        InboxItem.related_type == "seat_lease").count() == 1
    assert X.c.post(f"/api/leases/{ls.id}/change-requests", json={"changes": {"ends_at": None}},
                    headers=X.tok("owner")).status_code == 403
    assert X.c.post(f"/api/leases/{ls.id}/change-requests/{cr['id']}/decide", json={"decision": "approved"},
                    headers=X.tR).status_code == 403
    ok(X.c.post(f"/api/leases/{ls.id}/change-requests/{cr['id']}/decide", json={"decision": "approved"},
                headers=X.tok("owner")))
    X.db.refresh(ls)
    assert ls.monthly_cost_cap_usd == 25 and ls.change_requests[0]["status"] == "approved"
    cr2 = ok(X.c.post(f"/api/leases/{ls.id}/change-requests", json={"changes": {"allowed_tools": ["company_context"]}},
                      headers=X.tR))
    ok(X.c.post(f"/api/leases/{ls.id}/change-requests/{cr2['id']}/decide", json={"decision": "rejected"},
                headers=X.tok("owner")))
    X.db.refresh(ls)
    assert ls.allowed_tools is None and ls.change_requests[1]["status"] == "rejected"
    assert X.c.post(f"/api/leases/{ls.id}/change-requests/{cr2['id']}/decide", json={"decision": "approved"},
                    headers=X.tok("owner")).status_code == 404


# ------------------------------------------------------------------ 10. đo phiên A2A

def test_a2a_calls_to_a_leased_seat_are_metered_from_gateway_usage(L, monkeypatch):
    X = L
    o, a, ls, ag, m = leased(X, monthly_cost_cap_usd=None, markup_pct=50)
    monkeypatch.setattr("app.api.a2a.get_runtime", lambda: X.gw)
    x = ok(X.c.post(f"/api/a2a/expose/{ag.id}", json={"enabled": True}, headers=X.tR), "expose")
    body = {"jsonrpc": "2.0", "id": 1, "method": "message/send",
            "params": {"message": {"role": "user", "contextId": "c1", "parts": [{"kind": "text", "text": "Đơn 12?"}]}}}
    for _ in range(2):
        r = X.c.post(f"/api/a2a/agents/{ag.runtime_agent_id}", json=body,
                     headers={"Authorization": f"Bearer {x['token']}"}).json()
        assert "result" in r, r
    rows = X.db.query(LeaseUsage).filter_by(lease_id=ls.id, kind="model", channel="a2a").order_by(LeaseUsage.id).all()
    # phiên tích luỹ 0.05 rồi 0.10 → hai dòng chênh lệch 0.05, tính 0.075 mỗi dòng
    assert [round(r_.cost_usd, 6) for r_ in rows] == [0.05, 0.05]
    assert all(r_.billed_usd == pytest.approx(0.075) for r_ in rows)
    assert rows[0].caller.startswith("a2a:exposure:") and rows[0].session_key.endswith("a2a-c1")
    # hợp đồng tạm dừng → A2A bị từ chối trước khi gọi model
    ok(X.c.post(f"/api/leases/{ls.id}/status", json={"action": "suspend"}, headers=X.tok("owner")))
    r = X.c.post(f"/api/a2a/agents/{ag.runtime_agent_id}", json=body,
                 headers={"Authorization": f"Bearer {x['token']}"}).json()
    assert r["error"]["code"] == -32003


# ------------------------------------------------------------------ 11. hết hạn → dọn ghế, giữ đo đếm

def test_expiry_tick_wipes_leased_workspace_but_keeps_usage(L):
    X = L
    o, a, ls, ag, m = leased(X, monthly_cost_cap_usd=None)
    rid = ag.runtime_agent_id
    cost_ledger.record_message_usage(X.db, organization_id=X.ro.id, task=None, agent_id=ag.id, session_key="s",
                                     raw=_frame("m-x", 0.2, "s"))
    X.db.add(KnowledgeDocument(organization_id=X.ro.id, company_id=X.rco.id, agent_id=ag.id, title="Ghi chú riêng ghế",
                               content="khách VIP", source_type="text"))
    X.db.commit()
    assert rid in X.gw.agents and X.db.query(AgentFileSnapshot).filter_by(agent_id=ag.id).count() > 0
    later = (ls.ends_at + timedelta(minutes=1)).isoformat()
    out = ok(X.c.post("/api/leases/tick", json={"now": later}, headers=X.tok("owner")))["results"]
    mine = next(r for r in out if r.get("lease_id") == ls.id)
    assert mine["status"] == "ended"
    X.db.expire_all()
    ls = X.db.get(SeatLease, ls.id)
    assert ls.status == "ended" and ls.wiped_at is not None
    assert rid not in X.gw.agents and not [k for k in X.gw.files if k[0] == rid]
    assert X.db.query(AgentFileSnapshot).filter_by(agent_id=ag.id).count() == 0
    assert X.db.query(KnowledgeDocument).filter_by(agent_id=ag.id).count() == 0
    assert X.db.get(Agent, ag.id).lifecycle == "retired"
    assert X.db.query(LeaseUsage).filter_by(lease_id=ls.id).count() == 1 and ls.wipe_report["usage_rows_kept"] == 1
    from app.services import seat_limits
    assert "kết thúc" in seat_limits.check(X.db, X.db.get(Member, m.id))
    # chào thuê quá hạn chưa ai nhận → ended
    o2 = offer(X, offer_expires_at=(datetime.utcnow() + timedelta(hours=1)).isoformat())
    asyncio.run(seat_leases.tick(X.db, X.gw, now=datetime.utcnow() + timedelta(hours=2)))
    X.db.expire_all()
    assert X.db.get(SeatLease, o2["id"]).status == "ended"


# ------------------------------------------------------------------ 12. bên cho thuê không thấy dữ liệu ghế bên thuê

def test_provider_cannot_see_renter_seat_data(L):
    X = L
    o, a, ls, ag, m = leased(X)
    v = ok(X.c.get(f"/api/leases/{ls.id}", headers=X.tok("owner")))
    assert "agent_id" not in v["renter"] and "member_id" not in v["renter"] and "block_reason" not in v
    lst = ok(X.c.get("/api/leases?side=provider", headers=X.tok("owner")))
    assert lst["items"][0]["id"] == ls.id and str(ag.runtime_agent_id) not in json.dumps(lst, default=str)
    for path in (f"/api/agents/{ag.id}/profile", f"/api/agents/{ag.id}/memory", f"/api/agents/{ag.id}/drift", f"/api/agents/{ag.id}/limits"):
        r = X.c.get(path, headers=X.tok("owner"))
        assert r.status_code in (403, 404), (path, r.status_code)
    # bên thuê thấy ghế của mình, tổ chức thứ ba không thấy hợp đồng
    assert ok(X.c.get(f"/api/leases/{ls.id}", headers=X.tR))["renter"]["agent_id"] == ag.id
    assert X.c.get(f"/api/leases/{ls.id}", headers=X.tok("other")).status_code == 404
    assert ok(X.c.get("/api/leases?side=renter", headers=X.tok("owner")))["items"] == []
    assert len(ok(X.c.get(f"/api/leases?side=renter&company_id={X.rco.id}", headers=X.tR))["items"]) == 1
    assert ok(X.c.get(f"/api/leases?side=renter&company_id={X.co.id}", headers=X.tR))["items"] == []
