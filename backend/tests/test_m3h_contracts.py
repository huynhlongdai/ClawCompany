"""M3h (P1) — hợp đồng & đối tác: ký qua ma trận ``contract`` (người đề xuất không tự duyệt; duyệt từ Hộp việc cũng áp dụng),
giá trị VND không phần lẻ, hợp đồng đã ký khoá điều khoản, hạn báo trước / hết hạn → lịch tuân thủ + MỘT việc + thẻ Hộp việc
``contract_due`` khi còn ≤ 30 ngày, tự gia hạn / hết hạn, agent đọc SLA từ tool (không đọc tệp ký, không thấy giá trị)."""
from datetime import timedelta

from app.models import InboxItem, Task
from app.models.company_ops import ComplianceDeadline, ComplianceRule
from app.models.contracts import BizContract
from app.services import company_mcp, contracts
from tests.test_m2b_company_foundation import E  # noqa: F401  (fixture)
from tests.test_m3_agents import env, hire  # noqa: F401  (fixture)
from tests.test_m3a_document_library import _seats


def partner(E, **kw):
    r = E.c.post("/api/team/partners", json={"company_id": E.co.id, "name": "Xưởng men Bát Tràng", "kind": "supplier",
                                             "tax_code": "0101234567", **kw}, headers=E.tok("manager"))
    assert r.status_code == 200, r.text
    return r.json()


def mkc(E, role="manager", **kw):
    return E.c.post("/api/team/biz-contracts", json={"company_id": E.co.id, **kw}, headers=E.tok(role))


