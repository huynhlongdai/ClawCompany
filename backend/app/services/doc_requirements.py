"""M3d — hồ sơ bắt buộc & lưu trữ. Spec: docs/company-knowledge-library-and-gaps.md §A2, §A8, §C M3d.

* Danh mục ``document_requirements`` là dữ liệu sửa được theo công ty, gieo mặc định từ các điểm ĐÃ KIỂM CHỨNG của bản
  kế hoạch (Luật DN 2020 Đ11, Luật 76/2025, Luật Kế toán Đ41 + NĐ 174/2016, BLLĐ 2019 Đ118–121, Luật 91/2025 + NĐ 356/2025);
  mục chưa đối chiếu văn bản gốc mang ``needs_review`` = "cần kiểm tra". Đây là LỊCH THAM KHẢO, không phải tư vấn pháp lý.
* Áp dụng theo điều kiện: loại hình (hồ sơ pháp nhân), số lao động là NGƯỜI (ghế agent không tính), có xử lý dữ liệu cá
  nhân, ngành (tên ngành công ty). Đạt = có tài liệu/hồ sơ đúng loại đang hiệu lực, hoặc tài liệu được gắn thẳng vào mục.
* Lưu trữ: ``retention_class`` → ``retain_until`` tự tính (mốc NĐ 174: kết thúc kỳ kế toán năm); huỷ trước hạn → 409; huỷ
  cần chủ; sau huỷ chỉ còn siêu dữ liệu + hash; tới hạn → đúng một thẻ Hộp việc ``record_disposal_due``.
* Giấy phép có ngày hết hạn → một nghĩa vụ trong lịch tuân thủ (M2c) nhắc trước 30 ngày."""
from __future__ import annotations

from datetime import date, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import Company, KnowledgeChunk, KnowledgeDocument, KnowledgeVector, Member
from app.models.documents import DocumentFile, DocumentLink, DocumentRequirement, DocumentVersion

DISCLAIMER_VI = "Lịch tham khảo, không phải tư vấn pháp lý — mục 'cần kiểm tra' chưa được đối chiếu văn bản gốc."
DISCLAIMER_EN = "Reference checklist, not legal advice — items marked 'to verify' have not been checked against the source text."
ENTITY_ALL = ("tnhh_1tv", "tnhh_2tv", "cp", "hop_danh", "dntn")
TEMPLATE_WORDS = {"shop": ("shop", "bán", "cửa hàng", "tiệm", "retail", "ecommerce", "gốm"),
                  "agency": ("agency", "marketing", "quảng cáo", "truyền thông"),
                  "ketoan": ("kế toán", "accounting", "thuế")}


def _R(key, name, name_en, pack, types, level, basis, cond=None, review=False, note=""):
    return {"key": key, "name": name, "name_en": name_en, "pack": pack, "doc_types": types, "level": level,
            "legal_basis": basis, "condition": cond or {}, "needs_review": review, "note": note}


