"""M3e — vòng học tài liệu. Spec: docs/company-knowledge-library-and-gaps.md §A10, §C M3e.

Nguồn → đề xuất → phiên bản NHÁP → duyệt (đường M3a, không đường tắt) → ban hành → đóng nguồn → chạy lại eval:
* cờ của agent (``document_flags`` mở) trên một tài liệu → MỘT đề xuất / tài liệu (gộp mọi cờ mở);
* lỗ hổng kiến thức (``knowledge_gaps`` mở của ghế thuộc công ty, gồm câu eval trượt ghi với source="eval") gom cụm theo
  từ khoá (Jaccard trên token không dấu, bỏ cụm hỏi) → cụm ≥ N lượt → nháp bổ sung vào tài liệu gần nhất, không có thì
  nháp bài FAQ mới. Câu hỏi được GỠ thông tin cá nhân (SĐT, email, CCCD, "chị Lan…") trước khi vào nháp;
* bài học đã duyệt có nhắc mã tài liệu (POL-003…) → đề xuất trên tài liệu đó;
* agent gọi ``company_doc_propose`` (nội dung mới đầy đủ) → phiên bản nháp, người duyệt.

Nội dung đề xuất KHÔNG do model viết (CometAPI hết hạn mức): nháp = bản đang hiệu lực + phần "[Cần bổ sung]" liệt kê câu
hỏi / ghi chú nguồn; người phụ trách sửa nháp rồi gửi duyệt. Ban hành → cờ ``resolved``, lỗ hổng ``resolved`` (+ tài liệu
đã giải), đề xuất ``eval_pending`` → ``docs.tick`` (hoặc nút "Chạy lại eval") ghi ``eval_after``."""
from __future__ import annotations

import re
from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import KnowledgeDocument, Member
from app.models.doc_ingest import DocProposal, RetrievalEvalRun
from app.models.documents import DocumentFlag, DocumentVersion
from app.models.learning import KnowledgeGap
from app.services import doc_library as lib
from app.services import knowledge_hub as kh

GAP_CLUSTER_MIN = 3          # cụm lỗ hổng ≥ 3 lượt hỏi → đề xuất
JACCARD_MIN = 0.5
TODO = "[Cần bổ sung]"

# ------------------------------------------------------------------ gỡ thông tin cá nhân

