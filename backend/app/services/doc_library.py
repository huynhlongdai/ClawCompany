"""M3a — thư viện tài liệu & hồ sơ công ty (ISO 9001 §7.5). Spec: docs/company-knowledge-library-and-gaps.md §A3–A5.

* Một tài liệu = một dòng ``knowledge_documents`` (sổ tài liệu). ``content`` của dòng đó LUÔN là bản đã ban hành —
  agent chỉ đọc cột này (qua ``knowledge_hub``), nên bản nháp/chờ duyệt không bao giờ tới agent.
* Phiên bản ở ``knowledge_document_versions``: nháp sửa được; rời nháp (gửi duyệt) là BẤT BIẾN — sửa = phiên bản mới.
* Hai lớp: ``document`` (có phiên bản, duyệt, hiệu lực, bị thay thế) và ``record`` (bằng chứng: lưu là khoá, không
  nháp/duyệt; thay = hồ sơ mới trỏ ``supersedes_id``).
* Vòng đời: draft → in_review → approved → published → superseded/archived. Duyệt theo ma trận phân quyền, loại việc
  ``doc_publish`` (gieo mặc định nếu công ty chưa có): mặc định trưởng phòng; rủi ro cao (chính sách gửi khách,
  nội quy, quy chế) → chủ. Người duyệt luôn là NGƯỜI; tác giả không tự duyệt bản của mình.
* Nhắc rà soát: ``tick`` (beat ``docs.tick`` mỗi giờ) — hạn rà soát tới → đúng MỘT thẻ Hộp việc ``doc_review_due``
  cho người phụ trách; ``effective_to`` qua → lưu trữ (rời AGENTS.md); bản đã duyệt tới ngày hiệu lực → ban hành.

Giới hạn tự khai: sửa siêu dữ liệu (đối tượng, nhạy cảm, cách agent dùng) không đi qua duyệt — chỉ ghi nhật ký
``company_events``; quyền sửa là manager của công ty (R1)."""
from __future__ import annotations

import difflib
import hashlib
import re
from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models import Approval, Company, KnowledgeDocument, Member
from app.models.documents import DocumentFile, DocumentLink, DocumentVersion

# ------------------------------------------------------------------ phân loại (A3)

GROUPS = {
    "legal": {"vi": "Pháp lý & quản trị", "en": "Legal & governance", "prefix": "LEG"},
    "policy": {"vi": "Chính sách & sổ tay", "en": "Policies & handbook", "prefix": "POL"},
    "process": {"vi": "Quy trình & mẫu", "en": "Processes & templates", "prefix": "PRC"},
    "product": {"vi": "Sản phẩm & thương hiệu", "en": "Products & brand", "prefix": "PRD"},
    "customer": {"vi": "Khách hàng", "en": "Customers", "prefix": "CUS"},
    "contract": {"vi": "Hợp đồng & đối tác", "en": "Contracts & partners", "prefix": "CON"},
    "hr": {"vi": "Nhân sự", "en": "People", "prefix": "HR"},
    "finance": {"vi": "Tài chính", "en": "Finance", "prefix": "FIN"},
}


def _T(group, cls, use, review, retention="", sens="internal", vi="", en="", risk="medium"):
    return {"group": group, "doc_class": cls, "agent_use": use, "review_days": review, "retention": retention,
            "sensitivity": sens, "vi": vi, "en": en, "risk": risk}


DOC_TYPES = {
    "legal_registration": _T("legal", "record", "none", None, "company_life", "internal", "Giấy chứng nhận ĐKDN", "Business registration"),
    "charter_legal": _T("legal", "record", "none", None, "company_life", "internal", "Điều lệ công ty", "Company charter"),
    "member_register": _T("legal", "record", "none", None, "company_life", "personal_data", "Sổ đăng ký thành viên/cổ đông", "Members/shareholders register"),
    "beneficial_owners": _T("legal", "record", "none", None, "bo_5y_after", "personal_data", "Danh sách chủ sở hữu hưởng lợi", "Beneficial owners list"),
    "license": _T("legal", "record", "none", None, "company_life", "internal", "Giấy phép / chứng nhận", "License / certificate"),
    "ip_certificate": _T("legal", "record", "none", None, "company_life", "internal", "Văn bằng sở hữu trí tuệ", "IP certificate"),
    "asset_title": _T("legal", "record", "none", None, "company_life", "confidential", "Giấy tờ sở hữu tài sản", "Asset title"),
    "internal_regulation": _T("legal", "document", "retrieve", 365, "superseded_10y", "internal", "Quy chế quản lý nội bộ", "Internal regulation", "high"),
    "meeting_minutes": _T("legal", "record", "none", None, "company_life", "confidential", "Biên bản họp", "Meeting minutes"),
    "resolution": _T("legal", "record", "retrieve", None, "company_life", "internal", "Nghị quyết / quyết định", "Resolution / decision"),
    "authority_policy": _T("legal", "document", "retrieve", 365, "superseded_10y", "internal", "Văn bản phân quyền", "Delegation of authority", "high"),
    "board_report": _T("legal", "record", "none", None, "company_life", "confidential", "Báo cáo HĐQT / chủ sở hữu", "Board report"),
    "dpia": _T("legal", "document", "none", 365, "superseded_10y", "confidential", "Đánh giá tác động xử lý DLCN", "Data protection impact assessment", "high"),
    "audit_conclusion": _T("legal", "record", "none", None, "company_life", "confidential", "Kết luận kiểm toán / thanh tra", "Audit conclusion"),
    "strategy_plan": _T("legal", "document", "retrieve", 180, "acct_10y", "confidential", "Kế hoạch chiến lược / OKR", "Strategy / OKR plan"),
    "policy": _T("policy", "document", "core", 180, "superseded_10y", "internal", "Chính sách", "Policy", "high"),
    "privacy_notice": _T("policy", "document", "retrieve", 180, "superseded_10y", "public", "Thông báo xử lý dữ liệu cá nhân", "Privacy notice", "high"),
    "handbook": _T("policy", "document", "retrieve", 180, "superseded_10y", "internal", "Sổ tay", "Handbook"),
    "labor_rules": _T("policy", "document", "retrieve", 365, "superseded_10y", "internal", "Nội quy lao động", "Labour rules", "high"),
    "code_of_conduct": _T("policy", "document", "retrieve", 365, "superseded_10y", "internal", "Quy tắc ứng xử", "Code of conduct", "high"),
    "external_law": _T("policy", "document", "retrieve", 180, "", "public", "Văn bản pháp luật (bên ngoài)", "External law"),
    "platform_policy": _T("policy", "document", "retrieve", 90, "", "public", "Chính sách sàn / nền tảng", "Platform policy"),
    "other": _T("policy", "document", "retrieve", 180, "", "internal", "Khác", "Other"),
    "sop": _T("process", "document", "retrieve", 90, "superseded_10y", "internal", "Quy trình (SOP)", "SOP", "low"),
    "work_instruction": _T("process", "document", "retrieve", 90, "superseded_10y", "internal", "Hướng dẫn công việc", "Work instruction", "low"),
    "checklist": _T("process", "document", "retrieve", 90, "", "internal", "Checklist", "Checklist", "low"),
    "template": _T("process", "document", "tool_only", 180, "", "internal", "Mẫu biểu", "Template", "low"),
    "lesson": _T("process", "record", "retrieve", None, "5y", "internal", "Bài học", "Lesson"),
    "postmortem": _T("process", "record", "retrieve", None, "5y", "internal", "Phân tích sự cố", "Postmortem"),
    "decision_record": _T("process", "record", "retrieve", None, "5y", "internal", "Hồ sơ quyết định (ADR)", "Decision record"),
    "product_sheet": _T("product", "document", "retrieve", 90, "5y", "public", "Mô tả sản phẩm", "Product sheet"),
    "price_list": _T("product", "document", "tool_only", 30, "5y", "internal", "Bảng giá", "Price list", "high"),
    "service_catalog": _T("product", "document", "retrieve", 90, "5y", "public", "Danh mục dịch vụ", "Service catalogue"),
    "promo": _T("product", "document", "retrieve", 30, "5y", "public", "Khuyến mãi", "Promotion", "high"),
    "brand_guide": _T("product", "document", "core", 180, "", "internal", "Bộ nhận diện / giọng thương hiệu", "Brand guide"),
    "tone_guide": _T("product", "document", "core", 180, "", "internal", "Giọng văn", "Tone guide"),
    "content_template": _T("product", "document", "retrieve", 180, "", "internal", "Mẫu nội dung", "Content template", "low"),
    "faq": _T("customer", "document", "retrieve", 60, "", "public", "Câu hỏi thường gặp", "FAQ"),
    "kcs_article": _T("customer", "document", "retrieve", 60, "", "internal", "Bài xử lý (KCS)", "Knowledge article (KCS)"),
    "canned_reply": _T("customer", "document", "retrieve", 60, "", "public", "Mẫu trả lời khách", "Canned reply", "high"),
    "contract": _T("contract", "record", "none", None, "10y_after_end", "confidential", "Hợp đồng (bản ký)", "Signed contract"),
    "nda": _T("contract", "record", "none", None, "10y_after_end", "confidential", "Thoả thuận bảo mật", "NDA"),
    "partner_terms": _T("contract", "document", "retrieve", 365, "", "internal", "Điều khoản đối tác", "Partner terms"),
    "supplier_profile": _T("contract", "document", "retrieve", 365, "", "internal", "Hồ sơ nhà cung cấp", "Supplier profile"),
    "employment_contract": _T("hr", "record", "none", None, "purpose_end", "personal_data", "Hợp đồng lao động", "Employment contract"),
    "hr_file": _T("hr", "record", "none", None, "purpose_end", "personal_data", "Hồ sơ nhân sự", "HR file"),
    "job_description": _T("hr", "document", "retrieve", 365, "", "internal", "Mô tả công việc", "Job description", "low"),
    "accounting_voucher": _T("finance", "record", "none", None, "acct_10y", "confidential", "Chứng từ kế toán", "Accounting voucher"),
    "ledger": _T("finance", "record", "none", None, "acct_10y", "confidential", "Sổ kế toán", "Ledger"),
    "financial_statement": _T("finance", "record", "none", None, "acct_10y", "confidential", "Báo cáo tài chính năm", "Annual financial statement"),
    "tax_filing": _T("finance", "record", "none", None, "acct_10y", "confidential", "Tờ khai thuế", "Tax filing"),
    "invoice": _T("finance", "record", "none", None, "acct_10y", "confidential", "Hoá đơn", "Invoice"),
    "budget_plan": _T("finance", "document", "none", 365, "acct_10y", "confidential", "Kế hoạch ngân sách", "Budget plan"),
}
DOC_CLASSES = ("document", "record")
STATUSES = ("draft", "in_review", "approved", "published", "superseded", "archived", "disposed")
OPEN_VERSION = ("draft", "in_review", "approved")
SENSITIVITY = ("public", "internal", "confidential", "restricted", "personal_data", "sensitive_personal_data")
SENS_RANK = {s: i for i, s in enumerate(SENSITIVITY)}
AGENT_USE = ("core", "retrieve", "tool_only", "none")
STALE_AFTER_DAYS = 30          # quá hạn rà soát 30 ngày → nhãn "cần rà soát" cho agent
LINK_TYPES = ("process", "process_step", "position", "sop", "io_contract", "company_rule", "product", "requirement")
MAX_FILE = 20_000_000