DEFAULTS = [
    # mọi doanh nghiệp
    _R("reg_certificate", "Giấy chứng nhận đăng ký doanh nghiệp", "Business registration certificate", "all", ["legal_registration"],
       "required", "Luật Doanh nghiệp 59/2020/QH14, Điều 11 khoản 1 điểm b (giấy phép và giấy chứng nhận khác)"),
    _R("charter", "Điều lệ công ty", "Company charter", "all", ["charter_legal"], "required",
       "Luật Doanh nghiệp 2020, Điều 11 khoản 1 điểm a", {"entity_types": ["tnhh_1tv", "tnhh_2tv", "cp", "hop_danh"]}),
    _R("member_register", "Sổ đăng ký thành viên / cổ đông", "Members / shareholders register", "all", ["member_register"], "required",
       "Luật Doanh nghiệp 2020, Điều 11 khoản 1 điểm a", {"entity_types": ["tnhh_2tv", "cp", "hop_danh"]}),
    _R("beneficial_owners", "Danh sách chủ sở hữu hưởng lợi (nếu có)", "Beneficial owners list (if any)", "all", ["beneficial_owners"],
       "required", "Luật 76/2025/QH15 sửa Luật DN (hiệu lực 01/07/2025): Điều 11 khoản 1 điểm h; lưu ≥ 05 năm sau giải thể"),
    _R("minutes", "Biên bản họp & quyết định của chủ sở hữu / HĐTV / HĐQT", "Meeting minutes & resolutions", "all",
       ["meeting_minutes", "resolution"], "required", "Luật Doanh nghiệp 2020, Điều 11 khoản 1 điểm d"),
    _R("accounting_books", "Sổ kế toán, chứng từ, báo cáo tài chính năm", "Ledgers, vouchers, annual financial statements", "all",
       ["ledger", "accounting_voucher", "financial_statement"], "required",
       "Luật DN 2020 Đ11 k1 điểm g; Luật Kế toán 88/2015 Đ41 (VBHN 25/VBHN-VPQH 2025); NĐ 174/2016 Đ12–14 (5/10 năm/vĩnh viễn)"),
    _R("licenses", "Giấy phép con theo ngành nghề có điều kiện", "Sector licences (conditional business lines)", "all", ["license"],
       "recommended", "Luật DN 2020 Đ11 k1 điểm b — danh sách ngành có điều kiện cần kiểm tra theo ngành của công ty", review=True),
    _R("authority_doc", "Ma trận phân quyền bằng văn bản", "Written delegation of authority", "all", ["authority_policy"],
       "recommended", "Thực hành quản trị (không bắt buộc theo luật)"),
    # có người lao động (người, không tính agent)
    _R("employment_contracts", "Hợp đồng lao động từng người", "Employment contract per employee", "employees", ["employment_contract"],
       "required", "Bộ luật Lao động 45/2019/QH14 (giao kết hợp đồng lao động)", {"min_humans": 1}),
    _R("labor_rules_written", "Nội quy lao động bằng văn bản + đăng ký tại Sở", "Written labour rules + registration", "employees",
       ["labor_rules"], "required",
       "BLLĐ 2019 Đ118 (từ 10 NLĐ phải bằng văn bản), Đ119 (đăng ký trong 10 ngày), Đ121 (hiệu lực sau 15 ngày)", {"min_humans": 10}),
    _R("labor_rules_basic", "Nội quy lao động (dưới 10 NLĐ: không bắt buộc bằng văn bản)", "Labour rules (under 10 employees: writing optional)",
       "employees", ["labor_rules"], "recommended",
       "BLLĐ 2019 Đ118 k1; NĐ 145/2020 Đ69 k1 (thoả thuận kỷ luật, trách nhiệm vật chất trong HĐLĐ)", {"min_humans": 1, "max_humans": 9}),
    _R("salary_scale", "Thang lương, bảng lương", "Salary scale", "employees", ["internal_regulation"], "recommended",
       "BLLĐ 2019 Đ93 — cần kiểm tra", {"min_humans": 1}, review=True),
    _R("handbook", "Sổ tay nhân viên", "Employee handbook", "employees", ["handbook"], "recommended", "Thực hành tốt", {"min_humans": 1}),
    # có xử lý dữ liệu cá nhân
    _R("privacy_notice", "Chính sách / thông báo xử lý dữ liệu cá nhân", "Personal data processing notice", "personal_data",
       ["privacy_notice"], "required", "Luật Bảo vệ dữ liệu cá nhân 91/2025/QH15 (hiệu lực 01/01/2026)", {"personal_data": True}),
    _R("dpia", "Hồ sơ đánh giá tác động xử lý dữ liệu cá nhân", "Personal data processing impact assessment", "personal_data",
       ["dpia"], "required", "NĐ 356/2025/NĐ-CP (thay NĐ 13/2023) — ngưỡng áp dụng cho DN nhỏ cần kiểm tra", {"personal_data": True}, review=True),
    _R("dsr_procedure", "Quy trình yêu cầu của chủ thể dữ liệu & sự cố lộ lọt", "Data subject request & breach procedure", "personal_data",
       [], "recommended", "Luật 91/2025/QH15; NĐ 356/2025 — gắn SOP tương ứng vào mục này", {"personal_data": True}),
    _R("ai_data_policy", "Chính sách dùng AI với dữ liệu khách", "AI use policy for customer data", "personal_data", [],
       "recommended", "NĐ 356/2025/NĐ-CP có quy định DLCN trong hệ thống AI — gắn chính sách vào mục này", {"personal_data": True}),
    # theo ngành
    _R("shop_customer_policies", "Chính sách đổi trả, vận chuyển, bảo hành, bảo mật hiển thị cho khách", "Customer-facing return, shipping, warranty, privacy policies",
       "shop", ["policy"], "recommended", "NĐ thương mại điện tử 52/2013, 85/2021 — cần kiểm tra", {"templates": ["shop"]}, review=True),
    _R("shop_faq", "FAQ chăm sóc khách", "Customer service FAQ", "shop", ["faq", "kcs_article"], "recommended", "Thực hành tốt",
       {"templates": ["shop"]}),
    _R("shop_price_list", "Bảng giá hiện hành (cho agent bán hàng)", "Current price list (for sales agents)", "shop", ["price_list"],
       "required", "Điều kiện vận hành của agent (không phải luật) — đạt khi có bảng giá hoặc danh mục sản phẩm có giá", {"templates": ["shop"]}),
    _R("agency_templates", "Mẫu hợp đồng dịch vụ, NDA, quy trình duyệt nội dung với khách", "Service contract & NDA templates, client approval flow",
       "agency", ["template", "nda", "sop"], "recommended", "Thực hành tốt", {"templates": ["agency"]}),
    _R("ketoan_license", "Chứng chỉ / đăng ký hành nghề dịch vụ kế toán", "Accounting services practice licence", "ketoan", ["license"],
       "required", "Luật Kế toán 2015 (dịch vụ kế toán) — cần kiểm tra", {"templates": ["ketoan"]}, review=True),
]


