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


class VersionIn(BaseModel):
    title: str | None = None
    content: str | None = None
    change_note: str | None = None
    effective_from: str | None = None


class DecideIn(BaseModel):
    decision: str
    note: str = ""


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
    out = lib.decide(db, active_org(principal), principal, doc_id, vid, payload.decision, payload.note)
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


@router.post("/docs/tick")
def tick(principal: Principal = Depends(require_company_role("owner")), db: Session = Depends(get_db)):
    """Chạy nhịp thư viện ngay (beat docs.tick mỗi giờ). Chỉ owner — dùng khi kiểm chứng."""
    if principal.company_roles is not None:
        raise HTTPException(403, "Chỉ owner tổ chức")
    return lib.tick(db, org_id=active_org(principal))
