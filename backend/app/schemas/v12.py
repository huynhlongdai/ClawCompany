from datetime import datetime
from pydantic import BaseModel, Field


class WorkspaceCreate(BaseModel):
    organization_id: int
    company_id: int | None = None
    project_id: int | None = None
    repository_id: int | None = None
    owner_member_id: int | None = None
    owner_agent_id: int | None = None
    name: str = Field(min_length=1, max_length=180)
    workspace_key: str = Field(min_length=1, max_length=180)
    base_ref: str = ""
    ttl_minutes: int | None = Field(default=720, ge=5, le=10080)


class SandboxProfileCreate(BaseModel):
    organization_id: int
    company_id: int | None = None
    name: str = Field(min_length=1, max_length=180)
    image: str = "python:3.12-slim"
    provider: str = Field(default="mock", pattern="^(mock|docker|kubernetes|microvm)$")
    cpu_limit: float = Field(default=1.0, ge=0.1, le=16)
    memory_mb: int = Field(default=1024, ge=128, le=32768)
    pids_limit: int = Field(default=256, ge=32, le=4096)
    timeout_seconds: int = Field(default=900, ge=5, le=7200)
    network_mode: str = Field(default="none", pattern="^(none|restricted)$")
    read_only_root: bool = True
    allowed_commands: list[str] = Field(default_factory=list)
    enabled: bool = True


class SandboxRunCreate(BaseModel):
    workspace_id: int
    profile_id: int
    delivery_run_id: int | None = None
    initiated_by_member_id: int | None = None
    initiated_by_agent_id: int | None = None
    purpose: str = Field(default="test", pattern="^(code|build|test|lint|review|utility)$")
    command: list[str] = Field(min_length=1)
    secret_grant_ids: list[int] = Field(default_factory=list)


class SecretReferenceCreate(BaseModel):
    organization_id: int
    company_id: int | None = None
    name: str = Field(min_length=1, max_length=180)
    provider: str = Field(default="env", pattern="^(env|vault|aws|gcp|azure)$")
    external_ref: str = Field(min_length=1, max_length=700)
    description: str = ""
    classification: str = Field(default="confidential", pattern="^(internal|confidential|restricted)$")


class SecretGrantCreate(BaseModel):
    secret_reference_id: int
    member_id: int | None = None
    agent_id: int | None = None
    sandbox_profile_id: int | None = None
    environment_id: int | None = None
    mount_name: str = Field(default="", max_length=180)
    permissions: list[str] = Field(default_factory=lambda: ["read"])
    expires_at: datetime | None = None


class DeploymentEnvironmentCreate(BaseModel):
    organization_id: int
    company_id: int | None = None
    project_id: int | None = None
    repository_id: int
    name: str = Field(min_length=1, max_length=180)
    slug: str = Field(min_length=1, max_length=120)
    environment_type: str = Field(default="preview", pattern="^(preview|staging|production)$")
    provider: str = Field(default="filesystem", pattern="^(filesystem|generic|kubernetes)$")
    target_ref: str = ""
    base_url: str = ""
    require_approval: bool = False
    approval_risk: str = Field(default="high", pattern="^(low|medium|high|critical)$")
    auto_deploy: bool = False


class ReleaseCreate(BaseModel):
    repository_id: int
    project_id: int | None = None
    delivery_run_id: int | None = None
    merge_request_id: int | None = None
    version: str = Field(min_length=1, max_length=120)
    commit_sha: str = Field(default="", max_length=80)
    release_notes: str = ""
    manifest: dict = Field(default_factory=dict)
    artifact_ids: list[int] = Field(default_factory=list)


class DeployRequest(BaseModel):
    environment_id: int
    requested_by_member_id: int | None = None


class RollbackDeploymentRequest(BaseModel):
    reason: str = ""
    requested_by_member_id: int | None = None


class DeliveryAutomationRuleCreate(BaseModel):
    organization_id: int
    repository_id: int
    pipeline_id: int | None = None
    project_id: int | None = None
    name: str = Field(min_length=1, max_length=180)
    handoff_purpose: str = Field(default="commit", max_length=80)
    target_member_id: int | None = None
    target_branch: str = "main"
    auto_prepare: bool = False
    auto_test: bool = False
    enabled: bool = True
