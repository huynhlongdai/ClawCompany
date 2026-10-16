"""M3f — sản phẩm/dịch vụ & bảng giá. Spec: docs/company-knowledge-library-and-gaps.md §B2, §C M3f.

* Giá là DỮ LIỆU có cấu trúc + lịch sử, không phải đoạn văn RAG. Mỗi lần đổi giá = một dòng ``catalog_prices`` mới
  (``pending`` → ``approved``/``rejected``); dòng đã duyệt không sửa. Giá đang áp dụng tại thời điểm t = dòng ``approved``
  cùng kênh có ``effective_from ≤ t < effective_to`` (mới nhất thắng). Giá hết hiệu lực / chờ duyệt không bao giờ trả cho agent.
* Tiền: mặc định VND (tiền kinh doanh của khách Việt, không có phần lẻ); USD được phép cho công ty bán bằng USD. Chi phí
  nền tảng vẫn là USD ở chỗ khác — hai thứ không quy đổi lẫn nhau.
* Đổi giá đi qua ma trận phân quyền, loại việc ``price_change``: rủi ro theo % thay đổi so với giá đang áp dụng
  (< ``HIGH_PCT`` → trưởng phòng; ≥ ``HIGH_PCT`` hoặc sản phẩm chưa có giá → chủ). Người xin là người có quyền duyệt → duyệt ngay.
* Agent đọc qua MCP ``company_product_lookup`` (chỉ tool, không vào AGENTS.md): sản phẩm đang bán + giá đang hiệu lực +
  chính sách (riêng của sản phẩm, không có thì lấy sự kiện công ty M3b) + tài liệu mô tả ``product_sheet`` (M3a)."""
from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal, InvalidOperation

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import Approval, KnowledgeDocument, Member
from app.models.catalog import CatalogPrice, CatalogProduct, PRODUCT_STATUSES

CURRENCIES = ("VND", "USD")
HIGH_PCT = 10            # đổi giá từ 10% trở lên (tăng hoặc giảm) = rủi ro cao → chủ duyệt
KINDS = ("product", "service")
SKU_RE = re.compile(r"^[A-Z0-9][A-Z0-9._-]{0,63}$")
POLICY_KEYS = {"return_days": int, "warranty_months": int, "note": str}


def fmt_money(amount, currency: str) -> str:
    a = Decimal(str(amount))
    if currency == "VND":
        return f"{int(a):,}".replace(",", ".") + " ₫"
    return f"${a:,.2f}" if currency == "USD" else f"{a} {currency}"


def _u(s: str) -> str:
    from app.services.knowledge_hub import unaccent
    return re.sub(r"\s+", " ", unaccent(s or "").lower()).strip()


def _company(db: Session, org_id: int, company_id: int | None, *, write: bool = False):
    from app.services.company_foundation import _company as c
    return c(db, org_id, company_id, write=write)


def _seat(principal, company_id: int | None) -> int | None:
    from app.services.doc_library import _seat as s
    return s(None, principal, company_id)


def _product(db: Session, org_id: int, pid: int) -> CatalogProduct:
    p = db.get(CatalogProduct, pid)
    if p is None or p.organization_id != org_id:
        raise HTTPException(404, "Không thấy sản phẩm")
    from app.core import company_scope
    company_scope.check(p.company_id)
    return p


def _dt(v) -> datetime | None:
    if v in (None, ""):
        return None
    if isinstance(v, datetime):
        return v
    try:
        return datetime.fromisoformat(str(v).replace("Z", ""))
    except ValueError:
        raise HTTPException(422, f"Ngày không hợp lệ: {v}") from None


def _amount(v, currency: str) -> Decimal:
    try:
        a = Decimal(str(v).replace(" ", "").replace("_", ""))
    except (InvalidOperation, ValueError):
        raise HTTPException(422, "Giá phải là số") from None
    if a <= 0:
        raise HTTPException(422, "Giá phải lớn hơn 0")
    if currency == "VND" and a != a.to_integral_value():
        raise HTTPException(422, "Giá VND không có phần lẻ (vd 350000)")
    if a >= Decimal("1e14"):
        raise HTTPException(422, "Giá quá lớn")
    return a


# ------------------------------------------------------------------ giá đang áp dụng

def prices_of(db: Session, product_id: int) -> list[CatalogPrice]:
    return (db.query(CatalogPrice).filter(CatalogPrice.product_id == product_id)
            .order_by(CatalogPrice.effective_from.desc(), CatalogPrice.id.desc()).all())