# ------------------------------------------------------------------ gieo + CRUD

def _company(db: Session, org_id: int, company_id: int | None, *, write: bool = False) -> Company:
    from app.services.company_foundation import _company as c
    return c(db, org_id, company_id, write=write)


def seed_defaults(db: Session, org_id: int, company_id: int, *, replace: bool = False) -> dict:
    have = {r.key for r in db.query(DocumentRequirement).filter(DocumentRequirement.company_id == company_id)}
    if replace:
        db.query(DocumentRequirement).filter(DocumentRequirement.company_id == company_id,
                                             DocumentRequirement.source == "default").delete(synchronize_session=False)
        have = set()
    n = 0
    for spec in DEFAULTS:
        if spec["key"] in have:
            continue
        db.add(DocumentRequirement(organization_id=org_id, company_id=company_id, source="default", enabled=True, **spec)); n += 1
    db.commit()
    return {"seeded": n}


def _req(db: Session, org_id: int, rid: int) -> DocumentRequirement:
    r = db.get(DocumentRequirement, rid)
    if r is None or r.organization_id != org_id:
        raise HTTPException(404, "Không thấy mục hồ sơ")
    from app.core import company_scope
    company_scope.check(r.company_id)
    return r


def upsert(db: Session, org_id: int, data: dict, rid: int | None = None) -> dict:
    if rid:
        r = _req(db, org_id, rid)
    else:
        co = _company(db, org_id, data.get("company_id"), write=True)
        if not (data.get("name") or "").strip():
            raise HTTPException(422, "Thiếu tên mục hồ sơ")
        r = DocumentRequirement(organization_id=org_id, company_id=co.id, source="custom", key=f"custom_{int(datetime.utcnow().timestamp())}")
    from app.services.doc_library import DOC_TYPES
    for k in ("name", "name_en", "legal_basis", "note"):
        if data.get(k) is not None:
            setattr(r, k, str(data[k])[:2000])
    if data.get("level") is not None:
        if data["level"] not in ("required", "recommended"):
            raise HTTPException(422, "level: required | recommended")
        r.level = data["level"]
    if data.get("doc_types") is not None:
        bad = [t for t in data["doc_types"] if t not in DOC_TYPES]
        if bad:
            raise HTTPException(422, f"doc_type lạ: {', '.join(bad)}")
        r.doc_types = list(data["doc_types"])
    for k in ("enabled", "needs_review"):
        if data.get(k) is not None:
            setattr(r, k, bool(data[k]))
    if data.get("condition") is not None:
        r.condition = dict(data["condition"])
    r.updated_at = datetime.utcnow()
    db.add(r); db.commit(); db.refresh(r)
    return {"id": r.id, "key": r.key}


