"""M3 — thư viện tài liệu & tri thức công ty (M3a), hồ sơ bắt buộc (M3d), sự kiện công ty (M3b), sản phẩm & giá (M3f).
Spec: docs/company-knowledge-library-and-gaps.md. Mọi route thuộc phạm vi công ty (R1: require_company_role +
company_scope.check ở service)."""
from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.authz import Principal, require_company_role
from app.core.tenancy import active_org
from app.db.session import get_db
from app.services import doc_library as lib

router = APIRouter(prefix="/team", tags=["documents"])


def resync_core_later(background: BackgroundTasks, principal: Principal, org_id: int) -> None:
    from app.api.team import _resync
    _resync(background, principal, org_id, None)


class DocIn(BaseModel):
    company_id: int | None = None
    title: str | None = None
    doc_type: str | None = None
    doc_class: str | None = None
    doc_code: str | None = None
    content: str | None = None
    change_note: str | None = None
    owner_position_id: int | None = None
    owner_member_id: int | None = None
    department_id: int | None = None
    audience: dict | None = None
    sensitivity: str | None = None
    agent_use: str | None = None
    customer_facing: bool | None = None
    lease_shareable: bool | None = None
    exportable: bool | None = None
    effective_from: str | None = None
    effective_to: str | None = None
    review_interval_days: int | None = None
    retention_class: str | None = None
    legal_hold: bool | None = None
    supersedes_id: int | None = None
    core_summary: str | None = None


class VersionIn(BaseModel):
    title: str | None = None
    content: str | None = None
    change_note: str | None = None
    effective_from: str | None = None
    core_summary: str | None = None


class DecideIn(BaseModel):
    decision: str
    note: str = ""
    override_conflicts: bool = False


class FactIn(BaseModel):
    company_id: int | None = None
    key: str
    value: str
    value_num: float | None = None
    unit: str | None = None


class FlagStatusIn(BaseModel):
    status: str


class LinkIn(BaseModel):
    target_type: str
    target_id: int
    note: str = ""


class NoteIn(BaseModel):
    note: str = ""
    reason: str = ""


@router.get("/docs/taxonomy")
def taxonomy(principal: Principal = Depends(require_company_role("member"))):
    return lib.taxonomy()


@router.get("/docs")
def list_docs(company_id: int | None = None, group: str = "", doc_type: str = "", status: str = "", agent_use: str = "",
              q: str = "", review: str = "", principal: Principal = Depends(require_company_role("member")),
              db: Session = Depends(get_db)):
    return lib.list_docs(db, active_org(principal), company_id, principal=principal, group=group, doc_type=doc_type,
                         status=status, agent_use=agent_use, q=q, review=review)


@router.post("/docs")
def create_doc(payload: DocIn, principal: Principal = Depends(require_company_role("manager")), db: Session = Depends(get_db)):
    return lib.create(db, active_org(principal), principal, payload.model_dump(exclude_none=True))


@router.post("/docs/upload")
async def upload_doc(file: UploadFile = File(...), company_id: int = Form(...), title: str = Form(default=""),
                     doc_type: str = Form(default="other"), doc_class: str = Form(default=""),
                     sensitivity: str = Form(default=""), agent_use: str = Form(default=""),
                     owner_position_id: int | None = Form(default=None), effective_from: str = Form(default=""),
                     change_note: str = Form(default=""), document_id: int | None = Form(default=None),
                     principal: Principal = Depends(require_company_role("manager")), db: Session = Depends(get_db)):
    """Tải tệp gốc (PDF/DOCX/MD/TXT/HTML/CSV; ảnh scan chỉ cho hồ sơ). Lưu tệp + sha256, trích chữ làm nội dung.
    ``document_id`` → tệp thành phiên bản nháp mới của tài liệu đó."""
    org = active_org(principal)
    data = await file.read()
    co = lib._company(db, org, company_id, write=True)
    text = lib.extract(file.filename or "", data)
    f = lib.store_file(db, org, co.id, file.filename or "", file.content_type or "", data)
    f.extracted_chars = len(text or "")
    db.add(f); db.commit()
    if document_id:
        return lib.new_version(db, org, principal, document_id, {"content": text, "change_note": change_note or f"Tệp {f.filename}",
                                                                "effective_from": effective_from or None, "title": title or None},
                               file=f)
    body = {"company_id": co.id, "title": title, "doc_type": doc_type, "content": text, "change_note": change_note or f"Tệp {f.filename}",
            "effective_from": effective_from or None, "owner_position_id": owner_position_id}
    for k, v in (("doc_class", doc_class), ("sensitivity", sensitivity), ("agent_use", agent_use)):
        if v:
            body[k] = v
    return lib.create(db, org, principal, {k: v for k, v in body.items() if v is not None}, file=f)


