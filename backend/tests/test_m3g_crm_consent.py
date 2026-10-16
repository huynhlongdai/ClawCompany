"""M3g (P1) — khách hàng & đồng ý DLCN (Luật 91/2025, NĐ 356/2025): đồng ý cần bằng chứng, rút đồng ý → hệ thống chặn marketing
(người và agent), PII che theo vai trò, agent chỉ thấy liên hệ của phòng mình + đã đồng ý, yêu cầu của chủ thể dữ liệu có hạn
(02 ngày làm việc / 10–15–20 ngày) thành việc + Hộp việc, xoá chạy hết quy trình và để lại bằng chứng. ORM thật trên SQLite."""
from datetime import datetime, timedelta

from app.models import Agent, InboxItem, Member, Task
from app.models.crm import CrmConsent, CrmContact, CrmInteraction
from app.services import company_mcp, crm
from tests.test_m2b_company_foundation import E  # noqa: F401  (fixture)
from tests.test_m3_agents import env, hire  # noqa: F401  (fixture)
from tests.test_m3a_document_library import _seats


def mkc(E, role="manager", **body):
    return E.c.post("/api/team/crm/contacts", json={"company_id": E.co.id, **body}, headers=E.tok(role))


def consent(E, cid, role="manager", **body):
    return E.c.post(f"/api/team/crm/contacts/{cid}/consents", json=body, headers=E.tok(role))


def test_consent_needs_evidence_withdraw_blocks_marketing_and_pii_masked_by_role(E):
    _seats(E)
    r = mkc(E, name="Nguyễn Thị Mai", phone="0912345678", email="mai.nguyen@example.com", address="12 Lê Lợi, Q1, TP.HCM",
            department_id=E.sales.id, tags=["khách sỉ"])
    assert r.status_code == 200, r.text
    c = r.json()
    assert c["phone"] == "0912345678" and c["pii_masked"] is False          # quản lý (org manager) thấy đủ
    assert mkc(E, role="member", name="x").status_code == 403                # thành viên không tạo
    # im lặng ≠ đồng ý: không bằng chứng → 422 có mã
    r = consent(E, c["id"], purpose="marketing", channel="zalo")
    assert r.status_code == 422 and r.json()["detail"]["error"] == "consent_evidence_required"
    assert consent(E, c["id"], purpose="spam", channel="zalo", evidence="form web").json()["detail"]["error"] == "invalid_purpose"
    m = consent(E, c["id"], purpose="marketing", channel="zalo", evidence="Form đăng ký web 16/10, ô tích không tích sẵn",
                notice_ref="POL-DLCN v1")
    assert m.status_code == 200, m.text
    assert consent(E, c["id"], purpose="marketing", channel="zalo", evidence="lần 2").status_code == 409
    # thành viên (trưởng phòng, org member) thấy PII đã che
    v = E.c.get(f"/api/team/crm/contacts/{c['id']}", headers=E.tok("member")).json()
    assert v["phone"] == "09******78" and v["email"] == "m***@example.com" and v["pii_masked"] is True and v["notes"] == ""
    assert v["address"].startswith("***") and "Lê Lợi" not in v["address"]
    # marketing đúng kênh được; sai kênh bị chặn + ghi bằng chứng
    ok = E.c.post(f"/api/team/crm/contacts/{c['id']}/outreach", json={"purpose": "marketing", "channel": "zalo",
                                                                    "message": "Ưu đãi tháng 10"}, headers=E.tok("manager"))
    assert ok.status_code == 200 and ok.json()["allowed"] is True
    bad = E.c.post(f"/api/team/crm/contacts/{c['id']}/outreach", json={"purpose": "marketing", "channel": "sms", "message": "x"},
                   headers=E.tok("manager"))
    assert bad.status_code == 409 and bad.json()["detail"]["error"] == "no_marketing_consent"
    assert E.c.get(f"/api/team/crm/audience?company_id={E.co.id}&channel=zalo", headers=E.tok("manager")).json()["contact_ids"] == [c["id"]]
    # rút đồng ý → dòng đóng (không xoá), marketing bị chặn ở mọi kênh, audience rỗng
    w = E.c.post(f"/api/team/crm/consents/{m.json()['id']}/withdraw", json={"reason": "Khách nhắn STOP"}, headers=E.tok("manager"))
    assert w.status_code == 200 and w.json()["status"] == "withdrawn" and w.json()["withdrawn_at"]
    assert E.c.post(f"/api/team/crm/consents/{m.json()['id']}/withdraw", json={}, headers=E.tok("manager")).status_code == 409
    bad = E.c.post(f"/api/team/crm/contacts/{c['id']}/outreach", json={"purpose": "marketing", "channel": "zalo", "message": "x"},
                   headers=E.tok("manager"))
    assert bad.status_code == 409 and bad.json()["detail"]["error"] == "no_marketing_consent"
    assert E.c.get(f"/api/team/crm/audience?company_id={E.co.id}&channel=zalo", headers=E.tok("manager")).json()["count"] == 0
    # chăm sóc theo yêu cầu của chính khách (service) vẫn được
    assert E.c.post(f"/api/team/crm/contacts/{c['id']}/outreach", json={"purpose": "service", "channel": "zalo",
                                                                      "message": "Đơn đã giao"}, headers=E.tok("manager")).status_code == 200
    assert E.db.query(CrmConsent).filter(CrmConsent.contact_id == c["id"]).count() == 1          # bằng chứng còn nguyên
    d = E.c.get(f"/api/team/crm/contacts/{c['id']}", headers=E.tok("manager")).json()
    kinds = [i["kind"] for i in d["interactions"]]
    assert kinds.count("outreach_blocked") == 2 and "consent" in kinds
    assert d["consent_history"][0]["withdrawn_reason"] == "Khách nhắn STOP"
    # đồng ý lại = dòng mới
    assert consent(E, c["id"], purpose="marketing", channel="zalo", evidence="Khách đăng ký lại tại cửa hàng").status_code == 200
    assert E.db.query(CrmConsent).filter(CrmConsent.contact_id == c["id"]).count() == 2
    # tổ chức khác không thấy
    assert E.c.get(f"/api/team/crm/contacts/{c['id']}", headers=E.tok("other")).status_code == 404
    # search_text không chứa PII (không vào chỉ mục)
    row = E.db.get(CrmContact, c["id"])
    assert "0912345678" not in row.search_text and "example.com" not in row.search_text


