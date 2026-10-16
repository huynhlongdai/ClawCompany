"""M3j — tài chính kinh doanh (sổ thu chi + lãi lỗ tháng + ngân sách so thực tế). Spec: docs/company-knowledge-library-and-gaps.md §C M3j.

Nói thẳng phạm vi: đây là sổ QUẢN TRỊ để chủ và agent biết thu–chi–ngân sách còn lại. KHÔNG phải sổ kế toán theo chế độ kế toán
doanh nghiệp (TT 133/2016/TT-BTC, TT 200/2014/TT-BTC), không lập BCTC, không khai thuế — cần kế toán / phần mềm kế toán
(``accounting_scope``). Xuất CSV cho kế toán.

* Tiền: VND mặc định, không phần lẻ. USD ghi được nhưng lãi lỗ tách theo tiền tệ, KHÔNG quy đổi. Chi phí nền tảng (model, ghế, USD)
  không nằm ở đây.
* Dòng đã ghi không sửa / xoá — sai thì huỷ (void, có lý do, giữ dấu vết) rồi ghi lại.
* Liên kết: sản phẩm (M3f — thiếu số tiền thì lấy giá đang hiệu lực × số lượng), hợp đồng / đối tác (M3h), khách (M3g), chứng từ (M3a).
* Ngân sách tháng theo nhóm chi (+ phòng): chạm ``alert_pct`` → MỘT thẻ Hộp việc ``finance_budget`` cho chủ (beat business.tick).
* Agent: MCP ``company_finance_budget`` — ngân sách / đã chi / còn lại tháng này theo nhóm (phòng của agent + toàn công ty), không
  thấy từng dòng thu chi."""
from __future__ import annotations

import csv
import io
import re
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.finance import FinBudget, FinCategory, FinEntry

CURRENCIES = ("VND", "USD")
DEFAULT_CATEGORIES = [
    ("income", "sales", "Doanh thu bán hàng"), ("income", "services", "Doanh thu dịch vụ"), ("income", "other_income", "Thu khác"),
    ("expense", "cogs", "Giá vốn hàng bán"), ("expense", "materials", "Nguyên vật liệu"), ("expense", "payroll", "Lương & phụ cấp"),
    ("expense", "rent", "Thuê mặt bằng"), ("expense", "shipping", "Vận chuyển"), ("expense", "marketing", "Marketing & quảng cáo"),
    ("expense", "software", "Phần mềm & dịch vụ số"), ("expense", "utilities", "Điện nước, internet"),
    ("expense", "taxes_fees", "Thuế & phí"), ("expense", "other_expense", "Chi khác"),
]
ACCOUNTING_SCOPE = {
    "is_accounting_ledger": False,
    "out_of_scope": ["sổ kế toán theo TT 133/2016 hoặc TT 200/2014", "báo cáo tài chính năm", "tờ khai thuế",
                     "hoá đơn điện tử", "khấu hao TSCĐ", "công nợ phải thu/phải trả chi tiết"],
    "needs": "kế toán / dịch vụ kế toán hoặc phần mềm kế toán — dùng nút Xuất CSV",
}
PERIOD_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def _err(status, code, message, **extra):
    return HTTPException(status, {"error": code, "message": message, **extra})


def _company(db, org_id, company_id, *, write=False):
    from app.services.company_foundation import _company as c
    return c(db, org_id, company_id, write=write)


def _seat(principal, company_id):
    from app.services.doc_library import _seat as s
    return s(None, principal, company_id)


def today_vn() -> date:
    return (datetime.utcnow() + timedelta(hours=7)).date()


def _money(v, cur) -> Decimal:
    try:
        a = Decimal(str(v).replace(" ", "").replace("_", ""))
    except (InvalidOperation, ValueError):
        raise _err(422, "invalid_amount", "Số tiền phải là số") from None
    if a <= 0 or a >= Decimal("1e16"):
        raise _err(422, "invalid_amount", "Số tiền phải > 0")
    if cur == "VND" and a != a.to_integral_value():
        raise _err(422, "vnd_no_decimals", "VND không có phần lẻ")
    return a


