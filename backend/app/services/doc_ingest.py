"""M3c — nạp & phân loại tài liệu. Spec: docs/company-knowledge-library-and-gaps.md §A7, §C M3c.

Đường vào (mọi đường đều tạo tài liệu NHÁP — kể cả hồ sơ — chờ duyệt theo ma trận ``doc_publish`` của M3a):
* tệp: PDF (lớp chữ pypdf; không có lớp chữ → OCR Tesseract nếu image có ``tesseract`` + ``pdftoppm``, không thì 422
  nói rõ), ảnh scan (OCR), DOCX, XLSX (đọc XML trong zip → bảng Markdown, không cần openpyxl), PPTX, MD/TXT/CSV/HTML;
* URL (``knowledge_hub.fetch_url``);
* Google Drive / Notion qua ``doc_sources`` (token mã hoá; chưa có token → ``needs_account`` + đường tay: tải tệp xuất
  từ Drive/Notion lên như tệp thường);
* "Tạo từ mẫu": mẫu tài liệu VN thường gặp (``TEMPLATES``) điền sẵn tên công ty.

Chống trùng: sha256 của tệp gốc (``document_files``) HOẶC của nội dung chuẩn hoá (``knowledge_document_versions
.content_hash``) đã có trong công ty → 409 kèm mã tài liệu cũ, ghi ``doc_imports.status=duplicate``.

Phân loại tự động (luật + regex, không gọi model — T1 có thể thay sau): loại tài liệu theo từ khoá, độ nhạy theo PII
(≥3 số CCCD hoặc ≥5 SĐT/email → ``personal_data`` + ``agent_use=none``), ngày hiệu lực đọc trong văn bản, mã đề xuất.
Trích sự kiện từ Giấy chứng nhận ĐKDN (tên, MST, ngày cấp lần đầu, người đại diện, địa chỉ, vốn điều lệ VND) → ĐỀ XUẤT
trên dòng nạp; người có quyền admin công ty bấm "Áp dụng" mới ghi vào hồ sơ pháp nhân."""
from __future__ import annotations

import base64
import hashlib
import io
import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from datetime import datetime, timedelta
from xml.etree import ElementTree as ET

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import Company, KnowledgeDocument
from app.models.doc_ingest import DocImport, DocSource, DocSourceItem
from app.models.documents import DocumentFile, DocumentVersion
from app.services import doc_library as lib
from app.services.knowledge_hub import unaccent

MIN_TEXT = 20
OCR_MAX_PAGES = 15

# ------------------------------------------------------------------ trích chữ


def ocr_status() -> dict:
    tess = shutil.which("tesseract")
    langs: list[str] = []
    if tess:
        try:
            out = subprocess.run([tess, "--list-langs"], capture_output=True, text=True, timeout=10)
            langs = [x.strip() for x in (out.stdout + out.stderr).splitlines()[1:] if x.strip() and " " not in x.strip()]
        except Exception:  # noqa: BLE001
            langs = []
    return {"tesseract": bool(tess), "pdftoppm": bool(shutil.which("pdftoppm")), "langs": langs,
            "vie": "vie" in langs}


def _ocr_lang() -> str:
    st = ocr_status()
    return "vie+eng" if st["vie"] and "eng" in st["langs"] else ("vie" if st["vie"] else "eng")


def _ocr_image_bytes(data: bytes, lang: str) -> str:
    r = subprocess.run(["tesseract", "stdin", "stdout", "-l", lang], input=data, capture_output=True, timeout=90)
    return r.stdout.decode("utf-8", errors="replace")


def _ocr_pdf(data: bytes, lang: str) -> str:
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "in.pdf")
        with open(src, "wb") as fh:
            fh.write(data)
        subprocess.run(["pdftoppm", "-r", "200", "-l", str(OCR_MAX_PAGES), "-png", src, os.path.join(d, "p")],
                       capture_output=True, timeout=110)
        pages = sorted(f for f in os.listdir(d) if f.startswith("p") and f.endswith(".png"))
        out = []
        for f in pages:
            with open(os.path.join(d, f), "rb") as fh:
                out.append(_ocr_image_bytes(fh.read(), lang).strip())
        return "\n\n".join(x for x in out if x)


def _xml_texts(raw: bytes, tag: str) -> list[str]:
    root = ET.fromstring(raw)
    return [el.text or "" for el in root.iter() if el.tag.endswith("}" + tag) or el.tag == tag]


def _xlsx(data: bytes) -> str:
    """XLSX → mỗi trang tính một bảng Markdown (đọc thẳng XML trong zip: sharedStrings + sheetN)."""
    z = zipfile.ZipFile(io.BytesIO(data))
    shared: list[str] = []
    if "xl/sharedStrings.xml" in z.namelist():
        root = ET.fromstring(z.read("xl/sharedStrings.xml"))
        for si in root:
            shared.append("".join(t.text or "" for t in si.iter() if t.tag.endswith("}t")))
    names: list[str] = []
    if "xl/workbook.xml" in z.namelist():
        names = [s.get("name") or "" for s in ET.fromstring(z.read("xl/workbook.xml")).iter() if s.tag.endswith("}sheet")]
    sheets = sorted((n for n in z.namelist() if re.match(r"xl/worksheets/sheet\d+\.xml$", n)),
                    key=lambda n: int(re.findall(r"\d+", n)[0]))
    out = []
    for i, n in enumerate(sheets):
        rows = []
        for row in ET.fromstring(z.read(n)).iter():
            if not row.tag.endswith("}row"):
                continue
            cells = []
            for c in row:
                if not c.tag.endswith("}c"):
                    continue
                v = next((x.text for x in c if x.tag.endswith("}v")), None)
                if c.get("t") == "s" and v is not None:
                    v = shared[int(v)] if int(v) < len(shared) else ""
                elif c.get("t") == "inlineStr":
                    v = "".join(t.text or "" for t in c.iter() if t.tag.endswith("}t"))
                cells.append((v or "").strip().replace("|", "/"))
            if any(cells):
                rows.append(cells)
        if not rows:
            continue
        w = max(len(r) for r in rows)
        rows = [r + [""] * (w - len(r)) for r in rows]
        title = names[i] if i < len(names) and names[i] else f"Trang {i + 1}"
        md = [f"## {title}", "| " + " | ".join(rows[0]) + " |", "|" + "---|" * w]
        md += ["| " + " | ".join(r) + " |" for r in rows[1:]]
        out.append("\n".join(md))
    return "\n\n".join(out)


