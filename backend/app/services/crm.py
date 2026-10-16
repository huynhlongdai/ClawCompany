"""M3g — khách hàng (CRM) của doanh nghiệp + đồng ý xử lý dữ liệu cá nhân. Spec: docs/company-knowledge-library-and-gaps.md §C M3g.

Căn cứ (đã mở đọc 16/10/2026, *không phải tư vấn pháp lý*):
* Luật Bảo vệ dữ liệu cá nhân 91/2025/QH15 (hiệu lực 1/1/2026): im lặng không phải đồng ý; chủ thể có quyền rút đồng ý,
  xem, sửa, xoá, hạn chế, phản đối.
* NĐ 356/2025/NĐ-CP Đ5 (thay NĐ 13/2023): phản hồi trong **02 ngày làm việc**; thực hiện: xem / sửa / cung cấp **10 ngày**,
  rút đồng ý / hạn chế / phản đối **15 ngày**, xoá **20 ngày** (bên thứ ba: 20 / 30 ngày); có thể gia hạn — mức gia hạn
  ``needs_review``. Nguồn: congbaocdn.chinhphu.vn (bản ký NĐ 356), thuvienphapluat.vn, baovedlcn.vn.

Luật cứng trong code (không phải lời nhắc):
1. Ghi đồng ý phải có bằng chứng (``evidence``) — không có → 422 ``consent_evidence_required``.
2. Dòng đồng ý không sửa / xoá; rút đồng ý = đóng dòng (thời điểm, lý do, người ghi). Đồng ý lại = dòng mới.
3. Liên hệ marketing: ``can_contact(purpose='marketing', channel)`` cần đồng ý ``marketing`` đang hiệu lực cho đúng kênh (hoặc kênh
   ``other`` = mọi kênh) và liên hệ không bị hạn chế / đã xoá. Không đạt → 409 ``no_marketing_consent`` + ghi tương tác
   ``outreach_blocked`` (bằng chứng hệ thống đã chặn). Đi qua đây: API outreach của người và MCP ``company_customer_outreach``.
4. Agent đọc liên hệ qua MCP ``company_customer_lookup`` — cắt theo quyền: chỉ liên hệ của phòng agent (hoặc chưa gán phòng),
   chỉ khi có đồng ý ``service`` hoặc ``ai_processing`` đang hiệu lực; điện thoại / email / địa chỉ LUÔN che (``09******89``);
   liên hệ hạn chế / đã xoá không trả. Dữ liệu liên hệ không vào RAG (không ghi vào knowledge_*).
5. Người: thành viên / người xem công ty thấy PII đã che; quản lý công ty trở lên thấy đủ.
6. Yêu cầu xoá: chạy hết quy trình → PII bị xoá trắng, nội dung tương tác bị gỡ, đồng ý giữ siêu dữ liệu (mục đích, thời điểm)
   làm bằng chứng; hồ sơ yêu cầu giữ hash bản ghi trước khi xoá + số dòng đã gỡ."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import Member
from app.models.crm import (CHANNELS, DSR_KINDS, PURPOSES, CrmConsent, CrmContact, CrmDataRequest, CrmInteraction)

# NĐ 356/2025 Đ5 — số ngày thực hiện theo loại yêu cầu (tính từ ngày nhận yêu cầu hợp lệ)
DSR_DAYS = {"access": 10, "correct": 10, "withdraw": 15, "restrict": 15, "object": 15, "delete": 20}
ACK_WORKING_DAYS = 2
LEGAL_BASIS = "Luật BVDLCN 91/2025/QH15; NĐ 356/2025/NĐ-CP Đ5 (phản hồi 02 ngày làm việc; 10/15/20 ngày theo loại)"
INTERACTION_KINDS = ("note", "call", "chat", "email", "meeting", "task", "inbox", "portal", "outreach", "outreach_blocked",
                     "dsr", "consent")
AGENT_READ_PURPOSES = ("service", "ai_processing")
PHONE_RE = re.compile(r"^\+?[0-9 .\-]{8,20}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _err(status: int, code: str, message: str, **extra) -> HTTPException:
    return HTTPException(status, {"error": code, "message": message, **extra})


def _company(db: Session, org_id: int, company_id: int | None, *, write: bool = False):
    from app.services.company_foundation import _company as c
    return c(db, org_id, company_id, write=write)


def _seat(principal, company_id: int | None) -> int | None:
    from app.services.doc_library import _seat as s
    return s(None, principal, company_id)


def _u(s: str) -> str:
    from app.services.knowledge_hub import unaccent
    return re.sub(r"\s+", " ", unaccent(s or "").lower()).strip()


def _dt(v) -> datetime | None:
    if v in (None, ""):
        return None
    if isinstance(v, datetime):
        return v
    try:
        return datetime.fromisoformat(str(v).replace("Z", ""))
    except ValueError:
        raise _err(422, "invalid_date", f"Ngày không hợp lệ: {v}") from None


# ------------------------------------------------------------------ PII

def mask_phone(p: str) -> str:
    d = re.sub(r"\D", "", p or "")
    return "" if not d else (d[:2] + "*" * max(0, len(d) - 4) + d[-2:] if len(d) > 4 else "*" * len(d))


def mask_email(e: str) -> str:
    if not e or "@" not in e:
        return ""
    user, dom = e.split("@", 1)
    return (user[:1] + "***@" + dom) if user else "***@" + dom


def mask_address(a: str) -> str:
    if not a:
        return ""
    parts = [x.strip() for x in a.split(",") if x.strip()]
    return ("***, " + ", ".join(parts[-2:])) if len(parts) > 2 else "***"


def can_see_pii(principal, company_id: int) -> bool:
    from app.core import company_scope
    if principal is None:
        return False
    if company_scope.restricted(principal):
        return company_scope.role_in(company_id, principal) in ("manager", "owner")
    return getattr(principal, "role", "") in ("owner", "admin", "manager")


# ------------------------------------------------------------------ đồng ý

def active_consents(db: Session, contact_id: int) -> list[CrmConsent]:
    return (db.query(CrmConsent).filter(CrmConsent.contact_id == contact_id, CrmConsent.status == "granted")
            .order_by(CrmConsent.id).all())


def has_consent(db: Session, c: CrmContact, purpose: str, channel: str | None = None) -> bool:
    if c.status == "erased" or c.restricted:
        return False
    for x in active_consents(db, c.id):
        if x.purpose == purpose and (channel is None or x.channel in (channel, "other")):
            return True
    return False


def can_contact(db: Session, c: CrmContact, purpose: str, channel: str | None = None) -> tuple[bool, str]:
    """(được phép, mã lý do). service: chăm sóc khách theo yêu cầu của chính khách / thực hiện hợp đồng — không cần đồng ý
    marketing nhưng liên hệ không được ở trạng thái hạn chế / đã xoá. marketing: cần đồng ý marketing đang hiệu lực đúng kênh."""
    if c.status == "erased":
        return False, "contact_erased"
    if c.restricted:
        return False, "processing_restricted"
    if purpose == "marketing":
        return (True, "ok") if has_consent(db, c, "marketing", channel) else (False, "no_marketing_consent")
    return True, "ok"


def public_consent(db: Session, x: CrmConsent) -> dict:
    return {"id": x.id, "contact_id": x.contact_id, "purpose": x.purpose, "channel": x.channel, "status": x.status,
            "granted_at": x.granted_at.isoformat() if x.granted_at else None, "evidence": x.evidence,
            "evidence_doc_id": x.evidence_doc_id, "notice_ref": x.notice_ref,
            "recorded_by": _name(db, x.recorded_by_member_id),
            "withdrawn_at": x.withdrawn_at.isoformat() if x.withdrawn_at else None, "withdrawn_reason": x.withdrawn_reason,
            "withdrawn_by": _name(db, x.withdrawn_by_member_id)}


def _name(db: Session, mid: int | None) -> str | None:
    m = db.get(Member, mid) if mid else None
    return m.name if m else None


def grant_consent(db: Session, org_id: int, principal, contact_id: int, data: dict, *, actor: int | None = None) -> dict:
    c = _contact(db, org_id, contact_id, write=True)
    if c.status == "erased":
        raise _err(409, "contact_erased", "Liên hệ đã bị xoá theo yêu cầu — không ghi đồng ý mới")
    purpose = str(data.get("purpose") or "")
    channel = str(data.get("channel") or "other")
    if purpose not in PURPOSES:
        raise _err(422, "invalid_purpose", "Mục đích không hợp lệ", allowed=list(PURPOSES))
    if channel not in CHANNELS:
        raise _err(422, "invalid_channel", "Kênh không hợp lệ", allowed=list(CHANNELS))
    evidence = str(data.get("evidence") or "").strip()
    if len(evidence) < 5 and not data.get("evidence_doc_id"):
        raise _err(422, "consent_evidence_required",
                   "Cần bằng chứng đồng ý (cách thu, thời điểm, nơi lưu) — im lặng không phải đồng ý (Luật 91/2025)")
    if any(x.purpose == purpose and x.channel == channel for x in active_consents(db, c.id)):
        raise _err(409, "consent_exists", "Đã có đồng ý đang hiệu lực cho mục đích + kênh này")
    seat = actor if actor is not None else _seat(principal, c.company_id)
    x = CrmConsent(organization_id=org_id, company_id=c.company_id, contact_id=c.id, purpose=purpose, channel=channel,
                   status="granted", granted_at=_dt(data.get("granted_at")) or datetime.utcnow(), evidence=evidence[:2000],
                   evidence_doc_id=data.get("evidence_doc_id") or None, notice_ref=str(data.get("notice_ref") or "")[:80],
                   recorded_by_member_id=seat)
    db.add(x); db.flush()
    _log(db, c, "consent", code="consent_granted", params={"purpose": purpose, "channel": channel}, member_id=seat)
    _event(db, c, "crm.consent_granted", seat, {"consent_id": x.id, "purpose": purpose, "channel": channel})
    db.commit()
    return public_consent(db, x)


def withdraw_consent(db: Session, org_id: int, principal, consent_id: int, reason: str = "", *, actor: int | None = None,
                     commit: bool = True) -> dict:
    x = db.get(CrmConsent, consent_id)
    if x is None or x.organization_id != org_id:
        raise _err(404, "not_found", "Không thấy bản ghi đồng ý")
    c = _contact(db, org_id, x.contact_id, write=True)
    if x.status != "granted":
        raise _err(409, "already_withdrawn", "Đồng ý này đã rút")
    seat = actor if actor is not None else _seat(principal, c.company_id)
    x.status, x.withdrawn_at, x.withdrawn_reason, x.withdrawn_by_member_id = "withdrawn", datetime.utcnow(), (reason or "")[:1000], seat
    db.add(x)
    _log(db, c, "consent", code="consent_withdrawn", params={"purpose": x.purpose, "channel": x.channel}, member_id=seat)
    _event(db, c, "crm.consent_withdrawn", seat, {"consent_id": x.id, "purpose": x.purpose, "channel": x.channel})
    if commit:
        db.commit()
    return public_consent(db, x)


# ------------------------------------------------------------------ liên hệ

def _contact(db: Session, org_id: int, cid: int, *, write: bool = False) -> CrmContact:
    c = db.get(CrmContact, cid)
    if c is None or c.organization_id != org_id:
        raise _err(404, "not_found", "Không thấy liên hệ")
    from app.core import company_scope
    company_scope.check(c.company_id, min_role="manager" if write else None)
    return c


def _event(db: Session, c: CrmContact, kind: str, actor: int | None, payload: dict) -> None:
    from app.services.company_event_bus import emit_event
    emit_event(db, organization_id=c.organization_id, company_id=c.company_id, event_type=kind, source="crm",
               aggregate_type="crm_contact", aggregate_id=str(c.id), actor_member_id=actor, payload=payload)


def _log(db: Session, c: CrmContact, kind: str, *, summary: str = "", code: str = "", params: dict | None = None,
         member_id: int | None = None, channel: str = "", direction: str = "", purpose: str = "service",
         task_id: int | None = None, inbox_item_id: int | None = None, conversation_id: int | None = None,
         occurred_at: datetime | None = None) -> CrmInteraction:
    it = CrmInteraction(organization_id=c.organization_id, company_id=c.company_id, contact_id=c.id, kind=kind, channel=channel,
                        direction=direction, purpose=purpose, summary=(summary or "")[:4000], code=code, params=params,
                        member_id=member_id, task_id=task_id, inbox_item_id=inbox_item_id, conversation_id=conversation_id,
                        occurred_at=occurred_at or datetime.utcnow())
    db.add(it); db.flush()
    return it


def _clean_contact(db: Session, c: CrmContact, data: dict) -> None:
    for k, lim in (("name", 200), ("org_name", 200), ("segment", 60), ("notes", 4000), ("address", 1000)):
        if data.get(k) is not None:
            setattr(c, k, str(data[k]).strip()[:lim])
    if data.get("kind") is not None:
        if data["kind"] not in ("person", "business"):
            raise _err(422, "invalid_kind", "kind: person | business")
        c.kind = data["kind"]
    if data.get("phone") is not None:
        p = str(data["phone"]).strip()
        if p and not PHONE_RE.match(p):
            raise _err(422, "invalid_phone", "Số điện thoại không hợp lệ")
        c.phone = p
    if data.get("email") is not None:
        e = str(data["email"]).strip().lower()
        if e and not EMAIL_RE.match(e):
            raise _err(422, "invalid_email", "Email không hợp lệ")
        c.email = e
    if data.get("tags") is not None:
        c.tags = [str(t).strip()[:40] for t in (data["tags"] or []) if str(t).strip()][:20] or None
    for k in ("owner_member_id", "department_id"):
        if k in data:
            v = data[k]
            if v:
                from app.models import Department
                obj = db.get(Member if k == "owner_member_id" else Department, int(v))
                ok_null = k == "owner_member_id" and obj is not None and obj.organization_id == c.organization_id and obj.company_id is None
                if obj is None or (obj.company_id != c.company_id and not ok_null):
                    raise _err(404, "not_found", "Người / phòng phụ trách không thuộc công ty này")
            setattr(c, k, int(v) if v else None)
    if not (c.name or "").strip():
        raise _err(422, "name_required", "Thiếu tên liên hệ")
    # search_text KHÔNG chứa PII (không số điện thoại / email / địa chỉ)
    c.search_text = _u(f"{c.name} {c.org_name} {c.segment} {' '.join(c.tags or [])}")
    c.updated_at = datetime.utcnow()


def public_contact(db: Session, c: CrmContact, *, pii: bool, detail: bool = False) -> dict:
    cons = active_consents(db, c.id)
    out = {"id": c.id, "company_id": c.company_id, "kind": c.kind, "name": c.name, "org_name": c.org_name,
           "phone": c.phone if pii else mask_phone(c.phone), "email": c.email if pii else mask_email(c.email),
           "address": c.address if pii else mask_address(c.address), "pii_masked": not pii,
           "tags": c.tags or [], "segment": c.segment, "source": c.source, "status": c.status, "restricted": c.restricted,
           "owner": _name(db, c.owner_member_id), "owner_member_id": c.owner_member_id, "department_id": c.department_id,
           "consents": sorted({f"{x.purpose}:{x.channel}" for x in cons}),
           "marketing_ok": any(x.purpose == "marketing" for x in cons) and not c.restricted and c.status != "erased",
           "open_requests": db.query(CrmDataRequest.id).filter(CrmDataRequest.contact_id == c.id,
                                                              CrmDataRequest.status.in_(("open", "in_progress"))).count(),
           "updated_at": c.updated_at.isoformat() if c.updated_at else None}
    if detail:
        out["notes"] = c.notes if pii else ""
        out["consent_history"] = [public_consent(db, x) for x in
                                  db.query(CrmConsent).filter(CrmConsent.contact_id == c.id).order_by(CrmConsent.id.desc())]
        out["interactions"] = [public_interaction(db, i) for i in
                               db.query(CrmInteraction).filter(CrmInteraction.contact_id == c.id)
                               .order_by(CrmInteraction.occurred_at.desc(), CrmInteraction.id.desc()).limit(100)]
        out["requests"] = [public_request(db, r) for r in
                           db.query(CrmDataRequest).filter(CrmDataRequest.contact_id == c.id).order_by(CrmDataRequest.id.desc())]
    return out


def public_interaction(db: Session, i: CrmInteraction) -> dict:
    return {"id": i.id, "kind": i.kind, "channel": i.channel, "direction": i.direction, "purpose": i.purpose,
            "summary": i.summary, "code": i.code, "params": i.params or {}, "task_id": i.task_id,
            "inbox_item_id": i.inbox_item_id, "conversation_id": i.conversation_id, "by": _name(db, i.member_id),
            "occurred_at": i.occurred_at.isoformat() if i.occurred_at else None}


def listing(db: Session, org_id: int, principal, company_id: int | None, *, q: str = "", segment: str = "",
            consent: str = "") -> dict:
    co = _company(db, org_id, company_id)
    pii = can_see_pii(principal, co.id)
    rows = db.query(CrmContact).filter(CrmContact.company_id == co.id)
    if segment:
        rows = rows.filter(CrmContact.segment == segment)
    items = []
    uq = _u(q)
    for c in rows.order_by(CrmContact.id.desc()).limit(2000):
        if uq and uq not in c.search_text and not (pii and uq in f"{c.phone} {c.email}".lower()):
            continue
        p = public_contact(db, c, pii=pii)
        if consent == "marketing" and not p["marketing_ok"]:
            continue
        items.append(p)
    now = datetime.utcnow()
    open_q = db.query(CrmDataRequest).filter(CrmDataRequest.company_id == co.id, CrmDataRequest.status.in_(("open", "in_progress")))
    from app.models import Department
    deps = [{"id": d.id, "name": d.name} for d in db.query(Department).filter(Department.company_id == co.id).order_by(Department.id)]
    return {"company_id": co.id, "items": items, "pii_masked": not pii, "purposes": list(PURPOSES), "channels": list(CHANNELS),
            "departments": deps, "dsr_kinds": list(DSR_KINDS), "dsr_days": DSR_DAYS,
            "counts": {"total": len(items), "marketing_ok": sum(1 for i in items if i["marketing_ok"]),
                       "open_requests": open_q.count(), "overdue_requests": open_q.filter(CrmDataRequest.due_at < now).count()}}


def create_contact(db: Session, org_id: int, principal, data: dict) -> dict:
    co = _company(db, org_id, data.get("company_id"), write=True)
    from app.core import company_scope
    company_scope.check(co.id, min_role="manager")
    seat = _seat(principal, co.id)
    c = CrmContact(organization_id=org_id, company_id=co.id, name="", source=str(data.get("source") or "manual")[:24],
                   created_by_member_id=seat, owner_member_id=seat)
    _clean_contact(db, c, data)
    db.add(c); db.flush()
    _event(db, c, "crm.contact_created", seat, {"source": c.source})
    db.commit(); db.refresh(c)
    for cs in data.get("consents") or []:
        grant_consent(db, org_id, principal, c.id, cs)
    return public_contact(db, c, pii=can_see_pii(principal, co.id), detail=True)


def update_contact(db: Session, org_id: int, principal, cid: int, data: dict) -> dict:
    c = _contact(db, org_id, cid, write=True)
    if c.status == "erased":
        raise _err(409, "contact_erased", "Liên hệ đã bị xoá theo yêu cầu")
    _clean_contact(db, c, data)
    _event(db, c, "crm.contact_changed", _seat(principal, c.company_id), {"fields": sorted(k for k in data if k != "company_id")})
    db.add(c); db.commit(); db.refresh(c)
    return public_contact(db, c, pii=can_see_pii(principal, c.company_id), detail=True)


def get_contact(db: Session, org_id: int, principal, cid: int) -> dict:
    c = _contact(db, org_id, cid)
    return public_contact(db, c, pii=can_see_pii(principal, c.company_id), detail=True)


def add_interaction(db: Session, org_id: int, principal, cid: int, data: dict) -> dict:
    c = _contact(db, org_id, cid, write=True)
    kind = str(data.get("kind") or "note")
    if kind not in ("note", "call", "chat", "email", "meeting", "task", "inbox", "portal"):
        raise _err(422, "invalid_kind", "Loại tương tác không hợp lệ")
    links = {}
    for k, model in (("task_id", "Task"), ("inbox_item_id", "InboxItem"), ("conversation_id", "Conversation")):
        v = data.get(k)
        if v:
            import app.models as M
            obj = db.get(getattr(M, model), int(v))
            if obj is None or getattr(obj, "organization_id", org_id) != org_id:
                raise _err(404, "not_found", f"Không thấy {k}")
            if model == "Task":
                from app.models import Project
                pr = db.get(Project, obj.project_id) if obj.project_id else None
                if pr is not None and pr.company_id != c.company_id:
                    raise _err(404, "not_found", "Việc thuộc công ty khác")
            elif getattr(obj, "company_id", None) not in (None, c.company_id):
                raise _err(404, "not_found", f"{k} thuộc công ty khác")
            links[k] = int(v)
    it = _log(db, c, kind, summary=str(data.get("summary") or ""), channel=str(data.get("channel") or "")[:16],
              direction=str(data.get("direction") or "")[:8], member_id=_seat(principal, c.company_id),
              occurred_at=_dt(data.get("occurred_at")), **links)
    db.commit()
    return public_interaction(db, it)


# ------------------------------------------------------------------ marketing guard

def outreach(db: Session, org_id: int, principal, cid: int, data: dict, *, actor: Member | None = None) -> dict:
    """Gửi / xếp lịch một tin cho khách. purpose=marketing → cần đồng ý marketing đúng kênh. Bị chặn = 409 + ghi bằng chứng.
    Hàm này KHÔNG tự gửi ra kênh ngoài (chưa có tích hợp kênh): nó ghi tương tác ``outreach`` đã được phép để người /
    agent gửi qua kênh của công ty, và là cổng duy nhất mọi đường gửi marketing phải đi qua."""
    c = db.get(CrmContact, cid)
    if c is None or c.organization_id != org_id:
        raise _err(404, "not_found", "Không thấy liên hệ")
    if actor is None:
        from app.core import company_scope
        company_scope.check(c.company_id, min_role="manager")
    purpose = str(data.get("purpose") or "marketing")
    channel = str(data.get("channel") or "other")
    if purpose not in ("service", "marketing"):
        raise _err(422, "invalid_purpose", "purpose: service | marketing")
    if channel not in CHANNELS:
        raise _err(422, "invalid_channel", "Kênh không hợp lệ", allowed=list(CHANNELS))
    seat = actor.id if actor is not None else _seat(principal, c.company_id)
    ok, why = can_contact(db, c, purpose, channel)
    if not ok:
        _log(db, c, "outreach_blocked", code=why, params={"purpose": purpose, "channel": channel},
             summary=str(data.get("message") or "")[:300], member_id=seat, channel=channel, direction="out", purpose=purpose)
        _event(db, c, "crm.outreach_blocked", seat, {"reason": why, "purpose": purpose, "channel": channel})
        db.commit()
        raise _err(409, why, "Không được liên hệ khách này cho mục đích/kênh này (chưa có đồng ý đang hiệu lực, "
                             "đã rút, bị hạn chế hoặc đã xoá)", purpose=purpose, channel=channel)
    it = _log(db, c, "outreach", summary=str(data.get("message") or "")[:4000], channel=channel, direction="out",
              purpose=purpose, member_id=seat, code="outreach_allowed")
    _event(db, c, "crm.outreach_logged", seat, {"purpose": purpose, "channel": channel, "interaction_id": it.id})
    db.commit()
    return {"allowed": True, "interaction": public_interaction(db, it)}


def marketing_audience(db: Session, org_id: int, company_id: int | None, channel: str = "other") -> list[int]:
    """Danh sách id liên hệ ĐƯỢC nhận marketing qua kênh — dùng cho mọi chiến dịch (không có đường thứ hai)."""
    co = _company(db, org_id, company_id)
    return [c.id for c in db.query(CrmContact).filter(CrmContact.company_id == co.id, CrmContact.status == "active")
            if can_contact(db, c, "marketing", channel)[0]]


# ------------------------------------------------------------------ yêu cầu của chủ thể dữ liệu

def add_working_days(db: Session, org_id: int, start: datetime, n: int) -> datetime:
    """+n ngày làm việc (bỏ T7, CN và ngày lễ trong lịch nghỉ của tổ chức)."""
    try:
        from app.services import holidays
        cal = holidays.calendar_of(db, org_id, {start.year, start.year + 1})
    except Exception:  # noqa: BLE001 — chưa có lịch nghỉ → chỉ bỏ cuối tuần
        cal = {}
    d, left = start, n
    while left > 0:
        d += timedelta(days=1)
        if d.weekday() < 5 and d.date() not in cal:
            left -= 1
    return d


def public_request(db: Session, r: CrmDataRequest) -> dict:
    now = datetime.utcnow()
    open_ = r.status in ("open", "in_progress")
    c = db.get(CrmContact, r.contact_id)
    return {"id": r.id, "contact_id": r.contact_id, "contact_name": c.name if c else None, "kind": r.kind, "status": r.status,
            "channel": r.channel, "received_at": r.received_at.isoformat(), "ack_due_at": r.ack_due_at.isoformat(),
            "due_at": r.due_at.isoformat(), "acknowledged_at": r.acknowledged_at.isoformat() if r.acknowledged_at else None,
            "days_allowed": DSR_DAYS.get(r.kind), "overdue": open_ and r.due_at < now,
            "ack_overdue": open_ and r.acknowledged_at is None and r.ack_due_at < now,
            "requester_note": r.requester_note, "handler": _name(db, r.handler_member_id), "handler_member_id": r.handler_member_id,
            "task_id": r.task_id, "result_note": r.result_note, "evidence": r.evidence or {},
            "closed_at": r.closed_at.isoformat() if r.closed_at else None, "legal_basis": LEGAL_BASIS}


def requests_list(db: Session, org_id: int, company_id: int | None, status: str = "") -> dict:
    co = _company(db, org_id, company_id)
    q = db.query(CrmDataRequest).filter(CrmDataRequest.company_id == co.id)
    if status == "open":
        q = q.filter(CrmDataRequest.status.in_(("open", "in_progress")))
    elif status:
        q = q.filter(CrmDataRequest.status == status)
    return {"company_id": co.id, "items": [public_request(db, r) for r in q.order_by(CrmDataRequest.due_at)],
            "days": DSR_DAYS, "ack_working_days": ACK_WORKING_DAYS, "legal_basis": LEGAL_BASIS, "needs_review": True}


def _dsr_project(db: Session, company_id: int):
    from app.models import Project
    pr = db.query(Project).filter(Project.company_id == company_id, Project.name == "Dữ liệu cá nhân").first()
    if pr is None:
        pr = Project(company_id=company_id, name="Dữ liệu cá nhân", status="active",
                     description="Yêu cầu của chủ thể dữ liệu (Luật BVDLCN 91/2025, NĐ 356/2025) — M3g")
        db.add(pr); db.commit(); db.refresh(pr)
    return pr


def _handler(db: Session, org_id: int, c: CrmContact) -> int | None:
    from app.services import authority
    if c.owner_member_id:
        m = db.get(Member, c.owner_member_id)
        if m is not None and m.member_type == "human":
            return m.id
    return authority.owner_member(db, org_id, c.company_id)


def open_request(db: Session, org_id: int, principal, cid: int, data: dict, *, actor: int | None = None) -> dict:
    c = _contact(db, org_id, cid, write=True)
    kind = str(data.get("kind") or "")
    if kind not in DSR_KINDS:
        raise _err(422, "invalid_kind", "Loại yêu cầu không hợp lệ", allowed=list(DSR_KINDS))
    if c.status == "erased":
        raise _err(409, "contact_erased", "Liên hệ đã bị xoá")
    received = _dt(data.get("received_at")) or datetime.utcnow()
    seat = actor if actor is not None else _seat(principal, c.company_id)
    handler = _handler(db, org_id, c)
    r = CrmDataRequest(organization_id=org_id, company_id=c.company_id, contact_id=c.id, kind=kind, status="open",
                       channel=str(data.get("channel") or "other")[:16], received_at=received,
                       ack_due_at=add_working_days(db, org_id, received, ACK_WORKING_DAYS),
                       due_at=received + timedelta(days=DSR_DAYS[kind]), requester_note=str(data.get("note") or "")[:2000],
                       handler_member_id=handler)
    db.add(r); db.flush()
    if handler:
        from app.services import inbox
        from app.services import workspace_ops as ops
        t = ops.create_task(db, _dsr_project(db, c.company_id), org_id,
                            title=f"Yêu cầu DLCN #{r.id} ({kind}) — hạn {(r.due_at + timedelta(hours=7)):%d/%m/%Y}"[:220],
                            description="\n".join([f"**Loại:** {kind}", f"**Liên hệ:** #{c.id}",
                                                   f"**Phản hồi trước:** {(r.ack_due_at + timedelta(hours=7)):%d/%m/%Y %H:%M} (giờ VN)",
                                                   f"**Thực hiện trước:** {(r.due_at + timedelta(hours=7)):%d/%m/%Y %H:%M} (giờ VN)",
                                                   f"**Căn cứ:** {LEGAL_BASIS}", "",
                                                   "Xử lý trong Công ty › Kinh doanh › Dữ liệu cá nhân. Không gửi dữ liệu qua kênh không xác minh."]),
                            assignee_member_id=handler, priority="high")
        t.due_at = r.due_at; db.add(t)
        r.task_id = t.id
        inbox.notify(db, organization_id=org_id, recipients=[handler], kind="dsr_due", company_id=c.company_id,
                     title=f"Yêu cầu dữ liệu cá nhân #{r.id} ({kind}) — phản hồi trước {(r.ack_due_at + timedelta(hours=7)):%d/%m %H:%M}",
                     related_type="crm_request", related_id=str(r.id), priority="high", task_id=t.id, commit=False)
    _log(db, c, "dsr", code=f"dsr_opened_{kind}", params={"request_id": r.id}, member_id=seat, task_id=r.task_id)
    _event(db, c, "crm.dsr_opened", seat, {"request_id": r.id, "kind": kind, "due_at": r.due_at.isoformat()})
    db.commit()
    return public_request(db, r)


def _req(db: Session, org_id: int, rid: int) -> CrmDataRequest:
    r = db.get(CrmDataRequest, rid)
    if r is None or r.organization_id != org_id:
        raise _err(404, "not_found", "Không thấy yêu cầu")
    from app.core import company_scope
    company_scope.check(r.company_id, min_role="manager")
    return r


def snapshot(db: Session, c: CrmContact) -> dict:
    """Bản dữ liệu của chủ thể (yêu cầu xem / cung cấp) — đủ PII, chỉ trả cho quản lý công ty xử lý yêu cầu."""
    return {"contact": {k: getattr(c, k) for k in ("id", "kind", "name", "phone", "email", "address", "org_name", "segment",
                                                    "source", "notes", "status")} | {"tags": c.tags or []},
            "consents": [public_consent(db, x) for x in db.query(CrmConsent).filter(CrmConsent.contact_id == c.id)],
            "interactions": [{"kind": i.kind, "channel": i.channel, "summary": i.summary,
                              "occurred_at": i.occurred_at.isoformat()} for i in
                             db.query(CrmInteraction).filter(CrmInteraction.contact_id == c.id).order_by(CrmInteraction.id)]}


def act_request(db: Session, org_id: int, principal, rid: int, data: dict) -> dict:
    """Bước xử lý: ack (đã phản hồi khách) | complete (thực hiện xong — làm đúng việc theo loại) | reject (có lý do)."""
    r = _req(db, org_id, rid)
    c = db.get(CrmContact, r.contact_id)
    action = str(data.get("action") or "")
    seat = _seat(principal, r.company_id)
    note = str(data.get("note") or "").strip()
    if r.status not in ("open", "in_progress"):
        raise _err(409, "request_closed", "Yêu cầu đã đóng")
    out_extra: dict = {}
    if action == "ack":
        r.acknowledged_at, r.status = datetime.utcnow(), "in_progress"
        _log(db, c, "dsr", code="dsr_acknowledged", params={"request_id": r.id}, member_id=seat)
    elif action == "reject":
        if len(note) < 5:
            raise _err(422, "reason_required", "Ghi lý do từ chối (vd. không xác minh được danh tính / luật khác buộc giữ)")
        r.status, r.result_note, r.closed_at, r.closed_by_member_id = "rejected", note[:2000], datetime.utcnow(), seat
        _log(db, c, "dsr", code="dsr_rejected", params={"request_id": r.id}, member_id=seat)
    elif action == "complete":
        ev: dict = {"completed_at": datetime.utcnow().isoformat(), "by_member_id": seat}
        if r.kind == "access":
            snap = snapshot(db, c)
            raw = json.dumps(snap, ensure_ascii=False, sort_keys=True, default=str)
            ev["export_sha256"], ev["export_bytes"] = hashlib.sha256(raw.encode()).hexdigest(), len(raw.encode())
            out_extra["export"] = snap
        elif r.kind == "withdraw":
            purposes = data.get("purposes") or [x.purpose for x in active_consents(db, c.id)]
            n = 0
            for x in active_consents(db, c.id):
                if x.purpose in purposes:
                    withdraw_consent(db, org_id, principal, x.id, f"Yêu cầu DLCN #{r.id}", actor=seat, commit=False); n += 1
            ev["consents_withdrawn"] = n
        elif r.kind in ("restrict", "object"):
            c.restricted, c.status = True, "restricted"
            ev["restricted"] = True
        elif r.kind == "correct":
            changes = {k: v for k, v in (data.get("changes") or {}).items() if k in ("name", "phone", "email", "address", "org_name")}
            if not changes:
                raise _err(422, "changes_required", "Ghi trường cần sửa")
            _clean_contact(db, c, changes)
            ev["fields_corrected"] = sorted(changes)
        elif r.kind == "delete":
            ev.update(erase(db, c, seat, r.id))
        r.status, r.closed_at, r.closed_by_member_id, r.result_note = "done", datetime.utcnow(), seat, note[:2000]
        r.acknowledged_at = r.acknowledged_at or datetime.utcnow()
        r.evidence = ev
        _log(db, c, "dsr", code=f"dsr_done_{r.kind}", params={"request_id": r.id}, member_id=seat)
    else:
        raise _err(422, "invalid_action", "action: ack | complete | reject")
    if r.status in ("done", "rejected") and r.task_id:
        from app.models import Task
        t = db.get(Task, r.task_id)
        if t is not None and t.status != "done":
            t.status = "done"; db.add(t)
    db.add(r); db.add(c)
    _event(db, c, f"crm.dsr_{action}", seat, {"request_id": r.id, "kind": r.kind})
    db.commit()
    return {**public_request(db, r), **out_extra}


def erase(db: Session, c: CrmContact, actor: int | None, request_id: int | None) -> dict:
    """Xoá theo yêu cầu: hash bản ghi trước khi xoá (bằng chứng), xoá trắng PII + ghi chú + nội dung tương tác; đồng ý giữ
    siêu dữ liệu (mục đích / kênh / thời điểm) và bị đóng; liên hệ còn dòng 'đã xoá' để chặn liên hệ lại."""
    raw = json.dumps(snapshot(db, c), ensure_ascii=False, sort_keys=True, default=str)
    digest = hashlib.sha256(raw.encode()).hexdigest()
    n_int = 0
    for i in db.query(CrmInteraction).filter(CrmInteraction.contact_id == c.id):
        if i.summary:
            i.summary = ""; db.add(i); n_int += 1
    n_cons = 0
    for x in db.query(CrmConsent).filter(CrmConsent.contact_id == c.id):
        x.evidence = "[đã xoá theo yêu cầu]" if x.evidence else ""
        if x.status == "granted":
            x.status, x.withdrawn_at, x.withdrawn_reason, x.withdrawn_by_member_id = "withdrawn", datetime.utcnow(), \
                f"Xoá dữ liệu theo yêu cầu #{request_id}", actor
        db.add(x); n_cons += 1
    c.name, c.phone, c.email, c.address, c.org_name, c.notes, c.tags, c.segment = f"[đã xoá #{c.id}]", "", "", "", "", "", None, ""
    c.search_text, c.status, c.erased_at = "", "erased", datetime.utcnow()
    db.add(c)
    return {"pre_erase_sha256": digest, "interactions_cleared": n_int, "consents_closed": n_cons}


def tick(db: Session, now: datetime | None = None) -> int:
    """Beat (business.tick): yêu cầu sắp quá hạn phản hồi / thực hiện → nhắc MỘT lần mỗi mốc cho người xử lý + chủ."""
    from app.services import authority, inbox
    now = now or datetime.utcnow()
    n = 0
    for r in db.query(CrmDataRequest).filter(CrmDataRequest.status.in_(("open", "in_progress")), CrmDataRequest.reminded_at.is_(None)):
        if r.due_at - now > timedelta(days=3) and not (r.acknowledged_at is None and r.ack_due_at <= now):
            continue
        owner = authority.owner_member(db, r.organization_id, r.company_id)
        inbox.notify(db, organization_id=r.organization_id, recipients=[r.handler_member_id, owner], kind="dsr_due",
                     company_id=r.company_id, priority="high", related_type="crm_request", related_id=str(r.id), task_id=r.task_id,
                     title=f"Yêu cầu dữ liệu cá nhân #{r.id} ({r.kind}) sắp/đã quá hạn {(r.due_at + timedelta(hours=7)):%d/%m/%Y}",
                     commit=False)
        r.reminded_at = now; db.add(r); n += 1
    db.commit()
    return n


# ------------------------------------------------------------------ agent (MCP)

def agent_lookup(db: Session, member: Member, *, query: str = "", contact_id: int | None = None, limit: int = 5) -> dict:
    """Cắt theo quyền: cùng công ty; phòng của agent (hoặc liên hệ chưa gán phòng); có đồng ý service / ai_processing đang hiệu
    lực; không hạn chế / không xoá. PII luôn che. Không trả ghi chú nội bộ; lịch sử chỉ 5 tương tác gần nhất (đã bỏ nội dung
    marketing bị chặn)."""
    if not member.company_id:
        return {"contacts": [], "note": "Seat không thuộc công ty nào"}
    q = db.query(CrmContact).filter(CrmContact.company_id == member.company_id, CrmContact.status == "active",
                                    CrmContact.restricted.is_(False))
    if member.department_id:
        q = q.filter((CrmContact.department_id.is_(None)) | (CrmContact.department_id == member.department_id))
    else:
        q = q.filter(CrmContact.department_id.is_(None))
    if contact_id:
        q = q.filter(CrmContact.id == contact_id)
    rows = q.order_by(CrmContact.id.desc()).limit(500).all()
    uq = _u(query)
    words = [w for w in uq.split() if len(w) > 1]
    if words and not contact_id:
        rows = [c for c in rows if all(w in c.search_text for w in words)]
    out, hidden = [], 0
    for c in rows:
        purposes = {x.purpose for x in active_consents(db, c.id)}
        if not purposes & set(AGENT_READ_PURPOSES):
            hidden += 1
            continue
        hist = (db.query(CrmInteraction).filter(CrmInteraction.contact_id == c.id, CrmInteraction.kind != "outreach_blocked")
                .order_by(CrmInteraction.occurred_at.desc()).limit(5).all())
        out.append({"contact_id": c.id, "name": c.name, "kind": c.kind, "org_name": c.org_name, "segment": c.segment,
                    "tags": c.tags or [], "phone": mask_phone(c.phone), "email": mask_email(c.email),
                    "marketing_allowed_channels": sorted({x.channel for x in active_consents(db, c.id) if x.purpose == "marketing"}),
                    "recent": [{"kind": i.kind, "channel": i.channel, "when": i.occurred_at.date().isoformat(),
                                "summary": (i.summary or "")[:200]} for i in hist]})
        if len(out) >= max(1, min(limit, 20)):
            break
    return {"contacts": out, "pii": "masked",
            "rules": "PII đã che — không hỏi lại / không đoán số điện thoại, email. Marketing chỉ qua company_customer_outreach "
                     "(hệ thống chặn liên hệ chưa đồng ý).",
            **({"hidden_without_consent": hidden} if hidden else {})}