def type_info(t: str) -> dict:
    return DOC_TYPES.get(t) or DOC_TYPES["other"]


def taxonomy() -> dict:
    return {"groups": [{"key": k, **v} for k, v in GROUPS.items()],
            "types": [{"key": k, **v} for k, v in DOC_TYPES.items()],
            "statuses": list(STATUSES), "sensitivity": list(SENSITIVITY), "agent_use": list(AGENT_USE),
            "classes": list(DOC_CLASSES), "link_types": list(LINK_TYPES)}


def _hash(text: str) -> str:
    return hashlib.sha256(re.sub(r"\s+", " ", text or "").strip().encode()).hexdigest()


def _dt(v) -> datetime | None:
    if v in (None, ""):
        return None
    if isinstance(v, datetime):
        return v
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        raise HTTPException(422, f"Ngày không hợp lệ: {v}") from None


def _iso(v: datetime | None) -> str | None:
    return v.isoformat() if v else None


# ------------------------------------------------------------------ quyền người dùng (R1 + nhạy cảm)

def human_max_sensitivity(principal, company_id: int | None) -> int:
    """Trần nhạy cảm người gọi được XEM nội dung: viewer/approver → internal; manager/owner công ty, admin/manager
    tổ chức → confidential; owner/admin tổ chức hoặc chủ công ty → mọi mức (kể cả dữ liệu cá nhân)."""
    from app.core import company_scope
    if principal is None:
        return SENS_RANK["sensitive_personal_data"]
    role = company_scope.role_in(company_id, principal) if company_scope.restricted(principal) else None
    if company_scope.restricted(principal):
        return {"owner": SENS_RANK["sensitive_personal_data"], "manager": SENS_RANK["confidential"]}.get(role or "", SENS_RANK["internal"])
    org_role = getattr(principal, "role", "member")
    if org_role in ("owner", "admin"):
        return SENS_RANK["sensitive_personal_data"]
    if org_role == "manager":
        return SENS_RANK["confidential"]
    return SENS_RANK["internal"]


def _company(db: Session, org_id: int, company_id: int | None, *, write: bool = False) -> Company:
    from app.services.company_foundation import _company as c
    return c(db, org_id, company_id, write=write)


def get_doc(db: Session, org_id: int, doc_id: int, *, principal=None, content: bool = False) -> KnowledgeDocument:
    from app.core import company_scope
    doc = db.get(KnowledgeDocument, doc_id)
    if doc is None or doc.organization_id != org_id:
        raise HTTPException(404, "Không thấy tài liệu")
    company_scope.check(doc.company_id)
    if content and SENS_RANK.get(doc.sensitivity or "internal", 1) > human_max_sensitivity(principal, doc.company_id):
        raise HTTPException(403, f"Tài liệu mức '{doc.sensitivity}' — vai trò của anh chưa đủ để xem nội dung.")
    return doc


def _seat(db: Session, principal, company_id: int | None) -> int | None:
    if principal is None:
        return None
    try:
        return principal.seat_in(company_id)
    except Exception:  # noqa: BLE001
        return None


# ------------------------------------------------------------------ biểu diễn

def _member_name(db: Session, mid: int | None) -> str | None:
    m = db.get(Member, mid) if mid else None
    return m.name if m else None


def review_state(doc: KnowledgeDocument, now: datetime | None = None) -> str:
    """ok | due (quá hạn rà soát) | stale (quá hạn > 30 ngày → agent thấy nhãn cần rà soát) | none"""
    if doc.status != "published" or not doc.review_due_at:
        return "none"
    now = now or datetime.utcnow()
    if doc.review_due_at > now:
        return "ok"
    return "stale" if doc.review_due_at + timedelta(days=STALE_AFTER_DAYS) <= now else "due"


def version_public(db: Session, v: DocumentVersion, *, content: bool = False) -> dict:
    out = {"id": v.id, "version_no": v.version_no, "status": v.status, "title": v.title, "change_note": v.change_note,
           "chars": len(v.content or ""), "content_hash": v.content_hash, "file_id": v.file_id,
           "author": _member_name(db, v.author_member_id), "author_member_id": v.author_member_id,
           "approver": _member_name(db, v.approver_member_id), "approver_member_id": v.approver_member_id,
           "approved_by": _member_name(db, v.approved_by_member_id), "approved_at": _iso(v.approved_at),
           "approval_id": v.approval_id, "review_note": v.review_note, "effective_from": _iso(v.effective_from),
           "published_at": _iso(v.published_at), "created_at": _iso(v.created_at),
           "core_summary": v.core_summary or "", "conflicts": v.conflicts or []}
    if content:
        out["content"] = v.content
    return out


