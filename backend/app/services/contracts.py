"""M3h — hợp đồng & đối tác. Spec: docs/company-knowledge-library-and-gaps.md §C M3h.

* Vòng đời: ``draft`` → (gửi ký) ``pending`` → duyệt theo ma trận loại việc ``contract`` (mặc định: chủ) → ``active`` (hoặc
  ``rejected`` → sửa → gửi lại). Người xin là người có quyền ký → duyệt ngay. Agent / người đề xuất không tự duyệt.
  Hợp đồng đã ký: điều khoản, giá trị, ngày KHÔNG sửa (409) — muốn đổi thì làm phụ lục = hợp đồng mới; chỉ gắn bản ký,
  đổi người phụ trách, chấm dứt.
* Tiền: giá trị hợp đồng mặc định VND (không phần lẻ), không quy đổi sang USD; ma trận thẩm quyền tiền tính USD (chi phí nền tảng)
  nên ``contract`` đi theo luật không dải tiền (``amount_usd=None``), rủi ro truyền qua ``risk``.
* Hạn: hạn báo trước = ngày hết hạn − số ngày báo trước. Hợp đồng hiệu lực → luật lịch tuân thủ ``contract_notice:<id>`` /
  ``contract_end:<id>`` (một lần, hiện trong Công ty › Vận hành › Tuân thủ). ``tick``: còn ≤ 30 ngày tới mốc → MỘT việc + thẻ
  Hộp việc ``contract_due`` cho người phụ trách + chủ (hạn tương ứng trong lịch đánh dấu đã nhắc, nối cùng việc); quá ngày hết
  hạn: tự gia hạn (nếu có) thì cộng ``renewal_months``, không thì ``expired``.
* Agent đọc qua MCP ``company_contract_get``: hợp đồng ĐANG HIỆU LỰC của công ty, điều khoản chính + SLA có cấu trúc + ngày;
  không trả nội dung tệp ký, không trả giá trị hợp đồng (thông tin thương mại)."""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import Approval, KnowledgeDocument, Member
from app.models.contracts import CONTRACT_KINDS, PARTNER_KINDS, BizContract, BizPartner

CURRENCIES = ("VND", "USD")
REMIND_DAYS = 30
SLA_KEYS = {"response_hours": int, "delivery_days": int, "payment_days": int, "warranty_months": int, "uptime_pct": float,
            "penalty": str}
LOCKED = ("title", "kind", "partner_id", "value_amount", "currency", "start_date", "end_date", "auto_renew", "renewal_months",
          "notice_days", "sla", "key_terms", "code")
CODE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9./_-]{0,47}$")


def _err(status: int, code: str, message: str, **extra) -> HTTPException:
    return HTTPException(status, {"error": code, "message": message, **extra})


def _company(db, org_id, company_id, *, write=False):
    from app.services.company_foundation import _company as c
    return c(db, org_id, company_id, write=write)


def _seat(principal, company_id):
    from app.services.doc_library import _seat as s
    return s(None, principal, company_id)


def _u(s: str) -> str:
    from app.services.knowledge_hub import unaccent
    return re.sub(r"\s+", " ", unaccent(s or "").lower()).strip()


def _name(db, mid):
    m = db.get(Member, mid) if mid else None
    return m.name if m else None


def _event(db, row, kind, actor, payload):
    from app.services.company_event_bus import emit_event
    emit_event(db, organization_id=row.organization_id, company_id=row.company_id, event_type=kind, source="contracts",
               aggregate_type="contract" if isinstance(row, BizContract) else "partner", aggregate_id=str(row.id),
               actor_member_id=actor, payload=payload)


def _date(v) -> date | None:
    if v in (None, ""):
        return None
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        raise _err(422, "invalid_date", f"Ngày không hợp lệ: {v}") from None


def today_vn() -> date:
    return (datetime.utcnow() + timedelta(hours=7)).date()