def test_contract_signing_goes_through_authority_matrix_and_locks_terms(E):
    _seats(E)
    p = partner(E)
    assert E.c.post("/api/team/partners", json={"company_id": E.co.id, "name": "x", "tax_code": "123"},
                    headers=E.tok("manager")).json()["detail"]["error"] == "invalid_tax_code"
    t0 = contracts.today_vn()
    r = mkc(E, title="Cung cấp men gốm 2026", kind="purchase", partner_id=p["id"], value_amount="120000000.5",
            start_date=t0.isoformat())
    assert r.status_code == 422 and r.json()["detail"]["error"] == "vnd_no_decimals", r.text
    r = mkc(E, title="Cung cấp men gốm 2026", kind="purchase", partner_id=p["id"], value_amount=120000000,
            start_date=t0.isoformat(), end_date=(t0 + timedelta(days=365)).isoformat(), notice_days=30, auto_renew=True,
            sla={"delivery_days": 5, "response_hours": 24, "payment_days": 30, "penalty": "0,5%/ngày chậm"},
            key_terms="Giao men trong 5 ngày; đổi lô lỗi trong 7 ngày.")
    assert r.status_code == 200, r.text
    c = r.json()
    assert c["code"].startswith("HD-") and c["status"] == "draft" and c["currency"] == "VND" and c["renewal_months"] == 12
    assert c["notice_deadline"] == (t0 + timedelta(days=335)).isoformat()
    assert mkc(E, role="member", title="x").status_code == 403
    # nhân viên gửi ký → ma trận contract: chủ ký; trưởng phòng / người đề xuất không duyệt được
    s = E.c.post(f"/api/team/biz-contracts/{c['id']}/submit", json={}, headers=E.tok("manager")).json()
    assert s["status"] == "pending" and s["approver_member_id"] == E.boss.id and s["auto_approved"] is False and s["approval_id"]
    assert E.c.post(f"/api/team/biz-contracts/{c['id']}/decide", json={"decision": "approved"}, headers=E.tok("member")).status_code == 403
    assert E.c.patch(f"/api/team/biz-contracts/{c['id']}", json={"value_amount": 1}, headers=E.tok("manager")).json()["detail"]["error"] == "contract_locked"
    # chủ duyệt từ Hộp việc → hiệu lực + 2 mốc vào lịch tuân thủ (loại contract)
    r = E.c.post(f"/api/inbox/approvals/{s['approval_id']}/decide", json={"decision": "approve"}, headers=E.tok("owner"))
    assert r.status_code == 200, r.text
    row = E.db.get(BizContract, c["id"]); E.db.refresh(row)
    assert row.status == "active" and row.decided_by_member_id == E.boss.id
    rules = E.db.query(ComplianceRule).filter(ComplianceRule.key.in_([f"contract_notice:{row.id}", f"contract_end:{row.id}"])).all()
    assert len(rules) == 2 and all(x.category == "contract" and x.enabled for x in rules)
    # đã ký: không sửa điều khoản; gắn bản ký thì được
    r = E.c.patch(f"/api/team/biz-contracts/{c['id']}", json={"end_date": "2030-01-01"}, headers=E.tok("manager"))
    assert r.status_code == 409 and r.json()["detail"]["error"] == "contract_locked"
    assert E.c.post(f"/api/team/biz-contracts/{c['id']}/terminate", json={"note": ""}, headers=E.tok("manager")).status_code == 422
    # chủ tự gửi ký hợp đồng của mình → ký ngay (người xin là người có quyền)
    own = E.c.post("/api/team/biz-contracts", json={"company_id": E.co.id, "title": "Thuê kho", "kind": "lease", "partner_id": p["id"],
                                               "start_date": t0.isoformat()}, headers=E.tok("owner")).json()
    s2 = E.c.post(f"/api/team/biz-contracts/{own['id']}/submit", json={}, headers=E.tok("owner")).json()
    assert s2["status"] == "active" and s2["auto_approved"] is True
    # từ chối cần lý do; bị từ chối sửa được rồi gửi lại
    d3 = mkc(E, title="Quảng cáo", kind="service", partner_id=p["id"], start_date=t0.isoformat()).json()
    s3 = E.c.post(f"/api/team/biz-contracts/{d3['id']}/submit", json={}, headers=E.tok("manager")).json()
    assert E.c.post(f"/api/team/biz-contracts/{d3['id']}/decide", json={"decision": "rejected"}, headers=E.tok("owner")).status_code == 422
    assert E.c.post(f"/api/team/biz-contracts/{d3['id']}/decide", json={"decision": "rejected", "note": "Giá cao"},
                    headers=E.tok("owner")).json()["status"] == "rejected"
    assert E.c.patch(f"/api/team/biz-contracts/{d3['id']}", json={"value_amount": 9000000}, headers=E.tok("manager")).status_code == 200
    assert s3["approval_id"]
    lst = E.c.get(f"/api/team/biz-contracts?company_id={E.co.id}", headers=E.tok("member")).json()
    assert lst["counts"]["active"] == 2 and lst["partners"][0]["active_contracts"] == 2
    assert E.c.get(f"/api/team/biz-contracts/{c['id']}", headers=E.tok("other")).status_code == 404