def ensure_categories(db, org_id, company_id) -> list[FinCategory]:
    rows = db.query(FinCategory).filter(FinCategory.company_id == company_id).all()
    if not rows:
        for kind, key, name in DEFAULT_CATEGORIES:
            db.add(FinCategory(organization_id=org_id, company_id=company_id, kind=kind, key=key, name=name))
        db.commit()
        rows = db.query(FinCategory).filter(FinCategory.company_id == company_id).all()
    return rows


def public_category(c: FinCategory) -> dict:
    return {"id": c.id, "kind": c.kind, "key": c.key, "name": c.name, "active": c.active}


def _period_bounds(period: str) -> tuple[date, date]:
    if not PERIOD_RE.match(period or ""):
        raise _err(422, "invalid_period", "Kỳ dạng YYYY-MM")
    y, m = int(period[:4]), int(period[5:])
    start = date(y, m, 1)
    end = date(y + (m == 12), m % 12 + 1, 1)
    return start, end


def public_entry(db, e: FinEntry, cats: dict) -> dict:
    c = cats.get(e.category_id)
    return {"id": e.id, "kind": e.kind, "category": public_category(c) if c else None, "amount": float(e.amount), "currency": e.currency,
            "occurred_on": e.occurred_on.isoformat(), "description": e.description, "department_id": e.department_id,
            "partner_id": e.partner_id, "contact_id": e.contact_id, "contract_id": e.contract_id, "product_id": e.product_id,
            "quantity": float(e.quantity) if e.quantity is not None else None, "document_id": e.document_id, "status": e.status,
            "void_reason": e.void_reason, "source": e.source}


def overview(db, org_id, company_id, period: str | None = None) -> dict:
    co = _company(db, org_id, company_id)
    cats = {c.id: c for c in ensure_categories(db, org_id, co.id)}
    period = period or today_vn().strftime("%Y-%m")
    start, end = _period_bounds(period)
    entries = (db.query(FinEntry).filter(FinEntry.company_id == co.id, FinEntry.occurred_on >= start, FinEntry.occurred_on < end)
               .order_by(FinEntry.occurred_on.desc(), FinEntry.id.desc()).all())
    live = [e for e in entries if e.status == "recorded"]
    pnl: dict = {}
    for cur in sorted({e.currency for e in live} | {"VND"}):
        rows = [e for e in live if e.currency == cur]
        inc = sum((Decimal(str(e.amount)) for e in rows if e.kind == "income"), Decimal(0))
        exp = sum((Decimal(str(e.amount)) for e in rows if e.kind == "expense"), Decimal(0))
        by_cat: dict = {}
        for e in rows:
            by_cat[e.category_id] = by_cat.get(e.category_id, Decimal(0)) + Decimal(str(e.amount))
        pnl[cur] = {"income": float(inc), "expense": float(exp), "net": float(inc - exp),
                    "by_category": [{"category": public_category(cats[k]), "amount": float(v)} for k, v in
                                    sorted(by_cat.items(), key=lambda kv: (cats[kv[0]].kind, -kv[1]))]}
    # 6 tháng gần nhất (VND)
    trend = []
    y, m = start.year, start.month
    for _ in range(6):
        s, e_ = _period_bounds(f"{y:04d}-{m:02d}")
        q = (db.query(FinEntry.kind, func.sum(FinEntry.amount)).filter(FinEntry.company_id == co.id, FinEntry.status == "recorded",
                                                                       FinEntry.currency == "VND", FinEntry.occurred_on >= s,
                                                                       FinEntry.occurred_on < e_).group_by(FinEntry.kind).all())
        d = {k: float(v or 0) for k, v in q}
        trend.append({"period": f"{y:04d}-{m:02d}", "income": d.get("income", 0.0), "expense": d.get("expense", 0.0),
                      "net": d.get("income", 0.0) - d.get("expense", 0.0)})
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    trend.reverse()
    return {"company_id": co.id, "period": period, "categories": [public_category(c) for c in cats.values()],
            "entries": [public_entry(db, e, cats) for e in entries[:500]], "pnl": pnl, "trend": trend,
            "budgets": budget_status(db, co.id, period, cats=cats), "currencies": list(CURRENCIES),
            "accounting_scope": ACCOUNTING_SCOPE}