def _pptx(data: bytes) -> str:
    z = zipfile.ZipFile(io.BytesIO(data))
    slides = sorted((n for n in z.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", n)),
                    key=lambda n: int(re.findall(r"\d+", n)[0]))
    out = []
    for i, n in enumerate(slides, 1):
        texts = [t.strip() for t in _xml_texts(z.read(n), "t") if t.strip()]
        if texts:
            out.append(f"## Trang chiếu {i}: {texts[0]}\n\n" + "\n".join(texts[1:]))
    return "\n\n".join(out)


IMAGE_EXT = (".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff")


def extract(filename: str, data: bytes) -> dict:
    """→ {text, method, ocr_used, note}. Không bao giờ trả chuỗi rỗng im lặng: ``note`` nói vì sao rỗng."""
    from app.services import knowledge_hub
    name = (filename or "").lower()
    st = None
    if name.endswith(IMAGE_EXT):
        st = ocr_status()
        if not st["tesseract"]:
            return {"text": "", "method": "image", "ocr_used": False,
                    "note": "Ảnh scan: máy chủ chưa cài Tesseract nên chưa đọc được chữ — lưu như hồ sơ (record)."}
        return {"text": _ocr_image_bytes(data, _ocr_lang()).strip(), "method": "ocr:tesseract", "ocr_used": True,
                "note": "" if st["vie"] else "OCR chỉ có gói tiếng Anh — dấu tiếng Việt có thể sai, cần soát lại."}
    try:
        if name.endswith(".xlsx"):
            return {"text": _xlsx(data), "method": "xlsx", "ocr_used": False, "note": ""}
        if name.endswith(".pptx"):
            return {"text": _pptx(data), "method": "pptx", "ocr_used": False, "note": ""}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(422, f"Không đọc được tệp {filename}: {exc}") from exc
    if name.endswith(".pdf"):
        text = knowledge_hub.extract_text(filename, data)
        if len(re.sub(r"\s+", "", text or "")) >= MIN_TEXT:
            return {"text": text, "method": "pypdf", "ocr_used": False, "note": ""}
        st = ocr_status()
        if st["tesseract"] and st["pdftoppm"]:
            t2 = _ocr_pdf(data, _ocr_lang()).strip()
            return {"text": t2, "method": "ocr:tesseract", "ocr_used": True,
                    "note": "PDF không có lớp chữ — đã OCR" + ("" if st["vie"] else " (chỉ gói tiếng Anh, cần soát dấu)")}
        return {"text": "", "method": "pypdf", "ocr_used": False,
                "note": "PDF không có lớp chữ (bản scan) và máy chủ chưa cài Tesseract/pdftoppm để OCR."}
    if name.endswith(".doc") or name.endswith(".xls") or name.endswith(".ppt"):
        raise HTTPException(422, "Định dạng Office cũ (.doc/.xls/.ppt) chưa đọc được — lưu lại dưới dạng .docx/.xlsx/.pptx")
    return {"text": knowledge_hub.extract_text(filename, data), "method": name.rsplit(".", 1)[-1] if "." in name else "text",
            "ocr_used": False, "note": ""}


# ------------------------------------------------------------------ phân loại (đề xuất)

TYPE_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("legal_registration", ("giay chung nhan dang ky doanh nghiep", "ma so doanh nghiep")),
    ("charter_legal", ("dieu le cong ty", "dieu le")),
    ("labor_rules", ("noi quy lao dong",)),
    ("employment_contract", ("hop dong lao dong",)),
    ("privacy_notice", ("du lieu ca nhan", "bao ve du lieu", "chinh sach bao mat")),
    ("price_list", ("bang gia",)),
    ("promo", ("khuyen mai", "chuong trinh uu dai")),
    ("license", ("giay phep", "giay chung nhan du dieu kien")),
    ("invoice", ("hoa don gia tri gia tang", "hoa don dien tu")),
    ("nda", ("thoa thuan bao mat", "non-disclosure")),
    ("contract", ("hop dong",)),
    ("faq", ("cau hoi thuong gap", "faq", "hoi dap")),
    ("canned_reply", ("mau tra loi", "kich ban tra loi")),
    ("job_description", ("mo ta cong viec",)),
    ("sop", ("quy trinh",)),
    ("checklist", ("checklist", "danh sach kiem tra")),
    ("policy", ("chinh sach", "doi tra", "hoan tien", "bao hanh", "van chuyen", "giao hang")),
    ("handbook", ("so tay",)),
    ("brand_guide", ("nhan dien thuong hieu", "giong thuong hieu")),
]

CCCD_RE = re.compile(r"(?<!\d)0\d{11}(?!\d)")
PHONE_RE = re.compile(r"(?<!\d)(?:\+?84|0)[35789]\d{8}(?!\d)")
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
DATE_RE = r"(\d{1,2})\s*[/.-]\s*(\d{1,2})\s*[/.-]\s*(\d{4})"
EFFECTIVE_RE = re.compile(r"hieu luc\s*(?:ke\s*)?(?:tu|:)?\s*(?:ngay)?\s*" + DATE_RE)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", unaccent(text or "").lower())


def pii_counts(text: str) -> dict:
    return {"cccd": len(set(CCCD_RE.findall(text or ""))), "phone": len(set(PHONE_RE.findall(text or ""))),
            "email": len(set(EMAIL_RE.findall(text or "")))}