@router.post("/docs/import-sops")
def import_sops(company_id: int, principal: Principal = Depends(require_company_role("manager")), db: Session = Depends(get_db)):
    return lib.import_sops(db, active_org(principal), principal, company_id)


@router.get("/docs/files/{file_id}")
def download_file(file_id: int, principal: Principal = Depends(require_company_role("member")), db: Session = Depends(get_db)):
    f = lib.file_of(db, active_org(principal), principal, file_id)
    return Response(content=f.data, media_type=f.mime or "application/octet-stream",
                    headers={"Content-Disposition": f'attachment; filename="{f.filename.encode("ascii", "ignore").decode() or "file"}"',
                             "X-Content-SHA256": f.sha256})


@router.get("/docs/{doc_id}")
def get_doc(doc_id: int, principal: Principal = Depends(require_company_role("member")), db: Session = Depends(get_db)):
    doc = lib.get_doc(db, active_org(principal), doc_id)
    return lib.public(db, doc, principal=principal, detail=True)


@router.patch("/docs/{doc_id}")
def patch_doc(doc_id: int, payload: DocIn, background: BackgroundTasks,
              principal: Principal = Depends(require_company_role("manager")), db: Session = Depends(get_db)):
    body = payload.model_dump(exclude_unset=True)
    out, affects = lib.update_meta(db, active_org(principal), principal, doc_id, body)
    if affects:
        resync_core_later(background, principal, active_org(principal))
    return out


@router.post("/docs/{doc_id}/versions")
def new_version(doc_id: int, payload: VersionIn, principal: Principal = Depends(require_company_role("manager")),
                db: Session = Depends(get_db)):
    return lib.new_version(db, active_org(principal), principal, doc_id, payload.model_dump(exclude_none=True))


@router.patch("/docs/{doc_id}/versions/{vid}")
def edit_version(doc_id: int, vid: int, payload: VersionIn, principal: Principal = Depends(require_company_role("manager")),
                 db: Session = Depends(get_db)):
    return lib.edit_version(db, active_org(principal), principal, doc_id, vid, payload.model_dump(exclude_unset=True))


@router.post("/docs/{doc_id}/versions/{vid}/submit")
def submit(doc_id: int, vid: int, background: BackgroundTasks, principal: Principal = Depends(require_company_role("manager")),
           db: Session = Depends(get_db)):
    out = lib.submit(db, active_org(principal), principal, doc_id, vid)
    if out.get("published") and out.get("core_changed"):
        resync_core_later(background, principal, active_org(principal))
    return out


@router.post("/docs/{doc_id}/versions/{vid}/decide")
def decide(doc_id: int, vid: int, payload: DecideIn, background: BackgroundTasks,
           principal: Principal = Depends(require_company_role("member")), db: Session = Depends(get_db)):
    out = lib.decide(db, active_org(principal), principal, doc_id, vid, payload.decision, payload.note,
                     override_conflicts=payload.override_conflicts)
    if out.get("published") and out.get("core_changed"):
        resync_core_later(background, principal, active_org(principal))
    return out


@router.get("/docs/{doc_id}/diff")
def diff(doc_id: int, a: int | None = None, b: int | None = None, principal: Principal = Depends(require_company_role("member")),
         db: Session = Depends(get_db)):
    return lib.diff(db, active_org(principal), principal, doc_id, a, b)


@router.post("/docs/{doc_id}/review")
def reviewed(doc_id: int, payload: NoteIn, principal: Principal = Depends(require_company_role("manager")),
             db: Session = Depends(get_db)):
    return lib.mark_reviewed(db, active_org(principal), principal, doc_id, payload.note)


@router.post("/docs/{doc_id}/archive")
def archive(doc_id: int, payload: NoteIn, background: BackgroundTasks,
            principal: Principal = Depends(require_company_role("manager")), db: Session = Depends(get_db)):
    out = lib.archive(db, active_org(principal), principal, doc_id, payload.reason or payload.note)
    if out.get("core_changed"):
        resync_core_later(background, principal, active_org(principal))
    return out


@router.post("/docs/{doc_id}/links")
def add_link(doc_id: int, payload: LinkIn, principal: Principal = Depends(require_company_role("manager")),
             db: Session = Depends(get_db)):
    return lib.add_link(db, active_org(principal), doc_id, payload.target_type, payload.target_id, payload.note)