# ------------------------------------------------------------------ đối tác

def public_partner(db: Session, p: BizPartner) -> dict:
    n_active = db.query(BizContract.id).filter(BizContract.partner_id == p.id, BizContract.status == "active").count()
    return {"id": p.id, "company_id": p.company_id, "kind": p.kind, "name": p.name, "tax_code": p.tax_code,
            "contact_person": p.contact_person, "phone": p.phone, "email": p.email, "address": p.address, "rating": p.rating,
            "notes": p.notes, "status": p.status, "active_contracts": n_active}


def _partner(db, org_id, pid, *, write=False) -> BizPartner:
    p = db.get(BizPartner, pid)
    if p is None or p.organization_id != org_id:
        raise _err(404, "not_found", "Không thấy đối tác")
    from app.core import company_scope
    company_scope.check(p.company_id, min_role="manager" if write else None)
    return p


def _apply_partner(p: BizPartner, data: dict) -> None:
    for k, lim in (("name", 220), ("contact_person", 160), ("phone", 40), ("email", 200), ("address", 1000), ("notes", 4000)):
        if data.get(k) is not None:
            setattr(p, k, str(data[k]).strip()[:lim])
    if data.get("kind") is not None:
        if data["kind"] not in PARTNER_KINDS:
            raise _err(422, "invalid_kind", "Loại đối tác không hợp lệ", allowed=list(PARTNER_KINDS))
        p.kind = data["kind"]
    if data.get("tax_code") is not None:
        t = str(data["tax_code"]).strip()
        if t and not re.match(r"^\d{10}(-\d{3})?$", t):
            raise _err(422, "invalid_tax_code", "MST gồm 10 chữ số (chi nhánh: 10 số + '-' + 3 số)")
        p.tax_code = t
    if "rating" in data:
        r = data["rating"]
        if r not in (None, ""):
            try:
                r = int(r)
            except (TypeError, ValueError):
                raise _err(422, "invalid_rating", "Đánh giá 1..5") from None
            if not 1 <= r <= 5:
                raise _err(422, "invalid_rating", "Đánh giá 1..5")
        p.rating = r or None
    if data.get("status") is not None:
        if data["status"] not in ("active", "inactive"):
            raise _err(422, "invalid_status", "status: active | inactive")
        p.status = data["status"]
    if not (p.name or "").strip():
        raise _err(422, "name_required", "Thiếu tên đối tác")
    p.search_text = _u(f"{p.name} {p.tax_code} {p.contact_person}")
    p.updated_at = datetime.utcnow()


def create_partner(db, org_id, principal, data):
    co = _company(db, org_id, data.get("company_id"), write=True)
    from app.core import company_scope
    company_scope.check(co.id, min_role="manager")
    p = BizPartner(organization_id=org_id, company_id=co.id, name="", created_by_member_id=_seat(principal, co.id))
    _apply_partner(p, data)
    db.add(p); db.flush()
    _event(db, p, "partner.created", p.created_by_member_id, {"kind": p.kind})
    db.commit(); db.refresh(p)
    return public_partner(db, p)


def update_partner(db, org_id, principal, pid, data):
    p = _partner(db, org_id, pid, write=True)
    _apply_partner(p, data)
    db.add(p); db.commit(); db.refresh(p)
    return public_partner(db, p)


# ------------------------------------------------------------------ hợp đồng

def notice_deadline(c: BizContract) -> date | None:
    if c.end_date and c.notice_days:
        return c.end_date - timedelta(days=int(c.notice_days))
    return None


def fmt_money(amount, currency):
    from app.services.catalog import fmt_money as f
    return f(amount, currency)