def budget_status(db, company_id, period, *, department_id: int | None = None, include_company_wide: bool = True,
                  cats: dict | None = None) -> list[dict]:
    cats = cats or {c.id: c for c in db.query(FinCategory).filter(FinCategory.company_id == company_id)}
    start, end = _period_bounds(period)
    q = db.query(FinBudget).filter(FinBudget.company_id == company_id, FinBudget.period == period)
    out = []
    for b in q.order_by(FinBudget.id).all():
        if department_id is not None and b.department_id not in ((department_id, None) if include_company_wide else (department_id,)):
            continue
        sq = db.query(func.sum(FinEntry.amount)).filter(FinEntry.company_id == company_id, FinEntry.category_id == b.category_id,
                                                        FinEntry.status == "recorded", FinEntry.currency == "VND",
                                                        FinEntry.occurred_on >= start, FinEntry.occurred_on < end)
        if b.department_id is not None:
            sq = sq.filter(FinEntry.department_id == b.department_id)
        spent = Decimal(str(sq.scalar() or 0))
        amt = Decimal(str(b.amount))
        pct = float(spent / amt * 100) if amt > 0 else 0.0
        c = cats.get(b.category_id)
        out.append({"id": b.id, "category": public_category(c) if c else None, "department_id": b.department_id, "period": b.period,
                    "budget": float(amt), "actual": float(spent), "remaining": float(amt - spent), "pct": round(pct, 1),
                    "alert_pct": b.alert_pct, "over": spent > amt, "alerting": pct >= b.alert_pct, "currency": "VND"})
    return out


def _cat(db, company_id, cid, kind=None) -> FinCategory:
    c = db.get(FinCategory, int(cid)) if cid else None
    if c is None or c.company_id != company_id:
        raise _err(404, "not_found", "Không thấy nhóm thu/chi")
    if kind and c.kind != kind:
        raise _err(422, "category_kind_mismatch", "Nhóm không khớp loại thu/chi")
    return c


def record(db, org_id, principal, data):
    co = _company(db, org_id, data.get("company_id"), write=True)
    from app.core import company_scope
    company_scope.check(co.id, min_role="manager")
    ensure_categories(db, org_id, co.id)
    kind = data.get("kind")
    if kind not in ("income", "expense"):
        raise _err(422, "invalid_kind", "kind: income | expense")
    cat = _cat(db, co.id, data.get("category_id"), kind)
    cur = str(data.get("currency") or "VND").upper()
    if cur not in CURRENCIES:
        raise _err(422, "invalid_currency", "Tiền tệ: VND | USD")
    e = FinEntry(organization_id=org_id, company_id=co.id, kind=kind, category_id=cat.id, currency=cur, amount=0,
                 occurred_on=today_vn(), description=str(data.get("description") or "")[:2000], source="manual",
                 created_by_member_id=_seat(principal, co.id))
    if data.get("occurred_on"):
        try:
            e.occurred_on = date.fromisoformat(str(data["occurred_on"])[:10])
        except ValueError:
            raise _err(422, "invalid_date", "Ngày không hợp lệ") from None
        if e.occurred_on > today_vn() + timedelta(days=1):
            raise _err(422, "future_date", "Không ghi thu chi cho ngày tương lai")
    # liên kết (cùng công ty)
    if data.get("product_id"):
        from app.models.catalog import CatalogProduct
        p = db.get(CatalogProduct, int(data["product_id"]))
        if p is None or p.company_id != co.id:
            raise _err(404, "not_found", "Sản phẩm không thuộc công ty này")
        e.product_id = p.id
        qty = Decimal(str(data.get("quantity") or 1))
        if qty <= 0:
            raise _err(422, "invalid_quantity", "Số lượng > 0")
        e.quantity = qty
        if data.get("amount") in (None, ""):
            from app.services import catalog
            pr = catalog.current_price(db, p.id)
            if pr is None:
                raise _err(422, "no_active_price", "Sản phẩm chưa có giá đang hiệu lực — nhập số tiền")
            if pr.currency != cur:
                raise _err(422, "currency_mismatch", "Tiền tệ khác giá sản phẩm")
            data = {**data, "amount": Decimal(str(pr.amount)) * qty}
            if not e.description:
                e.description = f"{p.sku} × {qty.normalize()}"
    for key, model_path in (("contract_id", "contracts.BizContract"), ("partner_id", "contracts.BizPartner"),
                            ("contact_id", "crm.CrmContact")):
        v = data.get(key)
        if v:
            mod, cls = model_path.split(".")
            import importlib
            M = getattr(importlib.import_module(f"app.models.{mod}"), cls)
            o = db.get(M, int(v))
            if o is None or o.company_id != co.id:
                raise _err(404, "not_found", f"{key} không thuộc công ty này")
            setattr(e, key, o.id)
    if data.get("department_id"):
        from app.models import Department
        d = db.get(Department, int(data["department_id"]))
        if d is None or d.company_id != co.id:
            raise _err(404, "not_found", "Phòng không thuộc công ty này")
        e.department_id = d.id
    if data.get("document_id"):
        from app.models import KnowledgeDocument
        d = db.get(KnowledgeDocument, int(data["document_id"]))
        if d is None or d.company_id != co.id:
            raise _err(404, "not_found", "Chứng từ không thuộc công ty này")
        e.document_id = d.id
    e.amount = _money(data.get("amount"), cur)
    db.add(e); db.flush()
    from app.services.company_event_bus import emit_event
    emit_event(db, organization_id=org_id, company_id=co.id, event_type="finance.entry_recorded", source="finance",
               aggregate_type="fin_entry", aggregate_id=str(e.id), actor_member_id=e.created_by_member_id,
               payload={"kind": kind, "amount": str(e.amount), "currency": cur, "category": cat.key or cat.name})
    db.commit(); db.refresh(e)
    return public_entry(db, e, {cat.id: cat})