# ------------------------------------------------------------------ đánh giá

def facts_of(db: Session, co: Company) -> dict:
    from app.models.company_foundation import CompanyProfile
    p = db.query(CompanyProfile).filter(CompanyProfile.company_id == co.id).first()
    humans = (db.query(Member).filter(Member.company_id == co.id, Member.member_type == "human", Member.status != "archived").count())
    s = (getattr(p, "compliance", None) or {}) if p is not None else {}
    ind = (co.industry or "").lower() + " " + (co.name or "").lower()
    templates = [k for k, words in TEMPLATE_WORDS.items() if any(w in ind for w in words)]
    return {"entity_type": (p.entity_type if p is not None else "") or "", "humans": humans,
            "personal_data": bool(s.get("personal_data", True)), "templates": templates}


def applies(r: DocumentRequirement, f: dict) -> tuple[bool, str]:
    c = r.condition or {}
    if c.get("entity_types") and f["entity_type"] and f["entity_type"] not in c["entity_types"]:
        return False, f"không áp dụng cho loại hình {f['entity_type']}"
    if c.get("min_humans") is not None and f["humans"] < int(c["min_humans"]):
        return False, f"{f['humans']} người lao động (< {c['min_humans']}; agent không tính)"
    if c.get("max_humans") is not None and f["humans"] > int(c["max_humans"]):
        return False, f"{f['humans']} người lao động (> {c['max_humans']})"
    if c.get("personal_data") and not f["personal_data"]:
        return False, "công ty khai không xử lý dữ liệu cá nhân"
    if c.get("templates") and not set(c["templates"]) & set(f["templates"]):
        return False, "không thuộc ngành của mục này"
    return True, ""


def _live(doc: KnowledgeDocument, now: datetime) -> bool:
    return doc.status == "published" and (doc.effective_to is None or doc.effective_to > now)