def classify(db: Session, company_id: int, title: str, text: str, *, default_type: str = "") -> dict:
    head = _norm((title or "") + "\n" + (text or "")[:4000])
    doc_type, why, hit_phrase = default_type or "other", ("source" if default_type else "default"), ""
    if not default_type:
        for t, words in TYPE_RULES:
            hit = next((w for w in words if w in head), None)
            if hit and t in lib.DOC_TYPES:
                doc_type, why, hit_phrase = t, "phrase", hit
                break
    ti = lib.DOC_TYPES[doc_type]
    pii = pii_counts(text)
    sensitivity, agent_use, sens_why = ti["sensitivity"], ti["agent_use"], ""
    if pii["cccd"] >= 3 or pii["phone"] >= 5 or pii["email"] >= 5:
        sensitivity, agent_use, sens_why = "personal_data", "none", "pii"     # UI hiển thị từ pii{} (vi/en)
    eff = None
    m = EFFECTIVE_RE.search(head)
    if m:
        try:
            eff = datetime(int(m.group(3)), int(m.group(2)), int(m.group(1))).date().isoformat()
        except ValueError:
            eff = None
    return {"doc_type": doc_type, "doc_type_vi": ti["vi"], "doc_type_en": ti["en"], "doc_type_reason": why,
            "doc_type_hit": hit_phrase, "doc_class": ti["doc_class"], "sensitivity": sensitivity,
            "agent_use": agent_use, "sensitivity_reason": sens_why, "pii": pii, "effective_from": eff,
            "doc_code": lib._next_code(db, company_id, ti["group"]), "group": ti["group"]}


# ------------------------------------------------------------------ trích sự kiện từ GCN ĐKDN (đề xuất)

def _after(label_re: str, text: str, stop: str = r"\n") -> str:
    m = re.search(label_re + r"\s*[:：]?\s*(.+?)(?:" + stop + r"|$)", text, flags=re.I)
    return (m.group(1).strip(" .;,") if m else "")


def extract_registration(text: str) -> dict:
    """Giấy chứng nhận đăng ký doanh nghiệp → {legal_name, tax_code, founded_on, legal_representative,
    registered_address, charter_capital_vnd}. Khớp trên bản bỏ dấu để chịu được OCR mất dấu; giá trị lấy từ bản gốc."""
    import unicodedata
    raw = unicodedata.normalize("NFC", text or "")
    flat = unaccent(raw)
    out: dict = {}

    def grab(pattern: str, stop: str = r"\n") -> str:
        m = re.search(pattern + r"\s*[:：]?\s*(.+?)(?:" + stop + r"|$)", flat, flags=re.I)
        if not m:
            return ""
        return raw[m.start(1):m.end(1)].strip(" .;,")   # unaccent giữ nguyên độ dài cho chữ Việt dựng sẵn

    mst = re.search(r"ma so (?:doanh nghiep|thue)\s*[:：]?\s*([0-9][0-9 .-]{8,16}[0-9])", flat, flags=re.I)
    if mst:
        out["tax_code"] = re.sub(r"\D", "", mst.group(1))[:14]
    name = grab(r"ten (?:cong ty|doanh nghiep) viet bang tieng viet")
    if name:
        out["legal_name"] = name
    d = re.search(r"dang ky lan dau\s*[:：]?\s*(?:ngay)?\s*(\d{1,2})\s*(?:thang|/|-|\.)\s*(\d{1,2})\s*(?:nam|/|-|\.)\s*(\d{4})",
                  flat, flags=re.I)
    if d:
        try:
            out["founded_on"] = datetime(int(d.group(3)), int(d.group(2)), int(d.group(1))).date().isoformat()
        except ValueError:
            pass
    addr = grab(r"dia chi tru so chinh")
    if addr:
        out["registered_address"] = addr
    rep = re.search(r"nguoi dai dien theo phap luat.{0,200}?ho (?:va )?ten\s*[:：]?\s*(.+?)(?:\n|gioi tinh|$)",
                    flat, flags=re.I | re.S)
    if rep:
        out["legal_representative"] = raw[rep.start(1):rep.end(1)].strip(" .;,")
    cap = re.search(r"von dieu le\s*[:：]?\s*([0-9][0-9.,\s]{3,25})\s*(?:dong|vnd|d\b)", flat, flags=re.I)
    if cap:
        out["charter_capital_vnd"] = int(re.sub(r"\D", "", cap.group(1)))
    return out


# ------------------------------------------------------------------ chống trùng

def _text_hash(text: str) -> str:
    return lib._hash(text)


def find_duplicate(db: Session, company_id: int, *, file_sha: str = "", text_hash: str = "") -> KnowledgeDocument | None:
    if file_sha:
        f = db.query(DocumentFile).filter(DocumentFile.company_id == company_id, DocumentFile.sha256 == file_sha).first()
        if f is not None:
            doc = (db.query(KnowledgeDocument).filter(KnowledgeDocument.file_id == f.id,
                                                      KnowledgeDocument.status != "disposed").first()
                   or db.query(KnowledgeDocument).join(DocumentVersion, DocumentVersion.document_id == KnowledgeDocument.id)
                   .filter(DocumentVersion.file_id == f.id, KnowledgeDocument.status != "disposed").first())
            if doc is not None:
                return doc
    if text_hash:
        return (db.query(KnowledgeDocument).join(DocumentVersion, DocumentVersion.document_id == KnowledgeDocument.id)
                .filter(KnowledgeDocument.company_id == company_id, DocumentVersion.content_hash == text_hash,
                        KnowledgeDocument.status.notin_(("disposed", "archived"))).first())
    return None


# ------------------------------------------------------------------ nạp

def public_import(db: Session, im: DocImport) -> dict:
    doc = db.get(KnowledgeDocument, im.document_id) if im.document_id else None
    dup = db.get(KnowledgeDocument, im.duplicate_of_id) if im.duplicate_of_id else None
    return {"id": im.id, "company_id": im.company_id, "source": im.source, "source_ref": im.source_ref,
            "filename": im.filename, "sha256": im.sha256, "status": im.status, "method": im.method,
            "ocr_used": bool(im.ocr_used), "extracted_chars": im.extracted_chars, "note": im.note,
            "suggestions": im.suggestions or {}, "proposals": im.proposals or {}, "proposals_status": im.proposals_status,
            "document": {"id": doc.id, "doc_code": doc.doc_code, "title": doc.title, "status": doc.status} if doc else None,
            "duplicate_of": {"id": dup.id, "doc_code": dup.doc_code, "title": dup.title} if dup else None,
            "created_at": im.created_at.isoformat() if im.created_at else None}