def test_deadlines_remind_once_auto_renew_expire_and_agent_reads_sla_not_value(E):
    _seats(E)
    p = partner(E)
    t0 = contracts.today_vn()
    c = E.c.post("/api/team/biz-contracts", json={"company_id": E.co.id, "title": "Vận chuyển GHN", "kind": "service", "partner_id": p["id"],
                                             "value_amount": 50000000, "start_date": (t0 - timedelta(days=300)).isoformat(),
                                             "end_date": (t0 + timedelta(days=40)).isoformat(), "notice_days": 30,
                                             "sla": {"delivery_days": 3, "response_hours": 4}}, headers=E.tok("owner")).json()
    E.c.post(f"/api/team/biz-contracts/{c['id']}/submit", json={}, headers=E.tok("owner"))
    # hạn báo trước còn 10 ngày → MỘT việc + thẻ contract_due; hết hạn còn 40 ngày → chưa nhắc
    out = contracts.tick(E.db, today=t0)
    assert out["reminded"] == 1 and contracts.tick(E.db, today=t0)["reminded"] == 0
    cards = E.db.query(InboxItem).filter(InboxItem.item_type == "contract_due").all()
    assert len(cards) >= 1 and all(x.related_id == str(c["id"]) for x in cards)
    tk = E.db.get(Task, cards[0].task_id)
    assert tk is not None and "hạn báo trước" in tk.title
    rule = E.db.query(ComplianceRule).filter(ComplianceRule.key == f"contract_notice:{c['id']}").one()
    dl = E.db.query(ComplianceDeadline).filter(ComplianceDeadline.rule_id == rule.id, ComplianceDeadline.status == "upcoming").one()
    assert dl.reminded_at is not None and dl.task_id == tk.id                      # lịch tuân thủ không nhắc lần hai
    # 20 ngày sau: hết hạn còn 20 → nhắc mốc hết hạn
    assert contracts.tick(E.db, today=t0 + timedelta(days=20))["reminded"] == 1
    # quá hạn, không tự gia hạn → expired, mốc trong lịch bị bỏ
    assert contracts.tick(E.db, today=t0 + timedelta(days=41))["expired"] == 1
    assert E.db.get(BizContract, c["id"]).status == "expired"
    # tự gia hạn: cộng 12 tháng
    r = E.c.post("/api/team/biz-contracts", json={"company_id": E.co.id, "title": "Thuê mặt bằng", "kind": "lease", "partner_id": p["id"],
                                             "start_date": (t0 - timedelta(days=360)).isoformat(), "end_date": (t0 - timedelta(days=1)).isoformat(),
                                             "auto_renew": True, "renewal_months": 12}, headers=E.tok("owner")).json()
    E.c.post(f"/api/team/biz-contracts/{r['id']}/submit", json={}, headers=E.tok("owner"))
    assert contracts.tick(E.db, today=t0)["renewed"] == 1
    row = E.db.get(BizContract, r["id"]); E.db.refresh(row)
    assert row.status == "active" and row.end_date.year == (t0 - timedelta(days=1)).year + 1
    # agent: hợp đồng đang hiệu lực, SLA số từ trường có cấu trúc, không có giá trị
    from app.models import Agent, Member
    a = hire(E); ag = E.db.get(Agent, a["agent_id"])
    ctx = company_mcp.ToolContext(db=E.db, member=E.db.get(Member, ag.member_id), agent=ag)
    ok, res = company_mcp.call(ctx, "company_contract_get", {"partner": "Bát Tràng"})
    assert ok and len(res["contracts"]) == 1 and res["contracts"][0]["title"] == "Thuê mặt bằng"       # GHN đã hết hạn → không trả
    assert "value_amount" not in res["contracts"][0] and "50000000" not in str(res)
    E.c.post("/api/team/biz-contracts", json={"company_id": E.co.id, "title": "Giao hàng nhanh", "kind": "service", "partner_id": p["id"],
                                         "start_date": t0.isoformat(), "sla": {"delivery_days": 2}}, headers=E.tok("owner"))
    d = E.db.query(BizContract).filter(BizContract.title == "Giao hàng nhanh").one()
    contracts.submit(E.db, E.org.id, type("P", (), {"seat_in": lambda self, c: E.boss.id, "member_ids": [E.boss.id], "role": "owner"})(), d.id)
    ok, res = company_mcp.call(ctx, "company_contract_get", {"query": "giao hang nhanh"})
    hit = [x for x in res["contracts"] if x["title"] == "Giao hàng nhanh"][0]
    assert hit["sla"]["delivery_days"] == 2 and hit["cite"].startswith("[HĐ:")
    assert company_mcp.TOOLS["company_contract_get"].writes is False
    ok, res = company_mcp.call(ctx, "company_contract_get", {"partner": "không tồn tại xyz"})
    assert ok and res["contracts"] == [] and "đừng đoán" in res["note"]