def void(db, org_id, principal, eid, reason):
    e = db.get(FinEntry, eid)
    if e is None or e.organization_id != org_id:
        raise _err(404, "not_found", "Không thấy dòng thu chi")
    from app.core import company_scope
    company_scope.check(e.company_id, min_role="manager")
    if e.status == "void":
        raise _err(409, "already_void", "Dòng đã huỷ")
    if len((reason or "").strip()) < 5:
        raise _err(422, "reason_required", "Ghi lý do huỷ")
    e.status, e.void_reason, e.voided_by_member_id = "void", reason[:1000], _seat(principal, e.company_id)
    from app.services.company_event_bus import emit_event
    emit_event(db, organization_id=org_id, company_id=e.company_id, event_type="finance.entry_voided", source="finance",
               aggregate_type="fin_entry", aggregate_id=str(e.id), actor_member_id=e.voided_by_member_id, payload={"reason": reason[:300]})
    db.add(e); db.commit()
    return public_entry(db, e, {c.id: c for c in db.query(FinCategory).filter(FinCategory.id == e.category_id)})


def add_category(db, org_id, principal, data):
    co = _company(db, org_id, data.get("company_id"), write=True)
    from app.core import company_scope
    company_scope.check(co.id, min_role="manager")
    ensure_categories(db, org_id, co.id)
    kind, name = data.get("kind"), str(data.get("name") or "").strip()[:120]
    if kind not in ("income", "expense") or not name:
        raise _err(422, "invalid_category", "Cần loại (income|expense) và tên")
    if db.query(FinCategory.id).filter(FinCategory.company_id == co.id, FinCategory.kind == kind, FinCategory.name == name).first():
        raise _err(409, "category_exists", "Nhóm đã có")
    c = FinCategory(organization_id=org_id, company_id=co.id, kind=kind, name=name)
    db.add(c); db.commit(); db.refresh(c)
    return public_category(c)


def set_budget(db, org_id, principal, data):
    co = _company(db, org_id, data.get("company_id"), write=True)
    from app.core import company_scope
    company_scope.check(co.id, min_role="admin")       # ngân sách là quyết định của chủ / quản trị công ty
    cat = _cat(db, co.id, data.get("category_id"), "expense")
    period = str(data.get("period") or today_vn().strftime("%Y-%m"))
    _period_bounds(period)
    dep = data.get("department_id") or None
    if dep:
        from app.models import Department
        d = db.get(Department, int(dep))
        if d is None or d.company_id != co.id:
            raise _err(404, "not_found", "Phòng không thuộc công ty này")
        dep = d.id
    amt = _money(data.get("amount"), "VND")
    pct = int(data.get("alert_pct") or 80)
    if not 1 <= pct <= 100:
        raise _err(422, "invalid_alert_pct", "Ngưỡng cảnh báo 1..100%")
    b = db.query(FinBudget).filter(FinBudget.company_id == co.id, FinBudget.category_id == cat.id, FinBudget.period == period,
                                   FinBudget.department_id.is_(dep) if dep is None else FinBudget.department_id == dep).first()
    if b is None:
        b = FinBudget(organization_id=org_id, company_id=co.id, category_id=cat.id, department_id=dep, period=period, amount=amt,
                      created_by_member_id=_seat(principal, co.id))
    b.amount, b.alert_pct, b.alerted_at = amt, pct, None
    db.add(b); db.commit()
    return budget_status(db, co.id, period)