def public(db: Session, c: BizContract, *, detail: bool = False) -> dict:
    p = db.get(BizPartner, c.partner_id) if c.partner_id else None
    d = db.get(KnowledgeDocument, c.document_id) if c.document_id else None
    t = today_vn()
    nd = notice_deadline(c)
    out = {"id": c.id, "company_id": c.company_id, "code": c.code, "title": c.title, "kind": c.kind,
           "partner": {"id": p.id, "name": p.name, "kind": p.kind} if p else None,
           "value_amount": float(c.value_amount) if c.value_amount is not None else None, "currency": c.currency,
           "start_date": c.start_date.isoformat() if c.start_date else None, "end_date": c.end_date.isoformat() if c.end_date else None,
           "auto_renew": c.auto_renew, "renewal_months": c.renewal_months, "notice_days": c.notice_days,
           "notice_deadline": nd.isoformat() if nd else None,
           "days_to_notice": (nd - t).days if nd else None, "days_to_end": (c.end_date - t).days if c.end_date else None,
           "sla": c.sla or {}, "key_terms": c.key_terms, "status": c.status, "locked": c.status in ("active", "expired", "terminated"),
           "document": {"id": d.id, "doc_code": d.doc_code, "title": d.title, "status": d.status} if d else None,
           "owner": _name(db, c.owner_member_id), "owner_member_id": c.owner_member_id,
           "approver": _name(db, c.approver_member_id), "approver_member_id": c.approver_member_id, "approval_id": c.approval_id,
           "requested_by_member_id": c.requested_by_member_id, "decided_by": _name(db, c.decided_by_member_id),
           "decided_at": c.decided_at.isoformat() if c.decided_at else None, "review_note": c.review_note}
    if detail:
        import json as _json
        from app.models.v10 import CompanyEvent
        out["history"] = [{"type": e.event_type, "at": e.occurred_at.isoformat() if e.occurred_at else None,
                           "by": _name(db, e.actor_member_id), "payload": _json.loads(e.payload_json or "{}")}
                          for e in db.query(CompanyEvent).filter(CompanyEvent.aggregate_type == "contract",
                                                                 CompanyEvent.aggregate_id == str(c.id),
                                                                 CompanyEvent.company_id == c.company_id)
                          .order_by(CompanyEvent.id.desc()).limit(50)]
    return out


def listing(db: Session, org_id: int, company_id: int | None, *, status: str = "", q: str = "") -> dict:
    co = _company(db, org_id, company_id)
    rows = db.query(BizContract).filter(BizContract.company_id == co.id)
    if status:
        rows = rows.filter(BizContract.status == status)
    items = [public(db, c) for c in rows.order_by(BizContract.end_date.is_(None), BizContract.end_date, BizContract.id)]
    if q:
        uq = _u(q)
        items = [i for i in items if uq in _u(f"{i['code']} {i['title']} {(i['partner'] or {}).get('name', '')}")]
    partners = [public_partner(db, p) for p in db.query(BizPartner).filter(BizPartner.company_id == co.id).order_by(BizPartner.name)]
    due = [i for i in items if i["status"] == "active" and (
        (i["days_to_notice"] is not None and 0 <= i["days_to_notice"] <= REMIND_DAYS)
        or (i["days_to_end"] is not None and 0 <= i["days_to_end"] <= REMIND_DAYS))]
    return {"company_id": co.id, "items": items, "partners": partners, "kinds": list(CONTRACT_KINDS), "partner_kinds": list(PARTNER_KINDS),
            "currencies": list(CURRENCIES), "remind_days": REMIND_DAYS,
            "counts": {"total": len(items), "active": sum(1 for i in items if i["status"] == "active"),
                       "pending": sum(1 for i in items if i["status"] == "pending"), "due_soon": len(due)}}


def _contract(db, org_id, cid, *, write=False) -> BizContract:
    c = db.get(BizContract, cid)
    if c is None or c.organization_id != org_id:
        raise _err(404, "not_found", "Không thấy hợp đồng")
    from app.core import company_scope
    company_scope.check(c.company_id, min_role="manager" if write else None)
    return c


