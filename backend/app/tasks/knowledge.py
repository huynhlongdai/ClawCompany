from app.worker import celery_app
from app.db.session import SessionLocal
from app.models import KnowledgeDocument, KnowledgeChunk, BackgroundJob
from app.services.vector_search import rebuild_document_vectors


def chunk_text(text: str, size: int = 800, overlap: int = 100):
    if not text:
        return []
    out = []
    start = 0
    while start < len(text):
        end = min(len(text), start + size)
        out.append(text[start:end])
        if end >= len(text):
            break
        start = max(start + 1, end - overlap)
    return out


@celery_app.task(name="knowledge.index_document")
def index_document(document_id: int):
    db = SessionLocal()
    job = None
    try:
        doc = db.get(KnowledgeDocument, document_id)
        if not doc:
            return {"status": "not_found"}
        job = BackgroundJob(
            organization_id=doc.organization_id,
            job_type="knowledge.index",
            resource_type="knowledge_document",
            resource_id=str(doc.id),
            status="running",
        )
        db.add(job); db.commit(); db.refresh(job)

        db.query(KnowledgeChunk).filter(KnowledgeChunk.document_id == document_id).delete()
        db.commit()
        chunks = chunk_text(doc.content or "")
        for idx, chunk in enumerate(chunks):
            db.add(KnowledgeChunk(
                document_id=doc.id, chunk_index=idx, content=chunk,
                embedding_provider="hash384",
            ))
        db.commit()
        vector_count = rebuild_document_vectors(db, document_id)

        doc.indexed = True
        job.status = "completed"
        job.result_json = f'{{"chunks":{len(chunks)},"vectors":{vector_count}}}'
        db.add(doc); db.add(job); db.commit()
        return {"status": "completed", "chunks": len(chunks), "vectors": vector_count}
    except Exception as exc:
        if job:
            job.status = "failed"; job.error = str(exc); db.add(job); db.commit()
        raise
    finally:
        db.close()