@router.delete("/docs/{doc_id}/links/{link_id}")
def remove_link(doc_id: int, link_id: int, principal: Principal = Depends(require_company_role("manager")),
                db: Session = Depends(get_db)):
    return lib.remove_link(db, active_org(principal), doc_id, link_id)


@router.post("/docs/{doc_id}/flags/{flag_id}")
def flag_status(doc_id: int, flag_id: int, payload: FlagStatusIn, principal: Principal = Depends(require_company_role("manager")),
                db: Session = Depends(get_db)):
    return lib.resolve_flag(db, active_org(principal), doc_id, flag_id, payload.status)


@router.get("/docs/{doc_id}/chunks")
def chunks(doc_id: int, principal: Principal = Depends(require_company_role("member")), db: Session = Depends(get_db)):
    """M3b: các đoạn đã chỉ mục (đề mục, §, tiêu đề ngữ cảnh) — để xem agent sẽ trích dẫn gì."""
    from app.models import KnowledgeChunk
    doc = lib.get_doc(db, active_org(principal), doc_id, principal=principal, content=True)
    rows = db.query(KnowledgeChunk).filter(KnowledgeChunk.document_id == doc.id).order_by(KnowledgeChunk.chunk_index).all()
    return {"items": [{"chunk_index": c.chunk_index, "section": c.section, "section_no": c.section_no, "chars": len(c.content or ""),
                       "head": (c.content or "").split("\n", 1)[0]} for c in rows]}


# ------------------------------------------------------------------ M3b sự kiện công ty

@router.get("/facts")
def facts(company_id: int | None = None, principal: Principal = Depends(require_company_role("member")), db: Session = Depends(get_db)):
    from app.services import company_facts
    return company_facts.listing(db, active_org(principal), company_id)


@router.put("/facts")
def put_fact(payload: FactIn, principal: Principal = Depends(require_company_role("manager")), db: Session = Depends(get_db)):
    from app.services import company_facts
    return company_facts.set_manual(db, active_org(principal), principal, payload.model_dump(exclude_none=True))


@router.delete("/facts/{fact_id}")
def del_fact(fact_id: int, principal: Principal = Depends(require_company_role("manager")), db: Session = Depends(get_db)):
    from app.services import company_facts
    return company_facts.remove_manual(db, active_org(principal), fact_id)


# ------------------------------------------------------------------ M3d hồ sơ bắt buộc & lưu trữ

class RequirementIn(BaseModel):
    company_id: int | None = None
    name: str | None = None
    name_en: str | None = None
    level: str | None = None
    doc_types: list[str] | None = None
    condition: dict | None = None
    legal_basis: str | None = None
    note: str | None = None
    needs_review: bool | None = None
    enabled: bool | None = None


class AttachIn(BaseModel):
    document_id: int


class DisposeIn(BaseModel):
    reason: str = ""


@router.get("/doc-requirements")
def requirements(company_id: int | None = None, principal: Principal = Depends(require_company_role("member")),
                 db: Session = Depends(get_db)):
    from app.services import doc_requirements
    return doc_requirements.evaluate(db, active_org(principal), company_id, principal=principal)


@router.post("/doc-requirements")
def add_requirement(payload: RequirementIn, principal: Principal = Depends(require_company_role("manager")),
                    db: Session = Depends(get_db)):
    from app.services import doc_requirements
    return doc_requirements.upsert(db, active_org(principal), payload.model_dump(exclude_none=True))


@router.patch("/doc-requirements/{rid}")
def edit_requirement(rid: int, payload: RequirementIn, principal: Principal = Depends(require_company_role("manager")),
                     db: Session = Depends(get_db)):
    from app.services import doc_requirements
    return doc_requirements.upsert(db, active_org(principal), payload.model_dump(exclude_none=True), rid)


@router.post("/doc-requirements/reseed")
def reseed_requirements(company_id: int | None = None, principal: Principal = Depends(require_company_role("manager")),
                        db: Session = Depends(get_db)):
    """Gieo lại mục mặc định còn thiếu (không động tới mục tự thêm)."""
    from app.services import doc_requirements
    co = doc_requirements._company(db, active_org(principal), company_id, write=True)
    return doc_requirements.seed_defaults(db, active_org(principal), co.id)


@router.post("/doc-requirements/{rid}/attach")
def attach_requirement(rid: int, payload: AttachIn, principal: Principal = Depends(require_company_role("manager")),
                       db: Session = Depends(get_db)):
    """Gắn thẳng một tài liệu vào mục (dùng cho mục không có loại tài liệu cố định, vd. quy trình DLCN)."""
    from app.services import doc_requirements
    doc_requirements._req(db, active_org(principal), rid)
    return lib.add_link(db, active_org(principal), payload.document_id, "requirement", rid, "M3d")


