"""M3f — sản phẩm/dịch vụ & bảng giá: SKU theo công ty, giá mặc định VND (không phần lẻ), lịch sử giá, đổi giá qua ma trận
price_change (< 10% → trưởng phòng; ≥ 10% hoặc giá mới → chủ; người đề xuất không tự duyệt), duyệt từ Hộp việc cũng áp dụng,
agent tra giá qua MCP company_product_lookup (chỉ giá đang hiệu lực, không trả giá chờ duyệt / hết hạn), eval 20 câu 0 giá bịa,
M3d 'Bảng giá hiện hành' đạt khi có giá. ORM thật trên SQLite, gateway giả."""
from datetime import datetime, timedelta

from app.models.catalog import CatalogPrice
from app.services import catalog, catalog_eval, company_mcp
from tests.test_m2b_company_foundation import E  # noqa: F401  (fixture)
from tests.test_m3_agents import env, hire  # noqa: F401  (fixture)
from tests.test_m3a_document_library import _seats


def mkp(E, role="owner", **body):
    return E.c.post("/api/team/catalog/products", json={"company_id": E.co.id, **body}, headers=E.tok(role))


def propose(E, pid, amount, role="manager", **kw):
    return E.c.post(f"/api/team/catalog/products/{pid}/prices", json={"amount": amount, **kw}, headers=E.tok(role))


def test_product_with_vnd_price_and_approval_by_matrix(E):
    thao = _seats(E)          # manager = Chị Thảo (nhân viên), member = Anh Minh (trưởng phòng), owner = Chị Lan
    r = mkp(E, sku="bat-men-lam", name="Bát men lam vẽ tay", unit="cái", price=185000, policies={"return_days": 7})
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["sku"] == "BAT-MEN-LAM" and p["price_request"]["auto_approved"] is True     # chủ đặt giá mới → duyệt ngay
    assert p["current_price"]["display"] == "185.000 ₫" and p["current_price"]["currency"] == "VND"
    assert mkp(E, sku="BAT-MEN-LAM", name="trùng").status_code == 409
    assert mkp(E, role="member", sku="X1", name="x").status_code == 403
    assert propose(E, p["id"], "185000.5").status_code == 422                          # VND không có phần lẻ
    assert propose(E, p["id"], 0).status_code == 422
    assert propose(E, p["id"], 10, currency="EUR").status_code == 422
    # sửa thông tin không được động vào giá
    assert E.c.patch(f"/api/team/catalog/products/{p['id']}", json={"price": 1}, headers=E.tok("manager")).status_code == 422
    # +5% → trưởng phòng (Anh Minh) duyệt; Chị Thảo không tự duyệt
    r = propose(E, p["id"], 194000, note="men tăng giá")
    assert r.status_code == 200, r.text
    small = r.json()
    assert small["status"] == "pending" and small["risk"] == "normal" and small["change_pct"] == 4.86
    assert small["approver_member_id"] == E.lead_s.id
    assert propose(E, p["id"], 199000).status_code == 409                              # đang có đề xuất chờ duyệt
    assert E.c.post(f"/api/team/catalog/prices/{small['id']}/decide", json={"decision": "approved"},
                    headers=E.tok("manager")).status_code == 403
    cur = E.c.get(f"/api/team/catalog/products/{p['id']}", headers=E.tok("member")).json()
    assert cur["current_price"]["display"] == "185.000 ₫" and cur["pending_price"]["id"] == small["id"]
    assert E.c.post(f"/api/team/catalog/prices/{small['id']}/decide", json={"decision": "rejected"},
                    headers=E.tok("member")).status_code == 422                        # từ chối phải có lý do
    r = E.c.post(f"/api/team/catalog/prices/{small['id']}/decide", json={"decision": "approved"}, headers=E.tok("member"))
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["current_price"]["display"] == "194.000 ₫"
    hist = d["history"]
    assert len(hist) == 2 and hist[0]["in_effect"] and hist[1]["effective_to"] is not None and hist[1]["decided_by"] == "Chị Lan"
    # −20% → rủi ro cao → chủ; duyệt từ Hộp việc (inbox_hub) cũng áp dụng giá
    big = propose(E, p["id"], 155000).json()
    assert big["risk"] == "high" and big["approver_member_id"] == E.boss.id and big["approval_id"]
    r = E.c.post(f"/api/inbox/approvals/{big['approval_id']}/decide", json={"decision": "approve"}, headers=E.tok("owner"))
    assert r.status_code == 200, r.text
    assert E.c.get(f"/api/team/catalog/products/{p['id']}", headers=E.tok("member")).json()["current_price"]["display"] == "155.000 ₫"
    # giá mới cho sản phẩm chưa có giá (nhân viên đề xuất) → chủ duyệt
    q = mkp(E, role="manager", sku="DIA-HOA-SEN", name="Đĩa hoa sen 24cm", price="240000").json()
    assert q["current_price"] is None and q["price_request"]["risk"] == "high" and q["price_request"]["approver_member_id"] == E.boss.id
    rule = [x for x in E.c.get(f"/api/team/authority?company_id={E.co.id}", headers=E.tok("member")).json()["rules"]
            if x["action_type"] == "price_change"]
    assert len(rule) == 2