def _record(db: Session, org_id: int, company_id: int, principal, **kw) -> DocImport:
    im = DocImport(organization_id=org_id, company_id=company_id,
                   created_by_member_id=lib._seat(db, principal, company_id) if principal else None, **kw)
    db.add(im); db.commit(); db.refresh(im)
    return im


def ingest(db: Session, org_id: int, principal, company_id: int, *, source: str, title: str = "", text: str = "",
           filename: str = "", data: bytes | None = None, mime: str = "", source_ref: str = "",
           source_id: int | None = None, overrides: dict | None = None, default_type: str = "") -> dict:
    """Nạp một tài liệu → nháp. 409 nếu trùng (tệp hoặc nội dung), 422 nếu không có chữ (trừ hồ sơ scan được chọn rõ)."""
    co = lib._company(db, org_id, company_id, write=True)
    overrides = {k: v for k, v in (overrides or {}).items() if v not in (None, "")}
    method, ocr_used, note = "text", False, ""
    file_sha = hashlib.sha256(data).hexdigest() if data is not None else ""
    if data is not None:
        dup = find_duplicate(db, co.id, file_sha=file_sha)
        if dup is not None:
            im = _record(db, org_id, co.id, principal, source=source, source_ref=source_ref or filename, source_id=source_id,
                         filename=filename, sha256=file_sha, status="duplicate", duplicate_of_id=dup.id,
                         note=f"Tệp trùng sha256 với {dup.doc_code}")
            raise HTTPException(409, {"error": "duplicate", "message": f"Tệp này đã có trong thư viện: {dup.doc_code} · {dup.title}",
                                      "document_id": dup.id, "doc_code": dup.doc_code, "import": public_import(db, im)})
        ex = extract(filename, data)
        text, method, ocr_used, note = ex["text"], ex["method"], ex["ocr_used"], ex["note"]
    text = (text or "").strip()
    th = _text_hash(text) if len(text) >= MIN_TEXT else ""
    if th:
        dup = find_duplicate(db, co.id, text_hash=th)
        if dup is not None:
            im = _record(db, org_id, co.id, principal, source=source, source_ref=source_ref or filename, source_id=source_id,
                         filename=filename, sha256=file_sha or th, status="duplicate", duplicate_of_id=dup.id,
                         method=method, extracted_chars=len(text), note=f"Nội dung trùng với {dup.doc_code}")
            raise HTTPException(409, {"error": "duplicate", "message": f"Nội dung này đã có trong thư viện: {dup.doc_code} · {dup.title}",
                                      "document_id": dup.id, "doc_code": dup.doc_code, "import": public_import(db, im)})
    name_title = (title or (filename.rsplit(".", 1)[0] if filename else "")).strip()
    sug = classify(db, co.id, name_title, text, default_type=default_type)
    want_class = overrides.get("doc_class") or lib.DOC_TYPES[overrides.get("doc_type") or sug["doc_type"]]["doc_class"]
    if len(text) < MIN_TEXT and not (want_class == "record" and data is not None):
        im = _record(db, org_id, co.id, principal, source=source, source_ref=source_ref or filename, source_id=source_id,
                     filename=filename, sha256=file_sha, status="empty", method=method, ocr_used=ocr_used,
                     extracted_chars=len(text), note=note or "Không trích được chữ", suggestions=sug)
        raise HTTPException(422, {"error": "empty_text", "message": (note or "Không trích được chữ từ nguồn này")
                                  + " — tài liệu cần nội dung chữ; bản scan giấy tờ thì chọn lớp 'Hồ sơ'.",
                                  "import": public_import(db, im)})
    f = lib.store_file(db, org_id, co.id, filename, mime, data) if data is not None else None
    if f is not None:
        f.extracted_chars = len(text); db.add(f); db.flush()
    body = {"company_id": co.id, "title": name_title or sug["doc_type"], "content": text,
            "doc_type": sug["doc_type"], "sensitivity": sug["sensitivity"], "agent_use": sug["agent_use"],
            "change_note": f"Nạp từ {source}: {source_ref or filename}"[:300]}
    if sug.get("effective_from"):
        body["effective_from"] = sug["effective_from"]
    body.update({k: v for k, v in overrides.items() if k in ("title", "doc_type", "doc_class", "sensitivity", "agent_use",
                                                          "effective_from", "owner_position_id")})
    if body.get("doc_type") and body["doc_type"] != sug["doc_type"] and "doc_class" not in overrides:
        body["doc_class"] = lib.DOC_TYPES[body["doc_type"]]["doc_class"]
    if sug["sensitivity"] == "personal_data":      # PII thắng lựa chọn tay: không để agent đọc hồ sơ có CCCD hàng loạt
        body["sensitivity"], body["agent_use"] = "personal_data", "none"
    doc = lib.create(db, org_id, principal, body, file=f, force_draft=True)
    proposals: dict = {}
    if (body.get("doc_type") or sug["doc_type"]) == "legal_registration" or "ma so doanh nghiep" in _norm(text[:3000]):
        reg = extract_registration(text)
        if reg:
            proposals["company_profile"] = reg
    from app.services import company_facts
    try:
        facts = company_facts.extract(text)
    except Exception:  # noqa: BLE001
        facts = []
    if facts:
        proposals["facts"] = [{"key": x.get("key"), "value": x.get("value")} for x in facts if isinstance(x, dict)][:20]
    im = _record(db, org_id, co.id, principal, source=source, source_ref=(source_ref or filename)[:500], source_id=source_id,
                 filename=filename[:300], sha256=file_sha or th, status="done", document_id=doc["id"], version_no=1,
                 method=method, ocr_used=ocr_used, extracted_chars=len(text), note=note, suggestions=sug,
                 proposals=proposals or None, proposals_status="pending" if proposals.get("company_profile") else "")
    return {"import": public_import(db, im), "document": doc}


