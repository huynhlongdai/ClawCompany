from datetime import datetime
from pydantic import BaseModel, Field


class AgentTeamCreate(BaseModel):
    organization_id: int
    team_key: str = Field(min_length=2, max_length=120)
    name: str
    mission: str = ""
    company_id: int | None = None
    lead_member_id: int | None = None
    collaboration_mode: str = "lead_routed"
    cross_company: bool = False


class AgentTeamMemberAdd(BaseModel):
    member_id: int
    team_role: str = "contributor"
    capabilities: list[str] = []
    allocation_percent: int = Field(default=100, ge=0, le=100)


class CollaborationRoomCreate(BaseModel):
    organization_id: int
    room_key: str = Field(min_length=2, max_length=120)
    topic: str = ""
    objective: str = ""
    company_id: int | None = None
    team_id: int | None = None
    project_id: int | None = None
    mode: str = "lead_routed"
    max_turns: int = Field(default=200, ge=1, le=5000)
    created_by_member_id: int | None = None
    seed_team_participants: bool = True


class RoomParticipantAdd(BaseModel):
    member_id: int
    participant_role: str = "contributor"
    can_post: bool = True
    can_decide: bool = False


class RoomTurnCreate(BaseModel):
    member_id: int
    content: str
    turn_type: str = "message"
    references: dict = {}
    knowledge_entry_ids: list[int] = []


class RoomCloseRequest(BaseModel):
    summary: str = ""
    publish_to_space_id: int | None = None
    member_id: int | None = None


class DelegationProposeRequest(BaseModel):
    organization_id: int
    from_member_id: int
    to_member_id: int
    title: str
    objective: str = ""
    acceptance_criteria: str = ""
    company_id: int | None = None
    room_id: int | None = None
    team_id: int | None = None
    task_id: int | None = None
    scope: dict = {}
    max_cost_usd: float = 0.0
    deadline_at: datetime | None = None


class DelegationDecisionRequest(BaseModel):
    member_id: int
    reason: str = ""


class DelegationDeliverRequest(BaseModel):
    member_id: int
    result_summary: str = ""
    delivery_artifact_id: int | None = None


class DelegationCompleteRequest(BaseModel):
    member_id: int
    accepted: bool = True
    reason: str = ""


class KnowledgeSpaceCreate(BaseModel):
    organization_id: int
    slug: str = Field(min_length=2, max_length=120)
    name: str
    description: str = ""
    owner_company_id: int | None = None
    classification: str = "restricted"
    default_permission: str = "none"


class KnowledgeGrantCreate(BaseModel):
    grantee_type: str
    grantee_id: int
    permission: str = "read"
    reason: str = ""
    granted_by_member_id: int | None = None
    expires_at: datetime | None = None


class KnowledgeEntryCreate(BaseModel):
    member_id: int
    title: str
    content: str
    summary: str = ""
    entry_type: str = "note"
    tags: list[str] = []
    room_id: int | None = None
    document_id: int | None = None
    supersedes_entry_id: int | None = None
    mirror_to_org_memory: bool = False


class KnowledgeSearchRequest(BaseModel):
    member_id: int
    query: str = ""
    space_ids: list[int] = []
    limit: int = Field(default=20, ge=1, le=100)