def _money(v, cur) -> Decimal | None:
    if v in (None, ""):
        return None
    try:
        a = Decimal(str(v).replace(" ", "").replace("_", ""))
    except (InvalidOperation, ValueError):
        raise _err(422, "invalid_amount", "Giá trị phải là số") from None
    if a < 0 or a >= Decimal("1e16"):
        raise _err(422, "invalid_amount", "Giá trị không hợp lệ")
    if cur == "VND" and a != a.to_integral_value():
        raise _err(422, "vnd_no_decimals", "VND không có phần lẻ")
    return a


def _sla(v) -> dict | None:
    if v in (None, {}):
        return None
    if not isinstance(v, dict):
        raise _err(422, "invalid_sla", "sla phải là object")
    out = {}
    for k, val in v.items():
        if k not in SLA_KEYS or val in (None, ""):
            continue
        typ = SLA_KEYS[k]
        try:
            val = typ(val) if typ is not str else str(val)[:500]
        except (TypeError, ValueError):
            raise _err(422, "invalid_sla", f"{k} phải là số") from None
        if typ is not str and val < 0:
            raise _err(422, "invalid_sla", f"{k} không âm")
        out[k] = val
    return out or None


def _apply(db, c: BizContract, data: dict) -> None:
    if data.get("code") is not None:
        code = str(data["code"]).strip()
        if not CODE_RE.match(code):
            raise _err(422, "invalid_code", "Số hợp đồng: chữ, số, . / _ - (tối đa 48)")
        if db.query(BizContract.id).filter(BizContract.company_id == c.company_id, BizContract.code == code,
                                           BizContract.id != (c.id or -1)).first():
            raise _err(409, "code_exists", f"Số hợp đồng {code} đã có")
        c.code = code
    for k, lim in (("title", 220), ("key_terms", 6000)):
        if data.get(k) is not None:
            setattr(c, k, str(data[k]).strip()[:lim])
    if data.get("kind") is not None:
        if data["kind"] not in CONTRACT_KINDS:
            raise _err(422, "invalid_kind", "Loại hợp đồng không hợp lệ", allowed=list(CONTRACT_KINDS))
        c.kind = data["kind"]
    if "partner_id" in data:
        pid = data["partner_id"]
        if pid:
            p = db.get(BizPartner, int(pid))
            if p is None or p.company_id != c.company_id:
                raise _err(404, "not_found", "Đối tác không thuộc công ty này")
        c.partner_id = int(pid) if pid else None
    if data.get("currency") is not None:
        cur = str(data["currency"]).upper()
        if cur not in CURRENCIES:
            raise _err(422, "invalid_currency", "Tiền tệ: VND | USD")
        c.currency = cur
    if "value_amount" in data:
        c.value_amount = _money(data["value_amount"], c.currency or "VND")
    for k in ("start_date", "end_date"):
        if k in data:
            setattr(c, k, _date(data[k]))
    if c.start_date and c.end_date and c.end_date <= c.start_date:
        raise _err(422, "end_before_start", "Ngày hết hạn phải sau ngày hiệu lực")
    if data.get("auto_renew") is not None:
        c.auto_renew = bool(data["auto_renew"])
    for k in ("renewal_months", "notice_days"):
        if k in data:
            v = data[k]
            if v in (None, ""):
                setattr(c, k, None)
            else:
                try:
                    v = int(v)
                except (TypeError, ValueError):
                    raise _err(422, f"invalid_{k}", f"{k} phải là số nguyên") from None
                if v < 0 or v > 3650:
                    raise _err(422, f"invalid_{k}", f"{k} ngoài khoảng")
                setattr(c, k, v)
    if c.auto_renew and not c.renewal_months:
        c.renewal_months = 12
    if "sla" in data:
        c.sla = _sla(data["sla"])
    if "owner_member_id" in data:
        v = data["owner_member_id"]
        if v:
            m = db.get(Member, int(v))
            if m is None or m.company_id != c.company_id:
                raise _err(404, "not_found", "Người phụ trách không thuộc công ty này")
        c.owner_member_id = int(v) if v else None
    if "document_id" in data:
        _attach(db, c, data["document_id"])
    if not (c.title or "").strip():
        raise _err(422, "title_required", "Thiếu tên hợp đồng")
    c.updated_at = datetime.utcnow()