def public(db: Session, doc: KnowledgeDocument, *, principal=None, detail: bool = False) -> dict:
    ti = type_info(doc.doc_type)
    open_v = (db.query(DocumentVersion).filter(DocumentVersion.document_id == doc.id,
                                               DocumentVersion.status.in_(OPEN_VERSION))
              .order_by(DocumentVersion.id.desc()).first())
    pos = None
    if doc.owner_position_id:
        from app.models.company_foundation import Position
        p = db.get(Position, doc.owner_position_id)
        pos = p.title if p else None
    f = db.get(DocumentFile, doc.file_id) if doc.file_id else None
    out = {"id": doc.id, "doc_code": doc.doc_code, "title": doc.title, "doc_type": doc.doc_type, "doc_type_vi": ti["vi"],
           "doc_type_en": ti["en"], "group": ti["group"], "doc_class": doc.doc_class, "status": doc.status,
           "version_no": doc.version_no, "company_id": doc.company_id, "department_id": doc.department_id,
           "owner_position_id": doc.owner_position_id, "owner_position": pos, "owner_member_id": doc.owner_member_id,
           "owner": _member_name(db, doc.owner_member_id), "audience": doc.audience or {}, "sensitivity": doc.sensitivity,
           "agent_use": doc.agent_use, "customer_facing": bool(doc.customer_facing), "lease_shareable": bool(doc.lease_shareable),
           "exportable": bool(doc.exportable), "effective_from": _iso(doc.effective_from), "effective_to": _iso(doc.effective_to),
           "review_interval_days": doc.review_interval_days, "review_due_at": _iso(doc.review_due_at),
           "last_reviewed_at": _iso(doc.last_reviewed_at), "review_state": review_state(doc),
           "supersedes_id": doc.supersedes_id, "source_type": doc.source_type, "source_url": doc.source_url or "",
           "retention_class": doc.retention_class, "retain_until": _iso(doc.retain_until), "legal_hold": bool(doc.legal_hold),
           "file": {"id": f.id, "filename": f.filename, "mime": f.mime, "size": f.size, "sha256": f.sha256} if f else None,
           "pending_version": version_public(db, open_v) if open_v else None, "is_core": bool(doc.is_core),
           "reuse_count": doc.reuse_count or 0, "chars": len(doc.content or ""), "core_summary": doc.core_summary or "",
           "flag_count": doc.flag_count or 0,
           "updated_at": _iso(getattr(doc, "updated_at", None)), "created_at": _iso(getattr(doc, "created_at", None))}
    if detail:
        can_read = SENS_RANK.get(doc.sensitivity or "internal", 1) <= human_max_sensitivity(principal, doc.company_id)
        out["can_read"] = can_read
        out["content"] = (doc.content or "") if can_read else ""
        vs = db.query(DocumentVersion).filter(DocumentVersion.document_id == doc.id).order_by(DocumentVersion.version_no.desc()).all()
        out["versions"] = [version_public(db, v, content=can_read and v.status in OPEN_VERSION) for v in vs]
        out["links"] = [{"id": lk.id, "target_type": lk.target_type, "target_id": lk.target_id, "note": lk.note}
                        for lk in db.query(DocumentLink).filter(DocumentLink.document_id == doc.id).order_by(DocumentLink.id)]
        from app.models.documents import DocumentFlag
        out["flags"] = [{"id": f.id, "reason": f.reason, "note": f.note, "version_no": f.version_no, "member": _member_name(db, f.member_id),
                         "task_id": f.task_id, "status": f.status, "created_at": _iso(f.created_at)}
                        for f in db.query(DocumentFlag).filter(DocumentFlag.document_id == doc.id).order_by(DocumentFlag.id.desc()).limit(50)]
        me = set(getattr(principal, "member_ids", []) or []) if principal is not None else set()
        out["i_can_approve"] = bool(open_v and open_v.status == "in_review" and (open_v.approver_member_id in me
                                    or getattr(principal, "role", "") == "owner") and open_v.author_member_id not in me)
    return out


# ------------------------------------------------------------------ danh sách + cây

def list_docs(db: Session, org_id: int, company_id: int | None, *, principal=None, group: str = "", doc_type: str = "",
              status: str = "", agent_use: str = "", q: str = "", review: str = "") -> dict:
    co = _company(db, org_id, company_id)
    base = db.query(KnowledgeDocument).filter(KnowledgeDocument.organization_id == org_id,
                                              or_(KnowledgeDocument.company_id == co.id, KnowledgeDocument.company_id.is_(None)))
    rows = base.order_by(KnowledgeDocument.id.desc()).limit(2000).all()
    tree: dict[str, dict] = {g: {"key": g, **GROUPS[g], "count": 0, "types": {}} for g in GROUPS}
    for d in rows:
        g = type_info(d.doc_type)["group"]
        tree[g]["count"] += 1
        tree[g]["types"][d.doc_type] = tree[g]["types"].get(d.doc_type, 0) + 1
    ql = (q or "").strip().lower()
    out = []
    for d in rows:
        ti = type_info(d.doc_type)
        if group and ti["group"] != group:
            continue
        if doc_type and d.doc_type != doc_type:
            continue
        if status and d.status != status:
            continue
        if agent_use and d.agent_use != agent_use:
            continue
        if review and review_state(d) not in review.split(","):
            continue
        if ql and ql not in (d.title or "").lower() and ql not in (d.doc_code or "").lower():
            continue
        out.append(public(db, d, principal=principal))
    counts = {"total": len(rows), "draft_or_review": sum(1 for d in rows if d.status in ("draft", "in_review", "approved")),
              "review_due": sum(1 for d in rows if review_state(d) in ("due", "stale")),
              "published": sum(1 for d in rows if d.status == "published")}
    return {"company_id": co.id, "items": out[:500], "tree": list(tree.values()), "counts": counts, "taxonomy": taxonomy()}


# ------------------------------------------------------------------ tạo / sửa

def _next_code(db: Session, company_id: int | None, group: str) -> str:
    prefix = GROUPS[group]["prefix"]
    codes = [c for (c,) in db.query(KnowledgeDocument.doc_code).filter(KnowledgeDocument.company_id == company_id,
                                                                       KnowledgeDocument.doc_code.like(prefix + "-%"))]
    n = 0
    for c in codes:
        m = re.match(rf"^{prefix}-(\d+)$", c or "")
        if m:
            n = max(n, int(m.group(1)))
    return f"{prefix}-{n + 1:03d}"


def _code_free(db: Session, company_id: int | None, code: str, exclude: int | None = None) -> None:
    q = db.query(KnowledgeDocument).filter(KnowledgeDocument.company_id == company_id, KnowledgeDocument.doc_code == code)
    if exclude:
        q = q.filter(KnowledgeDocument.id != exclude)
    if q.first() is not None:
        raise HTTPException(409, f"Mã tài liệu {code} đã có trong công ty này")


