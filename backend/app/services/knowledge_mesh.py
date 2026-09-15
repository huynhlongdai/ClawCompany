"""v16 shared knowledge mesh.

Agents from different companies can share knowledge, but only through explicit
grants. Permission resolution is deny-by-default and every access attempt
(including denials) is logged.
"""
import json
from datetime import datetime, timezone
from sqlalchemy import or_
from sqlalchemy.orm import Session
from app.models import (SharedKnowledgeSpace, KnowledgeGrant, SharedKnowledgeEntry, KnowledgeAccessLog,
                        AgentTeamMember, Member)
from app.services.company_event_bus import emit_event
from app.services.org_memory import remember


class KnowledgeMeshError(Exception):
    pass


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


PERMISSION_ORDER = {"none": 0, "read": 1, "contribute": 2, "admin": 3}
VALID_GRANTEE_TYPES = ("company", "department", "team", "member")
VALID_CLASSIFICATIONS = ("org_public", "restricted", "confidential")


def create_space(db: Session, *, organization_id: int, slug: str, name: str, description: str = "",
                 owner_company_id: int | None = None, classification: str = "restricted",
                 default_permission: str = "none") -> SharedKnowledgeSpace:
    if classification not in VALID_CLASSIFICATIONS:
        raise KnowledgeMeshError(f"Unsupported classification: {classification}")
    if default_permission not in ("none", "read"):
        raise KnowledgeMeshError("default_permission must be none or read")
    if classification == "confidential" and default_permission != "none":
        raise KnowledgeMeshError("Confidential spaces cannot have an organization-wide default permission")
    if db.query(SharedKnowledgeSpace).filter(SharedKnowledgeSpace.organization_id == organization_id,
                                             SharedKnowledgeSpace.slug == slug).first():
        raise KnowledgeMeshError("Knowledge space slug already exists")
    item = SharedKnowledgeSpace(organization_id=organization_id, owner_company_id=owner_company_id, slug=slug,
                                name=name, description=description, classification=classification,
                                default_permission=default_permission, status="active")
    db.add(item); db.commit(); db.refresh(item)
    emit_event(db, organization_id=organization_id, company_id=owner_company_id,
               event_type="knowledge.space.created", source="knowledge_mesh",
               aggregate_type="shared_knowledge_space", aggregate_id=str(item.id),
               payload={"slug": slug, "classification": classification})
    return item


def grant_access(db: Session, space: SharedKnowledgeSpace, *, grantee_type: str, grantee_id: int,
                 permission: str = "read", reason: str = "", granted_by_member_id: int | None = None,
                 expires_at: datetime | None = None) -> KnowledgeGrant:
    if grantee_type not in VALID_GRANTEE_TYPES:
        raise KnowledgeMeshError(f"Unsupported grantee type: {grantee_type}")
    if permission not in ("read", "contribute", "admin"):
        raise KnowledgeMeshError(f"Unsupported permission: {permission}")
    item = KnowledgeGrant(organization_id=space.organization_id, space_id=space.id, grantee_type=grantee_type,
                          grantee_id=grantee_id, permission=permission, reason=reason,
                          granted_by_member_id=granted_by_member_id, expires_at=expires_at, status="active")
    db.add(item); db.commit(); db.refresh(item)
    emit_event(db, organization_id=space.organization_id, company_id=space.owner_company_id,
               event_type="knowledge.grant.created", source="knowledge_mesh",
               aggregate_type="shared_knowledge_space", aggregate_id=str(space.id),
               actor_member_id=granted_by_member_id,
               payload={"grantee_type": grantee_type, "grantee_id": grantee_id, "permission": permission})
    return item


def revoke_grant(db: Session, grant: KnowledgeGrant) -> KnowledgeGrant:
    grant.status = "revoked"; grant.revoked_at = utcnow()
    db.add(grant); db.commit(); db.refresh(grant)
    return grant


def _grant_applies(grant: KnowledgeGrant, member: Member, team_ids: set[int], moment: datetime) -> bool:
    if grant.status != "active":
        return False
    if grant.expires_at is not None and grant.expires_at < moment:
        return False
    if grant.grantee_type == "member":
        return grant.grantee_id == member.id
    if grant.grantee_type == "company":
        return member.company_id is not None and grant.grantee_id == member.company_id
    if grant.grantee_type == "department":
        return getattr(member, "department_id", None) is not None and grant.grantee_id == member.department_id
    if grant.grantee_type == "team":
        return grant.grantee_id in team_ids
    return False


def effective_permission(db: Session, space: SharedKnowledgeSpace, member_id: int) -> str:
    """Deny-by-default permission resolution for one member on one space."""
    member = db.get(Member, member_id)
    if not member or member.organization_id != space.organization_id:
        return "none"
    if space.status != "active":
        return "none"
    moment = utcnow()
    best = space.default_permission if space.classification != "confidential" else "none"
    if space.owner_company_id is not None and member.company_id == space.owner_company_id:
        best = "contribute" if PERMISSION_ORDER[best] < PERMISSION_ORDER["contribute"] else best
    team_ids = {x.team_id for x in db.query(AgentTeamMember).filter(AgentTeamMember.member_id == member_id,
                                                                    AgentTeamMember.status == "active").all()}
    grants = db.query(KnowledgeGrant).filter(KnowledgeGrant.space_id == space.id,
                                             KnowledgeGrant.status == "active").all()
    for grant in grants:
        if _grant_applies(grant, member, team_ids, moment) and \
                PERMISSION_ORDER[grant.permission] > PERMISSION_ORDER[best]:
            best = grant.permission
    return best