def _attach(db, c: BizContract, did) -> None:
    if not did:
        c.document_id = None
        return
    d = db.get(KnowledgeDocument, int(did))
    if d is None or d.company_id != c.company_id:
        raise _err(404, "not_found", "Không thấy tài liệu trong công ty này")
    c.document_id = d.id


def _next_code(db, company_id) -> str:
    y = today_vn().year
    n = db.query(BizContract.id).filter(BizContract.company_id == company_id).count() + 1
    while True:
        code = f"HD-{y}-{n:03d}"
        if not db.query(BizContract.id).filter(BizContract.company_id == company_id, BizContract.code == code).first():
            return code
        n += 1


def create(db, org_id, principal, data):
    co = _company(db, org_id, data.get("company_id"), write=True)
    from app.core import company_scope
    company_scope.check(co.id, min_role="manager")
    seat = _seat(principal, co.id)
    c = BizContract(organization_id=org_id, company_id=co.id, code="", title="", status="draft", owner_member_id=seat,
                    requested_by_member_id=seat, currency="VND")
    data = dict(data)
    data.setdefault("code", _next_code(db, co.id))
    _apply(db, c, data)
    db.add(c); db.flush()
    _event(db, c, "contract.created", seat, {"code": c.code})
    db.commit(); db.refresh(c)
    return public(db, c, detail=True)


def update(db, org_id, principal, cid, data):
    c = _contract(db, org_id, cid, write=True)
    if c.status in ("active", "expired", "terminated", "pending"):
        bad = [k for k in data if k in LOCKED]
        if bad:
            raise _err(409, "contract_locked", "Hợp đồng đã gửi ký / đã ký: không sửa điều khoản — làm phụ lục (hợp đồng mới)",
                       fields=bad)
    _apply(db, c, {k: v for k, v in data.items() if k != "company_id"})
    _event(db, c, "contract.changed", _seat(principal, c.company_id), {"fields": sorted(k for k in data if k != "company_id")})
    db.add(c); db.commit(); db.refresh(c)
    return public(db, c, detail=True)


def get(db, org_id, cid):
    return public(db, _contract(db, org_id, cid), detail=True)


def submit(db, org_id, principal, cid, data: dict | None = None):
    """Gửi ký: ma trận ``contract`` chọn người ký; người xin có quyền → ký ngay."""
    c = _contract(db, org_id, cid, write=True)
    if c.status not in ("draft", "rejected"):
        raise _err(409, "not_draft", "Chỉ gửi ký hợp đồng nháp / bị từ chối")
    if not c.partner_id or not c.start_date:
        raise _err(422, "missing_fields", "Cần đối tác và ngày hiệu lực trước khi gửi ký")
    seat = _seat(principal, c.company_id)
    req = db.get(Member, seat) if seat else None
    risk = (data or {}).get("risk") or "normal"
    from app.services import authority
    authority.ensure_action_defaults(db, org_id, c.company_id, "contract")
    d = authority.decide(db, req, "contract", risk=risk, company_id=c.company_id)
    approver = d.approver_member_id if d is not None else authority.owner_member(db, org_id, c.company_id)
    c.status, c.requested_by_member_id, c.approver_member_id = "pending", seat, approver
    c.review_note = ""
    db.add(c); db.flush()
    _event(db, c, "contract.submitted", seat, {"approver_member_id": approver})
    if req is not None and req.member_type == "human" and approver == req.id:
        db.commit()
        _decide(db, c, "approved", seat, note=d.reason if d else "")
        return {**public(db, c, detail=True), "auto_approved": True, "authority": d.card() if d else None}
    val = fmt_money(c.value_amount, c.currency) if c.value_amount is not None else "—"
    p = db.get(BizPartner, c.partner_id)
    a = Approval(organization_id=org_id, company_id=c.company_id, requester_member_id=seat, approver_member_id=approver,
                 action=f"Ký hợp đồng {c.code}: {c.title}"[:220], risk=risk, policy_key=f"contract:{c.id}", status="pending",
                 evidence=(f"Đối tác: {p.name if p else '—'}; giá trị {val}; hiệu lực {c.start_date:%d/%m/%Y}"
                           + (f" → {c.end_date:%d/%m/%Y}" if c.end_date else "") + (f"\n{c.key_terms[:1500]}" if c.key_terms else ""))[:2000],
                 payload=authority.annotate({"contract_id": c.id, "code": c.code}, d))
    db.add(a); db.flush()
    c.approval_id = a.id
    db.add(c); db.commit()
    return {**public(db, c, detail=True), "auto_approved": False, "authority": d.card() if d else None}