def current_price(db: Session, product_id: int, *, at: datetime | None = None, channel: str = "default",
                  rows: list[CatalogPrice] | None = None) -> CatalogPrice | None:
    at = at or datetime.utcnow()
    for p in rows if rows is not None else prices_of(db, product_id):
        if (p.status == "approved" and p.channel == channel and p.effective_from <= at
                and (p.effective_to is None or p.effective_to > at)):
            return p
    return None


def has_active_prices(db: Session, company_id: int) -> bool:
    """Dùng ở M3d (mục 'Bảng giá hiện hành'): công ty có ít nhất một sản phẩm đang bán với giá đang hiệu lực."""
    now = datetime.utcnow()
    q = (db.query(CatalogPrice.id).join(CatalogProduct, CatalogProduct.id == CatalogPrice.product_id)
         .filter(CatalogProduct.company_id == company_id, CatalogProduct.status == "active", CatalogPrice.status == "approved",
                 CatalogPrice.effective_from <= now)
         .filter((CatalogPrice.effective_to.is_(None)) | (CatalogPrice.effective_to > now)))
    return q.first() is not None


# ------------------------------------------------------------------ biểu diễn

def public_price(p: CatalogPrice | None) -> dict | None:
    if p is None:
        return None
    return {"id": p.id, "amount": float(p.amount), "currency": p.currency, "display": fmt_money(p.amount, p.currency),
            "channel": p.channel, "status": p.status, "risk": p.risk,
            "change_pct": float(p.change_pct) if p.change_pct is not None else None,
            "effective_from": p.effective_from.isoformat(), "effective_to": p.effective_to.isoformat() if p.effective_to else None,
            "note": p.note, "approval_id": p.approval_id, "requested_by_member_id": p.requested_by_member_id,
            "approver_member_id": p.approver_member_id, "decided_by_member_id": p.decided_by_member_id,
            "decided_at": p.decided_at.isoformat() if p.decided_at else None, "review_note": p.review_note,
            "created_at": p.created_at.isoformat() if p.created_at else None}


def _doc_ref(db: Session, doc_id: int | None) -> dict | None:
    d = db.get(KnowledgeDocument, doc_id) if doc_id else None
    return {"id": d.id, "doc_code": d.doc_code, "title": d.title, "status": d.status, "version_no": d.version_no} if d else None


def public(db: Session, p: CatalogProduct, *, detail: bool = False) -> dict:
    rows = prices_of(db, p.id)
    cur = current_price(db, p.id, rows=rows)
    out = {"id": p.id, "company_id": p.company_id, "sku": p.sku, "name": p.name, "description": p.description, "kind": p.kind,
           "category": p.category, "unit": p.unit, "status": p.status, "policies": p.policies or {},
           "document": _doc_ref(db, p.document_id), "current_price": public_price(cur),
           "pending_price": public_price(next((x for x in rows if x.status == "pending"), None)),
           "scheduled_price": public_price(next((x for x in rows if x.status == "approved" and x.effective_from > datetime.utcnow()), None)),
           "updated_at": p.updated_at.isoformat() if p.updated_at else None}
    if detail:
        names = {m.id: m.name for m in db.query(Member).filter(Member.id.in_(
            {x for r in rows for x in (r.requested_by_member_id, r.approver_member_id, r.decided_by_member_id) if x} or {-1}))}
        out["history"] = [{**public_price(r), "requested_by": names.get(r.requested_by_member_id),
                           "approver": names.get(r.approver_member_id), "decided_by": names.get(r.decided_by_member_id),
                           "in_effect": cur is not None and r.id == cur.id,
                           "expired": r.status == "approved" and r.effective_to is not None and r.effective_to <= datetime.utcnow()}
                          for r in rows]
    return out


def listing(db: Session, org_id: int, company_id: int | None, *, q: str = "", status: str = "") -> dict:
    co = _company(db, org_id, company_id)
    rows = db.query(CatalogProduct).filter(CatalogProduct.company_id == co.id)
    if status:
        rows = rows.filter(CatalogProduct.status == status)
    items = [public(db, p) for p in rows.order_by(CatalogProduct.sku).limit(1000)]
    if q:
        uq = _u(q)
        items = [i for i in items if uq in _u(f"{i['sku']} {i['name']} {i['category']}")]
    return {"company_id": co.id, "items": items, "currencies": list(CURRENCIES), "kinds": list(KINDS), "statuses": list(PRODUCT_STATUSES),
            "high_pct": HIGH_PCT, "counts": {"total": len(items), "priced": sum(1 for i in items if i["current_price"]),
                                             "pending": sum(1 for i in items if i["pending_price"])}}