def _apply_meta(db: Session, doc: KnowledgeDocument, data: dict) -> None:
    if data.get("title"):
        doc.title = str(data["title"]).strip()[:220]
    for k in ("customer_facing", "lease_shareable", "exportable", "legal_hold"):
        if data.get(k) is not None:
            setattr(doc, k, bool(data[k]))
    if data.get("sensitivity") is not None:
        if data["sensitivity"] not in SENSITIVITY:
            raise HTTPException(422, f"sensitivity phải là một trong {', '.join(SENSITIVITY)}")
        doc.sensitivity = data["sensitivity"]
    if data.get("agent_use") is not None:
        if data["agent_use"] not in AGENT_USE:
            raise HTTPException(422, f"agent_use phải là một trong {', '.join(AGENT_USE)}")
        doc.agent_use = data["agent_use"]
        doc.is_core = doc.agent_use == "core"     # cờ cũ của kho tri thức đi theo
    if doc.sensitivity in ("personal_data", "sensitive_personal_data", "restricted") and doc.agent_use in ("core", "retrieve"):
        doc.agent_use, doc.is_core = "none", False   # A6: dữ liệu cá nhân không bao giờ vào RAG / AGENTS.md
    if data.get("owner_position_id") is not None:
        pid = data["owner_position_id"] or None
        if pid:
            from app.models.company_foundation import Position
            p = db.get(Position, pid)
            if p is None or p.company_id != doc.company_id:
                raise HTTPException(404, "Không thấy chức danh này trong công ty")
        doc.owner_position_id = pid
    if data.get("owner_member_id") is not None:
        mid = data["owner_member_id"] or None
        if mid:
            m = db.get(Member, mid)
            if m is None or m.organization_id != doc.organization_id:
                raise HTTPException(404, "Không thấy người phụ trách")
        doc.owner_member_id = mid
    if data.get("department_id") is not None:
        did = data["department_id"] or None
        if did:
            from app.models import Department
            d = db.get(Department, did)
            if d is None or d.company_id != doc.company_id:
                raise HTTPException(404, "Không thấy phòng ban trong công ty")
        doc.department_id = did
    if data.get("audience") is not None:
        a = data["audience"] or {}
        if not isinstance(a, dict):
            raise HTTPException(422, "audience phải là object {department_ids, position_ids, seat_ids}")
        clean = {k: [int(x) for x in (a.get(k) or [])] for k in ("department_ids", "position_ids", "seat_ids") if a.get(k)}
        doc.audience = clean or None
    if data.get("review_interval_days") is not None:
        n = int(data["review_interval_days"] or 0)
        if n < 0 or n > 3650:
            raise HTTPException(422, "Chu kỳ rà soát 0–3650 ngày")
        doc.review_interval_days = n or None
        if doc.status == "published":
            base = doc.last_reviewed_at or doc.effective_from or datetime.utcnow()
            doc.review_due_at = base + timedelta(days=n) if n else None
            doc.review_notified_at = None
    if "effective_to" in data:
        doc.effective_to = _dt(data.get("effective_to"))
    if data.get("retention_class") is not None:
        doc.retention_class = str(data["retention_class"])[:32]
    if data.get("doc_code"):
        code = str(data["doc_code"]).strip().upper()[:40]
        if not re.match(r"^[A-Z0-9][A-Z0-9._-]{1,39}$", code):
            raise HTTPException(422, "Mã tài liệu chỉ gồm chữ in, số, '-', '_' , '.'")
        _code_free(db, doc.company_id, code, doc.id)
        doc.doc_code = code


def create(db: Session, org_id: int, principal, data: dict, *, file: DocumentFile | None = None) -> dict:
    co = _company(db, org_id, data.get("company_id"), write=True)
    t = data.get("doc_type") or "other"
    if t not in DOC_TYPES:
        raise HTTPException(422, f"doc_type lạ: {t}")
    ti = DOC_TYPES[t]
    cls = data.get("doc_class") or ti["doc_class"]
    if cls not in DOC_CLASSES:
        raise HTTPException(422, "doc_class phải là document hoặc record")
    title = (data.get("title") or (file.filename.rsplit(".", 1)[0] if file else "")).strip()
    if not title:
        raise HTTPException(422, "Thiếu tiêu đề tài liệu")
    content = (data.get("content") or "").strip()
    if cls == "document" and len(content) < 20 and file is None:
        raise HTTPException(422, "Tài liệu trống hoặc quá ngắn (cần ít nhất 20 ký tự)")
    if cls == "document" and file is not None and len(content) < 20:
        raise HTTPException(422, "Không trích được chữ từ tệp (PDF scan?) — tài liệu cần có nội dung chữ. "
                                 "Hồ sơ (record) dạng scan thì chọn lớp 'Hồ sơ'.")
    supersedes = None
    if data.get("supersedes_id"):
        supersedes = get_doc(db, org_id, int(data["supersedes_id"]))
        if supersedes.company_id != co.id:
            raise HTTPException(404, "Không thấy tài liệu bị thay thế trong công ty này")
    seat = _seat(db, principal, co.id)
    now = datetime.utcnow()
    doc = KnowledgeDocument(organization_id=org_id, company_id=co.id, title=title[:220], source_type="upload" if file else "text",
                            content="", content_hash="", access_level="restricted", indexed=False, doc_type=t, doc_class=cls,
                            sensitivity=ti["sensitivity"], agent_use=ti["agent_use"], is_core=ti["agent_use"] == "core",
                            status="draft", version_no=0, review_interval_days=ti["review_days"],
                            retention_class=ti["retention"], owner_member_id=seat, synced_at=now,
                            file_id=file.id if file else None, supersedes_id=supersedes.id if supersedes else None)
    db.add(doc); db.flush()
    _apply_meta(db, doc, {k: v for k, v in data.items() if k not in ("title",)})
    if not doc.doc_code:
        doc.doc_code = _next_code(db, co.id, ti["group"])
    v = DocumentVersion(document_id=doc.id, version_no=1, status="draft", title=doc.title, content=content,
                        core_summary=(data.get("core_summary") or "").strip()[:1200],
                        content_hash=_hash(content), file_id=doc.file_id, change_note=(data.get("change_note") or "Bản đầu")[:2000],
                        author_member_id=seat, author_user_id=getattr(principal, "user_id", None),
                        effective_from=_dt(data.get("effective_from")))
    db.add(v); db.flush()
    from app.services.company_event_bus import emit_event
    emit_event(db, organization_id=org_id, company_id=co.id, event_type="document.created", source="doc_library",
               aggregate_type="document", aggregate_id=str(doc.id), actor_member_id=seat,
               payload={"doc_code": doc.doc_code, "doc_type": t, "doc_class": cls})
    if cls == "record":
        # Hồ sơ: lưu là khoá — ban hành ngay, không nháp/duyệt (ISO 7.5.3 "bảo vệ khỏi sửa đổi ngoài ý muốn").
        v.approved_by_member_id, v.approved_at = seat, now
        _publish(db, doc, v, now=now)
        if supersedes is not None and supersedes.status == "published":
            supersedes.status = "superseded"
            from app.services import doc_requirements
            doc_requirements.refresh_retention(db, supersedes)
            db.add(supersedes)
    db.commit(); db.refresh(doc)
    if doc.doc_type == "license":
        from app.services import doc_requirements
        doc_requirements.sync_license_deadline(db, doc)
        if supersedes is not None and supersedes.doc_type == "license":
            doc_requirements.sync_license_deadline(db, supersedes)   # giấy cũ bị thay → bỏ nhắc gia hạn giấy cũ
    return public(db, doc, principal=principal, detail=True)


def update_meta(db: Session, org_id: int, principal, doc_id: int, data: dict) -> tuple[dict, bool]:
    doc = get_doc(db, org_id, doc_id)
    if doc.status in ("disposed",):
        raise HTTPException(409, "Tài liệu đã huỷ — chỉ còn siêu dữ liệu")
    if "content" in data and data["content"] is not None:
        raise HTTPException(409, "Nội dung không sửa trực tiếp: tạo phiên bản mới (POST /docs/{id}/versions)"
                            if doc.doc_class == "document" else "Hồ sơ đã khoá — không sửa được; lưu hồ sơ mới thay thế")
    if doc.doc_class == "record":
        allowed = {"legal_hold", "retention_class", "owner_member_id", "owner_position_id", "sensitivity", "agent_use",
                   "review_interval_days", "effective_to", "audience"}
        bad = [k for k, v in data.items() if v is not None and k not in allowed]
        if bad:
            raise HTTPException(409, f"Hồ sơ đã khoá — không sửa được: {', '.join(bad)}")
    before = (doc.agent_use, doc.sensitivity, doc.status, repr(doc.audience), doc.title)
    if data.get("legal_hold") is False and doc.legal_hold:
        from app.core import company_scope   # gỡ giữ pháp lý: chỉ chủ
        role = company_scope.role_in(doc.company_id, principal) if company_scope.restricted(principal) else getattr(principal, "role", "")
        if role != "owner":
            raise HTTPException(403, "Gỡ 'giữ theo yêu cầu pháp lý' cần chủ doanh nghiệp")
    _apply_meta(db, doc, data)
    if "retention_class" in data or "effective_to" in data:
        from app.services import doc_requirements
        doc_requirements.refresh_retention(db, doc)
    from app.services.company_event_bus import emit_event
    emit_event(db, organization_id=org_id, company_id=doc.company_id, event_type="document.meta_changed", source="doc_library",
               aggregate_type="document", aggregate_id=str(doc.id), actor_member_id=_seat(db, principal, doc.company_id),
               payload={k: v for k, v in data.items() if k != "content"})
    db.add(doc); db.commit(); db.refresh(doc)
    after = (doc.agent_use, doc.sensitivity, doc.status, repr(doc.audience), doc.title)
    if doc.doc_type == "license" and "effective_to" in data:
        from app.services import doc_requirements
        doc_requirements.sync_license_deadline(db, doc)
    affects = doc.status == "published" and before != after and "core" in (before[0], after[0])
    return public(db, doc, principal=principal, detail=True), affects