@router.post("/docs/{doc_id}/dispose")
def dispose(doc_id: int, payload: DisposeIn, principal: Principal = Depends(require_company_role("manager")),
            db: Session = Depends(get_db)):
    """Huỷ hồ sơ đã hết hạn lưu: chỉ chủ (owner); giữ siêu dữ liệu + hash. Trước hạn / giữ pháp lý → 409."""
    from app.services import doc_requirements
    return doc_requirements.dispose(db, active_org(principal), principal, doc_id, payload.reason)


# ------------------------------------------------------------------ M3f sản phẩm & bảng giá

class ProductIn(BaseModel):
    company_id: int | None = None
    sku: str | None = None
    name: str | None = None
    description: str | None = None
    kind: str | None = None
    category: str | None = None
    unit: str | None = None
    status: str | None = None
    policies: dict | None = None
    document_id: int | None = None
    price: str | float | None = None
    currency: str | None = None
    effective_from: str | None = None
    price_note: str | None = None


class PriceIn(BaseModel):
    amount: str | float
    currency: str = "VND"
    channel: str = "default"
    effective_from: str | None = None
    effective_to: str | None = None
    note: str = ""


class PriceDecideIn(BaseModel):
    decision: str
    note: str = ""


class LookupIn(BaseModel):
    company_id: int | None = None
    query: str = ""
    sku: str = ""


@router.get("/catalog")
def catalog_list(company_id: int | None = None, q: str = "", status: str = "",
                 principal: Principal = Depends(require_company_role("member")), db: Session = Depends(get_db)):
    from app.services import catalog
    return catalog.listing(db, active_org(principal), company_id, q=q, status=status)


@router.post("/catalog/products")
def catalog_create(payload: ProductIn, principal: Principal = Depends(require_company_role("manager")), db: Session = Depends(get_db)):
    from app.services import catalog
    return catalog.create_product(db, active_org(principal), principal, payload.model_dump(exclude_none=True))


@router.get("/catalog/products/{pid}")
def catalog_get(pid: int, principal: Principal = Depends(require_company_role("member")), db: Session = Depends(get_db)):
    from app.services import catalog
    return catalog.get_product(db, active_org(principal), pid)


@router.patch("/catalog/products/{pid}")
def catalog_patch(pid: int, payload: ProductIn, principal: Principal = Depends(require_company_role("manager")),
                  db: Session = Depends(get_db)):
    from app.services import catalog
    data = payload.model_dump(exclude_unset=True)
    data.pop("company_id", None)
    return catalog.update_product(db, active_org(principal), principal, pid, data)


@router.post("/catalog/products/{pid}/prices")
def catalog_propose(pid: int, payload: PriceIn, principal: Principal = Depends(require_company_role("manager")),
                    db: Session = Depends(get_db)):
    """Đề xuất giá mới → ma trận price_change (người đề xuất có quyền → áp dụng ngay)."""
    from app.services import catalog
    return catalog.propose_price(db, active_org(principal), principal, pid, payload.model_dump())


@router.post("/catalog/prices/{price_id}/decide")
def catalog_decide(price_id: int, payload: PriceDecideIn, principal: Principal = Depends(require_company_role("member")),
                   db: Session = Depends(get_db)):
    from app.services import catalog
    return catalog.decide_price(db, active_org(principal), principal, price_id, payload.decision, payload.note)


@router.post("/catalog/prices/{price_id}/cancel")
def catalog_cancel(price_id: int, principal: Principal = Depends(require_company_role("manager")), db: Session = Depends(get_db)):
    from app.services import catalog
    return catalog.cancel_price(db, active_org(principal), principal, price_id)


@router.post("/catalog/lookup")
def catalog_lookup(payload: LookupIn, principal: Principal = Depends(require_company_role("member")), db: Session = Depends(get_db)):
    """Xem trước đúng thứ agent nhận từ MCP company_product_lookup."""
    from app.services import catalog
    co = catalog._company(db, active_org(principal), payload.company_id)
    return catalog.lookup(db, co.id, query=payload.query, sku=payload.sku)


@router.post("/docs/tick")
def tick(principal: Principal = Depends(require_company_role("owner")), db: Session = Depends(get_db)):
    """Chạy nhịp thư viện ngay (beat docs.tick mỗi giờ). Chỉ owner — dùng khi kiểm chứng."""
    if principal.company_roles is not None:
        raise HTTPException(403, "Chỉ owner tổ chức")
    return lib.tick(db, org_id=active_org(principal))