def test_agent_lookup_only_sees_prices_in_effect(E):
    _seats(E)
    p = mkp(E, sku="AM-TRA", name="Ấm trà tử sa 250ml", unit="bộ", price=1250000).json()
    old = E.db.get(CatalogPrice, p["current_price"]["id"])
    old.effective_from = datetime.utcnow() - timedelta(days=10); E.db.commit()
    tomorrow = (datetime.utcnow() + timedelta(days=1)).replace(microsecond=0)
    r = propose(E, p["id"], 1350000, role="owner", effective_from=tomorrow.isoformat())      # hẹn giá mới từ mai
    assert r.json()["status"] == "approved"
    out = catalog.lookup(E.db, E.co.id, query="am tra tu sa gia bao nhieu")
    assert out["products"][0]["price"]["display"] == "1.250.000 ₫"                       # giá hẹn chưa tới ngày
    later = catalog.current_price(E.db, p["id"], at=tomorrow + timedelta(minutes=1))
    assert catalog.fmt_money(later.amount, later.currency) == "1.350.000 ₫"
    # giá hết hiệu lực → không trả giá, có cảnh báo
    for row in E.db.query(CatalogPrice).filter(CatalogPrice.product_id == p["id"]):
        row.effective_to = datetime.utcnow() - timedelta(minutes=1)
    E.db.commit()
    hit = catalog.lookup(E.db, E.co.id, sku="am-tra")["products"][0]
    assert hit["price"] is None and "KHÔNG báo giá" in hit["warning"]
    # sản phẩm nháp không lộ cho agent; sản phẩm khác công ty / tổ chức không lộ
    mkp(E, sku="NHAP-1", name="Ấm nháp", status="draft")
    assert all(x["sku"] != "NHAP-1" for x in catalog.lookup(E.db, E.co.id, query="am nhap")["products"])
    assert catalog.lookup(E.db, None, query="am")["products"] == []
    assert E.c.get(f"/api/team/catalog/products/{p['id']}", headers=E.tok("other")).status_code == 404
    # tool MCP có thật, chỉ đọc
    t = company_mcp.TOOLS["company_product_lookup"]
    assert t.writes is False and t.scope == "company.knowledge:read"
    pv = E.c.post("/api/team/catalog/lookup", json={"company_id": E.co.id, "query": "ấm trà"}, headers=E.tok("member")).json()
    assert pv["products"][0]["sku"] == "AM-TRA"


def test_eval_20_questions_zero_fabricated_prices_and_m3d_price_list(E):
    _seats(E)
    from app.services import doc_requirements
    co = E.co
    assert catalog.has_active_prices(E.db, co.id) is False
    assert catalog_eval.seed(E.db, E.org.id, co.id)["seeded"] == 9
    res = catalog_eval.run(E.db, co.id)
    bad = [r for r in res["rows"] if not r["ok"]]
    assert res["questions"] == 20 and res["fabricated_prices"] == 0 and not bad, bad
    assert catalog.has_active_prices(E.db, co.id) is True
    ev = doc_requirements.evaluate(E.db, E.org.id, co.id)
    item = next(i for i in ev["items"] if i["key"] == "shop_price_list")          # "Nova Shop" → gói shop
    assert item["status"] == "ok" and item["documents"][0]["doc_code"] == "CATALOG"
    # chính sách: riêng của sản phẩm thắng, không có thì lấy sự kiện công ty
    bat = catalog.lookup(E.db, co.id, sku="BAT-MEN-LAM")["products"][0]
    assert bat["policies"]["return_days"]["value"] == 7 and bat["policies"]["return_days"]["source"] == "sản phẩm BAT-MEN-LAM"
    lst = E.c.get(f"/api/team/catalog?company_id={co.id}", headers=E.tok("member")).json()
    assert lst["counts"]["total"] == 9 and lst["counts"]["pending"] == 1 and lst["high_pct"] == 10
