"""M5b việc 9 — kho tri thức hợp nhất: nạp (văn bản / tệp / URL) → cắt đoạn → chỉ mục → tra có trích dẫn.

* Một tài liệu = ``KnowledgeDocument`` (phạm vi: toàn tổ chức, công ty, phòng, dự án hoặc riêng một agent).
  Trùng nội dung (``content_hash``) trong cùng tổ chức + phạm vi → trả lại tài liệu cũ, không nạp lại.
* Cắt đoạn theo đoạn văn (~1.000 ký tự, chồng 150) để trích dẫn trỏ đúng chỗ.
* Tra cứu: điểm lai = độ phủ từ khoá (chính xác với tiếng Việt có dấu) + cosine vector băm 384 chiều sẵn có.
  Agent chỉ thấy tài liệu thuộc phạm vi của mình. Không tìm thấy gì đủ tốt → ghi "lỗ hổng kiến thức".
* Tài liệu từ URL đồng bộ lại được; nội dung đổi → các khoá học dùng tài liệu đó chuyển agent sang "cần ôn".
"""
from __future__ import annotations

import hashlib
import io
import re
import json
from datetime import datetime
from html.parser import HTMLParser

from fastapi import HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models import (Agent, Department, KnowledgeChunk, KnowledgeDocument, KnowledgeVector, Member, Project, Task)
from app.models.learning import Course, CourseEnrollment, KnowledgeGap
from app.services.vector_search import TOKEN_RE, cosine, hash384_embedding, index_chunk_vector

CHUNK = 1000
OVERLAP = 150
MAX_CHARS = 400_000
MAX_FETCH = 3_000_000
GAP_THRESHOLD = 0.34      # điểm tốt nhất dưới mức này = coi như không có tài liệu trả lời được
STOP = {"và", "là", "của", "có", "cho", "các", "những", "một", "được", "không", "với", "trong", "khi", "thì",
        "này", "đó", "the", "a", "an", "of", "to", "is", "in", "and", "or", "for", "gì", "nào", "sao", "bao"}


# ------------------------------------------------------------------ đọc tệp / URL

class _Html(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "nav", "footer", "header", "form"}
    BLOCK = {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "section", "article", "pre", "td"}

    def __init__(self):
        super().__init__()
        self.out, self.skip, self.title, self._t = [], 0, "", False

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
        if tag == "title":
            self._t = True
        if tag in self.BLOCK:
            self.out.append("\n")
        if tag in ("h1", "h2", "h3") and not self.skip:
            self.out.append("## ")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.skip:
            self.skip -= 1
        if tag == "title":
            self._t = False
        if tag in self.BLOCK:
            self.out.append("\n")

    def handle_data(self, data):
        if self._t:
            self.title += data
        elif not self.skip:
            self.out.append(data)


def html_to_text(html: str) -> tuple[str, str]:
    p = _Html()
    p.feed(html)
    text = re.sub(r"[ \t\r\f\v]+", " ", "".join(p.out))
    text = re.sub(r"\n\s*\n+", "\n\n", text).strip()
    return p.title.strip(), text


def extract_text(filename: str, data: bytes) -> str:
    name = (filename or "").lower()
    try:
        if name.endswith(".pdf"):
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(data))
            return "\n\n".join((pg.extract_text() or "").strip() for pg in reader.pages).strip()
        if name.endswith(".docx"):
            import docx
            d = docx.Document(io.BytesIO(data))
            parts = []
            for para in d.paragraphs:
                t = para.text.strip()
                if t:
                    parts.append(("## " + t) if (para.style is not None and str(para.style.name).lower().startswith("heading")) else t)
            for table in d.tables:
                for row in table.rows:
                    parts.append(" | ".join(c.text.strip() for c in row.cells))
            return "\n\n".join(parts)
        raw = data.decode("utf-8", errors="replace")
        if name.endswith((".html", ".htm")):
            return html_to_text(raw)[1]
        if name.endswith((".txt", ".md", ".markdown", ".csv", ".json", ".yaml", ".yml")) or "." not in name:
            return raw
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(422, f"Không đọc được tệp {filename}: {exc}") from exc
    raise HTTPException(422, "Chỉ nhận PDF, DOCX, Markdown, TXT, CSV, HTML")


def fetch_url(url: str) -> tuple[str, str]:
    import httpx
    if not re.match(r"^https?://", url or ""):
        raise HTTPException(422, "URL phải bắt đầu bằng http:// hoặc https://")
    try:
        with httpx.Client(follow_redirects=True, timeout=20, headers={"User-Agent": "ClawCompanyKB/1.0"}) as c:
            r = c.get(url)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"Không tải được URL: {exc}") from exc
    if r.status_code >= 400:
        raise HTTPException(502, f"URL trả lỗi HTTP {r.status_code}")
    if len(r.content) > MAX_FETCH:
        raise HTTPException(422, "Trang quá lớn (tối đa 3 MB)")
    ctype = r.headers.get("content-type", "")
    if "pdf" in ctype:
        return "", extract_text("x.pdf", r.content)
    if "html" in ctype or r.text.lstrip().startswith("<"):
        return html_to_text(r.text)
    return "", r.text


# ------------------------------------------------------------------ cắt đoạn + chỉ mục