def evaluate(db: Session, org_id: int, company_id: int | None, *, principal=None) -> dict:
    co = _company(db, org_id, company_id)
    if not db.query(DocumentRequirement.id).filter(DocumentRequirement.company_id == co.id).first():
        seed_defaults(db, org_id, co.id)
    f = facts_of(db, co)
    now = datetime.utcnow()
    docs = db.query(KnowledgeDocument).filter(KnowledgeDocument.organization_id == org_id,
                                              (KnowledgeDocument.company_id == co.id) | (KnowledgeDocument.company_id.is_(None))).all()
    links = {}
    for lk in db.query(DocumentLink).filter(DocumentLink.target_type == "requirement",
                                            DocumentLink.document_id.in_([d.id for d in docs] or [-1])):
        links.setdefault(lk.target_id, []).append(lk.document_id)
    by_id = {d.id: d for d in docs}
    items = []
    for r in db.query(DocumentRequirement).filter(DocumentRequirement.company_id == co.id).order_by(DocumentRequirement.id):
        ok_apply, why = applies(r, f)
        if not r.enabled:
            ok_apply, why = False, "đã tắt"
        matched = [d for d in docs if d.doc_type in (r.doc_types or []) and _live(d, now)]
        matched += [by_id[i] for i in links.get(r.id, []) if i in by_id and _live(by_id[i], now) and by_id[i] not in matched]
        if r.key == "shop_price_list" and not matched:
            try:
                from app.services import catalog
                if catalog.has_active_prices(db, co.id):
                    matched = ["catalog"]
            except Exception:  # noqa: BLE001 — M3f chưa có
                pass
        status = "na" if not ok_apply else ("ok" if matched else "missing")
        items.append({"id": r.id, "key": r.key, "name": r.name, "name_en": r.name_en or r.name, "pack": r.pack, "level": r.level,
                      "legal_basis": r.legal_basis, "needs_review": bool(r.needs_review), "enabled": bool(r.enabled),
                      "doc_types": r.doc_types or [], "condition": r.condition or {}, "source": r.source, "status": status,
                      "why": why, "note": r.note,
                      "documents": [{"id": d.id, "doc_code": d.doc_code, "title": d.title} if not isinstance(d, str)
                                    else {"id": None, "doc_code": "CATALOG", "title": "Danh mục sản phẩm có giá"} for d in matched][:5]})
    req = [i for i in items if i["status"] != "na" and i["level"] == "required"]
    return {"company_id": co.id, "facts": f, "items": items, "disclaimer_vi": DISCLAIMER_VI, "disclaimer_en": DISCLAIMER_EN,
            "required_total": len(req), "required_ok": sum(1 for i in req if i["status"] == "ok"),
            "retention": retention_overview(db, co.id, now)}


# ------------------------------------------------------------------ lưu trữ

def _add_years(d: datetime, n: int) -> datetime:
    try:
        return d.replace(year=d.year + n)
    except ValueError:
        return d.replace(year=d.year + n, day=28)


def compute_retain_until(doc: KnowledgeDocument, *, now: datetime | None = None) -> datetime | None:
    now = now or datetime.utcnow()
    base = doc.effective_from or getattr(doc, "created_at", None) or now
    cls = doc.retention_class or ""
    if cls in ("acct_10y", "acct_5y"):
        n = 10 if cls == "acct_10y" else 5
        return datetime(base.year + n, 12, 31, 23, 59)      # NĐ 174: mốc = kết thúc kỳ kế toán năm (năm dương lịch)
    if cls == "5y":
        return _add_years(base, 5)
    if cls == "superseded_10y":
        return _add_years(now, 10) if doc.status in ("superseded", "archived") else None
    if cls == "10y_after_end":
        return _add_years(doc.effective_to, 10) if doc.effective_to else None
    return None          # company_life | bo_5y_after | permanent | purpose_end | "" → không tự huỷ


def refresh_retention(db: Session, doc: KnowledgeDocument) -> None:
    doc.retain_until = compute_retain_until(doc)
    db.add(doc)


def retention_overview(db: Session, company_id: int, now: datetime) -> dict:
    rows = (db.query(KnowledgeDocument).filter(KnowledgeDocument.company_id == company_id, KnowledgeDocument.status != "disposed",
                                               KnowledgeDocument.retain_until.isnot(None)).order_by(KnowledgeDocument.retain_until).limit(200).all())
    return {"items": [{"id": d.id, "doc_code": d.doc_code, "title": d.title, "retention_class": d.retention_class,
                       "retain_until": d.retain_until.isoformat(), "legal_hold": bool(d.legal_hold),
                       "due": d.retain_until <= now and not d.legal_hold} for d in rows],
            "due": sum(1 for d in rows if d.retain_until <= now and not d.legal_hold)}