# ------------------------------------------------------------------ phiên bản

def _version(db: Session, doc: KnowledgeDocument, vid: int) -> DocumentVersion:
    v = db.get(DocumentVersion, vid)
    if v is None or v.document_id != doc.id:
        raise HTTPException(404, "Không thấy phiên bản")
    return v


def new_version(db: Session, org_id: int, principal, doc_id: int, data: dict, *, file: DocumentFile | None = None) -> dict:
    doc = get_doc(db, org_id, doc_id, principal=principal, content=True)
    if doc.doc_class == "record":
        raise HTTPException(409, "Hồ sơ đã khoá — không có phiên bản mới; lưu hồ sơ mới với supersedes_id")
    if doc.status in ("archived", "disposed", "superseded"):
        raise HTTPException(409, f"Tài liệu đang {doc.status} — không thêm phiên bản")
    if db.query(DocumentVersion).filter(DocumentVersion.document_id == doc.id, DocumentVersion.status.in_(OPEN_VERSION)).first():
        raise HTTPException(409, "Đã có một phiên bản đang soạn/chờ duyệt — sửa bản đó hoặc chờ duyệt xong")
    content = (data.get("content") or "").strip()
    if len(content) < 20:
        raise HTTPException(422, "Phiên bản trống hoặc quá ngắn (cần ít nhất 20 ký tự)")
    last = db.query(DocumentVersion).filter(DocumentVersion.document_id == doc.id).order_by(DocumentVersion.version_no.desc()).first()
    seat = _seat(db, principal, doc.company_id)
    v = DocumentVersion(document_id=doc.id, version_no=(last.version_no if last else 0) + 1, status="draft",
                        title=(data.get("title") or doc.title)[:220], content=content, content_hash=_hash(content),
                        file_id=file.id if file else None, change_note=(data.get("change_note") or "")[:2000],
                        author_member_id=seat, author_user_id=getattr(principal, "user_id", None),
                        effective_from=_dt(data.get("effective_from")),
                        core_summary=(data.get("core_summary") if data.get("core_summary") is not None else doc.core_summary or "")[:1200])
    db.add(v); db.commit(); db.refresh(v)
    return version_public(db, v, content=True)


def edit_version(db: Session, org_id: int, principal, doc_id: int, vid: int, data: dict) -> dict:
    doc = get_doc(db, org_id, doc_id, principal=principal, content=True)
    v = _version(db, doc, vid)
    if v.status != "draft":
        raise HTTPException(409, f"Phiên bản v{v.version_no} đang '{v.status}' — bất biến; tạo phiên bản mới để sửa")
    if data.get("content") is not None:
        c = data["content"].strip()
        if len(c) < 20:
            raise HTTPException(422, "Phiên bản trống hoặc quá ngắn (cần ít nhất 20 ký tự)")
        v.content, v.content_hash = c, _hash(c)
    if data.get("title"):
        v.title = data["title"].strip()[:220]
    if data.get("change_note") is not None:
        v.change_note = data["change_note"][:2000]
    if data.get("core_summary") is not None:
        v.core_summary = data["core_summary"].strip()[:1200]
    if "effective_from" in data:
        v.effective_from = _dt(data.get("effective_from"))
    db.add(v); db.commit(); db.refresh(v)
    return version_public(db, v, content=True)


def risk_of(doc: KnowledgeDocument) -> str:
    r = type_info(doc.doc_type)["risk"]
    if doc.customer_facing and r != "high":
        r = "high"
    return r


def _ensure_rules(db: Session, doc: KnowledgeDocument) -> None:
    from app.services import authority
    authority.ensure_action_defaults(db, doc.organization_id, doc.company_id, "doc_publish")


def submit(db: Session, org_id: int, principal, doc_id: int, vid: int, *, requester: Member | None = None) -> dict:
    """Gửi duyệt: phiên bản thành bất biến; người duyệt theo ma trận (doc_publish). Người gửi đã là người có quyền
    duyệt (vd. chủ) → duyệt ngay, ghi rõ lý do."""
    doc = get_doc(db, org_id, doc_id)
    v = _version(db, doc, vid)
    if v.status != "draft":
        raise HTTPException(409, f"Phiên bản v{v.version_no} đang '{v.status}'")
    _ensure_rules(db, doc)
    from app.services import authority
    seat = requester.id if requester is not None else _seat(db, principal, doc.company_id)
    req_m = requester or (db.get(Member, seat) if seat else None)
    d = authority.decide(db, req_m, "doc_publish", risk=risk_of(doc), company_id=doc.company_id)
    approver = d.approver_member_id if d is not None else authority.owner_member(db, org_id, doc.company_id)
    v.status, v.approver_member_id = "in_review", approver
    if doc.status == "draft":
        doc.status = "in_review"
    from app.services import company_facts
    v.conflicts = company_facts.conflicts_for(db, doc, v.content) or None   # M3b: số liệu lệch với nguồn khác
    db.add(v); db.add(doc); db.flush()
    if v.conflicts:
        from app.services import inbox
        others = [db.get(KnowledgeDocument, c["other_doc_id"]) for c in v.conflicts if c.get("other_doc_id")]
        recips = [_review_owner(db, doc)] + [_review_owner(db, o) for o in others if o is not None]
        inbox.notify(db, organization_id=org_id, recipients=recips, kind="doc_conflict", company_id=doc.company_id,
                     title=f"{doc.doc_code} v{v.version_no} mâu thuẫn {len(v.conflicts)} số liệu với nguồn khác",
                     related_type="document", related_id=str(doc.id), commit=False,
                     line="; ".join(f"{c['label']}: {c['value']} ≠ {c['other_value']} ({c['other_source']})" for c in v.conflicts)[:380])
    self_ok = (req_m is not None and req_m.member_type == "human" and approver == req_m.id) or (d is not None and d.approver_kind == "none"
                                                                                               and (req_m is None or req_m.member_type == "human"))
    if self_ok and not v.conflicts:
        db.commit()
        return _decide_version(db, doc, v, "approved", seat, note=(d.reason if d else "Người gửi là người có quyền duyệt"))
    a = Approval(organization_id=org_id, company_id=doc.company_id, requester_member_id=seat, approver_member_id=approver,
                 action=f"Ban hành tài liệu {doc.doc_code} v{v.version_no}: {v.title}"[:220], risk=risk_of(doc),
                 policy_key=f"doc_publish:{doc.id}:{v.id}", status="pending",
                 evidence=((v.change_note or "") + ("\nMÂU THUẪN: " + "; ".join(f"{c['label']}: {c['value']} ≠ {c['other_value']} ({c['other_source']})"
                                                                         for c in v.conflicts) if v.conflicts else ""))[:2000],
                 payload=authority.annotate({"document_id": doc.id, "version_id": v.id, "doc_code": doc.doc_code}, d))
    db.add(a); db.flush()
    v.approval_id = a.id
    db.add(v); db.commit()
    return {**public(db, doc, principal=principal, detail=True), "approval_id": a.id,
            "authority": d.card() if d is not None else None, "conflicts": v.conflicts or []}