def test_agent_sees_only_own_department_consented_contacts_masked_and_outreach_tool_blocks(E):
    _seats(E)
    a = hire(E)                       # agent phòng Bán hàng
    ag = E.db.get(Agent, a["agent_id"]); me = E.db.get(Member, ag.member_id)
    c1 = mkc(E, name="Trần Văn Bình", phone="0987654321", email="binh@example.com", department_id=E.sales.id, segment="sỉ").json()
    c2 = mkc(E, name="Lê Thu Bình", phone="0901111222", department_id=E.mkt.id).json()          # phòng khác
    c3 = mkc(E, name="Phạm Bình", phone="0903333444").json()                                     # chưa đồng ý gì
    consent(E, c1["id"], purpose="service", channel="other", evidence="Khách mua hàng, đồng ý điều khoản đơn #12")
    consent(E, c2["id"], purpose="service", channel="other", evidence="Khách mua hàng, đồng ý điều khoản đơn #13")
    ctx = company_mcp.ToolContext(db=E.db, member=me, agent=ag)
    ok, out = company_mcp.call(ctx, "company_customer_lookup", {"query": "bình"})
    assert ok, out
    ids = [x["contact_id"] for x in out["contacts"]]
    assert ids == [c1["id"]] and out["hidden_without_consent"] == 1                               # c2 phòng khác, c3 chưa đồng ý
    x = out["contacts"][0]
    assert x["phone"] == "09******21" and x["email"] == "b***@example.com" and out["pii"] == "masked"
    assert "0987654321" not in str(out)
    # marketing qua tool: chưa đồng ý marketing → bị chặn, có bằng chứng
    ok, res = company_mcp.call(ctx, "company_customer_outreach", {"contact_id": c1["id"], "purpose": "marketing",
                                                                  "channel": "zalo", "message": "Giảm 20%"})
    assert not ok and res["error"] == "no_marketing_consent"
    assert E.db.query(CrmInteraction).filter(CrmInteraction.contact_id == c1["id"], CrmInteraction.kind == "outreach_blocked",
                                             CrmInteraction.member_id == me.id).count() == 1
    ok, res = company_mcp.call(ctx, "company_customer_outreach", {"contact_id": c2["id"], "message": "x"})
    assert not ok and res["error"] in ("forbidden", "not_found")
    consent(E, c1["id"], purpose="marketing", channel="zalo", evidence="Form web, ô tích tự nguyện")
    ok, res = company_mcp.call(ctx, "company_customer_outreach", {"contact_id": c1["id"], "purpose": "marketing",
                                                                  "channel": "zalo", "message": "Giảm 20%"})
    assert ok and res["allowed"] is True
    t = company_mcp.TOOLS["company_customer_lookup"]
    assert t.writes is False and t.scope == "company.knowledge:read"
    from app.services import tool_permissions
    assert tool_permissions.action_of("company_customer_outreach") == "send"
    # hạn chế xử lý → agent không thấy nữa
    E.db.get(CrmContact, c1["id"]).restricted = True; E.db.commit()
    assert crm.agent_lookup(E.db, me, query="bình")["contacts"] == []


