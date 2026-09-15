from datetime import datetime
from sqlalchemy import String, Integer, DateTime, ForeignKey, Text, Float, Boolean
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base


class DevWorkspace(Base):
    __tablename__ = "dev_workspaces"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"), nullable=True, index=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), nullable=True, index=True)
    repository_id: Mapped[int | None] = mapped_column(ForeignKey("repositories.id"), nullable=True, index=True)
    owner_member_id: Mapped[int | None] = mapped_column(ForeignKey("members.id"), nullable=True, index=True)
    owner_agent_id: Mapped[int | None] = mapped_column(ForeignKey("agents.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(180))
    workspace_key: Mapped[str] = mapped_column(String(180), index=True)
    root_path: Mapped[str] = mapped_column(String(1000), default="")
    base_ref: Mapped[str] = mapped_column(String(180), default="")
    status: Mapped[str] = mapped_column(String(32), default="ready", index=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class SandboxProfile(Base):
    __tablename__ = "sandbox_profiles"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(180))
    image: Mapped[str] = mapped_column(String(300), default="python:3.12-slim")
    provider: Mapped[str] = mapped_column(String(40), default="mock")  # mock|docker|kubernetes
    cpu_limit: Mapped[float] = mapped_column(Float, default=1.0)
    memory_mb: Mapped[int] = mapped_column(Integer, default=1024)
    pids_limit: Mapped[int] = mapped_column(Integer, default=256)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=900)
    network_mode: Mapped[str] = mapped_column(String(32), default="none")  # none|restricted
    read_only_root: Mapped[bool] = mapped_column(Boolean, default=True)
    allowed_commands_json: Mapped[str] = mapped_column(Text, default="[]")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class SandboxRun(Base):
    __tablename__ = "sandbox_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("dev_workspaces.id"), index=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("sandbox_profiles.id"), index=True)
    delivery_run_id: Mapped[int | None] = mapped_column(ForeignKey("delivery_runs.id"), nullable=True, index=True)
    initiated_by_member_id: Mapped[int | None] = mapped_column(ForeignKey("members.id"), nullable=True)
    initiated_by_agent_id: Mapped[int | None] = mapped_column(ForeignKey("agents.id"), nullable=True)
    purpose: Mapped[str] = mapped_column(String(64), default="test", index=True)
    command_json: Mapped[str] = mapped_column(Text, default="[]")
    secret_grant_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    provider_run_id: Mapped[str] = mapped_column(String(240), default="")
    exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stdout_text: Mapped[str] = mapped_column(Text, default="")
    stderr_text: Mapped[str] = mapped_column(Text, default="")
    error: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class SecretReference(Base):
    """Metadata only. Secret values never belong in the ClawCompany database."""
    __tablename__ = "secret_references"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(180))
    provider: Mapped[str] = mapped_column(String(48), default="env")  # env|vault|aws|gcp|azure
    external_ref: Mapped[str] = mapped_column(String(700))
    description: Mapped[str] = mapped_column(Text, default="")
    classification: Mapped[str] = mapped_column(String(32), default="confidential")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class SecretGrant(Base):
    __tablename__ = "secret_grants"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    secret_reference_id: Mapped[int] = mapped_column(ForeignKey("secret_references.id"), index=True)
    member_id: Mapped[int | None] = mapped_column(ForeignKey("members.id"), nullable=True, index=True)
    agent_id: Mapped[int | None] = mapped_column(ForeignKey("agents.id"), nullable=True, index=True)
    sandbox_profile_id: Mapped[int | None] = mapped_column(ForeignKey("sandbox_profiles.id"), nullable=True, index=True)
    environment_id: Mapped[int | None] = mapped_column(ForeignKey("deployment_environments.id"), nullable=True, index=True)
    mount_name: Mapped[str] = mapped_column(String(180), default="")
    permissions_json: Mapped[str] = mapped_column(Text, default='["read"]')
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class DeploymentEnvironment(Base):
    __tablename__ = "deployment_environments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"), nullable=True, index=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), nullable=True, index=True)
    repository_id: Mapped[int] = mapped_column(ForeignKey("repositories.id"), index=True)
    name: Mapped[str] = mapped_column(String(180))
    slug: Mapped[str] = mapped_column(String(120), index=True)
    environment_type: Mapped[str] = mapped_column(String(32), default="preview", index=True)  # preview|staging|production
    provider: Mapped[str] = mapped_column(String(48), default="filesystem")
    target_ref: Mapped[str] = mapped_column(String(700), default="")
    base_url: Mapped[str] = mapped_column(String(1000), default="")
    require_approval: Mapped[bool] = mapped_column(Boolean, default=False)
    approval_risk: Mapped[str] = mapped_column(String(24), default="high")
    auto_deploy: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Release(Base):
    __tablename__ = "releases"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    repository_id: Mapped[int] = mapped_column(ForeignKey("repositories.id"), index=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), nullable=True, index=True)
    delivery_run_id: Mapped[int | None] = mapped_column(ForeignKey("delivery_runs.id"), nullable=True, index=True)
    merge_request_id: Mapped[int | None] = mapped_column(ForeignKey("repository_merge_requests.id"), nullable=True, index=True)
    created_by_member_id: Mapped[int | None] = mapped_column(ForeignKey("members.id"), nullable=True)
    version: Mapped[str] = mapped_column(String(120), index=True)
    commit_sha: Mapped[str] = mapped_column(String(80), index=True)
    status: Mapped[str] = mapped_column(String(32), default="draft", index=True)
    release_notes: Mapped[str] = mapped_column(Text, default="")
    manifest_json: Mapped[str] = mapped_column(Text, default="{}")
    approval_id: Mapped[int | None] = mapped_column(ForeignKey("approvals.id"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    released_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ReleaseArtifact(Base):
    __tablename__ = "release_artifacts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    release_id: Mapped[int] = mapped_column(ForeignKey("releases.id"), index=True)
    artifact_id: Mapped[int] = mapped_column(ForeignKey("artifacts.id"), index=True)
    purpose: Mapped[str] = mapped_column(String(48), default="source")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class PreviewEnvironment(Base):
    __tablename__ = "preview_environments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    environment_id: Mapped[int] = mapped_column(ForeignKey("deployment_environments.id"), index=True)
    release_id: Mapped[int] = mapped_column(ForeignKey("releases.id"), index=True)
    delivery_run_id: Mapped[int | None] = mapped_column(ForeignKey("delivery_runs.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(180))
    status: Mapped[str] = mapped_column(String(32), default="provisioning", index=True)
    url: Mapped[str] = mapped_column(String(1000), default="")
    provider_ref: Mapped[str] = mapped_column(String(700), default="")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    destroyed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Deployment(Base):
    __tablename__ = "deployments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    environment_id: Mapped[int] = mapped_column(ForeignKey("deployment_environments.id"), index=True)
    release_id: Mapped[int] = mapped_column(ForeignKey("releases.id"), index=True)
    requested_by_member_id: Mapped[int | None] = mapped_column(ForeignKey("members.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    provider_ref: Mapped[str] = mapped_column(String(700), default="")
    deployed_path: Mapped[str] = mapped_column(String(1000), default="")
    previous_deployment_id: Mapped[int | None] = mapped_column(ForeignKey("deployments.id"), nullable=True)
    error: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class DeploymentRollback(Base):
    __tablename__ = "deployment_rollbacks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    environment_id: Mapped[int] = mapped_column(ForeignKey("deployment_environments.id"), index=True)
    from_deployment_id: Mapped[int] = mapped_column(ForeignKey("deployments.id"), index=True)
    to_deployment_id: Mapped[int] = mapped_column(ForeignKey("deployments.id"), index=True)
    requested_by_member_id: Mapped[int | None] = mapped_column(ForeignKey("members.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    reason: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class DeliveryAutomationRule(Base):
    __tablename__ = "delivery_automation_rules"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    repository_id: Mapped[int] = mapped_column(ForeignKey("repositories.id"), index=True)
    pipeline_id: Mapped[int | None] = mapped_column(ForeignKey("delivery_pipelines.id"), nullable=True, index=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(180))
    handoff_purpose: Mapped[str] = mapped_column(String(80), default="commit")
    target_member_id: Mapped[int | None] = mapped_column(ForeignKey("members.id"), nullable=True, index=True)
    target_branch: Mapped[str] = mapped_column(String(180), default="main")
    auto_prepare: Mapped[bool] = mapped_column(Boolean, default=False)
    auto_test: Mapped[bool] = mapped_column(Boolean, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