def chunk_text(text: str, size: int = CHUNK, overlap: int = OVERLAP) -> list[str]:
    paras = [p.strip() for p in re.split(r"\n\s*\n", text or "") if p.strip()]
    out, cur = [], ""
    for p in paras:
        while len(p) > size:                       # đoạn quá dài → cắt cứng, giữ chồng lấn
            if cur:
                out.append(cur); cur = ""
            out.append(p[:size]); p = p[size - overlap:]
        if len(cur) + len(p) + 2 > size and cur:
            out.append(cur)
            tail = cur[-overlap:]
            cur = (tail + "\n\n" + p) if overlap else p
        else:
            cur = (cur + "\n\n" + p) if cur else p
    if cur:
        out.append(cur)
    return out


def _hash(text: str) -> str:
    return hashlib.sha256(re.sub(r"\s+", " ", text or "").strip().encode()).hexdigest()


def unaccent(text: str) -> str:
    """Bỏ dấu tiếng Việt (đ → d) để tra được cả khi gõ không dấu."""
    import unicodedata
    t = (text or "").replace("đ", "d").replace("Đ", "D")
    return "".join(c for c in unicodedata.normalize("NFD", t) if unicodedata.category(c) != "Mn")


HEAD_RE = re.compile(r"^(#{1,4})\s+(.+?)\s*#*\s*$")


def sections(text: str) -> list[tuple[str, int, str]]:
    """M3b: [(đường dẫn đề mục "A › B", số mục §n, thân)] theo đề mục Markdown. Phần trước đề mục đầu tiên = §0."""
    out, stack, body, no, path = [], [], [], 0, ""
    for line in (text or "").splitlines():
        m = HEAD_RE.match(line.strip())
        if m:
            if "\n".join(body).strip():
                out.append((path, no, "\n".join(body).strip()))
            level, title = len(m.group(1)), m.group(2).strip()
            stack = [x for x in stack if x[0] < level] + [(level, title)]
            no += 1
            path, body = " › ".join(t for _, t in stack), []
            continue
        body.append(line)
    if "\n".join(body).strip() or not out:
        out.append((path, no, "\n".join(body).strip()))
    return [x for x in out if x[2] or x[0]]


def context_header(doc: KnowledgeDocument, path: str) -> str:
    """Tiêu đề ngữ cảnh xác định cho mỗi đoạn (Contextual Retrieval, không tốn model): mã + phiên bản + tiêu đề › mục
    + loại + ngày hiệu lực. Đưa vào cả embedding lẫn chỉ mục từ khoá."""
    head = f"{doc.doc_code} v{doc.version_no} · " if getattr(doc, "doc_code", "") else ""
    eff = f" · hiệu lực {doc.effective_from:%d/%m/%Y}" if getattr(doc, "effective_from", None) else ""
    return f"[{head}{doc.title}{' › ' + path if path else ''}{eff}]"


def chunk_doc(doc: KnowledgeDocument) -> list[dict]:
    out = []
    for path, no, body in sections(doc.content or ""):
        hdr = context_header(doc, path)
        for part in chunk_text(body or path, size=max(300, CHUNK - len(hdr) - 1)):
            out.append({"section": path[:300], "section_no": no, "content": hdr + "\n" + part})
    return out


def reindex(db: Session, doc: KnowledgeDocument) -> int:
    old = [c.id for c in db.query(KnowledgeChunk.id).filter(KnowledgeChunk.document_id == doc.id).all()]
    if old:
        db.query(KnowledgeVector).filter(KnowledgeVector.chunk_id.in_(old)).delete(synchronize_session=False)
        db.query(KnowledgeChunk).filter(KnowledgeChunk.document_id == doc.id).delete(synchronize_session=False)
    parts = chunk_doc(doc)
    from app.services import embeddings
    real = embeddings.embed([p["content"] for p in parts])
    prov = embeddings.provider_name() if real else "hash384"
    for i, part in enumerate(parts):
        ch = KnowledgeChunk(document_id=doc.id, chunk_index=i, content=part["content"], embedding_provider=prov,
                            section=part["section"], section_no=part["section_no"],
                            search_text=unaccent(part["content"].lower()))
        db.add(ch); db.flush()
        if real:
            db.add(KnowledgeVector(chunk_id=ch.id, embedding_json=json.dumps(real[i])))
        else:
            index_chunk_vector(db, ch)
    doc.indexed = True
    db.add(doc); db.commit()
    return len(parts)


def _check_scope(db: Session, org_id: int, data: dict) -> dict:
    out = {"company_id": data.get("company_id"), "department_id": data.get("department_id"),
           "project_id": data.get("project_id"), "agent_id": data.get("agent_id"),
           "role_keyword": (data.get("role_keyword") or "").strip()[:120]}
    if out["department_id"]:
        d = db.get(Department, out["department_id"])
        if d is None:
            raise HTTPException(404, "Không thấy phòng ban")
        out["company_id"] = out["company_id"] or d.company_id
    if out["project_id"] and db.get(Project, out["project_id"]) is None:
        raise HTTPException(404, "Không thấy dự án")
    if out["agent_id"]:
        ag = db.get(Agent, out["agent_id"])
        m = db.get(Member, ag.member_id) if ag else None
        if m is None or m.organization_id != org_id:
            raise HTTPException(404, "Không thấy agent")
    return out


