import json
from sqlalchemy import or_
from sqlalchemy.orm import Session
from app.models import OrganizationMemory


def remember(db: Session, *, organization_id: int, content: str, memory_type: str = "fact", company_id: int | None = None,
             department_id: int | None = None, project_id: int | None = None, agent_id: int | None = None,
             source_type: str = "manual", source_id: str = "", importance: int = 3, confidence: float = 1.0,
             tags: list[str] | None = None):
    item = OrganizationMemory(
        organization_id=organization_id, company_id=company_id, department_id=department_id, project_id=project_id,
        agent_id=agent_id, memory_type=memory_type, content=content, source_type=source_type, source_id=source_id,
        importance=importance, confidence=confidence, tags_json=json.dumps(tags or [], ensure_ascii=False), status="active",
    )
    db.add(item); db.commit(); db.refresh(item)
    return item


def search_memories(db: Session, organization_id: int, query: str = "", limit: int = 20, company_id: int | None = None):
    q = db.query(OrganizationMemory).filter(
        OrganizationMemory.organization_id == organization_id,
        OrganizationMemory.status == "active",
    )
    if company_id is not None:
        q = q.filter(or_(OrganizationMemory.company_id == company_id, OrganizationMemory.company_id.is_(None)))
    tokens = [x.strip() for x in query.replace(",", " ").split() if len(x.strip()) > 1][:8]
    if tokens:
        q = q.filter(or_(*[OrganizationMemory.content.ilike(f"%{token}%") for token in tokens]))
    return q.order_by(OrganizationMemory.importance.desc(), OrganizationMemory.id.desc()).limit(max(1, min(limit, 100))).all()
