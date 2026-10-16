"""M3j (P1) — tài chính kinh doanh đơn giản (KHÔNG phải sổ kế toán): thu chi VND không phần lẻ, bán hàng nối sản phẩm (lấy giá đang
hiệu lực × số lượng), dòng đã ghi chỉ huỷ được (có lý do) chứ không sửa/xoá, lãi lỗ tháng tách theo tiền tệ (USD không quy đổi),
ngân sách tháng: chỉ quản trị đặt, chạm ngưỡng → MỘT thẻ Hộp việc, agent xem còn lại qua tool (không thấy từng dòng)."""
from app.models import Agent, InboxItem, Member
from app.models.finance import FinCategory
from app.services import company_mcp, finance
from tests.test_m2b_company_foundation import E  # noqa: F401  (fixture)
from tests.test_m3_agents import env, hire  # noqa: F401  (fixture)
from tests.test_m3a_document_library import _seats
from tests.test_m3f_catalog import mkp


def cat(E, key):
    finance.ensure_categories(E.db, E.org.id, E.co.id)
    return E.db.query(FinCategory).filter(FinCategory.company_id == E.co.id, FinCategory.key == key).one().id


def rec(E, role="manager", **kw):
    return E.c.post("/api/team/finance/entries", json={"company_id": E.co.id, **kw}, headers=E.tok(role))


def test_ledger_entries_pnl_void_and_scope(E):
    _seats(E)
    p = mkp(E, sku="BAT-MEN-LAM", name="Bát men lam", price=185000).json()
    t = finance.today_vn()
    r = rec(E, kind="income", category_id=cat(E, "sales"), product_id=p["id"], quantity=2)
    assert r.status_code == 200, r.text
    sale = r.json()
    assert sale["amount"] == 370000 and sale["currency"] == "VND" and sale["description"].startswith("BAT-MEN-LAM")
    assert rec(E, kind="expense", category_id=cat(E, "rent"), amount="5000000.5").json()["detail"]["error"] == "vnd_no_decimals"
    assert rec(E, kind="expense", category_id=cat(E, "sales"), amount=1).json()["detail"]["error"] == "category_kind_mismatch"
    assert rec(E, kind="expense", category_id=cat(E, "rent"), amount=1, occurred_on="2099-01-01").json()["detail"]["error"] == "future_date"
    assert rec(E, role="member", kind="expense", category_id=cat(E, "rent"), amount=1).status_code == 403
    rent = rec(E, kind="expense", category_id=cat(E, "rent"), amount=5000000, description="Thuê tháng 10").json()
    rec(E, kind="expense", category_id=cat(E, "software"), amount="20.50", currency="USD", description="Tên miền")
    wrong = rec(E, kind="expense", category_id=cat(E, "shipping"), amount=999999).json()
    assert E.c.post(f"/api/team/finance/entries/{wrong['id']}/void", json={"reason": ""}, headers=E.tok("manager")).status_code == 422
    assert E.c.post(f"/api/team/finance/entries/{wrong['id']}/void", json={"reason": "Nhập nhầm số"}, headers=E.tok("manager")).json()["status"] == "void"
    assert E.c.post(f"/api/team/finance/entries/{wrong['id']}/void", json={"reason": "lần hai"}, headers=E.tok("manager")).status_code == 409
    # thành viên không xem thu chi; quản lý xem
    assert E.c.get(f"/api/team/finance?company_id={E.co.id}", headers=E.tok("member")).status_code == 403
    ov = E.c.get(f"/api/team/finance?company_id={E.co.id}", headers=E.tok("manager")).json()
    vnd = ov["pnl"]["VND"]
    assert vnd["income"] == 370000 and vnd["expense"] == 5000000 and vnd["net"] == -4630000      # dòng huỷ không tính
    assert ov["pnl"]["USD"]["expense"] == 20.5                                                       # USD tách riêng, không quy đổi
    assert ov["accounting_scope"]["is_accounting_ledger"] is False and len(ov["trend"]) == 6
    assert ov["trend"][-1]["period"] == t.strftime("%Y-%m") and ov["trend"][-1]["net"] == -4630000
    assert any(e["status"] == "void" and e["void_reason"] == "Nhập nhầm số" for e in ov["entries"])  # dấu vết còn
    csv = E.c.get(f"/api/team/finance/export?company_id={E.co.id}", headers=E.tok("manager"))
    assert csv.status_code == 200 and "Thuê tháng 10" in csv.text and "Nhập nhầm số" in csv.text
    # liên kết sai công ty → 404; tổ chức khác không thấy
    assert rec(E, kind="income", category_id=cat(E, "sales"), amount=1, contract_id=999).status_code == 404
    assert E.c.get(f"/api/team/finance?company_id={E.co.id}", headers=E.tok("other")).status_code in (403, 404)
    assert rent["category"]["key"] == "rent"


def test_budget_alert_once_and_agent_sees_remaining_not_entries(E):
    _seats(E)
    ship = cat(E, "shipping")
    body = {"company_id": E.co.id, "category_id": ship, "amount": 1000000, "alert_pct": 80}
    assert E.c.put("/api/team/finance/budgets", json=body, headers=E.tok("manager")).status_code == 403     # chỉ quản trị
    r = E.c.put("/api/team/finance/budgets", json=body, headers=E.tok("owner"))
    assert r.status_code == 200, r.text
    E.c.put("/api/team/finance/budgets", json={**body, "category_id": cat(E, "marketing"), "department_id": E.mkt.id, "amount": 3000000},
            headers=E.tok("owner"))
    assert E.c.put("/api/team/finance/budgets", json={**body, "category_id": cat(E, "sales")}, headers=E.tok("owner")).status_code == 422
    rec(E, kind="expense", category_id=ship, amount=500000)
    assert finance.tick(E.db) == 0
    rec(E, kind="expense", category_id=ship, amount=350000)
    assert finance.tick(E.db) == 1 and finance.tick(E.db) == 0
    card = E.db.query(InboxItem).filter(InboxItem.item_type == "finance_budget").one()
    assert card.recipient_member_id == E.boss.id and "85.0%" in card.title
    a = hire(E)                                          # agent phòng Bán hàng
    ag = E.db.get(Agent, a["agent_id"])
    ctx = company_mcp.ToolContext(db=E.db, member=E.db.get(Member, ag.member_id), agent=ag)
    ok, res = company_mcp.call(ctx, "company_finance_budget", {})
    assert ok, res
    assert [(b["category"], b["remaining"], b["scope"]) for b in res["budgets"]] == [("Vận chuyển", 150000, "company")]   # ngân sách phòng Marketing không lộ
    assert "entries" not in res and "350000" not in str({k: v for k, v in res.items() if k != "budgets"})
    ok, res = company_mcp.call(ctx, "company_finance_budget", {"category": "marketing"})
    assert res["budgets"] == [] and "đừng đoán" in res["note"]
    assert company_mcp.TOOLS["company_finance_budget"].writes is False