def _decide_version(db: Session, doc: KnowledgeDocument, v: DocumentVersion, decision: str, actor: int | None,
                    *, note: str = "", now: datetime | None = None) -> dict:
    now = now or datetime.utcnow()
    v.review_note = (note or "")[:2000]
    if decision == "approved":
        v.status, v.approved_by_member_id, v.approved_at = "approved", actor, now
        if v.effective_from and v.effective_from > now:
            if doc.status in ("draft", "in_review"):
                doc.status = "approved"
            db.add(v); db.add(doc); db.commit()
            return {**public(db, doc, detail=True), "published": False}
        res = _publish(db, doc, v, now=now)
        db.commit()
        return {**public(db, doc, detail=True), "published": True, **res}
    v.status = "rejected"
    if doc.status == "in_review" and not doc.current_version_id:
        doc.status = "draft"
    db.add(v); db.add(doc); db.commit()
    return {**public(db, doc, detail=True), "published": False}


def decide(db: Session, org_id: int, principal, doc_id: int, vid: int, decision: str, note: str = "",
           override_conflicts: bool = False) -> dict:
    if decision not in ("approved", "rejected"):
        raise HTTPException(422, "decision phải là approved hoặc rejected")
    doc = get_doc(db, org_id, doc_id)
    v = _version(db, doc, vid)
    if v.status != "in_review":
        raise HTTPException(409, f"Phiên bản v{v.version_no} đang '{v.status}' — không chờ duyệt")
    me = set(getattr(principal, "member_ids", []) or [])
    if v.author_member_id and v.author_member_id in me and v.approver_member_id != v.author_member_id:
        raise HTTPException(403, "Tác giả không tự duyệt phiên bản của mình")
    if v.approver_member_id not in me and getattr(principal, "role", "") != "owner":
        raise HTTPException(403, {"error": "not_the_approver", "approver_member_id": v.approver_member_id,
                                  "message": f"Người duyệt theo ma trận là {_member_name(db, v.approver_member_id)}"})
    if decision == "approved" and v.conflicts and not override_conflicts:
        raise HTTPException(409, {"error": "conflicts", "conflicts": v.conflicts,
                                  "message": "Phiên bản này mâu thuẫn số liệu với nguồn khác — sửa, hoặc duyệt với override_conflicts=true"})
    actor = v.approver_member_id if v.approver_member_id in me else _seat(db, principal, doc.company_id)
    if v.approval_id:
        a = db.get(Approval, v.approval_id)
        if a is not None and a.status == "pending":
            a.status, a.resolution_note = decision, note[:2000]
            db.add(a)
    return _decide_version(db, doc, v, decision, actor, note=note)


def on_approval_resolved(db: Session, a: Approval, principal, *, actor_member_id: int | None = None) -> None:
    """Approval duyệt từ /api/approvals/{id}/resolve hoặc Hộp việc (inbox_hub.after_decision, truyền actor_member_id)."""
    try:
        _, did, vid = (a.policy_key or "").split(":")
        doc, v = db.get(KnowledgeDocument, int(did)), db.get(DocumentVersion, int(vid))
    except ValueError:
        return
    if doc is None or v is None or v.status != "in_review":
        return
    if principal is None:
        actor = actor_member_id
    else:
        me = set(getattr(principal, "member_ids", []) or [])
        actor = v.approver_member_id if v.approver_member_id in me else _seat(db, principal, doc.company_id)
    _decide_version(db, doc, v, "approved" if a.status == "approved" else "rejected", actor, note=a.resolution_note or "")


def _publish(db: Session, doc: KnowledgeDocument, v: DocumentVersion, *, now: datetime) -> dict:
    """Bản v thành bản đang hiệu lực: bản cũ → superseded, nội dung sổ = v, chỉ mục lại, khoá học dùng tài liệu → cần ôn."""
    prev = (db.query(DocumentVersion).filter(DocumentVersion.document_id == doc.id, DocumentVersion.status == "published",
                                             DocumentVersion.id != v.id).all())
    for p in prev:
        p.status = "superseded"; db.add(p)
    v.status, v.published_at = "published", now
    changed = (doc.content_hash or "") != v.content_hash
    doc.content, doc.content_hash, doc.title = v.content, v.content_hash, v.title or doc.title
    doc.version_no, doc.current_version_id, doc.status = v.version_no, v.id, "published"
    doc.effective_from = v.effective_from or now
    if v.file_id:
        doc.file_id = v.file_id
    doc.core_summary = v.core_summary or ""
    doc.last_reviewed_at, doc.review_notified_at = now, None
    from app.services import doc_requirements
    doc.retain_until = doc_requirements.compute_retain_until(doc, now=now)
    doc.review_due_at = now + timedelta(days=doc.review_interval_days) if doc.review_interval_days else None
    doc.synced_at = now
    db.add(v); db.add(doc); db.flush()
    from app.services import knowledge_hub
    chunks = knowledge_hub.reindex(db, doc) if (doc.content or "").strip() else 0
    stale = knowledge_hub.mark_courses_stale(db, doc) if prev and changed else 0
    from app.services import company_facts
    facts = company_facts.upsert_from_doc(db, doc)
    from app.services.company_event_bus import emit_event
    emit_event(db, organization_id=doc.organization_id, company_id=doc.company_id, event_type="document.published",
               source="doc_library", aggregate_type="document", aggregate_id=str(doc.id), actor_member_id=v.approved_by_member_id,
               payload={"doc_code": doc.doc_code, "version_no": v.version_no, "superseded": [p.version_no for p in prev]})
    return {"chunks": chunks, "stale_enrollments": stale, "superseded_versions": [p.version_no for p in prev], "facts": facts,
            "core_changed": doc.agent_use == "core"}


def mark_reviewed(db: Session, org_id: int, principal, doc_id: int, note: str = "") -> dict:
    doc = get_doc(db, org_id, doc_id)
    if doc.status != "published":
        raise HTTPException(409, "Chỉ rà soát tài liệu đang hiệu lực")
    now = datetime.utcnow()
    doc.last_reviewed_at, doc.last_reviewed_by, doc.review_notified_at = now, _seat(db, principal, doc.company_id), None
    doc.review_due_at = now + timedelta(days=doc.review_interval_days) if doc.review_interval_days else None
    db.add(doc); db.commit()
    return public(db, doc, principal=principal, detail=True)


def archive(db: Session, org_id: int, principal, doc_id: int, reason: str = "") -> dict:
    doc = get_doc(db, org_id, doc_id)
    if doc.status in ("archived", "disposed"):
        raise HTTPException(409, f"Tài liệu đã {doc.status}")
    was_core = doc.status == "published" and doc.agent_use == "core"
    doc.status = "archived"
    from app.services import company_facts, doc_requirements
    company_facts.retire_doc(db, doc)
    doc_requirements.refresh_retention(db, doc)
    for v in db.query(DocumentVersion).filter(DocumentVersion.document_id == doc.id, DocumentVersion.status.in_(OPEN_VERSION)):
        v.status = "rejected"; v.review_note = "Tài liệu đã lưu trữ"; db.add(v)
    from app.services.company_event_bus import emit_event
    emit_event(db, organization_id=org_id, company_id=doc.company_id, event_type="document.archived", source="doc_library",
               aggregate_type="document", aggregate_id=str(doc.id), actor_member_id=_seat(db, principal, doc.company_id),
               payload={"reason": reason[:300]})
    db.add(doc); db.commit()
    if doc.doc_type == "license":      # M3d: giấy phép lưu trữ → tắt nghĩa vụ gia hạn, bỏ hạn đã sinh
        doc_requirements.sync_license_deadline(db, doc)
    return {**public(db, doc, principal=principal, detail=True), "core_changed": was_core}