def ingest(db: Session, org_id: int, *, title: str, content: str, source_type: str = "text",
           source_url: str = "", scope: dict | None = None, is_core: bool = False) -> dict:
    content = (content or "").strip()
    if len(content) < 20:
        raise HTTPException(422, "Tài liệu trống hoặc quá ngắn (cần ít nhất 20 ký tự có chữ)")
    if len(content) > MAX_CHARS:
        content = content[:MAX_CHARS]
    sc = _check_scope(db, org_id, scope or {})
    h = _hash(content)
    q = db.query(KnowledgeDocument).filter(KnowledgeDocument.organization_id == org_id, KnowledgeDocument.content_hash == h)
    for k, v in sc.items():
        q = q.filter(getattr(KnowledgeDocument, k) == v) if v is not None else q.filter(getattr(KnowledgeDocument, k).is_(None))
    old = q.first()
    if old is not None:
        if is_core and not old.is_core:
            old.is_core = True; db.add(old); db.commit()
        return {**public(db, old), "duplicate": True}
    doc = KnowledgeDocument(organization_id=org_id, title=(title or "Tài liệu").strip()[:220], content=content,
                            source_type=source_type, source_url=source_url[:1000], content_hash=h,
                            synced_at=datetime.utcnow(), access_level="restricted", is_core=bool(is_core), **sc)
    db.add(doc); db.commit(); db.refresh(doc)
    from app.services import doc_library     # M3a: phiên bản 1 đã ban hành + mã tài liệu (trước khi cắt đoạn: tiêu đề ngữ cảnh mang mã)
    doc_library.init_legacy(db, doc)
    reindex(db, doc)
    return {**public(db, doc), "duplicate": False}


def resync(db: Session, org_id: int, doc_id: int) -> dict:
    doc = get(db, org_id, doc_id)
    if not doc.source_url:
        raise HTTPException(409, "Tài liệu này không có nguồn URL để đồng bộ lại")
    title, text = fetch_url(doc.source_url)
    h = _hash(text)
    doc.synced_at = datetime.utcnow()
    if h == doc.content_hash:
        db.add(doc); db.commit()
        return {**public(db, doc), "changed": False, "stale_enrollments": 0}
    doc.content, doc.content_hash = text[:MAX_CHARS], h
    reindex(db, doc)
    from app.services import doc_library     # M3a: nguồn ngoài đổi → phiên bản mới (bản cũ superseded)
    doc_library.legacy_new_content(db, doc)
    stale = mark_courses_stale(db, doc)
    return {**public(db, doc), "changed": True, "stale_enrollments": stale}


def mark_courses_stale(db: Session, doc: KnowledgeDocument) -> int:
    n = 0
    for c in db.query(Course).filter(Course.organization_id == doc.organization_id).all():
        ids = list(c.document_ids or [])
        if doc.id not in ids:
            continue
        idx = ids.index(doc.id)
        for e in db.query(CourseEnrollment).filter(CourseEnrollment.course_id == c.id).all():
            if e.status in ("passed", "failed", "exam") or e.module_index > idx:
                e.status, e.module_index = "stale", idx
                e.note = f"Tài liệu \"{doc.title}\" vừa thay đổi — cần ôn lại từ module {idx + 1}"
                db.add(e); n += 1
    db.commit()
    return n


def get(db: Session, org_id: int, doc_id: int) -> KnowledgeDocument:
    doc = db.get(KnowledgeDocument, doc_id)
    if doc is None or doc.organization_id != org_id:
        raise HTTPException(404, "Không thấy tài liệu")
    return doc


def delete(db: Session, org_id: int, doc_id: int) -> dict:
    doc = get(db, org_id, doc_id)
    from app.services import doc_requirements     # M3d: hồ sơ / còn hạn lưu / giữ pháp lý → 409
    doc_requirements.can_delete(doc)
    old = [c.id for c in db.query(KnowledgeChunk.id).filter(KnowledgeChunk.document_id == doc.id).all()]
    if old:
        db.query(KnowledgeVector).filter(KnowledgeVector.chunk_id.in_(old)).delete(synchronize_session=False)
    db.query(KnowledgeChunk).filter(KnowledgeChunk.document_id == doc.id).delete(synchronize_session=False)
    db.query(KnowledgeGap).filter(KnowledgeGap.resolved_document_id == doc.id).update({KnowledgeGap.resolved_document_id: None})
    from app.models.documents import CompanyFact, DocumentFlag, DocumentLink, DocumentVersion
    for m in (DocumentVersion, DocumentLink, DocumentFlag):
        db.query(m).filter(m.document_id == doc.id).delete(synchronize_session=False)
    db.query(CompanyFact).filter(CompanyFact.source_doc_id == doc.id).delete(synchronize_session=False)
    db.delete(doc); db.commit()
    return {"deleted": doc_id}


def scope_label(db: Session, doc: KnowledgeDocument) -> str:
    if doc.role_keyword and not doc.agent_id:
        return f"Nghề: {doc.role_keyword}"
    if doc.agent_id:
        ag = db.get(Agent, doc.agent_id); m = db.get(Member, ag.member_id) if ag else None
        return f"Riêng {m.name}" if m else "Riêng một agent"
    if doc.project_id:
        p = db.get(Project, doc.project_id); return f"Dự án {p.name}" if p else "Dự án"
    if doc.department_id:
        d = db.get(Department, doc.department_id); return f"Phòng {d.name}" if d else "Phòng ban"
    if doc.company_id:
        return "Công ty"
    return "Toàn tổ chức"