def test_data_subject_requests_have_legal_deadlines_tasks_and_erase_leaves_evidence(E):
    _seats(E)
    c = mkc(E, name="Đỗ Hồng Nhung", phone="0911222333", email="nhung@example.com", notes="Khách quen, thích men lam").json()
    consent(E, c["id"], purpose="marketing", channel="email", evidence="Form web 01/10")
    E.c.post(f"/api/team/crm/contacts/{c['id']}/interactions", json={"kind": "call", "summary": "Hỏi về bộ ấm chén men lam"},
             headers=E.tok("manager"))
    # xem dữ liệu: 10 ngày; phản hồi 02 ngày làm việc (thứ Sáu → thứ Ba)
    fri = datetime(2026, 10, 16, 3, 0)
    r = E.c.post(f"/api/team/crm/contacts/{c['id']}/requests", json={"kind": "access", "received_at": fri.isoformat()},
                 headers=E.tok("manager"))
    assert r.status_code == 200, r.text
    acc = r.json()
    assert acc["due_at"].startswith("2026-10-26") and acc["ack_due_at"].startswith("2026-10-20") and acc["days_allowed"] == 10
    assert acc["task_id"] and E.db.get(Task, acc["task_id"]).assignee_member_id
    assert E.db.query(InboxItem).filter(InboxItem.item_type == "dsr_due").count() >= 1
    assert E.c.post(f"/api/team/crm/requests/{acc['id']}/act", json={"action": "reject"}, headers=E.tok("manager")).status_code == 422
    done = E.c.post(f"/api/team/crm/requests/{acc['id']}/act", json={"action": "complete"}, headers=E.tok("manager")).json()
    assert done["status"] == "done" and len(done["evidence"]["export_sha256"]) == 64
    assert done["export"]["contact"]["phone"] == "0911222333"
    assert E.db.get(Task, acc["task_id"]).status == "done"
    assert E.c.post(f"/api/team/crm/requests/{acc['id']}/act", json={"action": "ack"}, headers=E.tok("manager")).status_code == 409
    # xoá: 20 ngày; chạy hết quy trình
    d = E.c.post(f"/api/team/crm/contacts/{c['id']}/requests", json={"kind": "delete", "note": "Khách yêu cầu qua email"},
                 headers=E.tok("manager")).json()
    assert d["days_allowed"] == 20
    assert E.c.get(f"/api/team/crm/requests?company_id={E.co.id}&status=open", headers=E.tok("member")).json()["items"][0]["id"] == d["id"]
    E.c.post(f"/api/team/crm/requests/{d['id']}/act", json={"action": "ack"}, headers=E.tok("manager"))
    out = E.c.post(f"/api/team/crm/requests/{d['id']}/act", json={"action": "complete"}, headers=E.tok("manager")).json()
    ev = out["evidence"]
    assert out["status"] == "done" and len(ev["pre_erase_sha256"]) == 64 and ev["interactions_cleared"] >= 1 and ev["consents_closed"] == 1
    row = E.db.get(CrmContact, c["id"])
    assert row.status == "erased" and row.phone == "" and row.email == "" and row.notes == "" and "Nhung" not in row.name
    assert all(not i.summary for i in E.db.query(CrmInteraction).filter(CrmInteraction.contact_id == c["id"]))
    x = E.db.query(CrmConsent).filter(CrmConsent.contact_id == c["id"]).one()
    assert x.status == "withdrawn" and x.purpose == "marketing" and x.granted_at              # siêu dữ liệu giữ làm bằng chứng
    # liên hệ đã xoá: không marketing, không ghi đồng ý mới, không sửa
    assert crm.can_contact(E.db, row, "marketing", "email") == (False, "contact_erased")
    assert consent(E, c["id"], purpose="marketing", channel="email", evidence="form").status_code == 409
    assert E.c.patch(f"/api/team/crm/contacts/{c['id']}", json={"name": "x"}, headers=E.tok("manager")).status_code == 409
    # nhắc hạn: yêu cầu rút đồng ý nhận 9 ngày trước (hạn 15) → còn ≤ 3 ngày → một thẻ, chạy lại không nhắc nữa
    c2 = mkc(E, name="Khách B").json()
    old = (datetime.utcnow() - timedelta(days=13)).isoformat()
    E.c.post(f"/api/team/crm/contacts/{c2['id']}/requests", json={"kind": "withdraw", "received_at": old}, headers=E.tok("manager"))
    assert crm.tick(E.db) == 1 and crm.tick(E.db) == 0