# ------------------------------------------------------------------ sản phẩm

def _policies(v) -> dict:
    if v is None:
        return {}
    if not isinstance(v, dict):
        raise HTTPException(422, "policies phải là object")
    out = {}
    for k, val in v.items():
        if k not in POLICY_KEYS or val in (None, ""):
            continue
        if POLICY_KEYS[k] is int:
            try:
                val = int(val)
            except (TypeError, ValueError):
                raise HTTPException(422, f"{k} phải là số nguyên") from None
            if val < 0:
                raise HTTPException(422, f"{k} không âm")
        else:
            val = str(val)[:500]
        out[k] = val
    return out


def _apply_meta(db: Session, p: CatalogProduct, data: dict) -> None:
    for k, lim in (("name", 220), ("description", 4000), ("category", 120), ("unit", 32)):
        if data.get(k) is not None:
            setattr(p, k, str(data[k]).strip()[:lim])
    if data.get("kind") is not None:
        if data["kind"] not in KINDS:
            raise HTTPException(422, "kind: product | service")
        p.kind = data["kind"]
    if data.get("status") is not None:
        if data["status"] not in PRODUCT_STATUSES:
            raise HTTPException(422, f"status: {' | '.join(PRODUCT_STATUSES)}")
        p.status = data["status"]
    if "policies" in data:
        p.policies = _policies(data["policies"]) or None
    if "document_id" in data:
        did = data["document_id"]
        if did:
            d = db.get(KnowledgeDocument, int(did))
            if d is None or d.company_id != p.company_id:
                raise HTTPException(404, "Không thấy tài liệu mô tả trong công ty này")
            p.document_id = d.id
        else:
            p.document_id = None
    if not (p.name or "").strip():
        raise HTTPException(422, "Thiếu tên sản phẩm")
    p.search_text = _u(f"{p.sku} {p.name} {p.category}")
    p.updated_at = datetime.utcnow()


def create_product(db: Session, org_id: int, principal, data: dict) -> dict:
    co = _company(db, org_id, data.get("company_id"), write=True)
    sku = str(data.get("sku") or "").strip().upper()
    if not SKU_RE.match(sku):
        raise HTTPException(422, "Mã SKU chỉ gồm chữ in, số, '-', '_', '.' (tối đa 64)")
    if db.query(CatalogProduct.id).filter(CatalogProduct.company_id == co.id, CatalogProduct.sku == sku).first():
        raise HTTPException(409, f"Mã {sku} đã có trong công ty")
    seat = _seat(principal, co.id)
    p = CatalogProduct(organization_id=org_id, company_id=co.id, sku=sku, name="", created_by_member_id=seat, status="active")
    _apply_meta(db, p, {"kind": "product", **data})
    db.add(p); db.flush()
    from app.services.company_event_bus import emit_event
    emit_event(db, organization_id=org_id, company_id=co.id, event_type="catalog.product_created", source="catalog",
               aggregate_type="product", aggregate_id=str(p.id), actor_member_id=seat, payload={"sku": sku})
    db.commit(); db.refresh(p)
    out = {"price_request": None}
    if data.get("price") not in (None, ""):
        out["price_request"] = propose_price(db, org_id, principal, p.id, {"amount": data["price"], "currency": data.get("currency"),
                                                                          "effective_from": data.get("effective_from"),
                                                                          "note": data.get("price_note") or "Giá đầu tiên"})
    return {**public(db, p, detail=True), **out}


def update_product(db: Session, org_id: int, principal, pid: int, data: dict) -> dict:
    """Sửa thông tin sản phẩm (KHÔNG sửa giá — giá đổi qua propose_price + duyệt)."""
    if any(k in data for k in ("price", "amount", "currency")):
        raise HTTPException(422, "Đổi giá qua 'Đề xuất giá mới' (đi theo ma trận duyệt), không sửa trực tiếp")
    p = _product(db, org_id, pid)
    before = (p.status, p.name)
    _apply_meta(db, p, data)
    from app.services.company_event_bus import emit_event
    emit_event(db, organization_id=org_id, company_id=p.company_id, event_type="catalog.product_changed", source="catalog",
               aggregate_type="product", aggregate_id=str(p.id), actor_member_id=_seat(principal, p.company_id),
               payload={"before": {"status": before[0], "name": before[1]}, "fields": sorted(data)})
    db.add(p); db.commit(); db.refresh(p)
    return public(db, p, detail=True)