def public(db: Session, doc: KnowledgeDocument) -> dict:
    n = db.query(KnowledgeChunk).filter(KnowledgeChunk.document_id == doc.id).count()
    return {"id": doc.id, "title": doc.title, "source_type": doc.source_type, "source_url": doc.source_url or "",
            "chars": len(doc.content or ""), "chunks": n, "scope": scope_label(db, doc),
            "company_id": doc.company_id, "department_id": doc.department_id, "project_id": doc.project_id,
            "agent_id": doc.agent_id, "is_core": bool(doc.is_core), "role_keyword": doc.role_keyword or "",
            "layer": layer_of(doc), "doc_code": doc.doc_code or "", "status": doc.status, "version_no": doc.version_no,
            "doc_type": doc.doc_type, "synced_at": doc.synced_at.isoformat() if doc.synced_at else None,
            "created_at": doc.created_at.isoformat() if getattr(doc, "created_at", None) else None}


def list_docs(db: Session, org_id: int, company_id: int | None = None) -> list[dict]:
    from app.core import company_scope
    q = db.query(KnowledgeDocument).filter(KnowledgeDocument.organization_id == org_id)
    q = company_scope.scope_filter(q, KnowledgeDocument.company_id, company_id)   # R1: theo công ty
    rows = q.order_by(KnowledgeDocument.id.desc()).limit(300).all()
    return [public(db, d) for d in rows]


# ------------------------------------------------------------------ tra cứu có trích dẫn

STOP_U = {unaccent(w) for w in STOP}
AGENT_SENS_MAX = 1          # agent đọc tới mức "internal" (public=0, internal=1); mật / dữ liệu cá nhân không bao giờ
RRF_K = 60
# M3b: từ lóng / tiếng Anh hay gặp trong chat bán hàng VN → cụm tương đương (không dấu). Một nhóm từ khoá "khớp" khi
# chính từ đó hoặc MỌI chữ của một cụm tương đương có trong đoạn. Danh sách chung cho thương mại điện tử, không theo
# một bộ eval; tắt được bằng expand=False (bộ eval báo cả hai con số).
SYNONYMS = {
    "freeship": ("mien phi van chuyen", "mien phi giao hang", "mien phi ship"),
    "ship": ("van chuyen", "giao hang"), "shipper": ("giao hang", "van chuyen"),
    "sale": ("giam gia", "khuyen mai"), "voucher": ("ma giam gia", "phieu qua"),
    "cod": ("thanh toan khi nhan hang",), "ck": ("chuyen khoan",),
    "refund": ("hoan tien",), "return": ("doi tra",), "bh": ("bao hanh",), "warranty": ("bao hanh",),
    "microwave": ("lo vi song",), "hotline": ("so dien thoai",), "sdt": ("so dien thoai", "hotline"),
    "shop": ("cua hang", "tiem"), "size": ("kich thuoc",), "order": ("don hang",), "invoice": ("hoa don",),
}


def _tokens(text: str) -> list[str]:
    """Token không dấu (khớp cả "doi tra" với "đổi trả"), bỏ từ dừng."""
    return [t for t in TOKEN_RE.findall(unaccent((text or "").lower())) if len(t) > 1 and t not in STOP_U]


def live_filter(q, now: datetime | None = None):
    """M3a: chỉ bản ĐÃ BAN HÀNH và đang trong hiệu lực (nháp / chờ duyệt / lưu trữ / hết hạn không bao giờ tới agent)."""
    now = now or datetime.utcnow()
    return (q.filter(KnowledgeDocument.status == "published")
            .filter(or_(KnowledgeDocument.effective_from.is_(None), KnowledgeDocument.effective_from <= now))
            .filter(or_(KnowledgeDocument.effective_to.is_(None), KnowledgeDocument.effective_to > now)))


def audience_ok(doc: KnowledgeDocument, member: Member | None) -> bool:
    """M3b: đối tượng (phòng / chức danh / ghế) — rỗng = cả công ty. Người (member None) thấy hết."""
    a = doc.audience or {}
    if member is None or not any(a.get(k) for k in ("department_ids", "position_ids", "seat_ids")):
        return True
    return (member.department_id in (a.get("department_ids") or []) or getattr(member, "position_id", None) in (a.get("position_ids") or [])
            or member.id in (a.get("seat_ids") or []))


def agent_ok(doc: KnowledgeDocument, member: Member | None, uses: tuple[str, ...] = ("core", "retrieve")) -> bool:
    """M3b — lọc quyền TRƯỚC khi chấm điểm (security trimming): cách dùng, nhạy cảm, đối tượng, lớp nghề."""
    if member is None:
        return True
    from app.services.doc_library import SENS_RANK
    return ((doc.agent_use or "retrieve") in uses and SENS_RANK.get(doc.sensitivity or "internal", 1) <= AGENT_SENS_MAX
            and audience_ok(doc, member) and role_ok(doc, member))