def can_delete(doc: KnowledgeDocument, now: datetime | None = None) -> None:
    """Chốt chung cho mọi đường xoá: hồ sơ / còn hạn lưu / giữ pháp lý → 409."""
    now = now or datetime.utcnow()
    if doc.legal_hold:
        raise HTTPException(409, "Tài liệu đang 'giữ theo yêu cầu pháp lý' — không xoá/huỷ được")
    if doc.retain_until and doc.retain_until > now:
        raise HTTPException(409, f"Còn hạn lưu trữ tới {doc.retain_until:%d/%m/%Y} — không xoá trước hạn")
    if doc.doc_class == "record" and not doc.retain_until:
        raise HTTPException(409, "Hồ sơ không có hạn huỷ (lưu suốt đời doanh nghiệp / theo luật) — không xoá được")


def dispose(db: Session, org_id: int, principal, doc_id: int, reason: str = "") -> dict:
    from app.core import company_scope
    from app.services import company_facts, doc_library
    doc = doc_library.get_doc(db, org_id, doc_id)
    role = company_scope.role_in(doc.company_id, principal) if company_scope.restricted(principal) else getattr(principal, "role", "")
    if role != "owner":
        raise HTTPException(403, "Huỷ hồ sơ cần chủ doanh nghiệp duyệt (vai trò owner)")
    if doc.status == "disposed":
        raise HTTPException(409, "Đã huỷ")
    now = datetime.utcnow()
    if not doc.retain_until:
        raise HTTPException(409, "Tài liệu không có hạn huỷ — không huỷ được")
    can_delete(doc, now)
    old = [c.id for c in db.query(KnowledgeChunk.id).filter(KnowledgeChunk.document_id == doc.id)]
    if old:
        db.query(KnowledgeVector).filter(KnowledgeVector.chunk_id.in_(old)).delete(synchronize_session=False)
        db.query(KnowledgeChunk).filter(KnowledgeChunk.document_id == doc.id).delete(synchronize_session=False)
    for v in db.query(DocumentVersion).filter(DocumentVersion.document_id == doc.id):
        v.content = ""; db.add(v)                       # giữ content_hash làm bằng chứng
    for fid in {doc.file_id} | {v.file_id for v in db.query(DocumentVersion).filter(DocumentVersion.document_id == doc.id)}:
        f = db.get(DocumentFile, fid) if fid else None
        if f is not None:
            f.data, f.meta = b"", {**(f.meta or {}), "disposed_at": now.isoformat()}; db.add(f)
    doc.content, doc.status, doc.disposed_at = "", "disposed", now
    doc.disposed_by = doc_library._seat(db, principal, doc.company_id)
    db.add(doc); db.commit()
    company_facts.retire_doc(db, doc)
    from app.services.company_event_bus import emit_event
    emit_event(db, organization_id=org_id, company_id=doc.company_id, event_type="document.disposed", source="doc_library",
               aggregate_type="document", aggregate_id=str(doc.id), actor_member_id=doc.disposed_by,
               payload={"doc_code": doc.doc_code, "content_hash": doc.content_hash, "reason": reason[:300]})
    return doc_library.public(db, doc, principal=principal, detail=True)


def disposal_tick(db: Session, now: datetime | None = None, org_id: int | None = None) -> int:
    from app.services import inbox
    from app.services.doc_library import _review_owner
    now = now or datetime.utcnow()
    q = db.query(KnowledgeDocument).filter(KnowledgeDocument.status != "disposed", KnowledgeDocument.retain_until.isnot(None),
                                           KnowledgeDocument.retain_until <= now, KnowledgeDocument.legal_hold.is_(False),
                                           KnowledgeDocument.disposal_notified_at.is_(None))
    if org_id:
        q = q.filter(KnowledgeDocument.organization_id == org_id)
    n = 0
    for d in q.all():
        from app.services import authority
        owner = authority.owner_member(db, d.organization_id, d.company_id) or _review_owner(db, d)
        inbox.notify(db, organization_id=d.organization_id, recipients=[owner], kind="record_disposal_due", company_id=d.company_id,
                     title=f"{d.doc_code} hết hạn lưu trữ ({d.retain_until:%d/%m/%Y}) — chờ chủ duyệt huỷ: {d.title}",
                     related_type="document", related_id=str(d.id), commit=False)
        d.disposal_notified_at = now; db.add(d); n += 1
    db.commit()
    return n