def ingest_url(db: Session, org_id: int, principal, company_id: int, url: str, overrides: dict | None = None) -> dict:
    from app.services import knowledge_hub
    title, text = knowledge_hub.fetch_url(url)
    return ingest(db, org_id, principal, company_id, source="url", title=(overrides or {}).get("title") or title or url,
                  text=text, source_ref=url, overrides=overrides)


def list_imports(db: Session, org_id: int, company_id: int, limit: int = 50) -> dict:
    lib._company(db, org_id, company_id)
    rows = (db.query(DocImport).filter(DocImport.company_id == company_id).order_by(DocImport.id.desc()).limit(limit).all())
    return {"items": [public_import(db, r) for r in rows], "ocr": ocr_status(), "templates": template_list(),
            "sources": [public_source(s) for s in db.query(DocSource).filter(DocSource.company_id == company_id)
                        .order_by(DocSource.id).all()]}


PROFILE_KEYS = ("legal_name", "tax_code", "founded_on", "legal_representative", "registered_address")


def decide_proposals(db: Session, org_id: int, principal, import_id: int, action: str, keys: list[str] | None = None) -> tuple[dict, bool]:
    """Áp dụng (một phần) / bỏ qua đề xuất hồ sơ pháp nhân. Áp dụng gọi ``company_foundation.save_profile`` — cùng đường
    ghi với form hồ sơ, nên hiến chương đổi thì AGENTS.md được đồng bộ lại."""
    im = db.get(DocImport, import_id)
    if im is None or im.organization_id != org_id:
        raise HTTPException(404, "Không thấy lần nạp này")
    from app.core import company_scope
    company_scope.check(im.company_id, min_role="admin")
    if im.proposals_status != "pending":
        raise HTTPException(409, f"Đề xuất đang '{im.proposals_status or 'không có'}'")
    changed = False
    if action == "apply":
        prop = dict((im.proposals or {}).get("company_profile") or {})
        data = {k: v for k, v in prop.items() if k in PROFILE_KEYS and (not keys or k in keys)}
        if "charter_capital_vnd" in prop and (not keys or "charter_capital_vnd" in keys):
            # hồ sơ lưu vốn theo USD (M2b) — không tự quy đổi; ghi số VND nguyên văn vào ghi chú vốn
            data["charter_capital_note"] = f"Vốn điều lệ {prop['charter_capital_vnd']:,} ₫ (theo GCN ĐKDN)".replace(",", ".")
        if "founded_on" in data:
            from datetime import date
            data["founded_on"] = date.fromisoformat(data["founded_on"])
        from app.services import company_foundation as cf
        _, changed = cf.save_profile(db, org_id, im.company_id, data, user_id=getattr(principal, "user_id", None))
        im.proposals_status = "applied"
    elif action == "dismiss":
        im.proposals_status = "dismissed"
    else:
        raise HTTPException(422, "action phải là apply hoặc dismiss")
    db.add(im); db.commit(); db.refresh(im)
    return public_import(db, im), changed


# ------------------------------------------------------------------ mẫu tài liệu VN ("Tạo từ mẫu")