def visible_docs_query(db: Session, org_id: int, member: Member | None, agent: Agent | None):
    q = live_filter(db.query(KnowledgeDocument).filter(KnowledgeDocument.organization_id == org_id))
    if member is None:      # người: thấy cả tổ chức (đã qua quyền API)
        return q
    from app.services import seat_leases   # R2: ghế thuê thấy thêm ĐÚNG các tài liệu bên cho thuê cấp
    ls = seat_leases.lease_of_member(db, member.id, live_only=True)
    scope = seat_leases.scope_doc_ids(ls) if ls is not None and ls.status == "active" else []
    proj_ids = [r[0] for r in db.query(Task.project_id).filter(Task.assignee_member_id == member.id).distinct().all() if r[0]]
    q = q.filter(or_(KnowledgeDocument.company_id.is_(None), KnowledgeDocument.company_id == member.company_id))
    q = q.filter(or_(KnowledgeDocument.department_id.is_(None), KnowledgeDocument.department_id == member.department_id))
    q = q.filter(or_(KnowledgeDocument.project_id.is_(None), KnowledgeDocument.project_id.in_(proj_ids or [-1])))
    q = q.filter(or_(KnowledgeDocument.agent_id.is_(None), KnowledgeDocument.agent_id == (agent.id if agent else -1)))
    if scope:
        own = [r[0] for r in q.with_entities(KnowledgeDocument.id).all()]
        return live_filter(db.query(KnowledgeDocument).filter(KnowledgeDocument.id.in_(own + scope)))
    return q


def cite_of(d: KnowledgeDocument, ch: KnowledgeChunk) -> str:
    if d.doc_code:
        return f"[DOC:{d.doc_code} v{d.version_no} §{ch.section_no}]"
    return f"[KB#{d.id}§{ch.chunk_index + 1}: {d.title}]"


def _pg_lexical(db: Session, doc_ids: list[int], qt: set[str]) -> dict[int, float]:
    """Postgres: FTS (to_tsvector 'simple' trên chữ không dấu, GIN) — hạng từ khoá kiểu BM25 của Postgres (ts_rank_cd)."""
    from sqlalchemy import bindparam, text
    terms = [re.sub(r"[^0-9a-z]", "", t) for t in qt]
    terms = [t for t in terms if t]
    if not terms or not doc_ids:
        return {}
    sql = text("SELECT id, ts_rank_cd(to_tsvector('simple', search_text), to_tsquery('simple', :q)) AS r FROM knowledge_chunks "
               "WHERE document_id IN :ids AND to_tsvector('simple', search_text) @@ to_tsquery('simple', :q) "
               "ORDER BY r DESC LIMIT 200").bindparams(bindparam("ids", expanding=True))
    try:
        return {int(i): float(r) for i, r in db.execute(sql, {"q": " | ".join(terms), "ids": doc_ids}).all()}
    except Exception as exc:  # noqa: BLE001 — FTS lỗi thì vẫn còn đường Python
        db.rollback()
        print(f"[kb] fts {exc}")
        return {}


def _pg_vector(db: Session, doc_ids: list[int], query: str) -> dict[int, float]:
    """Postgres + pgvector (cột knowledge_vectors.embedding vector(384), vector băm): cosine trong DB."""
    from sqlalchemy import bindparam, text
    v = "[" + ",".join(f"{x:.8f}" for x in hash384_embedding(query)) + "]"
    sql = text("SELECT kv.chunk_id, 1 - (kv.embedding <=> CAST(:v AS vector)) AS s FROM knowledge_vectors kv "
               "JOIN knowledge_chunks c ON c.id = kv.chunk_id WHERE c.document_id IN :ids AND kv.embedding IS NOT NULL "
               "ORDER BY kv.embedding <=> CAST(:v AS vector) LIMIT 200").bindparams(bindparam("ids", expanding=True))
    try:
        return {int(i): float(sv) for i, sv in db.execute(sql, {"v": v, "ids": doc_ids}).all()}
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        print(f"[kb] pgvector {exc}")
        return {}


