"""M3f — eval tra giá (app/evals/catalog_gom_moc.json): gieo danh mục mẫu vào một công ty rồi hỏi 20 câu qua đúng hàm mà
MCP company_product_lookup dùng. Đo: top-1 đúng sản phẩm, giá trả về đúng giá đang hiệu lực, và SỐ GIÁ BỊA = mọi giá xuất hiện
trong kết quả (ở bất kỳ hạng nào) khác giá đang hiệu lực tính độc lập từ catalog_prices. Không gọi model."""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy.orm import Session

from app.models.catalog import CatalogPrice, CatalogProduct
from app.services import catalog

EVAL = Path(__file__).resolve().parents[1] / "evals" / "catalog_gom_moc.json"


def load() -> dict:
    return json.loads(EVAL.read_text(encoding="utf-8"))


def seed(db: Session, org_id: int, company_id: int) -> dict:
    """Gieo trực tiếp (bỏ qua duyệt — dữ liệu eval, decided_by trống). Đã có SKU → bỏ qua."""
    now, made = datetime.utcnow(), 0
    for spec in load()["products"]:
        if db.query(CatalogProduct.id).filter(CatalogProduct.company_id == company_id, CatalogProduct.sku == spec["sku"]).first():
            continue
        p = CatalogProduct(organization_id=org_id, company_id=company_id, sku=spec["sku"], name=spec["name"],
                           category=spec.get("category", ""), unit=spec.get("unit", "cái"), kind=spec.get("kind", "product"),
                           status="discontinued" if spec.get("discontinued") else "active", policies=spec.get("policies"),
                           description=f"{spec['name']} — hàng của Tiệm Gốm Mộc (dữ liệu eval M3f).")
        p.search_text = catalog._u(f"{p.sku} {p.name} {p.category}")
        db.add(p); db.flush(); made += 1
        mk = lambda **kw: db.add(CatalogPrice(organization_id=org_id, company_id=company_id, product_id=p.id, currency="VND",  # noqa: E731
                                              note="eval M3f", **kw))
        if spec.get("price") and spec.get("expired"):
            mk(amount=spec["price"], status="approved", effective_from=now - timedelta(days=60), effective_to=now - timedelta(days=1),
               decided_at=now)
        elif spec.get("price"):
            end = now + timedelta(days=1) if spec.get("scheduled") else None
            mk(amount=spec["price"], status="approved", effective_from=now - timedelta(days=30), effective_to=end, decided_at=now)
            if spec.get("scheduled"):
                mk(amount=spec["scheduled"], status="approved", effective_from=end, decided_at=now)
        if spec.get("pending_only"):
            mk(amount=spec["pending_only"], status="pending", effective_from=now, risk="high")
    db.commit()
    return {"seeded": made}


def run(db: Session, company_id: int) -> dict:
    data = load()
    truth = {}
    for p in db.query(CatalogProduct).filter(CatalogProduct.company_id == company_id):
        cur = catalog.current_price(db, p.id)
        truth[p.sku] = catalog.fmt_money(cur.amount, cur.currency) if cur and p.status == "active" else None
    rows, top_ok, price_ok, fabricated = [], 0, 0, 0
    for q in data["questions"]:
        res = catalog.lookup(db, company_id, query=q.get("q", ""), sku=q.get("sku_lookup", ""))
        prods = res["products"]
        top = prods[0] if prods else None
        got = (top or {}).get("price") or {}
        ok_top = bool(top and top["sku"] == q["sku"])
        ok_price = ok_top and (got.get("display") if got else None) == q["display"]
        fab = sum(1 for x in prods if x.get("price") and x["price"]["display"] != truth.get(x["sku"]))
        top_ok += ok_top; price_ok += ok_price; fabricated += fab
        rows.append({"q": q.get("q") or "sku=" + q["sku_lookup"], "want": q["sku"], "got": top and top["sku"],
                     "price": got.get("display") if got else None, "expected": q["display"], "ok": ok_price, "fabricated": fab})
    n = len(data["questions"])
    return {"questions": n, "top1": round(top_ok / n, 3), "price_correct": round(price_ok / n, 3), "fabricated_prices": fabricated,
            "rows": rows}