def _decide(db, c: BizContract, decision: str, actor, *, note: str = ""):
    c.decided_by_member_id, c.decided_at, c.review_note = actor, datetime.utcnow(), (note or "")[:2000]
    if decision == "approved":
        c.status = "active"
        _event(db, c, "contract.signed", actor, {"code": c.code})
    else:
        c.status = "rejected"
        _event(db, c, "contract.rejected", actor, {"code": c.code})
    db.add(c); db.commit(); db.refresh(c)
    if c.status == "active":
        sync_deadlines(db, c)
    return c


def decide(db, org_id, principal, cid, decision, note=""):
    if decision not in ("approved", "rejected"):
        raise _err(422, "invalid_decision", "decision: approved | rejected")
    c = _contract(db, org_id, cid)
    if c.status != "pending":
        raise _err(409, "not_pending", "Hợp đồng không chờ ký")
    me = set(getattr(principal, "member_ids", []) or [])
    if c.requested_by_member_id in me and c.approver_member_id != c.requested_by_member_id:
        raise _err(403, "self_approval", "Người đề xuất không tự duyệt hợp đồng của mình")
    if c.approver_member_id not in me and getattr(principal, "role", "") != "owner":
        raise _err(403, "not_the_approver", "Không phải người ký theo ma trận (contract)", approver_member_id=c.approver_member_id)
    if decision == "rejected" and not (note or "").strip():
        raise _err(422, "reason_required", "Ghi lý do từ chối")
    actor = c.approver_member_id if c.approver_member_id in me else _seat(principal, c.company_id)
    if c.approval_id:
        a = db.get(Approval, c.approval_id)
        if a is not None and a.status == "pending":
            a.status, a.resolution_note = decision, (note or "")[:2000]; db.add(a)
    _decide(db, c, decision, actor, note=note)
    return public(db, c, detail=True)


def on_approval_resolved(db, a: Approval, *, actor_member_id=None) -> None:
    try:
        cid = int((a.policy_key or "").split(":")[1])
    except (IndexError, ValueError):
        return
    c = db.get(BizContract, cid)
    if c is None or c.status != "pending":
        return
    _decide(db, c, "approved" if a.status == "approved" else "rejected", actor_member_id or a.approver_member_id,
            note=a.resolution_note or "")


def terminate(db, org_id, principal, cid, note=""):
    c = _contract(db, org_id, cid, write=True)
    if c.status != "active":
        raise _err(409, "not_active", "Chỉ chấm dứt hợp đồng đang hiệu lực")
    if len((note or "").strip()) < 5:
        raise _err(422, "reason_required", "Ghi lý do chấm dứt")
    c.status, c.terminated_at, c.review_note = "terminated", datetime.utcnow(), note[:2000]
    _event(db, c, "contract.terminated", _seat(principal, c.company_id), {"reason": note[:300]})
    db.add(c); db.commit()
    sync_deadlines(db, c)
    return public(db, c, detail=True)