def search(db: Session, org_id: int, query: str, *, member: Member | None = None, agent: Agent | None = None,
           limit: int = 6, log_gap: bool = True, task_id: int | None = None, track: bool = True,
           expand: bool = True) -> dict:
    """M3b: lọc quyền trước (công ty/phòng/dự án/agent/thuê + trạng thái/hiệu lực + cách dùng/nhạy cảm/đối tượng) → điểm
    lai từ khoá không dấu + vector → xếp hạng hợp nhất RRF (Postgres: FTS + pgvector). Điểm tuyệt đối (0..1) vẫn quyết
    "tìm thấy" / ghi lỗ hổng như trước."""
    import json as _json
    from app.services import doc_library
    query = (query or "").strip()
    qt = set(_tokens(query))
    groups = [(t, [f" {a} " for a in (SYNONYMS.get(t, ()) if expand else ())]) for t in qt]
    lex_terms = set(qt) | {w for _t, alts in groups for a in alts for w in a.split()}
    docs = {d.id: d for d in visible_docs_query(db, org_id, member, agent).all() if agent_ok(d, member)}
    hits = []
    if qt and docs:
        from app.services import embeddings
        qemb = hash384_embedding(query)
        prov = embeddings.provider_name()
        real_q = (embeddings.embed([query]) or [None])[0] if prov != "hash384" else None
        rows = (db.query(KnowledgeChunk, KnowledgeVector)
                .outerjoin(KnowledgeVector, KnowledgeVector.chunk_id == KnowledgeChunk.id)
                .filter(KnowledgeChunk.document_id.in_(list(docs))).limit(20000).all())
        pg = db.get_bind().dialect.name == "postgresql"
        fts = _pg_lexical(db, list(docs), lex_terms) if pg else {}
        pvec = _pg_vector(db, list(docs), query) if pg and real_q is None else {}
        cand = []
        # IDF theo nhóm từ khoá trên các đoạn được phép (kiểu BM25): từ hiếm ("freeship") nặng hơn từ phổ biến ("đơn")
        toks = {ch.id: set(_tokens(ch.search_text or ch.content)) for ch, _kv in rows}
        flat = {ch.id: " " + " ".join(re.findall(r"[0-9a-z]+", ch.search_text or unaccent((ch.content or "").lower()))) + " "
                for ch, _kv in rows}
        cur: dict = {}
        hit = lambda t, alts, ct: t in ct or any(a in cur["flat"] for a in alts)  # noqa: E731 — cụm phải liền nhau
        import math
        nchunks = max(1, len(toks))
        df = [0] * len(groups)
        for cid, ct in toks.items():
            cur["flat"] = flat[cid]
            for i, (t, alts) in enumerate(groups):
                df[i] += hit(t, alts, ct)
        idf = [math.log(1 + nchunks / (1 + n)) for n in df]
        idf_sum = sum(idf) or 1.0
        for ch, kv in rows:
            ct = toks[ch.id]
            cur["flat"] = flat[ch.id]
            cover = sum(w for (t, alts), w in zip(groups, idf) if hit(t, alts, ct)) / idf_sum
            title_bonus = 0.1 if qt & set(_tokens(docs[ch.document_id].title)) else 0.0
            try:
                emb = _json.loads(kv.embedding_json) if kv else []
            except Exception:  # noqa: BLE001
                emb = []
            if real_q is not None and ch.embedding_provider == prov and emb:
                sem = embeddings.semantic(cosine(real_q, emb))
                s = 0.45 * cover + 0.55 * sem + title_bonus
                if cover > 0 or sem >= 0.35:
                    cand.append({"ch": ch, "s": s, "lex": fts.get(ch.id, cover), "vec": sem})
                continue
            if ch.id in pvec:
                vec = max(0.0, pvec[ch.id])
            else:
                if ch.embedding_provider != "hash384" or not emb:
                    emb = hash384_embedding(ch.search_text or ch.content)
                vec = max(0.0, cosine(qemb, emb))
            s = 0.7 * cover + 0.3 * vec + title_bonus
            if cover > 0:
                cand.append({"ch": ch, "s": s, "lex": fts.get(ch.id, 0.0) + cover, "vec": vec})
        # RRF: hạng từ khoá + hạng vector (k=60), hoà → điểm tuyệt đối
        for key in ("lex", "vec"):
            for rank, c in enumerate(sorted(cand, key=lambda c: -c[key])):
                c["rrf"] = c.get("rrf", 0.0) + 1.0 / (RRF_K + rank + 1)
        cand.sort(key=lambda c: (-c["rrf"], -c["s"]))
        seen_docs: set[int] = set()
        for c in cand[:limit]:
            ch = c["ch"]; d = docs[ch.document_id]
            stale = doc_library.review_state(d) == "stale"
            hits.append({"chunk_id": ch.id, "document_id": d.id, "doc_code": d.doc_code or "", "version_no": d.version_no,
                         "title": d.title, "chunk": ch.chunk_index, "section": ch.section or "", "section_no": ch.section_no,
                         "score": round(c["s"], 3), "source_url": d.source_url or "", "scope": scope_label(db, d),
                         "cite": cite_of(d, ch), "stale": stale, "content": ch.content,
                         **({"note": "Tài liệu đang quá hạn rà soát — nói rõ với người hỏi là theo tài liệu (đang chờ rà soát)"} if stale else {})})
            seen_docs.add(d.id)
        if member is not None and seen_docs and track:
            now = datetime.utcnow()
            for did in seen_docs:
                d = docs[did]; d.reuse_count = (d.reuse_count or 0) + 1; d.last_used_at = now; db.add(d)
            db.commit()
    best = max((h["score"] for h in hits), default=0.0)
    gap = None
    if log_gap and member is not None and query and best < GAP_THRESHOLD:
        gap = record_gap(db, org_id, member.id, query, source="search", task_id=task_id)
    return {"query": query, "hits": hits, "best_score": best, "found": best >= GAP_THRESHOLD,
            "gap_id": gap.id if gap else None}


# ------------------------------------------------------------------ lỗ hổng kiến thức

def record_gap(db: Session, org_id: int, member_id: int | None, question: str, *, source: str,
               task_id: int | None = None) -> KnowledgeGap:
    key = hashlib.sha256(" ".join(sorted(set(_tokens(question)))).encode()).hexdigest()[:32]
    g = (db.query(KnowledgeGap).filter(KnowledgeGap.organization_id == org_id, KnowledgeGap.question_key == key,
                                       KnowledgeGap.status == "open").first())
    if g is not None:
        g.count += 1; g.updated_at = datetime.utcnow()
    else:
        g = KnowledgeGap(organization_id=org_id, member_id=member_id, question=question[:2000], question_key=key,
                         source=source, task_id=task_id)
    db.add(g); db.commit(); db.refresh(g)
    return g


def list_gaps(db: Session, org_id: int, status: str = "open") -> list[dict]:
    q = db.query(KnowledgeGap).filter(KnowledgeGap.organization_id == org_id)
    if status != "all":
        q = q.filter(KnowledgeGap.status == status)
    names = {m.id: m.name for m in db.query(Member).filter(Member.organization_id == org_id).all()}
    out = []
    for g in q.order_by(KnowledgeGap.count.desc(), KnowledgeGap.updated_at.desc()).limit(200).all():
        out.append({"id": g.id, "question": g.question, "who": names.get(g.member_id), "source": g.source,
                    "source_vi": {"search": "Tra không ra", "report": "Agent báo thiếu", "exam": "Sai khi thi"}.get(g.source, g.source),
                    "count": g.count, "status": g.status, "task_id": g.task_id,
                    "resolved_document_id": g.resolved_document_id,
                    "updated_at": g.updated_at.isoformat() if g.updated_at else None})
    return out