TEMPLATES: dict[str, dict] = {
    "noi_quy": {"doc_type": "labor_rules", "vi": "Nội quy lao động", "en": "Labour rules",
                "basis": "Bộ luật Lao động 2019 Đ118–119 (≥10 NLĐ: bằng văn bản + đăng ký với cơ quan lao động) — cần kiểm tra",
                "body": """# Nội quy lao động — {company}

## 1. Thời giờ làm việc, nghỉ ngơi
- Giờ làm việc: …… (ví dụ 8:00–17:00, thứ Hai–thứ Bảy), nghỉ trưa ……
- Nghỉ hằng tuần, nghỉ lễ Tết theo Bộ luật Lao động.

## 2. Trật tự tại nơi làm việc
- ……

## 3. An toàn, vệ sinh lao động
- ……

## 4. Bảo vệ tài sản, bí mật kinh doanh, công nghệ
- ……

## 5. Phòng, chống quấy rối tình dục tại nơi làm việc
- Hành vi bị cấm, cách báo cáo, cách xử lý.

## 6. Hành vi vi phạm kỷ luật và hình thức xử lý
- Khiển trách / kéo dài thời hạn nâng lương / cách chức / sa thải — ghi rõ hành vi tương ứng.

## 7. Trách nhiệm vật chất
- ……

## 8. Người có thẩm quyền xử lý kỷ luật
- ……
"""},
    "doi_tra": {"doc_type": "policy", "vi": "Chính sách đổi trả & hoàn tiền", "en": "Returns & refund policy",
                "basis": "Luật Bảo vệ quyền lợi người tiêu dùng 2023; NĐ 52/2013, 85/2021 (TMĐT) — cần kiểm tra",
                "body": """# Chính sách đổi trả & hoàn tiền — {company}

## 1. Thời hạn đổi trả
Khách được đổi/trả trong **7 ngày** kể từ ngày nhận hàng.

## 2. Điều kiện
- Sản phẩm còn nguyên vẹn, đủ phụ kiện, có hoá đơn/mã đơn.
- Hàng lỗi do nhà sản xuất hoặc vỡ khi vận chuyển: đổi mới miễn phí (cần video mở hàng).

## 3. Không áp dụng
- ……

## 4. Hoàn tiền
Hoàn tiền trong **48 giờ** làm việc kể từ khi nhận lại hàng, qua phương thức thanh toán ban đầu.

## 5. Phí vận chuyển đổi trả
- Lỗi của cửa hàng: cửa hàng chịu. Khách đổi ý: khách chịu.
"""},
    "cskh": {"doc_type": "sop", "vi": "Quy trình chăm sóc khách hàng", "en": "Customer service process",
             "basis": "Thực hành tốt", "body": """# Quy trình chăm sóc khách hàng — {company}

## 1. Tiếp nhận
- Kênh: …… (Zalo, Facebook, Shopee, hotline). Phản hồi đầu tiên trong **15 phút** giờ làm việc.

## 2. Phân loại yêu cầu
- Hỏi thông tin / Đặt hàng / Khiếu nại / Đổi trả.

## 3. Xử lý
- Tra tài liệu đã ban hành (chính sách, bảng giá) trước khi trả lời; không hứa ngoài chính sách.

## 4. Chuyển cấp
- Khiếu nại, hoàn tiền vượt hạn mức, khách giận dữ → chuyển trưởng nhóm trong 30 phút.

## 5. Đóng yêu cầu & ghi nhận
- Xác nhận khách hài lòng, ghi chú, gắn nhãn.
"""},
    "khieu_nai": {"doc_type": "sop", "vi": "Quy trình xử lý khiếu nại", "en": "Complaint handling process",
                  "basis": "Luật Bảo vệ quyền lợi người tiêu dùng 2023 — cần kiểm tra", "body": """# Quy trình xử lý khiếu nại — {company}

## 1. Ghi nhận khiếu nại
- Nội dung, thời điểm, bằng chứng, mã đơn.

## 2. Xác minh (trong 24 giờ)
- ……

## 3. Phương án giải quyết
- Đổi / hoàn tiền / bồi thường — theo chính sách đổi trả.

## 4. Phản hồi khách & lưu hồ sơ
- ……
"""},
    "bao_mat_dlcn": {"doc_type": "privacy_notice", "vi": "Thông báo xử lý dữ liệu cá nhân", "en": "Privacy notice",
                     "basis": "NĐ 13/2023/NĐ-CP; Luật Bảo vệ dữ liệu cá nhân 2025 — cần kiểm tra", "body": """# Thông báo xử lý dữ liệu cá nhân — {company}

## 1. Dữ liệu thu thập
- Họ tên, số điện thoại, địa chỉ giao hàng, lịch sử đơn hàng.

## 2. Mục đích
- Giao hàng, chăm sóc khách hàng, bảo hành. Không bán dữ liệu cho bên thứ ba.

## 3. Thời gian lưu
- ……

## 4. Quyền của chủ thể dữ liệu
- Xem, sửa, xoá, rút lại đồng ý — liên hệ ……

## 5. Bên nhận dữ liệu
- Đơn vị vận chuyển, cổng thanh toán.
"""},
    "van_chuyen": {"doc_type": "policy", "vi": "Chính sách vận chuyển", "en": "Shipping policy", "basis": "Thực hành tốt",
                   "body": """# Chính sách vận chuyển — {company}

## 1. Phí vận chuyển
- Miễn phí giao hàng cho đơn từ **……đ**; dưới mức này phí theo đơn vị vận chuyển.

## 2. Thời gian giao
- Nội thành: 1–2 ngày; tỉnh: 3–5 ngày.

## 3. Hàng dễ vỡ
- Đóng gói chống sốc; vỡ khi nhận → xem chính sách đổi trả.
"""},
    "bao_hanh": {"doc_type": "policy", "vi": "Chính sách bảo hành", "en": "Warranty policy", "basis": "Thực hành tốt",
                 "body": """# Chính sách bảo hành — {company}

## 1. Thời hạn bảo hành
- Bảo hành **…… tháng** kể từ ngày mua.

## 2. Phạm vi
- ……

## 3. Cách yêu cầu bảo hành
- ……
"""},
    "faq": {"doc_type": "faq", "vi": "Câu hỏi thường gặp", "en": "FAQ", "basis": "Thực hành tốt",
            "body": """# Câu hỏi thường gặp — {company}

## Đơn bao nhiêu thì được miễn phí giao hàng?
……

## Bao lâu thì nhận được hàng?
……

## Đổi trả thế nào?
Xem chính sách đổi trả.

## Hotline của cửa hàng là gì?
……
"""},
}


def template_list() -> list[dict]:
    return [{"key": k, "vi": v["vi"], "en": v["en"], "doc_type": v["doc_type"], "basis": v["basis"]} for k, v in TEMPLATES.items()]


def from_template(db: Session, org_id: int, principal, company_id: int, key: str, title: str = "") -> dict:
    tpl = TEMPLATES.get(key)
    if tpl is None:
        raise HTTPException(404, "Không có mẫu này")
    co = lib._company(db, org_id, company_id, write=True)
    body = tpl["body"].format(company=co.name)
    doc = lib.create(db, org_id, principal, {"company_id": co.id, "title": title or tpl["vi"], "doc_type": tpl["doc_type"],
                                             "content": body, "change_note": f"Tạo từ mẫu: {tpl['vi']} (căn cứ: {tpl['basis']})"},
                     force_draft=True)
    im = _record(db, org_id, co.id, principal, source="template", source_ref=key, status="done", document_id=doc["id"],
                 version_no=1, method="template", extracted_chars=len(body),
                 note="Mẫu tham khảo, không phải tư vấn pháp lý — điền các chỗ '……' trước khi gửi duyệt")
    return {"import": public_import(db, im), "document": doc}


# ------------------------------------------------------------------ nguồn đồng bộ (Drive / Notion / URL)

def _fernet():
    from cryptography.fernet import Fernet
    from app.core.config import settings
    key = base64.urlsafe_b64encode(hashlib.sha256(("doc-sources:" + (settings.jwt_secret or "")).encode()).digest())
    return Fernet(key)


def seal(token: str) -> str:
    return _fernet().encrypt(token.encode()).decode() if token else ""


def unseal(blob: str) -> str:
    return _fernet().decrypt(blob.encode()).decode() if blob else ""


def public_source(s: DocSource) -> dict:
    return {"id": s.id, "company_id": s.company_id, "kind": s.kind, "name": s.name, "config": s.config or {},
            "has_credential": bool(s.credential_enc), "credential_hint": s.credential_hint,
            "default_doc_type": s.default_doc_type, "interval_minutes": s.interval_minutes, "status": s.status,
            "last_synced_at": s.last_synced_at.isoformat() if s.last_synced_at else None, "last_error": s.last_error}