def _log(db: Session, space: SharedKnowledgeSpace, member_id: int | None, action: str, permission: str,
         detail: str = "", result_count: int = 0) -> KnowledgeAccessLog:
    item = KnowledgeAccessLog(organization_id=space.organization_id, space_id=space.id, member_id=member_id,
                             action=action, permission_used=permission, detail=detail, result_count=result_count)
    db.add(item); db.commit(); db.refresh(item)
    return item


def require_permission(db: Session, space: SharedKnowledgeSpace, member_id: int, minimum: str) -> str:
    permission = effective_permission(db, space, member_id)
    if PERMISSION_ORDER[permission] < PERMISSION_ORDER[minimum]:
        _log(db, space, member_id, "denied", permission, detail=f"required={minimum}")
        raise KnowledgeMeshError(f"Member {member_id} lacks {minimum} permission on space {space.slug}")
    return permission


def contribute_entry(db: Session, space: SharedKnowledgeSpace, *, member_id: int, title: str, content: str,
                     summary: str = "", entry_type: str = "note", tags: list[str] | None = None,
                     room_id: int | None = None, document_id: int | None = None,
                     supersedes_entry_id: int | None = None,
                     mirror_to_org_memory: bool = False) -> SharedKnowledgeEntry:
    permission = require_permission(db, space, member_id, "contribute")
    version = 1
    if supersedes_entry_id is not None:
        previous = db.get(SharedKnowledgeEntry, supersedes_entry_id)
        if not previous or previous.space_id != space.id:
            raise KnowledgeMeshError("Superseded entry does not belong to this space")
        version = previous.version + 1
        previous.status = "superseded"
        db.add(previous)
    memory_id = None
    if mirror_to_org_memory:
        memory = remember(db, organization_id=space.organization_id, content=f"{title}\n{content}",
                          memory_type="shared_knowledge", company_id=space.owner_company_id,
                          source_type="knowledge_mesh", source_id=space.slug, tags=tags or [])
        memory_id = memory.id
    item = SharedKnowledgeEntry(organization_id=space.organization_id, space_id=space.id, document_id=document_id,
                                memory_id=memory_id, room_id=room_id, title=title, summary=summary,
                                content=content, entry_type=entry_type, source_type="member",
                                source_id=str(member_id), contributed_by_member_id=member_id,
                                tags_json=json.dumps(tags or [], ensure_ascii=False), version=version,
                                supersedes_entry_id=supersedes_entry_id, status="active")
    db.add(item); db.commit(); db.refresh(item)
    _log(db, space, member_id, "contribute", permission, detail=title, result_count=1)
    emit_event(db, organization_id=space.organization_id, company_id=space.owner_company_id,
               event_type="knowledge.entry.contributed", source="knowledge_mesh",
               aggregate_type="shared_knowledge_space", aggregate_id=str(space.id), actor_member_id=member_id,
               payload={"entry_id": item.id, "title": title, "version": version})
    return item


def readable_spaces(db: Session, organization_id: int, member_id: int) -> list[SharedKnowledgeSpace]:
    spaces = db.query(SharedKnowledgeSpace).filter(SharedKnowledgeSpace.organization_id == organization_id,
                                                   SharedKnowledgeSpace.status == "active").all()
    return [x for x in spaces if PERMISSION_ORDER[effective_permission(db, x, member_id)] >= PERMISSION_ORDER["read"]]


def search(db: Session, *, organization_id: int, member_id: int, query: str = "",
           space_ids: list[int] | None = None, limit: int = 20) -> list[dict]:
    """Search only the spaces this member may read; denied spaces are skipped and logged."""
    candidates = readable_spaces(db, organization_id, member_id)
    if space_ids:
        requested = set(space_ids)
        allowed_ids = {x.id for x in candidates}
        for space_id in requested - allowed_ids:
            space = db.get(SharedKnowledgeSpace, space_id)
            if space and space.organization_id == organization_id:
                _log(db, space, member_id, "denied", "none", detail="search")
        candidates = [x for x in candidates if x.id in requested]
    if not candidates:
        return []
    tokens = [x.strip() for x in query.replace(",", " ").split() if len(x.strip()) > 1][:8]
    q = db.query(SharedKnowledgeEntry).filter(
        SharedKnowledgeEntry.space_id.in_([x.id for x in candidates]),
        SharedKnowledgeEntry.status == "active")
    if tokens:
        conditions = []
        for token in tokens:
            conditions.append(SharedKnowledgeEntry.title.ilike(f"%{token}%"))
            conditions.append(SharedKnowledgeEntry.content.ilike(f"%{token}%"))
        q = q.filter(or_(*conditions))
    rows = q.order_by(SharedKnowledgeEntry.id.desc()).limit(max(1, min(limit, 100))).all()
    by_space: dict[int, SharedKnowledgeSpace] = {x.id: x for x in candidates}
    for space in candidates:
        hits = len([r for r in rows if r.space_id == space.id])
        _log(db, space, member_id, "search", effective_permission(db, space, member_id),
             detail=query, result_count=hits)
    return [{"entry_id": r.id, "space_id": r.space_id, "space_slug": by_space[r.space_id].slug,
             "title": r.title, "summary": r.summary, "entry_type": r.entry_type, "version": r.version,
             "contributed_by_member_id": r.contributed_by_member_id,
             "content": r.content[:4000]} for r in rows]


def publish_room_summary(db: Session, space: SharedKnowledgeSpace, *, member_id: int, room_id: int,
                         title: str, summary: str) -> SharedKnowledgeEntry:
    return contribute_entry(db, space, member_id=member_id, title=title, content=summary, summary=summary[:500],
                            entry_type="decision", room_id=room_id, tags=["collaboration", "room-summary"])