def resolve_gap(db: Session, org_id: int, gap_id: int, *, document_id: int | None, dismiss: bool = False) -> dict:
    g = db.get(KnowledgeGap, gap_id)
    if g is None or g.organization_id != org_id:
        raise HTTPException(404, "Không thấy lỗ hổng này")
    if document_id:
        get(db, org_id, document_id)
    g.status = "dismissed" if dismiss else "resolved"
    g.resolved_document_id = document_id
    g.resolved_at = datetime.utcnow()
    db.add(g); db.commit()
    return {"id": g.id, "status": g.status}


# ------------------------------------------------------------------ kiến thức cốt lõi 3 lớp → AGENTS.md
# Đo trên VM (eval CSKH 15/10/2026): agent KHÔNG tự gọi company_knowledge_search khi khách hỏi chính sách,
# kể cả khi AGENTS.md dặn — chỉ tra khi được nhắc "dựa theo tài liệu". Nên phần cốt lõi phải nằm sẵn trong
# ngữ cảnh (bài học FastClaw: kho nhỏ thì nhúng thẳng). Ba lớp: riêng agent / nghề (chức danh) / công ty.

CORE_BUDGET = 12_000
LAYER_BUDGET = {"personal": 3_000, "profession": 4_500, "company": 4_500}
LAYER_VI = {"personal": "Riêng bạn", "profession": "Nghề nghiệp", "company": "Công ty"}


def layer_of(doc: KnowledgeDocument) -> str:
    if doc.agent_id:
        return "personal"
    if doc.role_keyword:
        return "profession"
    return "company"


def role_ok(doc: KnowledgeDocument, member: Member | None) -> bool:
    kw = (doc.role_keyword or "").strip().lower()
    return not kw or member is None or kw in (member.role or "").lower()


def core_docs(db: Session, org_id: int, *, company_id: int | None, department_id: int | None, role: str,
              agent_id: int | None, member: Member | None = None) -> list[KnowledgeDocument]:
    q = (live_filter(db.query(KnowledgeDocument)).filter(KnowledgeDocument.organization_id == org_id,
                                                         KnowledgeDocument.is_core.is_(True), KnowledgeDocument.project_id.is_(None))
         .filter(or_(KnowledgeDocument.company_id.is_(None), KnowledgeDocument.company_id == company_id))
         .filter(or_(KnowledgeDocument.department_id.is_(None), KnowledgeDocument.department_id == department_id))
         .filter(or_(KnowledgeDocument.agent_id.is_(None), KnowledgeDocument.agent_id == (agent_id or -1))))
    r = (role or "").lower()
    out = [d for d in q.order_by(KnowledgeDocument.id).all() if not d.role_keyword or d.role_keyword.lower() in r]
    if member is not None:   # M3b: đối tượng chức danh/phòng/ghế + nhạy cảm (tài liệu mật không vào AGENTS.md)
        out = [d for d in out if agent_ok(d, member, ("core",))]
    return out


CORE_FULL_MAX = 1_200      # tài liệu cốt lõi ngắn hơn mức này vào nguyên văn; dài hơn → bản tóm tắt
SUMMARY_MAX = 600


def auto_summary(text: str, limit: int = SUMMARY_MAX) -> str:
    """Tóm tắt xác định (không model): mỗi mục một dòng "Đề mục: câu đầu". Không cắt giữa câu — dòng không vừa thì bỏ."""
    lines = []
    for path, _no, body in sections(text):
        first = re.split(r"(?<=[.!?…])\s+|\n", (body or "").strip(), maxsplit=1)[0].strip()
        line = f"- {path}: {first}" if path and first else f"- {first or path}"
        if len("\n".join(lines + [line])) > limit:
            break
        lines.append(line)
    return "\n".join(lines)


def core_body(d: KnowledgeDocument) -> tuple[str, bool]:
    """(phần đưa vào AGENTS.md, có phải tóm tắt không)."""
    body = re.sub(r"\n{3,}", "\n\n", (d.content or "").strip())
    if (d.core_summary or "").strip():
        return d.core_summary.strip()[:SUMMARY_MAX * 2], True
    if len(body) <= CORE_FULL_MAX:
        return body, False
    return auto_summary(body), True


