"""M3b — bộ eval CSKH xác định (không model): recall@k của truy hồi MỚI (knowledge_hub.search: lọc quyền trước, cắt
theo đề mục + tiêu đề ngữ cảnh, từ khoá không dấu, RRF; Postgres thêm FTS + pgvector) so với truy hồi CŨ (trước M3b:
cắt 1.000 ký tự theo đoạn, từ khoá có dấu, 0.7·phủ từ + 0.3·cosine vector băm + thưởng tiêu đề) trên cùng tài liệu.

Bộ câu hỏi: app/evals/cskh_gom_moc.json (33 câu, có câu gõ không dấu / diễn đạt khác). Đo ở mức tài liệu (đúng tài liệu
trong top-k) và mức mục (đúng §mục trong top-k — chỉ đường mới có mục). Vector băm → kết quả lặp lại y hệt mỗi lần chạy."""
from __future__ import annotations

import json
import re
from pathlib import Path

from sqlalchemy.orm import Session

from app.models import KnowledgeDocument, Member
from app.services import knowledge_hub as kh
from app.services.vector_search import TOKEN_RE, cosine, hash384_embedding

EVAL_FILE = Path(__file__).resolve().parents[1] / "evals" / "cskh_gom_moc.json"


def load() -> dict:
    return json.loads(EVAL_FILE.read_text(encoding="utf-8"))


def _old_tokens(text: str) -> set[str]:
    return {t for t in TOKEN_RE.findall((text or "").lower()) if len(t) > 1 and t not in kh.STOP}


def legacy_rank(docs: list[KnowledgeDocument], query: str, k: int = 6) -> list[int]:
    """Đường cũ (knowledge_hub trước M3b, vector băm) → [document_id] của top-k đoạn."""
    qt = _old_tokens(query)
    if not qt:
        return []
    qemb = hash384_embedding(query)
    scored = []
    for d in docs:
        tb = 0.1 if qt & _old_tokens(d.title) else 0.0
        for part in kh.chunk_text(d.content or ""):
            ct = _old_tokens(part)
            cover = len(qt & ct) / len(qt)
            if cover > 0:
                scored.append((0.7 * cover + 0.3 * max(0.0, cosine(qemb, hash384_embedding(part))) + tb, d.id))
    scored.sort(key=lambda x: -x[0])
    return [did for _s, did in scored[:k]]


def run(db: Session, org_id: int, member: Member, *, titles: dict[str, str] | None = None, k: int = 6) -> dict:
    """``titles``: khoá tài liệu trong bộ eval → tiêu đề thật trong DB (mặc định = tiêu đề trong bộ eval)."""
    data = load()
    by_title = {d["key"]: (titles or {}).get(d["key"], d["title"]) for d in data["docs"]}
    visible = [d for d in kh.visible_docs_query(db, org_id, member, None).all() if kh.agent_ok(d, member)]
    id_of = {}
    for key, t in by_title.items():
        m = [d for d in visible if d.title == t]
        if m:
            id_of[key] = m[-1].id
    rows, old_doc = [], 0
    new_doc = new_sec = cite_cur = noexp = 0
    for q in data["questions"]:
        want = id_of.get(q["doc"])
        old = legacy_rank(visible, q["q"], k)
        res = kh.search(db, org_id, q["q"], member=member, limit=k, log_gap=False, track=False)
        hits = res["hits"]
        ok_old = want in old
        ne = kh.search(db, org_id, q["q"], member=member, limit=k, log_gap=False, track=False, expand=False)["hits"]
        noexp += any(h["document_id"] == want for h in ne)
        ok_new = any(h["document_id"] == want for h in hits)
        ok_sec = any(h["document_id"] == want and q["section"].lower() in (h.get("section") or "").lower() for h in hits)
        top = hits[0] if hits else None
        cur = bool(top and top["doc_code"] and re.search(rf"v{top['version_no']} ", top["cite"] + " "))
        old_doc += ok_old; new_doc += ok_new; new_sec += ok_sec; cite_cur += cur
        rows.append({"q": q["q"], "want": q["doc"], "old": ok_old, "new": ok_new, "section": ok_sec,
                     "top": (top or {}).get("cite"), "top_section": (top or {}).get("section")})
    n = len(data["questions"])
    return {"name": data["name"], "questions": n, "k": k, "docs_found": len(id_of), "docs_expected": len(by_title),
            "recall_old": round(old_doc / n, 3), "recall_new": round(new_doc / n, 3),
            "section_recall_new": round(new_sec / n, 3), "recall_new_without_synonyms": round(noexp / n, 3), "top_cites_current_version": round(cite_cur / n, 3),
            "delta_points": round(100 * (new_doc - old_doc) / n, 1), "rows": rows,
            "dialect": db.get_bind().dialect.name}