def get_product(db: Session, org_id: int, pid: int) -> dict:
    return public(db, _product(db, org_id, pid), detail=True)


# ------------------------------------------------------------------ đổi giá (ma trận price_change)

def propose_price(db: Session, org_id: int, principal, pid: int, data: dict, *, requester: Member | None = None) -> dict:
    p = _product(db, org_id, pid)
    cur_code = str(data.get("currency") or "VND").upper()
    if cur_code not in CURRENCIES:
        raise HTTPException(422, f"Tiền tệ: {' | '.join(CURRENCIES)}")
    amount = _amount(data.get("amount"), cur_code)
    channel = str(data.get("channel") or "default").strip()[:32] or "default"
    now = datetime.utcnow()
    start = _dt(data.get("effective_from")) or now
    end = _dt(data.get("effective_to"))
    if end is not None and end <= start:
        raise HTTPException(422, "Hiệu lực đến phải sau hiệu lực từ")
    if db.query(CatalogPrice.id).filter(CatalogPrice.product_id == p.id, CatalogPrice.channel == channel,
                                        CatalogPrice.status == "pending").first():
        raise HTTPException(409, "Sản phẩm đang có một đề xuất giá chờ duyệt cho kênh này — duyệt / huỷ nó trước")
    base = current_price(db, p.id, at=max(start, now), channel=channel)
    pct = None
    if base is not None and base.currency == cur_code and Decimal(str(base.amount)) > 0:
        pct = (amount - Decimal(str(base.amount))) / Decimal(str(base.amount)) * 100
    risk = "high" if pct is None or abs(pct) >= HIGH_PCT else "normal"
    seat = requester.id if requester is not None else _seat(principal, p.company_id)
    req_m = requester or (db.get(Member, seat) if seat else None)
    from app.services import authority
    authority.ensure_action_defaults(db, org_id, p.company_id, "price_change")
    d = authority.decide(db, req_m, "price_change", risk=risk, company_id=p.company_id)
    approver = d.approver_member_id if d is not None else authority.owner_member(db, org_id, p.company_id)
    row = CatalogPrice(organization_id=org_id, company_id=p.company_id, product_id=p.id, channel=channel, amount=amount,
                       currency=cur_code, effective_from=start, effective_to=end, status="pending",
                       previous_price_id=base.id if base else None, change_pct=round(pct, 2) if pct is not None else None,
                       risk=risk, note=str(data.get("note") or "")[:2000], requested_by_member_id=seat, approver_member_id=approver)
    db.add(row); db.flush()
    from app.services.company_event_bus import emit_event
    emit_event(db, organization_id=org_id, company_id=p.company_id, event_type="catalog.price_proposed", source="catalog",
               aggregate_type="product", aggregate_id=str(p.id), actor_member_id=seat,
               payload={"price_id": row.id, "amount": str(amount), "currency": cur_code, "change_pct": float(pct) if pct is not None else None})
    self_ok = (req_m is not None and req_m.member_type == "human" and approver == req_m.id) or \
              (d is not None and d.approver_kind == "none" and (req_m is None or req_m.member_type == "human"))
    if self_ok:
        db.commit()
        _decide(db, row, "approved", seat, note=(d.reason if d else "Người đề xuất là người có quyền duyệt"))
        return {**public_price(row), "authority": d.card() if d else None, "auto_approved": True}
    change = (f"{fmt_money(base.amount, base.currency)} → " if base else "giá mới ") + fmt_money(amount, cur_code)
    a = Approval(organization_id=org_id, company_id=p.company_id, requester_member_id=seat, approver_member_id=approver,
                 action=f"Đổi giá {p.sku} {p.name}: {change}"[:220], risk=risk, policy_key=f"price_change:{row.id}",
                 status="pending",
                 evidence=(f"{change}" + (f" ({float(pct):+.1f}%)" if pct is not None else " (chưa có giá đang áp dụng)")
                           + f"; hiệu lực từ {start:%d/%m/%Y %H:%M}" + (f" đến {end:%d/%m/%Y}" if end else "")
                           + (f"\n{row.note}" if row.note else ""))[:2000],
                 payload=authority.annotate({"product_id": p.id, "price_id": row.id, "sku": p.sku, "amount": str(amount),
                                             "currency": cur_code}, d))
    db.add(a); db.flush()
    row.approval_id = a.id
    db.add(row); db.commit()
    return {**public_price(row), "authority": d.card() if d else None, "auto_approved": False}