def diff(db: Session, org_id: int, principal, doc_id: int, a: int | None, b: int | None) -> dict:
    doc = get_doc(db, org_id, doc_id, principal=principal, content=True)
    vs = db.query(DocumentVersion).filter(DocumentVersion.document_id == doc.id).order_by(DocumentVersion.version_no).all()
    if not vs:
        raise HTTPException(404, "Chưa có phiên bản")
    by = {v.version_no: v for v in vs}
    vb = by.get(b) if b else vs[-1]
    va = by.get(a) if a else (by.get(vb.version_no - 1) if vb else None)
    if vb is None:
        raise HTTPException(404, "Không thấy phiên bản")
    old = (va.content if va else "").splitlines()
    lines = list(difflib.unified_diff(old, (vb.content or "").splitlines(), fromfile=f"v{va.version_no if va else 0}",
                                      tofile=f"v{vb.version_no}", lineterm="", n=2))
    added = sum(1 for ln in lines if ln.startswith("+") and not ln.startswith("+++"))
    removed = sum(1 for ln in lines if ln.startswith("-") and not ln.startswith("---"))
    return {"from": va.version_no if va else 0, "to": vb.version_no, "lines": lines[:2000], "added": added, "removed": removed}


# ------------------------------------------------------------------ tệp gốc

def store_file(db: Session, org_id: int, company_id: int | None, filename: str, mime: str, data: bytes) -> DocumentFile:
    if len(data) > MAX_FILE:
        raise HTTPException(422, "Tệp tối đa 20 MB")
    sha = hashlib.sha256(data).hexdigest()
    old = db.query(DocumentFile).filter(DocumentFile.organization_id == org_id, DocumentFile.company_id == company_id,
                                        DocumentFile.sha256 == sha).first()
    if old is not None:
        return old
    f = DocumentFile(organization_id=org_id, company_id=company_id, filename=(filename or "tep")[:300],
                     mime=(mime or "application/octet-stream")[:120], size=len(data), sha256=sha, data=data)
    db.add(f); db.flush()
    return f


def extract(filename: str, data: bytes) -> str:
    from app.services import knowledge_hub
    name = (filename or "").lower()
    if name.endswith((".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff")):
        return ""            # ảnh scan: OCR là M3c — hồ sơ vẫn lưu được (chỉ tệp + siêu dữ liệu)
    return knowledge_hub.extract_text(filename, data)


def file_of(db: Session, org_id: int, principal, file_id: int) -> DocumentFile:
    f = db.get(DocumentFile, file_id)
    if f is None or f.organization_id != org_id:
        raise HTTPException(404, "Không thấy tệp")
    doc = (db.query(KnowledgeDocument).filter(KnowledgeDocument.file_id == f.id).first()
           or db.query(KnowledgeDocument).join(DocumentVersion, DocumentVersion.document_id == KnowledgeDocument.id)
           .filter(DocumentVersion.file_id == f.id).first())
    if doc is not None:
        get_doc(db, org_id, doc.id, principal=principal, content=True)
    else:
        from app.core import company_scope
        company_scope.check(f.company_id)
    return f


# ------------------------------------------------------------------ liên kết

def add_link(db: Session, org_id: int, doc_id: int, target_type: str, target_id: int, note: str = "") -> dict:
    doc = get_doc(db, org_id, doc_id)
    if target_type not in LINK_TYPES:
        raise HTTPException(422, f"target_type phải là một trong {', '.join(LINK_TYPES)}")
    from app.models.company_foundation import Position
    from app.models.company_ops import Process, ProcessStep
    from app.models.extended import SOP
    from app.models.catalog import CatalogProduct
    from app.models.documents import DocumentRequirement
    model = {"position": Position, "process": Process, "process_step": ProcessStep, "sop": SOP,
             "requirement": DocumentRequirement, "product": CatalogProduct}.get(target_type)
    if model is not None:
        row = db.get(model, int(target_id))
        cid = getattr(row, "company_id", None)
        if row is not None and target_type == "process_step":
            pr = db.get(Process, row.process_id)
            cid = pr.company_id if pr else None
        if row is None or (cid and cid != doc.company_id):
            raise HTTPException(404, f"Không thấy {target_type} #{target_id} trong công ty")
        if target_type == "sop":
            row.document_id = doc.id; db.add(row)
    lk = DocumentLink(document_id=doc.id, target_type=target_type, target_id=int(target_id), note=note[:300])
    db.add(lk); db.commit()
    return {"id": lk.id, "target_type": target_type, "target_id": lk.target_id}


def remove_link(db: Session, org_id: int, doc_id: int, link_id: int) -> dict:
    doc = get_doc(db, org_id, doc_id)
    lk = db.get(DocumentLink, link_id)
    if lk is None or lk.document_id != doc.id:
        raise HTTPException(404, "Không thấy liên kết")
    db.delete(lk); db.commit()
    return {"deleted": link_id}


def import_sops(db: Session, org_id: int, principal, company_id: int | None) -> dict:
    """SOP của công ty → tài liệu doc_type=sop (phiên bản 1 đã ban hành, chép nội dung), sops.document_id trỏ về."""
    from app.models.extended import SOP
    co = _company(db, org_id, company_id, write=True)
    made = []
    for s in db.query(SOP).filter(SOP.organization_id == org_id, SOP.company_id == co.id).order_by(SOP.id):
        if s.document_id and db.get(KnowledgeDocument, s.document_id) is not None:
            continue
        if len((s.content or "").strip()) < 20:
            continue
        now = datetime.utcnow()
        doc = KnowledgeDocument(organization_id=org_id, company_id=co.id, department_id=s.department_id, title=s.title[:220],
                                source_type="text", content="", content_hash="", access_level="restricted", doc_type="sop",
                                doc_class="document", sensitivity="internal", agent_use="retrieve", status="draft",
                                version_no=0, review_interval_days=DOC_TYPES["sop"]["review_days"],
                                retention_class=DOC_TYPES["sop"]["retention"], owner_member_id=s.owner_member_id, synced_at=now)
        db.add(doc); db.flush()
        doc.doc_code = _next_code(db, co.id, "process")
        v = DocumentVersion(document_id=doc.id, version_no=1, status="draft", title=doc.title, content=s.content.strip(),
                            content_hash=_hash(s.content), change_note=f"Nhập từ SOP #{s.id} ({s.version})",
                            author_member_id=s.owner_member_id, approved_by_member_id=_seat(db, principal, co.id), approved_at=now)
        db.add(v); db.flush()
        _publish(db, doc, v, now=now)
        s.document_id = doc.id
        db.add(DocumentLink(document_id=doc.id, target_type="sop", target_id=s.id, note="SOP gốc"))
        db.add(s); db.flush()
        made.append({"sop_id": s.id, "document_id": doc.id, "doc_code": doc.doc_code})
    db.commit()
    return {"imported": made}


# ------------------------------------------------------------------ kho cũ (/learning/docs) → sổ tài liệu

def init_legacy(db: Session, doc: KnowledgeDocument) -> None:
    """Tài liệu nạp qua đường cũ (Kho tri thức): ban hành ngay như trước M3a, nhưng có phiên bản 1 + mã."""
    if doc.current_version_id:
        return
    t = doc.doc_type or "other"
    if not doc.doc_code:
        doc.doc_code = _next_code(db, doc.company_id, type_info(t)["group"]) if doc.company_id else f"DOC-{doc.id}"
    doc.agent_use = "core" if doc.is_core else (doc.agent_use if doc.agent_use in AGENT_USE and doc.agent_use != "core" else "retrieve")
    v = DocumentVersion(document_id=doc.id, version_no=1, status="published", title=doc.title, content=doc.content or "",
                        content_hash=doc.content_hash or _hash(doc.content), change_note="Nạp qua Kho tri thức",
                        published_at=datetime.utcnow())
    db.add(v); db.flush()
    doc.current_version_id, doc.version_no, doc.status = v.id, 1, "published"
    doc.effective_from = doc.effective_from or datetime.utcnow()
    db.add(doc); db.commit()
    from app.services import company_facts
    company_facts.upsert_from_doc(db, doc)


