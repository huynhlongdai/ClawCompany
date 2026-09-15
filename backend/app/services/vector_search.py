import hashlib, json, math, re
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.core.config import settings
from app.models import KnowledgeDocument, KnowledgeChunk, KnowledgeVector

TOKEN_RE = re.compile(r"[\wÀ-ỹ]+", re.UNICODE)

def hash384_embedding(value: str, dim: int | None = None) -> list[float]:
    dim = dim or settings.embedding_dim
    vec = [0.0] * dim
    for token in TOKEN_RE.findall((value or "").lower()):
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=16).digest()
        idx = int.from_bytes(digest[:4], "big") % dim
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vec[idx] += sign
    norm = math.sqrt(sum(x*x for x in vec)) or 1.0
    return [x / norm for x in vec]

def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    return sum(x*y for x, y in zip(a, b))

def _is_postgres(db: Session) -> bool:
    return db.get_bind().dialect.name == "postgresql"

def ensure_pgvector(db: Session):
    if not _is_postgres(db):
        return
    db.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    db.execute(text("ALTER TABLE knowledge_vectors ADD COLUMN IF NOT EXISTS embedding vector(384)"))
    db.commit()

def index_chunk_vector(db: Session, chunk: KnowledgeChunk) -> KnowledgeVector:
    emb = hash384_embedding(chunk.content)
    item = db.query(KnowledgeVector).filter(KnowledgeVector.chunk_id == chunk.id).first()
    if not item:
        item = KnowledgeVector(chunk_id=chunk.id)
    item.embedding_json = json.dumps(emb)
    db.add(item)
    db.commit()
    db.refresh(item)
    if _is_postgres(db):
        ensure_pgvector(db)
        literal = "[" + ",".join(f"{x:.8f}" for x in emb) + "]"
        db.execute(text("UPDATE knowledge_vectors SET embedding = CAST(:v AS vector) WHERE id=:id"), {"v": literal, "id": item.id})
        db.commit()
    return item

def rebuild_document_vectors(db: Session, document_id: int) -> int:
    chunks = db.query(KnowledgeChunk).filter(KnowledgeChunk.document_id == document_id).order_by(KnowledgeChunk.chunk_index).all()
    for chunk in chunks:
        index_chunk_vector(db, chunk)
    return len(chunks)

def search_vectors(db: Session, organization_id: int, query: str, company_id: int | None = None,
                   department_id: int | None = None, project_id: int | None = None, limit: int = 10):
    qemb = hash384_embedding(query)
    base = db.query(KnowledgeChunk, KnowledgeDocument).join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeChunk.document_id)
    base = base.filter(KnowledgeDocument.organization_id == organization_id)
    if company_id is not None:
        base = base.filter(KnowledgeDocument.company_id == company_id)
    if department_id is not None:
        base = base.filter(KnowledgeDocument.department_id == department_id)
    if project_id is not None:
        base = base.filter(KnowledgeDocument.project_id == project_id)

    if _is_postgres(db):
        ensure_pgvector(db)
        literal = "[" + ",".join(f"{x:.8f}" for x in qemb) + "]"
        sql = """
        SELECT kc.id AS chunk_id, kd.id AS document_id, kd.title, kc.content,
               1 - (kv.embedding <=> CAST(:q AS vector)) AS score
        FROM knowledge_chunks kc
        JOIN knowledge_documents kd ON kd.id = kc.document_id
        JOIN knowledge_vectors kv ON kv.chunk_id = kc.id
        WHERE kd.organization_id = :org
          AND (:company IS NULL OR kd.company_id = :company)
          AND (:department IS NULL OR kd.department_id = :department)
          AND (:project IS NULL OR kd.project_id = :project)
        ORDER BY kv.embedding <=> CAST(:q AS vector)
        LIMIT :limit
        """
        rows = db.execute(text(sql), {
            "q": literal, "org": organization_id, "company": company_id,
            "department": department_id, "project": project_id, "limit": limit,
        }).mappings().all()
        return [dict(r) for r in rows]

    rows = []
    for chunk, doc in base.all():
        kv = db.query(KnowledgeVector).filter(KnowledgeVector.chunk_id == chunk.id).first()
        if not kv:
            kv = index_chunk_vector(db, chunk)
        try:
            emb = json.loads(kv.embedding_json or "[]")
        except Exception:
            emb = []
        rows.append({
            "chunk_id": chunk.id, "document_id": doc.id, "title": doc.title,
            "content": chunk.content, "score": cosine(qemb, emb),
        })
    rows.sort(key=lambda x: x["score"], reverse=True)
    return rows[:limit]