def _source_status(s: DocSource) -> str:
    if s.status == "paused":
        return "paused"
    if s.kind in ("gdrive", "notion") and not s.credential_enc:
        return "needs_account"
    return "active"


def save_source(db: Session, org_id: int, principal, data: dict, source_id: int | None = None) -> dict:
    if source_id:
        s = db.get(DocSource, source_id)
        if s is None or s.organization_id != org_id:
            raise HTTPException(404, "Không thấy nguồn này")
        lib._company(db, org_id, s.company_id, write=True)
    else:
        kind = data.get("kind")
        if kind not in ("url", "gdrive", "notion"):
            raise HTTPException(422, "kind phải là url, gdrive hoặc notion")
        co = lib._company(db, org_id, data.get("company_id"), write=True)
        s = DocSource(organization_id=org_id, company_id=co.id, kind=kind,
                      created_by_member_id=lib._seat(db, principal, co.id))
    for k in ("name", "default_doc_type"):
        if data.get(k) is not None:
            setattr(s, k, str(data[k])[:200])
    if s.default_doc_type and s.default_doc_type not in lib.DOC_TYPES:
        raise HTTPException(422, f"doc_type lạ: {s.default_doc_type}")
    if data.get("interval_minutes"):
        s.interval_minutes = max(60, int(data["interval_minutes"]))
    if data.get("config") is not None:
        cfg = dict(data["config"] or {})
        if s.kind == "url" and not re.match(r"^https?://", cfg.get("url") or ""):
            raise HTTPException(422, "Nguồn URL cần config.url bắt đầu bằng http(s)://")
        if s.kind == "notion":
            cfg["page_ids"] = [re.sub(r"[^0-9a-fA-F]", "", p)[-32:] for p in (cfg.get("page_ids") or []) if p]
        s.config = cfg
    if data.get("credential"):
        tok = str(data["credential"]).strip()
        s.credential_enc, s.credential_hint = seal(tok), "…" + tok[-4:]
    if data.get("paused") is not None:
        s.status = "paused" if data["paused"] else "active"
    s.status = _source_status(s) if s.status != "error" or data.get("credential") else s.status
    db.add(s); db.commit(); db.refresh(s)
    return public_source(s)


class SourceError(Exception):
    pass


class Connector:
    """Giao diện nguồn: ``items(source)`` → [{id, title, version}] ; ``fetch(source, item)`` → (tên tệp, bytes|None, text)."""
    kind = ""

    def items(self, s: DocSource) -> list[dict]:
        raise NotImplementedError

    def fetch(self, s: DocSource, item: dict) -> tuple[str, bytes | None, str]:
        raise NotImplementedError


class UrlConnector(Connector):
    kind = "url"

    def items(self, s):
        url = (s.config or {}).get("url") or ""
        return [{"id": url, "title": (s.name or url)[:300], "version": ""}]   # version = sha của nội dung (so ở sync)

    def fetch(self, s, item):
        from app.services import knowledge_hub
        title, text = knowledge_hub.fetch_url(item["id"])
        item["title"] = title or item["title"]
        return "", None, text


class GoogleDriveConnector(Connector):
    """Drive API v3 bằng access token OAuth (scope drive.readonly) của tài khoản công ty. Google Docs → export
    text/plain; tệp PDF/DOCX → tải gốc. Phiên bản = modifiedTime. (Làm mới token OAuth: cần app OAuth của anh — xem báo cáo.)"""
    kind = "gdrive"
    API = "https://www.googleapis.com/drive/v3"

    def _get(self, s, path, **params):
        import httpx
        tok = unseal(s.credential_enc)
        r = httpx.get(self.API + path, params=params, headers={"Authorization": f"Bearer {tok}"}, timeout=30)
        if r.status_code in (401, 403):
            raise SourceError(f"Google Drive từ chối token (HTTP {r.status_code}) — kết nối lại tài khoản")
        if r.status_code >= 400:
            raise SourceError(f"Google Drive HTTP {r.status_code}: {r.text[:200]}")
        return r

    def items(self, s):
        folder = (s.config or {}).get("folder_id") or ""
        if not folder:
            raise SourceError("Thiếu config.folder_id (id thư mục Drive)")
        q = f"'{folder}' in parents and trashed = false"
        r = self._get(s, "/files", q=q, fields="files(id,name,mimeType,modifiedTime)", pageSize=100)
        return [{"id": f["id"], "title": f["name"], "version": f.get("modifiedTime", ""), "mime": f.get("mimeType", "")}
                for f in r.json().get("files", [])]

    def fetch(self, s, item):
        mime = item.get("mime", "")
        if mime == "application/vnd.google-apps.document":
            return "", None, self._get(s, f"/files/{item['id']}/export", mimeType="text/plain").text
        if mime == "application/vnd.google-apps.spreadsheet":
            return "", None, self._get(s, f"/files/{item['id']}/export", mimeType="text/csv").text
        data = self._get(s, f"/files/{item['id']}", alt="media").content
        return item["title"], data, ""