def _decide(db: Session, row: CatalogPrice, decision: str, actor: int | None, *, note: str = "") -> CatalogPrice:
    now = datetime.utcnow()
    row.status = "approved" if decision == "approved" else "rejected"
    row.decided_by_member_id, row.decided_at, row.review_note = actor, now, (note or "")[:2000]
    if row.status == "approved":
        if row.effective_from < now:
            row.effective_from = now          # duyệt muộn: giá có hiệu lực từ lúc duyệt, không hồi tố
        # giá cũ cùng kênh còn mở → đóng tại mốc hiệu lực của giá mới (lịch sử giữ nguyên)
        for old in db.query(CatalogPrice).filter(CatalogPrice.product_id == row.product_id, CatalogPrice.channel == row.channel,
                                                 CatalogPrice.status == "approved", CatalogPrice.id != row.id,
                                                 CatalogPrice.effective_from < row.effective_from):
            if old.effective_to is None or old.effective_to > row.effective_from:
                old.effective_to = row.effective_from; db.add(old)
    db.add(row)
    from app.services.company_event_bus import emit_event
    emit_event(db, organization_id=row.organization_id, company_id=row.company_id, event_type=f"catalog.price_{row.status}",
               source="catalog", aggregate_type="product", aggregate_id=str(row.product_id), actor_member_id=actor,
               payload={"price_id": row.id, "amount": str(row.amount), "currency": row.currency})
    db.commit(); db.refresh(row)
    return row


def decide_price(db: Session, org_id: int, principal, price_id: int, decision: str, note: str = "") -> dict:
    if decision not in ("approved", "rejected"):
        raise HTTPException(422, "decision phải là approved hoặc rejected")
    row = db.get(CatalogPrice, price_id)
    if row is None or row.organization_id != org_id:
        raise HTTPException(404, "Không thấy đề xuất giá")
    from app.core import company_scope
    company_scope.check(row.company_id)
    if row.status != "pending":
        raise HTTPException(409, f"Đề xuất giá đang '{row.status}' — không chờ duyệt")
    me = set(getattr(principal, "member_ids", []) or [])
    if row.requested_by_member_id and row.requested_by_member_id in me and row.approver_member_id != row.requested_by_member_id:
        raise HTTPException(403, "Người đề xuất không tự duyệt giá của mình")
    if row.approver_member_id not in me and getattr(principal, "role", "") != "owner":
        raise HTTPException(403, {"error": "not_the_approver", "approver_member_id": row.approver_member_id,
                                  "message": "Không phải người duyệt theo ma trận (price_change)"})
    if decision == "rejected" and not (note or "").strip():
        raise HTTPException(422, "Ghi lý do từ chối")
    actor = row.approver_member_id if row.approver_member_id in me else _seat(principal, row.company_id)
    if row.approval_id:
        a = db.get(Approval, row.approval_id)
        if a is not None and a.status == "pending":
            a.status, a.resolution_note = decision, (note or "")[:2000]; db.add(a)
    _decide(db, row, decision, actor, note=note)
    return public(db, db.get(CatalogProduct, row.product_id), detail=True)


def cancel_price(db: Session, org_id: int, principal, price_id: int) -> dict:
    row = db.get(CatalogPrice, price_id)
    if row is None or row.organization_id != org_id:
        raise HTTPException(404, "Không thấy đề xuất giá")
    from app.core import company_scope
    company_scope.check(row.company_id)
    if row.status != "pending":
        raise HTTPException(409, "Chỉ huỷ được đề xuất đang chờ duyệt")
    row.status = "cancelled"; row.decided_at = datetime.utcnow(); db.add(row)
    if row.approval_id:
        a = db.get(Approval, row.approval_id)
        if a is not None and a.status == "pending":
            a.status, a.resolution_note = "cancelled", "Người đề xuất huỷ"; db.add(a)
    db.commit()
    return public(db, db.get(CatalogProduct, row.product_id), detail=True)