def legacy_new_content(db: Session, doc: KnowledgeDocument) -> None:
    """URL đồng bộ lại ra nội dung mới (nguồn bên ngoài) → một phiên bản mới đã ban hành, bản cũ superseded."""
    last = db.query(DocumentVersion).filter(DocumentVersion.document_id == doc.id).order_by(DocumentVersion.version_no.desc()).first()
    for p in db.query(DocumentVersion).filter(DocumentVersion.document_id == doc.id, DocumentVersion.status == "published"):
        p.status = "superseded"; db.add(p)
    v = DocumentVersion(document_id=doc.id, version_no=(last.version_no if last else 0) + 1, status="published", title=doc.title,
                        content=doc.content or "", content_hash=doc.content_hash, change_note=f"Đồng bộ lại từ {doc.source_url}"[:2000],
                        published_at=datetime.utcnow())
    db.add(v); db.flush()
    doc.current_version_id, doc.version_no = v.id, v.version_no
    db.add(doc); db.commit()
    from app.services import company_facts
    company_facts.upsert_from_doc(db, doc)


# ------------------------------------------------------------------ đánh dấu (agent "flag it")

FLAG_REASONS = {"wrong": "sai", "outdated": "đã cũ", "conflict": "mâu thuẫn", "missing_case": "thiếu trường hợp"}


def flag(db: Session, *, member: Member, doc: KnowledgeDocument, reason: str, note: str = "", task_id: int | None = None) -> dict:
    from app.models.documents import DocumentFlag
    if reason not in FLAG_REASONS:
        raise HTTPException(422, f"reason phải là một trong {', '.join(FLAG_REASONS)}")
    f = DocumentFlag(document_id=doc.id, version_no=doc.version_no, reason=reason, note=(note or "")[:2000],
                     member_id=member.id, task_id=task_id, status="open")
    doc.flag_count = (doc.flag_count or 0) + 1
    db.add(f); db.add(doc); db.flush()
    from app.services import inbox
    inbox.notify(db, organization_id=doc.organization_id, recipients=[_review_owner(db, doc)], kind="doc_flagged",
                 title=f"{member.name} đánh dấu {doc.doc_code or doc.title} là {FLAG_REASONS[reason]}", task_id=None,
                 related_type="document", related_id=str(doc.id), company_id=doc.company_id, commit=False,
                 line=f"{doc.doc_code} v{doc.version_no}: {FLAG_REASONS[reason]} — {note[:200]}")
    db.commit()
    open_n = db.query(DocumentFlag).filter(DocumentFlag.document_id == doc.id, DocumentFlag.status == "open").count()
    return {"flag_id": f.id, "doc_code": doc.doc_code, "open_flags": open_n,
            "message": "Đã báo người phụ trách tài liệu (Hộp việc). Trong lúc chờ, nói rõ với người hỏi là đang xác minh."}


def resolve_flag(db: Session, org_id: int, doc_id: int, flag_id: int, status: str) -> dict:
    from app.models.documents import DocumentFlag
    doc = get_doc(db, org_id, doc_id)
    f = db.get(DocumentFlag, flag_id)
    if f is None or f.document_id != doc.id:
        raise HTTPException(404, "Không thấy đánh dấu")
    if status not in ("resolved", "dismissed"):
        raise HTTPException(422, "status: resolved | dismissed")
    f.status = status; db.add(f); db.commit()
    return {"id": f.id, "status": f.status}


def by_code(db: Session, member: Member, code: str) -> KnowledgeDocument | None:
    """Tài liệu theo mã trong công ty của ghế (kể cả bản đã cấp qua hợp đồng thuê) — bản đang hiệu lực."""
    from app.services import knowledge_hub
    q = knowledge_hub.visible_docs_query(db, member.organization_id, member, None)
    return q.filter(KnowledgeDocument.doc_code == (code or "").strip().upper()).first()


# ------------------------------------------------------------------ nhịp (beat docs.tick)

def _review_owner(db: Session, doc: KnowledgeDocument) -> int | None:
    if doc.owner_member_id:
        return doc.owner_member_id
    if doc.owner_position_id:
        m = (db.query(Member).filter(Member.position_id == doc.owner_position_id, Member.status != "archived")
             .order_by(Member.member_type.desc(), Member.id).first())
        if m is not None:
            return m.id
    from app.services import authority
    return authority.owner_member(db, doc.organization_id, doc.company_id)


def tick(db: Session, now: datetime | None = None, org_id: int | None = None) -> dict:
    now = now or datetime.utcnow()

    def _org(q):
        return q.filter(KnowledgeDocument.organization_id == org_id) if org_id else q
    out = {"published": 0, "archived": 0, "review_due": 0, "core_orgs": []}
    expired_licenses: list[KnowledgeDocument] = []
    core_orgs: set[int] = set()
    for v in db.query(DocumentVersion).filter(DocumentVersion.status == "approved", DocumentVersion.effective_from <= now).all():
        doc = db.get(KnowledgeDocument, v.document_id)
        if doc is None or doc.status in ("archived", "disposed") or (org_id and doc.organization_id != org_id):
            continue
        r = _publish(db, doc, v, now=now)
        db.commit(); out["published"] += 1
        if r["core_changed"]:
            core_orgs.add(doc.organization_id)
    for doc in _org(db.query(KnowledgeDocument).filter(KnowledgeDocument.status == "published", KnowledgeDocument.effective_to.isnot(None),
                                                       KnowledgeDocument.effective_to <= now)).all():
        doc.status = "archived"; db.add(doc); out["archived"] += 1
        from app.services import company_facts, doc_requirements
        company_facts.retire_doc(db, doc)
        doc_requirements.refresh_retention(db, doc)          # M3d: lưu trữ → hạn lưu tính lại (vd. superseded_10y)
        if doc.doc_type == "license":
            expired_licenses.append(doc)
        if doc.agent_use == "core":
            core_orgs.add(doc.organization_id)
        from app.services import inbox
        inbox.notify(db, organization_id=doc.organization_id, recipients=[_review_owner(db, doc)], kind="doc_expired",
                     title=f"Tài liệu {doc.doc_code} hết hiệu lực — đã lưu trữ: {doc.title}", related_type="document",
                     related_id=str(doc.id), company_id=doc.company_id, commit=False)
    db.commit()
    for doc in expired_licenses:                             # M3d: giấy phép hết hạn → tắt nghĩa vụ gia hạn đã quá
        from app.services import doc_requirements
        doc_requirements.sync_license_deadline(db, doc)
    due = _org(db.query(KnowledgeDocument).filter(KnowledgeDocument.status == "published", KnowledgeDocument.review_due_at.isnot(None),
                                                  KnowledgeDocument.review_due_at <= now)).all()
    from app.services import inbox
    for doc in due:
        if doc.review_notified_at is not None and doc.review_notified_at >= doc.review_due_at:
            continue     # đã nhắc cho hạn này — đúng một thẻ mỗi hạn
        inbox.notify(db, organization_id=doc.organization_id, recipients=[_review_owner(db, doc)], kind="doc_review_due",
                     title=f"Đến hạn rà soát {doc.doc_code} v{doc.version_no}: {doc.title}", related_type="document",
                     related_id=str(doc.id), company_id=doc.company_id, commit=False,
                     line=f"{doc.doc_code} quá hạn rà soát từ {doc.review_due_at:%d/%m/%Y} — xác nhận còn đúng hoặc soạn phiên bản mới")
        doc.review_notified_at = now
        db.add(doc); out["review_due"] += 1
    db.commit()
    from app.services import doc_requirements
    out["disposal_due"] = doc_requirements.disposal_tick(db, now=now, org_id=org_id)
    out["core_orgs"] = sorted(core_orgs)
    return out


async def regen_agents(db: Session, runtime, org_id: int) -> dict:
    """Sinh lại AGENTS.md (phần cốt lõi) cho mọi seat agent đang sống của tổ chức — không cần người gọi."""
    from app.models import Agent
    from app.services import agent_hr
    seats = (db.query(Agent, Member).join(Member, Member.id == Agent.member_id)
             .filter(Member.organization_id == org_id, Agent.lifecycle.notin_(("retired", "runtime_missing"))).all())
    n = 0
    for ag, m in seats:
        try:
            r = await agent_hr._regen(db, runtime, ag, m, ("AGENTS.md",), None)
            n += bool((r.get("AGENTS.md") or {}).get("written"))
        except Exception as exc:  # noqa: BLE001
            print(f"[docs] regen {ag.id}: {exc}")
    return {"seats": len(seats), "written": n}
