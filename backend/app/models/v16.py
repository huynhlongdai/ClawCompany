"""v16 — Agent Collaboration Fabric & Shared Knowledge Mesh.

These models describe how multiple AI employees (and humans) from different
companies of the same organization work together: durable agent teams,
turn-ordered collaboration rooms, explicit delegation contracts, and a
grant-based shared knowledge mesh.
"""
from datetime import datetime, timezone
from sqlalchemy import String, Integer, DateTime, ForeignKey, Text, Float, Boolean, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class AgentTeam(Base):
    """A durable crew of human/AI members that works on a shared mission."""
    __tablename__ = "agent_teams"
    __table_args__ = (UniqueConstraint("organization_id", "team_key", name="uq_agent_team_org_key"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"), nullable=True, index=True)
    team_key: Mapped[str] = mapped_column(String(120), index=True)
    name: Mapped[str] = mapped_column(String(180))
    mission: Mapped[str] = mapped_column(Text, default="")
    lead_member_id: Mapped[int | None] = mapped_column(ForeignKey("members.id"), nullable=True, index=True)
    collaboration_mode: Mapped[str] = mapped_column(String(32), default="lead_routed")  # lead_routed|round_robin|parallel
    cross_company: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    disbanded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class AgentTeamMember(Base):
    __tablename__ = "agent_team_members"
    __table_args__ = (UniqueConstraint("team_id", "member_id", name="uq_agent_team_member"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("agent_teams.id"), index=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id"), index=True)
    team_role: Mapped[str] = mapped_column(String(32), default="contributor")  # lead|contributor|reviewer|observer
    capabilities_json: Mapped[str] = mapped_column(Text, default="[]")
    turn_order: Mapped[int] = mapped_column(Integer, default=0)
    allocation_percent: Mapped[int] = mapped_column(Integer, default=100)
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    joined_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    left_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class CollaborationRoom(Base):
    """An ordered, auditable working session shared by several members."""
    __tablename__ = "collaboration_rooms"
    __table_args__ = (UniqueConstraint("organization_id", "room_key", name="uq_collab_room_org_key"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"), nullable=True, index=True)
    team_id: Mapped[int | None] = mapped_column(ForeignKey("agent_teams.id"), nullable=True, index=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), nullable=True, index=True)
    room_key: Mapped[str] = mapped_column(String(120), index=True)
    topic: Mapped[str] = mapped_column(String(300), default="")
    objective: Mapped[str] = mapped_column(Text, default="")
    mode: Mapped[str] = mapped_column(String(32), default="lead_routed")  # lead_routed|round_robin|free
    status: Mapped[str] = mapped_column(String(32), default="open", index=True)  # open|locked|closed
    turn_cursor: Mapped[int] = mapped_column(Integer, default=0)
    max_turns: Mapped[int] = mapped_column(Integer, default=200)
    created_by_member_id: Mapped[int | None] = mapped_column(ForeignKey("members.id"), nullable=True)
    summary: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class RoomParticipant(Base):
    __tablename__ = "room_participants"
    __table_args__ = (UniqueConstraint("room_id", "member_id", name="uq_room_participant"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    room_id: Mapped[int] = mapped_column(ForeignKey("collaboration_rooms.id"), index=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id"), index=True)
    participant_role: Mapped[str] = mapped_column(String(32), default="contributor")
    seat_order: Mapped[int] = mapped_column(Integer, default=0)
    can_post: Mapped[bool] = mapped_column(Boolean, default=True)
    can_decide: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    joined_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class RoomTurn(Base):
    __tablename__ = "room_turns"
    __table_args__ = (UniqueConstraint("room_id", "sequence", name="uq_room_turn_sequence"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    room_id: Mapped[int] = mapped_column(ForeignKey("collaboration_rooms.id"), index=True)
    sequence: Mapped[int] = mapped_column(Integer, index=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id"), index=True)
    turn_type: Mapped[str] = mapped_column(String(32), default="message")  # message|proposal|decision|handoff|summary
    content: Mapped[str] = mapped_column(Text, default="")
    references_json: Mapped[str] = mapped_column(Text, default="{}")
    knowledge_entry_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class DelegationContract(Base):
    """Explicit agent-to-agent work contract with an auditable state machine."""
    __tablename__ = "delegation_contracts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"), nullable=True, index=True)
    room_id: Mapped[int | None] = mapped_column(ForeignKey("collaboration_rooms.id"), nullable=True, index=True)
    team_id: Mapped[int | None] = mapped_column(ForeignKey("agent_teams.id"), nullable=True, index=True)
    from_member_id: Mapped[int] = mapped_column(ForeignKey("members.id"), index=True)
    to_member_id: Mapped[int] = mapped_column(ForeignKey("members.id"), index=True)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(240))
    objective: Mapped[str] = mapped_column(Text, default="")
    acceptance_criteria: Mapped[str] = mapped_column(Text, default="")
    scope_json: Mapped[str] = mapped_column(Text, default="{}")
    max_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(32), default="proposed", index=True)
    # proposed|accepted|rejected|delivered|completed|cancelled
    delivery_artifact_id: Mapped[int | None] = mapped_column(ForeignKey("artifacts.id"), nullable=True)
    result_summary: Mapped[str] = mapped_column(Text, default="")
    decision_reason: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class SharedKnowledgeSpace(Base):
    """A governed knowledge boundary that can be shared across companies."""
    __tablename__ = "shared_knowledge_spaces"
    __table_args__ = (UniqueConstraint("organization_id", "slug", name="uq_knowledge_space_org_slug"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    owner_company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"), nullable=True, index=True)
    slug: Mapped[str] = mapped_column(String(120), index=True)
    name: Mapped[str] = mapped_column(String(180))
    description: Mapped[str] = mapped_column(Text, default="")
    classification: Mapped[str] = mapped_column(String(32), default="restricted")  # org_public|restricted|confidential
    default_permission: Mapped[str] = mapped_column(String(24), default="none")  # none|read
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class KnowledgeGrant(Base):
    """Explicit grant of a knowledge space to a company/department/team/member."""
    __tablename__ = "knowledge_grants"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    space_id: Mapped[int] = mapped_column(ForeignKey("shared_knowledge_spaces.id"), index=True)
    grantee_type: Mapped[str] = mapped_column(String(24), index=True)  # company|department|team|member
    grantee_id: Mapped[int] = mapped_column(Integer, index=True)
    permission: Mapped[str] = mapped_column(String(24), default="read")  # read|contribute|admin
    granted_by_member_id: Mapped[int | None] = mapped_column(ForeignKey("members.id"), nullable=True)
    reason: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class SharedKnowledgeEntry(Base):
    __tablename__ = "shared_knowledge_entries"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    space_id: Mapped[int] = mapped_column(ForeignKey("shared_knowledge_spaces.id"), index=True)
    document_id: Mapped[int | None] = mapped_column(ForeignKey("knowledge_documents.id"), nullable=True, index=True)
    memory_id: Mapped[int | None] = mapped_column(ForeignKey("organization_memories.id"), nullable=True, index=True)
    room_id: Mapped[int | None] = mapped_column(ForeignKey("collaboration_rooms.id"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(300))
    summary: Mapped[str] = mapped_column(Text, default="")
    content: Mapped[str] = mapped_column(Text, default="")
    entry_type: Mapped[str] = mapped_column(String(32), default="note")  # note|decision|sop|finding|artifact_ref
    source_type: Mapped[str] = mapped_column(String(48), default="manual")
    source_id: Mapped[str] = mapped_column(String(180), default="")
    contributed_by_member_id: Mapped[int | None] = mapped_column(ForeignKey("members.id"), nullable=True, index=True)
    tags_json: Mapped[str] = mapped_column(Text, default="[]")
    version: Mapped[int] = mapped_column(Integer, default=1)
    supersedes_entry_id: Mapped[int | None] = mapped_column(ForeignKey("shared_knowledge_entries.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class KnowledgeAccessLog(Base):
    __tablename__ = "knowledge_access_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    space_id: Mapped[int] = mapped_column(ForeignKey("shared_knowledge_spaces.id"), index=True)
    member_id: Mapped[int | None] = mapped_column(ForeignKey("members.id"), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(24), index=True)  # search|read|contribute|denied
    permission_used: Mapped[str] = mapped_column(String(24), default="none")
    detail: Mapped[str] = mapped_column(Text, default="")
    result_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