# ------------------------------------------------------------------ lịch tuân thủ + nhắc

def sync_deadlines(db, c: BizContract) -> list[int]:
    from app.models.company_ops import ComplianceDeadline, ComplianceRule
    from app.services import compliance_calendar
    marks = {f"contract_notice:{c.id}": (notice_deadline(c), "Hạn báo trước (gia hạn / không gia hạn)"),
             f"contract_end:{c.id}": (c.end_date, "Hết hạn")}
    ids = []
    for key, (d, what) in marks.items():
        r = db.query(ComplianceRule).filter(ComplianceRule.company_id == c.company_id, ComplianceRule.key == key).first()
        live = c.status == "active" and d is not None
        if r is not None:
            for dl in db.query(ComplianceDeadline).filter(ComplianceDeadline.rule_id == r.id, ComplianceDeadline.status == "upcoming"):
                if not live or dl.statutory_date != d:
                    dl.status = "skipped"; db.add(dl)
        if not live:
            if r is not None:
                r.enabled = False; db.add(r)
            continue
        if r is None:
            r = ComplianceRule(organization_id=c.organization_id, company_id=c.company_id, key=key, category="contract", source="custom")
        r.name = f"{what}: hợp đồng {c.code} — {c.title}"[:200]
        r.frequency, r.due_rule, r.remind_days, r.enabled = "once", {"type": "fixed_date", "date": d.isoformat()}, REMIND_DAYS, True
        r.legal_basis = "Theo điều khoản của chính hợp đồng (không phải nghĩa vụ luật định)"
        r.note = f"Tự sinh từ sổ hợp đồng (P1 M3h) #{c.id}"
        db.add(r); db.commit(); db.refresh(r); ids.append(r.id)
    db.commit()
    if ids:
        compliance_calendar.generate(db, c.organization_id, c.company_id)
    return ids


def _project(db, company_id):
    from app.models import Project
    pr = db.query(Project).filter(Project.company_id == company_id, Project.name == "Hợp đồng").first()
    if pr is None:
        pr = Project(company_id=company_id, name="Hợp đồng", status="active", description="Việc nhắc hạn hợp đồng (P1 M3h)")
        db.add(pr); db.commit(); db.refresh(pr)
    return pr