def export_csv(db, org_id, company_id, period) -> str:
    co = _company(db, org_id, company_id)
    cats = {c.id: c for c in ensure_categories(db, org_id, co.id)}
    start, end = _period_bounds(period)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id", "ngay", "loai", "nhom", "so_tien", "tien_te", "dien_giai", "trang_thai", "ly_do_huy", "hop_dong_id", "san_pham_id",
                "so_luong", "chung_tu_id"])
    for e in (db.query(FinEntry).filter(FinEntry.company_id == co.id, FinEntry.occurred_on >= start, FinEntry.occurred_on < end)
              .order_by(FinEntry.occurred_on, FinEntry.id)):
        w.writerow([e.id, e.occurred_on.isoformat(), e.kind, cats[e.category_id].name, f"{Decimal(str(e.amount)):f}", e.currency,
                    e.description, e.status, e.void_reason, e.contract_id or "", e.product_id or "",
                    f"{Decimal(str(e.quantity)):f}" if e.quantity is not None else "", e.document_id or ""])
    return buf.getvalue()


def tick(db: Session) -> int:
    from app.services import authority, inbox
    period = today_vn().strftime("%Y-%m")
    n = 0
    for b in db.query(FinBudget).filter(FinBudget.period == period, FinBudget.alerted_at.is_(None)).all():
        st = next((x for x in budget_status(db, b.company_id, period) if x["id"] == b.id), None)
        if st is None or not st["alerting"]:
            continue
        owner = authority.owner_member(db, b.organization_id, b.company_id)
        name = (st["category"] or {}).get("name", "")
        inbox.notify(db, organization_id=b.organization_id, recipients=[owner], kind="finance_budget", company_id=b.company_id,
                     title=f"Ngân sách {name} tháng {period}: đã chi {st['pct']}% ({int(st['actual']):,} / {int(st['budget']):,} ₫)".replace(",", "."),
                     related_type="fin_budget", related_id=str(b.id), priority="high" if st["over"] else "normal", commit=False)
        b.alerted_at = datetime.utcnow(); db.add(b); n += 1
    db.commit()
    return n


def agent_budget(db, member, *, category: str = "") -> dict:
    if not member.company_id:
        return {"budgets": [], "note": "Seat không thuộc công ty nào"}
    period = today_vn().strftime("%Y-%m")
    rows = budget_status(db, member.company_id, period, department_id=member.department_id) if member.department_id \
        else [x for x in budget_status(db, member.company_id, period) if x["department_id"] is None]
    if category:
        from app.services.knowledge_hub import unaccent
        u = unaccent(category).lower()
        rows = [x for x in rows if x["category"] and (u in unaccent(x["category"]["name"]).lower() or u == x["category"]["key"])]
    return {"period": period, "currency": "VND",
            "budgets": [{"category": x["category"]["name"] if x["category"] else None, "scope": "department" if x["department_id"] else "company",
                         "budget": int(x["budget"]), "spent": int(x["actual"]), "remaining": int(x["remaining"]), "pct_used": x["pct"],
                         "over": x["over"]} for x in rows],
            "rule": "Kiểm còn lại trước khi đề xuất chi; khoản chi vượt 'remaining' phải nói rõ là vượt ngân sách khi xin duyệt. "
                    "Đây là ngân sách kinh doanh (VND), không phải ngân sách model (USD).",
            **({} if rows else {"note": "Chưa đặt ngân sách tháng này cho nhóm/phòng này — hỏi người phụ trách, đừng đoán"})}