class NotionConnector(Connector):
    """Notion API (integration token, trang đã chia sẻ cho integration). Trang → Markdown theo khối; phiên bản =
    last_edited_time."""
    kind = "notion"
    API = "https://api.notion.com/v1"

    def _get(self, s, path, **params):
        import httpx
        r = httpx.get(self.API + path, params=params, timeout=30,
                      headers={"Authorization": f"Bearer {unseal(s.credential_enc)}", "Notion-Version": "2022-06-28"})
        if r.status_code in (401, 403, 404):
            raise SourceError(f"Notion từ chối (HTTP {r.status_code}) — kiểm tra token và đã chia sẻ trang cho integration")
        if r.status_code >= 400:
            raise SourceError(f"Notion HTTP {r.status_code}: {r.text[:200]}")
        return r.json()

    def items(self, s):
        out = []
        for pid in (s.config or {}).get("page_ids") or []:
            p = self._get(s, f"/pages/{pid}")
            title = ""
            for prop in (p.get("properties") or {}).values():
                if prop.get("type") == "title":
                    title = "".join(t.get("plain_text", "") for t in prop.get("title", []))
            out.append({"id": pid, "title": title or pid, "version": p.get("last_edited_time", "")})
        return out

    def fetch(self, s, item):
        lines, cursor = [], None
        for _ in range(20):
            params = {"page_size": 100, **({"start_cursor": cursor} if cursor else {})}
            res = self._get(s, f"/blocks/{item['id']}/children", **params)
            for b in res.get("results", []):
                t = b.get("type", "")
                rich = (b.get(t) or {}).get("rich_text") or []
                txt = "".join(x.get("plain_text", "") for x in rich)
                prefix = {"heading_1": "# ", "heading_2": "## ", "heading_3": "### ", "bulleted_list_item": "- ",
                          "numbered_list_item": "1. ", "to_do": "- [ ] ", "quote": "> "}.get(t, "")
                if txt:
                    lines.append(prefix + txt)
            if not res.get("has_more"):
                break
            cursor = res.get("next_cursor")
        return "", None, "\n\n".join(lines)


CONNECTORS: dict[str, Connector] = {"url": UrlConnector(), "gdrive": GoogleDriveConnector(), "notion": NotionConnector()}


def sync_source(db: Session, s: DocSource, *, principal=None, now: datetime | None = None) -> dict:
    """Một chu kỳ đồng bộ: mục mới → tài liệu nháp; mục đổi (phiên bản ngoài hoặc sha nội dung khác) → PHIÊN BẢN NHÁP mới
    của tài liệu đã liên kết (không bao giờ tự ban hành). Tài liệu đang có bản nháp/chờ duyệt → ghi bản ngoài mới vào
    bản nháp đó nếu còn nháp, không thì để lượt sau."""
    now = now or datetime.utcnow()
    if s.kind in ("gdrive", "notion") and not s.credential_enc:
        s.status = "needs_account"; db.add(s); db.commit()
        return {"source": s.id, "status": "needs_account", "created": 0, "updated": 0}
    conn = CONNECTORS[s.kind]
    created = updated = unchanged = 0
    errors: list[str] = []
    try:
        items = conn.items(s)
    except (SourceError, HTTPException) as exc:
        s.status, s.last_error, s.last_synced_at = "error", str(getattr(exc, "detail", exc))[:1000], now
        db.add(s); db.commit()
        return {"source": s.id, "status": "error", "error": s.last_error, "created": 0, "updated": 0}
    for it in items:
        row = db.query(DocSourceItem).filter(DocSourceItem.source_id == s.id, DocSourceItem.external_id == it["id"]).first()
        if row is not None and it.get("version") and row.external_version == it["version"]:
            unchanged += 1
            continue
        try:
            fname, data, text = conn.fetch(s, it)
        except (SourceError, HTTPException) as exc:
            errors.append(f"{it.get('title')}: {getattr(exc, 'detail', exc)}")
            continue
        if data is not None:
            ex = extract(fname or it["title"], data)
            text = ex["text"]
        sha = _text_hash(text or "")
        if row is not None and row.sha256 == sha:
            row.external_version, row.last_synced_at = it.get("version", ""), now
            db.add(row); unchanged += 1
            continue
        doc = db.get(KnowledgeDocument, row.document_id) if row is not None and row.document_id else None
        if doc is not None and doc.status not in ("archived", "disposed"):
            open_v = (db.query(DocumentVersion).filter(DocumentVersion.document_id == doc.id,
                                                      DocumentVersion.status.in_(lib.OPEN_VERSION)).first())
            note = f"Đồng bộ {s.kind}: {it.get('title')} ({it.get('version') or 'nội dung đổi'})"[:300]
            if open_v is None:
                lib.new_version(db, s.organization_id, principal, doc.id, {"content": text, "change_note": note})
            elif open_v.status == "draft":
                lib.edit_version(db, s.organization_id, principal, doc.id, open_v.id, {"content": text, "change_note": note})
            else:
                errors.append(f"{doc.doc_code}: đang chờ duyệt — bản ngoài mới sẽ vào lượt sau")
                continue
            updated += 1
        else:
            try:
                out = ingest(db, s.organization_id, principal, s.company_id, source=s.kind, title=it.get("title") or "",
                             text=text, source_ref=f"{s.kind}:{it['id']}", source_id=s.id,
                             default_type=s.default_doc_type)
                doc_id = out["document"]["id"]
            except HTTPException as exc:
                d = exc.detail if isinstance(exc.detail, dict) else {}
                if d.get("error") == "duplicate":
                    doc_id = d.get("document_id")
                else:
                    errors.append(f"{it.get('title')}: {d.get('message') or exc.detail}")
                    continue
            if row is None:
                row = DocSourceItem(source_id=s.id, external_id=it["id"][:300])
            row.document_id = doc_id
            created += 1
        if row is None:
            row = DocSourceItem(source_id=s.id, external_id=it["id"][:300], document_id=doc.id if doc else None)
        row.title, row.external_version, row.sha256, row.last_synced_at = (it.get("title") or "")[:300], it.get("version", ""), sha, now
        db.add(row); db.commit()
    s.status = "error" if errors and not (created or updated or unchanged) else "active"
    s.last_error, s.last_synced_at = "\n".join(errors)[:1000], now
    db.add(s); db.commit()
    return {"source": s.id, "status": s.status, "created": created, "updated": updated, "unchanged": unchanged,
            "errors": errors}


def sync_due(db: Session, now: datetime | None = None) -> dict:
    """Beat (trong ``docs.tick`` mỗi giờ): đồng bộ nguồn tới hạn. Không có người gọi → tác giả phiên bản là hệ thống."""
    now = now or datetime.utcnow()
    out = []
    for s in db.query(DocSource).filter(DocSource.status.in_(("active", "error"))).all():
        if s.last_synced_at and s.last_synced_at + timedelta(minutes=max(60, s.interval_minutes or 60)) > now:
            continue
        out.append(sync_source(db, s, now=now))
    return {"synced": out}