def tick(db: Session, today: date | None = None) -> dict:
    from app.models.company_ops import ComplianceDeadline, ComplianceRule
    from app.services import authority, inbox
    from app.services import workspace_ops as ops
    today = today or today_vn()
    out = {"reminded": 0, "renewed": 0, "expired": 0}
    for c in db.query(BizContract).filter(BizContract.status == "active").all():
        if c.end_date and c.end_date < today:
            if c.auto_renew and c.renewal_months:
                old = c.end_date
                m = c.end_date.month - 1 + c.renewal_months
                y, mo = c.end_date.year + m // 12, m % 12 + 1
                import calendar
                c.end_date = date(y, mo, min(c.end_date.day, calendar.monthrange(y, mo)[1]))
                c.notice_reminded_at = c.end_reminded_at = None
                _event(db, c, "contract.auto_renewed", None, {"from": old.isoformat(), "to": c.end_date.isoformat()})
                db.add(c); db.commit(); sync_deadlines(db, c); out["renewed"] += 1
            else:
                c.status = "expired"
                _event(db, c, "contract.expired", None, {"end_date": c.end_date.isoformat()})
                db.add(c); db.commit(); sync_deadlines(db, c); out["expired"] += 1
            continue
        owner = authority.owner_member(db, c.organization_id, c.company_id)
        for kind, d, flag in (("notice", notice_deadline(c), "notice_reminded_at"), ("end", c.end_date, "end_reminded_at")):
            if d is None or getattr(c, flag) is not None or not (0 <= (d - today).days <= REMIND_DAYS):
                continue
            who = c.owner_member_id or owner
            label = "hạn báo trước" if kind == "notice" else "hết hạn"
            title = f"Hợp đồng {c.code} {label} {d:%d/%m/%Y} (còn {(d - today).days} ngày) — {c.title}"[:220]
            t = ops.create_task(db, _project(db, c.company_id), c.organization_id, title=title,
                                description="\n".join([f"**Hợp đồng:** {c.code} — {c.title}", f"**Mốc:** {label} {d:%d/%m/%Y}",
                                                       f"**Tự gia hạn:** {'có, ' + str(c.renewal_months) + ' tháng' if c.auto_renew else 'không'}",
                                                       "", "Quyết định gia hạn / đàm phán lại / báo chấm dứt trước mốc này. "
                                                       "Xong thì chuyển việc sang xong."]),
                                assignee_member_id=who, priority="high" if (d - today).days <= 7 else "medium")
            t.due_at = datetime.combine(d, datetime.min.time()) + timedelta(hours=10)
            inbox.notify(db, organization_id=c.organization_id, recipients=[who, owner], kind="contract_due", company_id=c.company_id,
                         title=title, related_type="contract", related_id=str(c.id), task_id=t.id,
                         priority="high" if (d - today).days <= 7 else "normal", commit=False)
            setattr(c, flag, datetime.utcnow())
            r = db.query(ComplianceRule).filter(ComplianceRule.company_id == c.company_id,
                                                ComplianceRule.key == f"contract_{kind}:{c.id}").first()
            if r is not None:
                for dl in db.query(ComplianceDeadline).filter(ComplianceDeadline.rule_id == r.id, ComplianceDeadline.status == "upcoming"):
                    dl.reminded_at, dl.task_id, dl.assignee_member_id = datetime.utcnow(), t.id, who; db.add(dl)
            db.add(c); db.commit(); out["reminded"] += 1
    return out


# ------------------------------------------------------------------ agent (MCP company_contract_get)

def agent_get(db: Session, company_id: int | None, *, query: str = "", code: str = "", partner: str = "") -> dict:
    if not company_id:
        return {"contracts": [], "note": "Seat không thuộc công ty nào"}
    rows = db.query(BizContract).filter(BizContract.company_id == company_id, BizContract.status == "active")
    if code:
        rows = rows.filter(BizContract.code == code.strip())
    items = rows.all()
    words = [w for w in _u(f"{query} {partner}").split() if len(w) > 1 and w not in {"hop", "dong", "cua", "voi", "nha", "cung", "cap", "sla"}]
    out = []
    for c in items:
        p = db.get(BizPartner, c.partner_id) if c.partner_id else None
        hay = _u(f"{c.code} {c.title} {p.name if p else ''} {p.tax_code if p else ''} {c.kind}")
        if words and not any(w in hay for w in words):
            continue
        nd = notice_deadline(c)
        out.append({"code": c.code, "title": c.title, "kind": c.kind, "partner": p.name if p else None,
                    "partner_kind": p.kind if p else None, "start_date": c.start_date.isoformat() if c.start_date else None,
                    "end_date": c.end_date.isoformat() if c.end_date else None, "auto_renew": c.auto_renew,
                    "notice_deadline": nd.isoformat() if nd else None, "sla": c.sla or {}, "key_terms": (c.key_terms or "")[:2000],
                    "cite": f"[HĐ:{c.code}]"})
    return {"contracts": out[:10], "rules": "Chỉ hợp đồng đang hiệu lực. Số SLA lấy đúng trường sla (không suy từ tệp ký). "
                                            "Giá trị hợp đồng không chia sẻ cho agent; cần thì hỏi người phụ trách.",
            **({} if out else {"note": "Không thấy hợp đồng đang hiệu lực khớp — đừng đoán điều khoản; hỏi người phụ trách"})}