# ------------------------------------------------------------------ giấy phép → lịch tuân thủ

def sync_license_deadline(db: Session, doc: KnowledgeDocument) -> int | None:
    """Giấy phép có ngày hết hạn (effective_to) → nghĩa vụ "Gia hạn …" một lần trong lịch tuân thủ, nhắc trước 30 ngày."""
    if doc.doc_type != "license" or not doc.company_id:
        return None
    from app.models.company_ops import ComplianceRule
    from app.services import compliance_calendar
    key = f"doc_license:{doc.id}"
    r = db.query(ComplianceRule).filter(ComplianceRule.company_id == doc.company_id, ComplianceRule.key == key).first()
    from app.models.company_ops import ComplianceDeadline

    def _skip_open(keep: date | None = None) -> None:
        # hạn đã sinh nhưng không còn đúng (giấy phép lưu trữ / gia hạn sang ngày khác) → bỏ, để không nhắc nhầm
        if r is None or r.id is None:
            return
        for dl in db.query(ComplianceDeadline).filter(ComplianceDeadline.rule_id == r.id, ComplianceDeadline.status == "upcoming"):
            if keep is None or dl.statutory_date != keep:
                dl.status = "skipped"; db.add(dl)
    if not doc.effective_to or doc.status in ("archived", "disposed", "superseded"):
        if r is not None:
            r.enabled = False; db.add(r); _skip_open(); db.commit()
        return None
    _skip_open(doc.effective_to.date())
    if r is None:
        r = ComplianceRule(organization_id=doc.organization_id, company_id=doc.company_id, key=key, category="license", source="custom")
    r.name = f"Gia hạn {doc.title} ({doc.doc_code})"[:200]
    r.frequency, r.due_rule, r.remind_days, r.enabled = "once", {"type": "fixed_date", "date": doc.effective_to.date().isoformat()}, 30, True
    r.legal_basis = "Luật Doanh nghiệp 2020 Đ11 k1 điểm b (giấy phép); hạn theo chính giấy phép"
    r.note = f"Tự sinh từ hồ sơ {doc.doc_code} (M3d)"
    db.add(r); db.commit(); db.refresh(r)
    compliance_calendar.generate(db, doc.organization_id, doc.company_id)
    return r.id


# ------------------------------------------------------------------ chấm sẵn sàng

def readiness_checks(db: Session, co: Company) -> list[tuple[str, str, float, str]]:
    """(key, nhãn, điểm 0..1, chi tiết) cho lớp "Hồ sơ & tài liệu" của agent_readiness."""
    ev = evaluate(db, co.organization_id, co.id)
    req_total, req_ok = ev["required_total"], ev["required_ok"]
    from app.services.doc_library import review_state
    docs = (db.query(KnowledgeDocument).filter(KnowledgeDocument.company_id == co.id, KnowledgeDocument.status == "published",
                                               KnowledgeDocument.agent_use.in_(("core", "retrieve"))).all())
    fresh = sum(1 for d in docs if review_state(d) in ("ok", "none"))
    return [("required_records", "Hồ sơ bắt buộc đã có (đang hiệu lực)", (req_ok / req_total) if req_total else 0.0,
             f"{req_ok}/{req_total} mục bắt buộc"),
            ("doc_freshness", "Tài liệu agent dùng còn trong hạn rà soát", (fresh / len(docs)) if docs else 0.0,
             f"{fresh}/{len(docs)} tài liệu")]