PII_RES = [
    (re.compile(r"(?<!\d)(?:\+?84|0)[35789](?:[\s.]?\d){8}(?!\d)"), "[SĐT]"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"), "[email]"),
    (re.compile(r"(?<!\d)\d{12}(?!\d)"), "[CCCD]"),
    (re.compile(r"(?<!\d)\d{9}(?!\d)"), "[số giấy tờ]"),
    (re.compile(r"\b(?:mã đơn|ma don|đơn hàng|don hang|order)\s*#?\s*[A-Z0-9-]{5,}", re.I), "[mã đơn]"),
]
NAME_RE = re.compile(r"\b((?i:anh|chị|chi|em|cô|co|chú|chu|bác|bac|bạn|ban|khách|khach))\s+((?:[A-ZĐ][\wÀ-ỹ]*\s?){1,3})")


def scrub(text: str) -> str:
    out = text or ""
    for rx, rep in PII_RES:
        out = rx.sub(rep, out)
    out = NAME_RE.sub(lambda m: m.group(1) + " [tên]", out)
    return re.sub(r"\s+", " ", out).strip()


# ------------------------------------------------------------------ biểu diễn

def public(db: Session, p: DocProposal) -> dict:
    doc = db.get(KnowledgeDocument, p.document_id) if p.document_id else None
    v = db.get(DocumentVersion, p.version_id) if p.version_id else None
    return {"id": p.id, "company_id": p.company_id, "kind": p.kind, "status": p.status, "title": p.title,
            "rationale": p.rationale, "new_document": bool(p.new_document), "source_refs": p.source_refs or {},
            "document": {"id": doc.id, "doc_code": doc.doc_code, "title": doc.title, "status": doc.status,
                         "version_no": doc.version_no} if doc else None,
            "version": {"id": v.id, "version_no": v.version_no, "status": v.status} if v else None,
            "eval_before": p.eval_before, "eval_after": p.eval_after, "eval_pending": bool(p.eval_pending),
            "created_at": p.created_at.isoformat() if p.created_at else None,
            "closed_at": p.closed_at.isoformat() if p.closed_at else None}


def _open_for_doc(db: Session, doc_id: int, kind: str | None = None) -> DocProposal | None:
    q = db.query(DocProposal).filter(DocProposal.document_id == doc_id, DocProposal.status == "open")
    if kind:
        q = q.filter(DocProposal.kind == kind)
    return q.first()


def _latest_eval(db: Session, company_id: int) -> dict | None:
    r = (db.query(RetrievalEvalRun).filter(RetrievalEvalRun.company_id == company_id)
         .order_by(RetrievalEvalRun.id.desc()).first())
    return {"run_id": r.id, "recall": r.recall, "top1": r.top1, "section_recall": r.section_recall,
            "misses": len(r.misses or []), "at": r.created_at.isoformat()} if r else None


def _draft_on(db: Session, doc: KnowledgeDocument, addition: str, note: str, *, principal=None,
              replace_content: str | None = None) -> DocumentVersion:
    """Nháp mới (hoặc ghi thêm vào nháp đang mở) của ``doc``: bản đang hiệu lực + ``addition``."""
    open_v = (db.query(DocumentVersion).filter(DocumentVersion.document_id == doc.id,
                                              DocumentVersion.status.in_(lib.OPEN_VERSION))
              .order_by(DocumentVersion.version_no.desc()).first())
    if open_v is not None and open_v.status != "draft":
        raise HTTPException(409, f"{doc.doc_code} đang có v{open_v.version_no} chờ duyệt — quyết bản đó trước")
    if open_v is not None:
        body = replace_content if replace_content is not None else (open_v.content.rstrip() + "\n\n" + addition)
        lib.edit_version(db, doc.organization_id, principal, doc.id, open_v.id, {"content": body, "change_note": note})
        db.refresh(open_v)
        return open_v
    base = replace_content if replace_content is not None else ((doc.content or "").rstrip() + "\n\n" + addition)
    if doc.status != "published":
        raise HTTPException(409, f"{doc.doc_code} đang {doc.status}")
    lib.new_version(db, doc.organization_id, principal, doc.id, {"content": base, "change_note": note[:2000]})
    return (db.query(DocumentVersion).filter(DocumentVersion.document_id == doc.id, DocumentVersion.status == "draft")
            .order_by(DocumentVersion.version_no.desc()).first())


def _notify(db: Session, doc: KnowledgeDocument, p: DocProposal) -> None:
    from app.services import inbox
    inbox.notify(db, organization_id=doc.organization_id, recipients=[lib._review_owner(db, doc)], kind="doc_proposal",
                 title=f"Đề xuất sửa {doc.doc_code}: {p.title}"[:200], related_type="document", related_id=str(doc.id),
                 company_id=doc.company_id, commit=False, line=p.rationale[:300])


# ------------------------------------------------------------------ nguồn 1: cờ của agent

FLAG_VI = {"wrong": "sai", "outdated": "đã cũ", "conflict": "mâu thuẫn", "missing_case": "thiếu trường hợp"}


def propose_from_flags(db: Session, doc: KnowledgeDocument, *, principal=None) -> DocProposal | None:
    flags = (db.query(DocumentFlag).filter(DocumentFlag.document_id == doc.id, DocumentFlag.status == "open")
             .order_by(DocumentFlag.id).all())
    if not flags or doc.status != "published":
        return None
    p = _open_for_doc(db, doc.id)
    known = set((p.source_refs or {}).get("flags", [])) if p else set()
    new = [f for f in flags if f.id not in known]
    if p is not None and not new:
        return p
    lines = [f"- ({FLAG_VI.get(f.reason, f.reason)}) {scrub(f.note) or 'không ghi chú'}" for f in (new or flags)]
    addition = f"## {TODO} Agent đánh dấu khi dùng tài liệu\n\n" + "\n".join(lines) + \
               "\n\n_(Sửa nội dung phía trên cho đúng rồi xoá phần này trước khi gửi duyệt.)_"
    v = _draft_on(db, doc, addition, f"Đề xuất từ {len(flags)} cờ của agent", principal=principal)
    if p is None:
        p = DocProposal(organization_id=doc.organization_id, company_id=doc.company_id, document_id=doc.id, kind="flag",
                        title=f"{len(flags)} cờ: " + ", ".join(sorted({FLAG_VI.get(f.reason, f.reason) for f in flags})),
                        eval_before=_latest_eval(db, doc.company_id))
    p.version_id = v.id if v else p.version_id
    p.source_refs = {**(p.source_refs or {}), "flags": sorted(known | {f.id for f in flags})}
    p.rationale = "; ".join(f"{FLAG_VI.get(f.reason, f.reason)}: {scrub(f.note)[:120]}" for f in flags)[:2000]
    db.add(p); db.flush()
    _notify(db, doc, p)
    db.commit(); db.refresh(p)
    return p


# ------------------------------------------------------------------ nguồn 2: cụm lỗ hổng kiến thức (+ eval trượt)

# Từ xưng hô / lời dẫn / chỗ giữ thông tin cá nhân: không phải chủ đề câu hỏi. Không bỏ thì "Chị Lan 09… hỏi tiệm có xuất
# hoá đơn đỏ…" và "xuất hoá đơn đỏ…" có Jaccard < 0.5 dù cùng một câu hỏi (đo trên bộ test M3e).
CLUSTER_NOISE = {"chi", "anh", "em", "co", "chu", "bac", "ban", "khach", "hoi", "can", "muon", "shop", "tiem", "oi",
                 "nhe", "vay", "duoc", "minh", "toi", "giup"}


def _qtokens(q: str) -> set[str]:
    clean = re.sub(r"\[[^\]]*\]", " ", scrub(q))      # bỏ [SĐT], [tên], [email]… sau khi gỡ thông tin cá nhân
    return set(kh._tokens(kh.strip_question_phrases(clean))) - CLUSTER_NOISE


def clusters(gaps: list[KnowledgeGap]) -> list[list[KnowledgeGap]]:
    """Gom cụm đơn giản (single-link) theo Jaccard token ≥ 0.5 — xác định, không cần embedding."""
    out: list[list[KnowledgeGap]] = []
    toks = {g.id: _qtokens(g.question) for g in gaps}
    for g in sorted(gaps, key=lambda x: x.id):
        best = None
        for c in out:
            if any(toks[g.id] and toks[h.id] and len(toks[g.id] & toks[h.id]) / len(toks[g.id] | toks[h.id]) >= JACCARD_MIN
                   for h in c):
                best = c; break
        if best is None:
            out.append([g])
        else:
            best.append(g)
    return out


def company_gaps(db: Session, company_id: int) -> list[KnowledgeGap]:
    mids = [m.id for m in db.query(Member.id).filter(Member.company_id == company_id).all()]
    if not mids:
        return []
    return (db.query(KnowledgeGap).filter(KnowledgeGap.member_id.in_(mids), KnowledgeGap.status == "open")
            .order_by(KnowledgeGap.id).all())


def propose_from_gaps(db: Session, org_id: int, company_id: int, *, principal=None, min_size: int = GAP_CLUSTER_MIN) -> list[DocProposal]:
    linked = set()
    for p in db.query(DocProposal).filter(DocProposal.company_id == company_id, DocProposal.status == "open").all():
        linked |= set((p.source_refs or {}).get("gaps", []))
    gaps = [g for g in company_gaps(db, company_id) if g.id not in linked]
    out = []
    for c in clusters(gaps):
        if sum(max(1, g.count or 1) for g in c) < min_size:
            continue
        rep = max(c, key=lambda g: g.count or 1)
        qs = []
        for g in sorted(c, key=lambda g: -(g.count or 1)):
            s = scrub(g.question)
            if s and s not in qs:
                qs.append(s)
        seat = _eval_member(db, company_id)   # tra như một agent của công ty → chỉ tài liệu công ty này, đúng quyền agent
        hits = kh.search(db, org_id, rep.question, member=seat, limit=1, log_gap=False, track=False)["hits"] if seat else []
        doc = db.get(KnowledgeDocument, hits[0]["document_id"]) if hits and hits[0]["score"] >= 0.25 else None
        if doc is not None and doc.company_id != company_id:
            doc = None
        block = "\n\n".join(f"### {q}\n\n{TODO} …… (trả lời theo chính sách đang áp dụng)" for q in qs[:10])
        title = f"Cụm {len(c)} câu hỏi ({sum(max(1, g.count or 1) for g in c)} lượt): {qs[0][:80]}"
        if doc is not None and doc.status == "published" and _open_for_doc(db, doc.id) is None:
            v = _draft_on(db, doc, f"## {TODO} Khách / agent hay hỏi mà tài liệu chưa trả lời\n\n" + block,
                          f"Đề xuất từ cụm lỗ hổng: {qs[0][:120]}", principal=principal)
            p = DocProposal(organization_id=org_id, company_id=company_id, document_id=doc.id, version_id=v.id if v else None,
                            kind="gap", title=title, eval_before=_latest_eval(db, company_id))
        else:
            co_name = lib._company(db, org_id, company_id).name
            body = f"# Câu hỏi thường gặp — bổ sung ({co_name})\n\n" + block
            d = lib.create(db, org_id, principal, {"company_id": company_id, "title": f"FAQ bổ sung: {qs[0][:120]}",
                                                   "doc_type": "faq", "content": body,
                                                   "change_note": "Nháp tự sinh từ cụm lỗ hổng kiến thức (vòng học M3e)"},
                           force_draft=True)
            doc = db.get(KnowledgeDocument, d["id"])
            v = db.query(DocumentVersion).filter(DocumentVersion.document_id == doc.id).first()
            p = DocProposal(organization_id=org_id, company_id=company_id, document_id=doc.id, version_id=v.id if v else None,
                            new_document=True, kind="gap", title=title, eval_before=_latest_eval(db, company_id))
        p.source_refs = {"gaps": [g.id for g in c], "questions": qs[:10],
                         "eval": any((g.source or "") == "eval" for g in c)}
        p.rationale = f"{len(c)} câu hỏi tương tự chưa có câu trả lời đủ tốt trong tài liệu (điểm truy hồi < {kh.GAP_THRESHOLD})."
        db.add(p); db.flush()
        _notify(db, doc, p)
        db.commit(); db.refresh(p)
        out.append(p)
    return out


# ------------------------------------------------------------------ nguồn 3: bài học đã duyệt / agent đề xuất

CODE_RE = re.compile(r"\b([A-Z]{2,4}-\d{3})\b")


def propose_from_lesson(db: Session, *, member: Member, text: str, lesson_ref: int | None = None) -> DocProposal | None:
    for code in dict.fromkeys(CODE_RE.findall(text or "")):
        doc = lib.by_code(db, member, code)
        if doc is None or doc.status != "published" or _open_for_doc(db, doc.id) is not None:
            continue
        v = _draft_on(db, doc, f"## {TODO} Bài học từ vận hành\n\n- {scrub(text)[:600]}",
                      f"Đề xuất từ bài học đã duyệt của {member.name}")
        p = DocProposal(organization_id=doc.organization_id, company_id=doc.company_id, document_id=doc.id,
                        version_id=v.id if v else None, kind="lesson", title=f"Bài học: {scrub(text)[:120]}",
                        rationale=scrub(text)[:2000], source_refs={"lesson_approval_id": lesson_ref},
                        created_by_member_id=member.id, eval_before=_latest_eval(db, doc.company_id))
        db.add(p); db.flush(); _notify(db, doc, p); db.commit(); db.refresh(p)
        return p
    return None


def agent_propose(db: Session, *, member: Member, code: str, content: str, note: str) -> dict:
    doc = lib.by_code(db, member, code)
    if doc is None:
        raise HTTPException(404, "Không thấy tài liệu theo mã này")
    if not kh.agent_ok(doc, member):
        raise HTTPException(403, "Tài liệu này không dành cho agent đọc/sửa")
    if len((content or "").strip()) < 20:
        raise HTTPException(422, "Nội dung đề xuất trống hoặc quá ngắn")
    if _open_for_doc(db, doc.id) is not None:
        raise HTTPException(409, f"{doc.doc_code} đã có một đề xuất đang mở — dùng company_doc_flag để ghi thêm ý kiến")
    v = _draft_on(db, doc, "", f"Agent {member.name} đề xuất: {scrub(note)[:300]}", replace_content=content.strip())
    p = DocProposal(organization_id=doc.organization_id, company_id=doc.company_id, document_id=doc.id,
                    version_id=v.id if v else None, kind="agent", title=f"{member.name}: {scrub(note)[:120] or 'đề xuất sửa'}",
                    rationale=scrub(note)[:2000], created_by_member_id=member.id, eval_before=_latest_eval(db, doc.company_id))
    db.add(p); db.flush(); _notify(db, doc, p); db.commit(); db.refresh(p)
    d = lib.diff(db, doc.organization_id, None, doc.id, None, v.version_no) if v else {}   # diff nhận số phiên bản, không phải id
    return {"proposal_id": p.id, "doc_code": doc.doc_code, "draft_version": v.version_no if v else None,
            "diff_stats": {k: d.get(k) for k in ("added", "removed") if isinstance(d, dict)},
            "message": "Đã tạo bản nháp — người phụ trách duyệt mới có hiệu lực. Trong lúc chờ vẫn dùng bản hiện hành."}


# ------------------------------------------------------------------ móc vào vòng đời M3a

def on_version_decided(db: Session, doc: KnowledgeDocument, v: DocumentVersion, decision: str) -> None:
    p = db.query(DocProposal).filter(DocProposal.version_id == v.id, DocProposal.status == "open").first()
    if p is None or decision != "rejected":
        return
    p.status, p.closed_at = "rejected", datetime.utcnow()
    db.add(p)


def on_published(db: Session, doc: KnowledgeDocument, v: DocumentVersion) -> None:
    p = db.query(DocProposal).filter(DocProposal.version_id == v.id, DocProposal.status == "open").first()
    if p is None:
        return
    now = datetime.utcnow()
    refs = p.source_refs or {}
    for fid in refs.get("flags", []):
        f = db.get(DocumentFlag, fid)
        if f is not None and f.status == "open":
            f.status = "resolved"; db.add(f)
    for gid in refs.get("gaps", []):
        g = db.get(KnowledgeGap, gid)
        if g is not None and g.status == "open":
            g.status, g.resolved_document_id, g.resolved_at = "resolved", doc.id, now; db.add(g)
    p.status, p.closed_at, p.eval_pending = "published", now, True
    db.add(p)


# ------------------------------------------------------------------ eval + bảng sức khoẻ

def _eval_member(db: Session, company_id: int) -> Member | None:
    from app.models import Agent
    return (db.query(Member).join(Agent, Agent.member_id == Member.id)
            .filter(Member.company_id == company_id, Member.status.in_(("active", "onboarding"))).order_by(Member.id).first())


def run_eval(db: Session, org_id: int, company_id: int, *, trigger: str = "manual", record_misses: bool = True) -> dict:
    """Chạy bộ eval CSKH (app/evals) bằng góc nhìn một agent của công ty. Câu trượt (không có tài liệu đúng trong top-k)
    → ghi lỗ hổng source="eval" (để vào vòng gom cụm). Công ty không có tài liệu nào của bộ eval → trả not_applicable."""
    from app.services import retrieval_eval
    m = _eval_member(db, company_id)
    if m is None:
        return {"status": "no_agent", "message": "Công ty chưa có agent để chạy eval"}
    out = retrieval_eval.run(db, org_id, m)
    if not out["docs_found"]:
        return {"status": "not_applicable", "message": "Bộ eval hiện có (CSKH gốm) không khớp tài liệu của công ty này"}
    misses = [r["q"] for r in out["rows"] if not r["new"]]
    run = RetrievalEvalRun(organization_id=org_id, company_id=company_id, trigger=trigger, questions=out["questions"],
                           recall=out["recall_new"], top1=out.get("top1_new", 0.0), section_recall=out["section_recall_new"],
                           misses=misses)
    db.add(run); db.commit(); db.refresh(run)
    if record_misses:
        for q in misses:
            kh.record_gap(db, org_id, m.id, q, source="eval")
    return {"status": "ok", "run_id": run.id, "recall": run.recall, "top1": run.top1, "section_recall": run.section_recall,
            "misses": misses, "questions": run.questions, "docs_found": out["docs_found"], "docs_expected": out["docs_expected"]}


def eval_pending(db: Session, *, org_id: int | None = None, reuse: dict | None = None) -> dict:
    """Beat: đề xuất đã ban hành chờ đo lại → một lần eval / công ty, ghi eval_after vào các đề xuất đó. Gọi từ API:
    ``org_id`` giới hạn trong tổ chức của người gọi, ``reuse`` = {company_id: kết quả eval vừa chạy} để không chạy hai lần."""
    done = dict(reuse or {})
    q = db.query(DocProposal).filter(DocProposal.eval_pending == True)  # noqa: E712
    if org_id is not None:
        q = q.filter(DocProposal.organization_id == org_id)
    for p in q.all():
        if p.company_id not in done:
            done[p.company_id] = run_eval(db, p.organization_id, p.company_id, trigger="publish")
        r = done[p.company_id]
        p.eval_after = {k: r.get(k) for k in ("status", "run_id", "recall", "top1", "section_recall")} | \
                       {"misses": len(r.get("misses") or [])}
        p.eval_pending = False
        db.add(p)
    db.commit()
    return {"companies": list(done)}


def dashboard(db: Session, org_id: int, company_id: int, now: datetime | None = None) -> dict:
    now = now or datetime.utcnow()
    lib._company(db, org_id, company_id)
    docs = db.query(KnowledgeDocument).filter(KnowledgeDocument.company_id == company_id).all()
    pub = [d for d in docs if d.status == "published" and d.doc_class == "document"]
    fresh = [d for d in pub if not d.review_due_at or d.review_due_at >= now]
    doc_ids = [d.id for d in docs] or [-1]
    flags = db.query(DocumentFlag).filter(DocumentFlag.document_id.in_(doc_ids)).all()
    mids = [m.id for m in db.query(Member.id).filter(Member.company_id == company_id).all()] or [-1]
    gaps = db.query(KnowledgeGap).filter(KnowledgeGap.member_id.in_(mids)).all()
    props = db.query(DocProposal).filter(DocProposal.company_id == company_id).order_by(DocProposal.id.desc()).all()
    runs = (db.query(RetrievalEvalRun).filter(RetrievalEvalRun.company_id == company_id)
            .order_by(RetrievalEvalRun.id.desc()).limit(10).all())
    since = now - timedelta(days=30)
    unused = [d for d in pub if (d.last_used_at is None and d.created_at and d.created_at < now - timedelta(days=180))
              or (d.last_used_at and d.last_used_at < now - timedelta(days=180))]
    closed_by_loop = [g for g in gaps if g.status == "resolved" and g.resolved_document_id]
    open_gaps = [g for g in gaps if g.status == "open"]
    cl = clusters(open_gaps)
    return {
        "company_id": company_id,
        "kpi": {"doc_freshness_rate": round(len(fresh) / len(pub), 3) if pub else None,
                "knowledge_gap_rate": None,   # cần số lượt tra cứu theo kỳ — chưa có bộ đếm, nói thẳng thay vì bịa
                "published_docs": len(pub), "fresh_docs": len(fresh)},
        "flags": {"open": sum(f.status == "open" for f in flags), "resolved": sum(f.status == "resolved" for f in flags),
                  "dismissed": sum(f.status == "dismissed" for f in flags)},
        "gaps": {"open": len(open_gaps), "open_asks": sum(max(1, g.count or 1) for g in open_gaps),
                 "resolved": sum(g.status == "resolved" for g in gaps), "closed_by_docs": len(closed_by_loop),
                 "closed_last_30d": sum(1 for g in closed_by_loop if g.resolved_at and g.resolved_at >= since),
                 "clusters": [{"size": len(c), "asks": sum(max(1, g.count or 1) for g in c),
                               "sample": scrub(max(c, key=lambda g: g.count or 1).question)[:160],
                               "ready": sum(max(1, g.count or 1) for g in c) >= GAP_CLUSTER_MIN}
                              for c in sorted(cl, key=lambda c: -sum(max(1, g.count or 1) for g in c))[:8]]},
        "proposals": {"open": sum(p.status == "open" for p in props), "published": sum(p.status == "published" for p in props),
                      "rejected": sum(p.status == "rejected" for p in props),
                      "items": [public(db, p) for p in props[:30]]},
        "eval": {"latest": _latest_eval(db, company_id),
                 "history": [{"id": r.id, "at": r.created_at.isoformat(), "trigger": r.trigger, "recall": r.recall,
                              "top1": r.top1, "misses": r.misses or []} for r in runs]},
        "unused_180d": [{"id": d.id, "doc_code": d.doc_code, "title": d.title} for d in unused[:10]],
        "gap_cluster_min": GAP_CLUSTER_MIN,
    }


def dismiss(db: Session, org_id: int, proposal_id: int) -> dict:
    p = db.get(DocProposal, proposal_id)
    if p is None or p.organization_id != org_id:
        raise HTTPException(404, "Không thấy đề xuất")
    from app.core import company_scope
    company_scope.check(p.company_id, min_role="manager")
    if p.status != "open":
        raise HTTPException(409, f"Đề xuất đang {p.status}")
    p.status, p.closed_at = "dismissed", datetime.utcnow()
    db.add(p); db.commit()
    return public(db, p)


def tick(db: Session) -> dict:
    """Beat (docs.tick): cờ mở → đề xuất; cụm lỗ hổng đủ lớn → đề xuất; đề xuất đã ban hành → chạy lại eval."""
    from app.models import Company
    out = {"flag_proposals": 0, "gap_proposals": 0}
    doc_ids = {f.document_id for f in db.query(DocumentFlag).filter(DocumentFlag.status == "open").all()}
    for did in doc_ids:
        d = db.get(KnowledgeDocument, did)
        if d is not None and d.status == "published":
            try:
                out["flag_proposals"] += propose_from_flags(db, d) is not None
            except HTTPException:
                db.rollback()
    for co in db.query(Company).all():
        try:
            out["gap_proposals"] += len(propose_from_gaps(db, co.organization_id, co.id))
        except HTTPException:
            db.rollback()
    out["eval"] = eval_pending(db)
    return out