def on_approval_resolved(db: Session, a: Approval, *, actor_member_id: int | None) -> None:
    """Approval price_change:<id> duyệt từ Hộp việc hoặc /api/approvals/{id}/resolve."""
    try:
        pid = int((a.policy_key or "").split(":")[1])
    except (IndexError, ValueError):
        return
    row = db.get(CatalogPrice, pid)
    if row is None or row.status != "pending":
        return
    _decide(db, row, "approved" if a.status == "approved" else "rejected", actor_member_id or a.approver_member_id,
            note=a.resolution_note or "")


# ------------------------------------------------------------------ agent tra cứu (MCP company_product_lookup)

def _score(p: CatalogProduct, words: list[str]) -> float:
    st = p.search_text or _u(f"{p.sku} {p.name} {p.category}")
    toks = set(st.split())
    return sum(1.0 if w in toks else (0.5 if len(w) > 2 and w in st else 0.0) for w in words) / max(1, len(words))


def lookup(db: Session, company_id: int | None, *, query: str = "", sku: str = "", channel: str = "default",
           limit: int = 5) -> dict:
    """Chỉ sản phẩm đang bán (hoặc ngừng bán — gắn cờ) + giá ĐANG hiệu lực. Không giá → nói rõ, cấm đoán."""
    if not company_id:
        return {"products": [], "note": "Seat không thuộc công ty nào"}
    rows = db.query(CatalogProduct).filter(CatalogProduct.company_id == company_id, CatalogProduct.status.in_(("active", "discontinued")))
    if sku:
        rows = rows.filter(CatalogProduct.sku == sku.strip().upper())
        hits = [(1.0, p) for p in rows.all()]
    else:
        words = [w for w in _u(query).split() if w not in {"gia", "bao", "nhieu", "tien", "cai", "cua", "la", "con", "khong", "ban"}]
        hits = sorted(((s, p) for p in rows.all() if (s := _score(p, words)) > 0), key=lambda x: (-x[0], x[1].sku)) if words else []
    from app.services import company_facts
    facts = {f["key"]: f for f in company_facts.for_agent(db, company_id).get("facts", [])}
    out = []
    for s, p in hits[:max(1, min(limit, 10))]:
        cur = current_price(db, p.id, channel=channel) or (current_price(db, p.id) if channel != "default" else None)
        pol = dict(p.policies or {})
        policies = {}
        for k, fk in (("return_days", "return_window_days"), ("warranty_months", "warranty_months")):
            if k in pol:
                policies[k] = {"value": pol[k], "source": f"sản phẩm {p.sku}"}
            elif fk in facts:
                policies[k] = {"value": facts[fk]["value"], "source": facts[fk]["source"], "conflict": facts[fk]["conflict"]}
        if pol.get("note"):
            policies["note"] = pol["note"]
        doc = db.get(KnowledgeDocument, p.document_id) if p.document_id else None
        live_doc = doc is not None and doc.status == "published"
        out.append({"sku": p.sku, "name": p.name, "kind": p.kind, "unit": p.unit, "category": p.category,
                    "status": p.status, "match": round(s, 2),
                    "price": ({"amount": float(cur.amount), "currency": cur.currency, "display": fmt_money(cur.amount, cur.currency),
                               "per": p.unit, "channel": cur.channel, "effective_from": cur.effective_from.date().isoformat(),
                               "valid_until": cur.effective_to.isoformat() if cur.effective_to else None} if cur and p.status == "active" else None),
                    "policies": policies, "description": (p.description or "")[:600],
                    "product_sheet": {"doc_code": doc.doc_code, "cite": f"[DOC:{doc.doc_code} v{doc.version_no}]"} if live_doc else None,
                    **({"warning": "Sản phẩm đã NGỪNG BÁN — không báo giá, đề xuất sản phẩm khác"} if p.status == "discontinued"
                       else {} if cur else {"warning": "Chưa có giá đang hiệu lực — KHÔNG báo giá, chuyển người phụ trách"})})
    return {"products": out, "currency_note": "Giá bán của công ty; VND không có phần lẻ. Chỉ báo đúng 'display', không làm tròn/ước lượng.",
            **({} if out else {"note": "Không thấy sản phẩm khớp — đừng đoán giá; hỏi lại tên/mã hoặc chuyển người phụ trách"})}