def core_section(db: Session, org_id: int, *, company_id: int | None, department_id: int | None, role: str,
                 agent_id: int | None, member: Member | None = None) -> str:
    docs = core_docs(db, org_id, company_id=company_id, department_id=department_id, role=role, agent_id=agent_id, member=member)
    # M2b: hiến chương công ty đứng đầu phần cốt lõi (không bị cắt bởi CORE_BUDGET ở cuối).
    from app.services.company_foundation import charter_block
    charter = charter_block(db, company_id)
    if not docs and not charter:
        return ""
    parts = ["## Kiến thức cốt lõi (luôn áp dụng khi trả lời; chi tiết khác: company_knowledge_search)"]
    if charter:
        parts.append(charter)
    used = len("\n\n".join(parts))
    for layer in ("personal", "profession", "company"):
        mine = [d for d in docs if layer_of(d) == layer]
        if not mine:
            continue
        left = LAYER_BUDGET[layer]
        head = LAYER_VI[layer] + (f" — {role}" if layer == "profession" and role else "")
        parts.append(f"### {head}")
        for d in mine:
            ref = f"company_doc_get doc_code={d.doc_code}" if d.doc_code else f"company_knowledge_get document_id={d.id}"
            tag = f" [{d.doc_code} v{d.version_no}]" if d.doc_code else ""
            body, summarized = core_body(d)
            block = f"#### {d.title}{tag}\n{body}" + (f"\n(Tóm tắt — nguyên văn: {ref})" if summarized else "")
            # M3b: không cắt cụt giữa chừng — không vừa ngân sách thì chỉ còn một dòng trỏ tới tài liệu
            if len(block) > left or used + len(block) + 2 > CORE_BUDGET:
                block = f"- {d.title}{tag}: đọc bằng {ref}"
            parts.append(block)
            left -= len(block); used += len(block) + 2
    return "\n\n".join(parts)[:CORE_BUDGET]


def core_for_member(db: Session, member: Member, agent: Agent | None) -> str:
    core = core_section(db, member.organization_id, company_id=member.company_id, department_id=member.department_id,
                        role=member.role or "", agent_id=agent.id if agent else None, member=member)
    from app.services import seat_leases   # R2: ghế thuê → sàn bên cho thuê đứng trước lớp bên thuê
    return seat_leases.layered_core(db, member, core)


def update_doc(db: Session, org_id: int, doc_id: int, data: dict) -> tuple[dict, bool]:
    """Sửa tiêu đề / cờ cốt lõi / lớp nghề. Trả (tài liệu, có ảnh hưởng tới phần cốt lõi không)."""
    doc = get(db, org_id, doc_id)
    before = (doc.is_core, doc.role_keyword or "", doc.title)
    if data.get("title"):
        doc.title = data["title"].strip()[:220]
    if data.get("is_core") is not None:
        doc.is_core = bool(data["is_core"])
        if doc.is_core:
            doc.agent_use = "core"
        elif doc.agent_use == "core":
            doc.agent_use = "retrieve"
    if data.get("role_keyword") is not None:
        doc.role_keyword = data["role_keyword"].strip()[:120]
    db.add(doc); db.commit()
    after = (doc.is_core, doc.role_keyword or "", doc.title)
    return public(db, doc), (before != after and (before[0] or after[0]))


def core_preview(db: Session, org_id: int, agent_id: int) -> dict:
    from app.services import agent_hr
    ag, m = agent_hr.seat(db, org_id, agent_id)
    text = core_for_member(db, m, ag)
    docs = core_docs(db, org_id, company_id=m.company_id, department_id=m.department_id, role=m.role or "", agent_id=ag.id)
    return {"agent_id": ag.id, "chars": len(text), "budget": CORE_BUDGET, "text": text,
            "documents": [{"id": d.id, "title": d.title, "layer": layer_of(d), "layer_vi": LAYER_VI[layer_of(d)]} for d in docs]}


async def sync_core(db: Session, principal, org_id: int, runtime) -> dict:
    """Sinh lại AGENTS.md cho mọi seat đang làm (kèm phần cốt lõi mới)."""
    from app.services import agent_hr
    seats = (db.query(Agent, Member).join(Member, Member.id == Agent.member_id)
             .filter(Member.organization_id == org_id, Agent.lifecycle.notin_(("retired", "runtime_missing"))).all())
    rows = []
    for ag, m in seats:
        try:
            out = await agent_hr.update_hr(db, principal, org_id, runtime, ag.id, {"regenerate_files": ["AGENTS.md"]}, set())
            w = ((out.get("files") or {}).get("AGENTS.md") or {})
            rows.append({"agent_id": ag.id, "name": m.name, "written": bool(w.get("written")), "note": w.get("reason") or ""})
        except Exception as exc:  # noqa: BLE001
            rows.append({"agent_id": ag.id, "name": m.name, "written": False, "note": str(getattr(exc, "detail", exc))[:200]})
    return {"seats": rows, "written": sum(r["written"] for r in rows)}



def reembed_all(db: Session, org_id: int) -> dict:
    """Chỉ mục lại mọi tài liệu chưa dùng embedding hiện hành (sau khi bật embedding thật hoặc đổi model)."""
    from app.services import embeddings
    prov = embeddings.provider_name()
    docs = db.query(KnowledgeDocument).filter(KnowledgeDocument.organization_id == org_id).all()
    done = skipped = 0
    for d in docs:
        provs = {p for (p,) in db.query(KnowledgeChunk.embedding_provider).filter(KnowledgeChunk.document_id == d.id).distinct()}
        if provs == {prov}:
            skipped += 1
            continue
        reindex(db, d)
        done += 1
    return {"provider": prov, "reindexed": done, "skipped": skipped}


def embedding_status(db: Session, org_id: int) -> dict:
    from app.services import embeddings
    prov = embeddings.provider_name()
    q = (db.query(KnowledgeChunk.embedding_provider).join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeChunk.document_id)
         .filter(KnowledgeDocument.organization_id == org_id))
    total = q.count()
    current = q.filter(KnowledgeChunk.embedding_provider == prov).count()
    return {"provider": prov, "semantic": prov != "hash384", "chunks": total, "chunks_current": current}
