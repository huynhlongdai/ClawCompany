from pydantic import BaseModel, Field


class RepositoryCreate(BaseModel):
    organization_id: int
    company_id: int | None = None
    project_id: int | None = None
    name: str = Field(min_length=1, max_length=180)
    provider: str = Field(default="local", pattern="^(local|github|generic_git)$")
    remote_url: str = ""
    default_branch: str = "main"
    initialize: bool = True


class RepositoryCredentialCreate(BaseModel):
    member_id: int | None = None
    agent_id: int | None = None
    provider_subject: str = ""
    secret_ref: str = ""
    permissions: list[str] = Field(default_factory=lambda: ["read", "write_branch"])
    branch_pattern: str = "*"


class TestProfileCreate(BaseModel):
    name: str = Field(min_length=1, max_length=180)
    commands: list[str] = Field(default_factory=list)
    timeout_seconds: int = Field(default=300, ge=10, le=3600)
    enabled: bool = True


class DeliveryPipelineCreate(BaseModel):
    repository_id: int
    project_id: int | None = None
    name: str = Field(min_length=1, max_length=180)
    target_branch: str = "main"
    test_profile_id: int | None = None
    require_tests: bool = True
    require_review: bool = True
    required_approvals: int = Field(default=1, ge=0, le=10)
    merge_strategy: str = Field(default="merge", pattern="^(merge|squash|rebase)$")
    auto_merge: bool = False
    enabled: bool = True


class DeliveryRunCreate(BaseModel):
    repository_id: int
    pipeline_id: int | None = None
    project_id: int | None = None
    task_id: int | None = None
    artifact_bundle_key: str = Field(min_length=1, max_length=180)
    target_branch: str | None = None
    source_branch: str | None = None
    initiated_by_member_id: int | None = None
    initiated_by_agent_id: int | None = None


class ReviewCreate(BaseModel):
    reviewer_member_id: int | None = None
    reviewer_agent_id: int | None = None


class ReviewDecision(BaseModel):
    verdict: str = Field(pattern="^(approve|changes_requested|reject)$")
    score: float = Field(default=0, ge=0, le=100)
    summary: str = ""
    findings: list[dict] = Field(default_factory=list)


class MergeRequestCreate(BaseModel):
    title: str = ""


class RollbackRequest(BaseModel):
    reason: str = ""


class ConflictResolutionRequest(BaseModel):
    resolutions: dict[str, str] = Field(min_length=1)
    note: str = ""


class WebhookEndpointCreate(BaseModel):
    organization_id: int
    company_id: int | None = None
    name: str = Field(min_length=1, max_length=180)
    target_url: str = Field(min_length=8, max_length=1000)
    event_pattern: str = "*"
    secret_ref: str = ""
    max_attempts: int = Field(default=5, ge=1, le=20)
    backoff_seconds: int = Field(default=30, ge=1, le=3600)
    enabled: bool = True
