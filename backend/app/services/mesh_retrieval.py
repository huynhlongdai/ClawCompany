"""v33: semantic retrieval for the shared knowledge mesh.

``knowledge_mesh.search`` matched with ``ILIKE %token%``. That is substring
matching, not retrieval: "chinh sach hoan tien" found nothing unless the entry
spelled it the same way, while v26 already shipped a real embedding path
(``vector_search.hash384_embedding`` + ``cosine``) used only by the document
chunk index.

This module puts the two together, and the order matters:

1. Permission filtering and access logging stay in ``knowledge_mesh.search``.
   Nothing here queries entries directly, so there is no way for a semantic
   path to read a space the member cannot read.
2. Re-ranking happens afterwards, in memory, over that already-authorised
   candidate set.

The ranker is honest about its own quality: ``hash384`` is a deterministic
hashing embedding, not a trained model. It beats substring matching on word
overlap and word order, and it does *not* understand synonyms. ``explain()``
says so, so nobody mistakes this for a vector database.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.services import knowledge_mesh
from app.services.vector_search import cosine, hash384_embedding

SOURCE = "mesh_retrieval"

KEYWORD = "keyword"
SEMANTIC = "semantic"
HYBRID = "hybrid"
MODES = (KEYWORD, SEMANTIC, HYBRID)

# How many authorised candidates to pull before re-ranking. Wider than the
# requested page, because the best semantic hit is often not a keyword hit.
CANDIDATE_FACTOR = 5
MAX_CANDIDATES = 100

# Only this much of an entry body is embedded. Long entries would otherwise
# average their own topic away.
EMBED_CHARS = 2000

# Below this the match is noise. Kept low because hash384 scores are dense.
MIN_SCORE = 0.02

# Weights for hybrid: keyword rank is a real signal (an exact substring match
# is rarely wrong), so it is not discarded, only outvoted.
SEMANTIC_WEIGHT = 0.7
KEYWORD_WEIGHT = 0.3


def explain() -> dict:
    return {
        "provider": "hash384",
        "trained_model": False,
        "understands_synonyms": False,
        "good_at": ["word overlap", "word order", "typo-free paraphrase"],
        "bad_at": ["synonyms", "cross-language queries", "very short entries"],
        "modes": list(MODES),
        "default_mode": HYBRID,
        "semantic_weight": SEMANTIC_WEIGHT,
        "keyword_weight": KEYWORD_WEIGHT,
        "min_score": MIN_SCORE,
        "permissions": "delegated to knowledge_mesh.search; never bypassed",
    }


def _text_of(row: dict) -> str:
    parts = [str(row.get("title") or ""), str(row.get("summary") or ""),
             str(row.get("content") or "")[:EMBED_CHARS]]
    return "\n".join(x for x in parts if x)


def score_rows(query: str, rows: list[dict]) -> list[dict]:
    """Attach a semantic score to already-authorised rows.

    Pure function: no database, no permissions, no side effects. This is the
    part the tests can reason about without a session.
    """
    if not query.strip():
        return [{**row, "score": None, "scored": False} for row in rows]
    qemb = hash384_embedding(query)
    out: list[dict] = []
    for row in rows:
        text = _text_of(row)
        if not text.strip():
            out.append({**row, "score": 0.0, "scored": True})
            continue
        out.append({**row, "score": round(float(cosine(qemb, hash384_embedding(text))), 6),
                    "scored": True})
    return out


def _blend(rows: list[dict]) -> list[dict]:
    """Combine semantic score with the keyword order the mesh returned."""
    total = max(1, len(rows))
    blended: list[dict] = []
    for index, row in enumerate(rows):
        keyword_score = 1.0 - (index / total)
        semantic = row.get("score")
        if semantic is None:
            combined = keyword_score
        else:
            combined = (SEMANTIC_WEIGHT * float(semantic)) + (KEYWORD_WEIGHT * keyword_score)
        blended.append({**row, "keyword_rank": index + 1,
                        "combined_score": round(combined, 6)})
    return blended


def search(db: Session, *, organization_id: int, member_id: int, query: str = "",
           space_ids: list[int] | None = None, limit: int = 20,
           mode: str = HYBRID) -> dict:
    """Retrieval over the mesh, ranked instead of merely filtered."""
    if mode not in MODES:
        mode = HYBRID
    page = max(1, min(int(limit), 100))
    candidate_limit = min(MAX_CANDIDATES, page * CANDIDATE_FACTOR)

    # The one and only read path: permission checks and audit logging happen
    # inside this call, for every mode including semantic.
    rows = knowledge_mesh.search(db, organization_id=organization_id, member_id=member_id,
                                 query=query, space_ids=space_ids, limit=candidate_limit)

    if mode == KEYWORD or not query.strip():
        ranked = [{**row, "score": None, "keyword_rank": i + 1, "combined_score": None}
                  for i, row in enumerate(rows)]
        return {"mode": KEYWORD if mode == KEYWORD else mode, "query": query,
                "candidates_considered": len(rows), "returned": len(ranked[:page]),
                "results": ranked[:page], "reranked": False, "explain": explain()}

    scored = score_rows(query, rows)
    if mode == SEMANTIC:
        kept = [r for r in scored if (r.get("score") or 0.0) >= MIN_SCORE]
        kept.sort(key=lambda r: r.get("score") or 0.0, reverse=True)
        for index, row in enumerate(kept):
            row["combined_score"] = row.get("score")
            row["semantic_rank"] = index + 1
    else:
        kept = _blend(scored)
        kept.sort(key=lambda r: r.get("combined_score") or 0.0, reverse=True)
        for index, row in enumerate(kept):
            row["semantic_rank"] = index + 1

    return {
        "mode": mode,
        "query": query,
        "candidates_considered": len(rows),
        "dropped_below_min_score": len(scored) - len(kept),
        "returned": len(kept[:page]),
        "results": kept[:page],
        "reranked": True,
        "explain": explain(),
    }
