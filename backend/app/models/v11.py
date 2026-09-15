from datetime import datetime
from sqlalchemy import String, Integer, DateTime, ForeignKey, Text, Float, Boolean
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base


class Repository(Base):
    __tablename__ = "repositories"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"), nullable=True, index=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(180))
    provider: Mapped[str] = mapped_column(String(40), default="local")  # local|github|generic_git
    remote_url: Mapped[str] = mapped_column(String(1000), default="")
    default_branch: Mapped[str] = mapped_column(String(180), default="main")
    local_path: Mapped[str] = mapped_column(String(1000), default="")
    external_repo_id: Mapped[str] = mapped_column(String(240), default="")
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class RepositoryIdentityCredential(Base):
    """Credential metadata only. Secrets live in an external secret manager or environment."""
    __tablename__ = "repository_identity_credentials"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    repository_id: Mapped[int] = mapped_column(ForeignKey("repositories.id"), index=True)
    member_id: Mapped[int | None] = mapped_column(ForeignKey("members.id"), nullable=True, index=True)
    agent_id: Mapped[int | None] = mapped_column(ForeignKey("agents.id"), nullable=True, index=True)
    provider_subject: Mapped[str] = mapped_column(String(240), default="")
    secret_ref: Mapped[str] = mapped_column(String(500), default="")
    permissions_json: Mapped[str] = mapped_column(Text, default="[]")
    branch_pattern: Mapped[str] = mapped_column(String(240), default="*")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class DeliveryPipeline(Base):
    __tablename__ = "delivery_pipelines"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    repository_id: Mapped[int] = mapped_column(ForeignKey("repositories.id"), index=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(180))
    target_branch: Mapped[str] = mapped_column(String(180), default="main")
    test_profile_id: Mapped[int | None] = mapped_column(ForeignKey("repository_test_profiles.id"), nullable=True)
    require_tests: Mapped[bool] = mapped_column(Boolean, default=True)
    require_review: Mapped[bool] = mapped_column(Boolean, default=True)
    required_approvals: Mapped[int] = mapped_column(Integer, default=1)
    merge_strategy: Mapped[str] = mapped_column(String(32), default="merge")  # merge|squash|rebase
    auto_merge: Mapped[bool] = mapped_column(Boolean, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class RepositoryTestProfile(Base):
    __tablename__ = "repository_test_profiles"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    repository_id: Mapped[int] = mapped_column(ForeignKey("repositories.id"), index=True)
    name: Mapped[str] = mapped_column(String(180))
    commands_json: Mapped[str] = mapped_column(Text, default="[]")
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=300)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class DeliveryRun(Base):
    __tablename__ = "delivery_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    pipeline_id: Mapped[int | None] = mapped_column(ForeignKey("delivery_pipelines.id"), nullable=True, index=True)
    repository_id: Mapped[int] = mapped_column(ForeignKey("repositories.id"), index=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), nullable=True, index=True)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id"), nullable=True, index=True)
    initiated_by_member_id: Mapped[int | None] = mapped_column(ForeignKey("members.id"), nullable=True)
    initiated_by_agent_id: Mapped[int | None] = mapped_column(ForeignKey("agents.id"), nullable=True)
    artifact_bundle_key: Mapped[str] = mapped_column(String(180), default="", index=True)
    source_branch: Mapped[str] = mapped_column(String(180), default="")
    target_branch: Mapped[str] = mapped_column(String(180), default="main")
    status: Mapped[str] = mapped_column(String(40), default="queued", index=True)
    worktree_path: Mapped[str] = mapped_column(String(1000), default="")
    base_commit_sha: Mapped[str] = mapped_column(String(80), default="")
    head_commit_sha: Mapped[str] = mapped_column(String(80), default="")
    patch_artifact_id: Mapped[int | None] = mapped_column(ForeignKey("artifacts.id"), nullable=True)
    merge_request_id: Mapped[int | None] = mapped_column(ForeignKey("repository_merge_requests.id"), nullable=True)
    error: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class DeliveryArtifact(Base):
    __tablename__ = "delivery_artifacts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    delivery_run_id: Mapped[int] = mapped_column(ForeignKey("delivery_runs.id"), index=True)
    artifact_id: Mapped[int] = mapped_column(ForeignKey("artifacts.id"), index=True)
    logical_path: Mapped[str] = mapped_column(String(500), default="")
    status: Mapped[str] = mapped_column(String(32), default="materialized")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class RepositoryTestRun(Base):
    __tablename__ = "repository_test_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    delivery_run_id: Mapped[int] = mapped_column(ForeignKey("delivery_runs.id"), index=True)
    profile_id: Mapped[int | None] = mapped_column(ForeignKey("repository_test_profiles.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    summary_json: Mapped[str] = mapped_column(Text, default="{}")
    log_text: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class RepositoryReview(Base):
    __tablename__ = "repository_reviews"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    delivery_run_id: Mapped[int] = mapped_column(ForeignKey("delivery_runs.id"), index=True)
    reviewer_member_id: Mapped[int | None] = mapped_column(ForeignKey("members.id"), nullable=True, index=True)
    reviewer_agent_id: Mapped[int | None] = mapped_column(ForeignKey("agents.id"), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    verdict: Mapped[str] = mapped_column(String(32), default="pending")  # approve|changes_requested|reject
    score: Mapped[float] = mapped_column(Float, default=0)
    summary: Mapped[str] = mapped_column(Text, default="")
    findings_json: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class RepositoryMergeRequest(Base):
    __tablename__ = "repository_merge_requests"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    repository_id: Mapped[int] = mapped_column(ForeignKey("repositories.id"), index=True)
    delivery_run_id: Mapped[int] = mapped_column(ForeignKey("delivery_runs.id"), unique=True, index=True)
    provider: Mapped[str] = mapped_column(String(40), default="local")
    external_id: Mapped[str] = mapped_column(String(160), default="")
    title: Mapped[str] = mapped_column(String(240), default="")
    source_branch: Mapped[str] = mapped_column(String(180))
    target_branch: Mapped[str] = mapped_column(String(180))
    status: Mapped[str] = mapped_column(String(32), default="open", index=True)
    url: Mapped[str] = mapped_column(String(1000), default="")
    merge_commit_sha: Mapped[str] = mapped_column(String(80), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    merged_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class RepositoryConflict(Base):
    __tablename__ = "repository_conflicts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    delivery_run_id: Mapped[int] = mapped_column(ForeignKey("delivery_runs.id"), index=True)
    path: Mapped[str] = mapped_column(String(500), default="")
    conflict_type: Mapped[str] = mapped_column(String(64), default="content")
    status: Mapped[str] = mapped_column(String(32), default="open", index=True)
    resolution: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class RepositoryRollback(Base):
    __tablename__ = "repository_rollbacks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    repository_id: Mapped[int] = mapped_column(ForeignKey("repositories.id"), index=True)
    merge_request_id: Mapped[int | None] = mapped_column(ForeignKey("repository_merge_requests.id"), nullable=True)
    requested_by_member_id: Mapped[int | None] = mapped_column(ForeignKey("members.id"), nullable=True)
    reverted_commit_sha: Mapped[str] = mapped_column(String(80))
    rollback_commit_sha: Mapped[str] = mapped_column(String(80), default="")
    status: Mapped[str] = mapped_column(String(32), default="queued")
    reason: Mapped[str] = mapped_column(Text, default="")
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class EventWebhookEndpoint(Base):
    __tablename__ = "event_webhook_endpoints"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(180))
    target_url: Mapped[str] = mapped_column(String(1000))
    event_pattern: Mapped[str] = mapped_column(String(180), default="*")
    secret_ref: Mapped[str] = mapped_column(String(500), default="")
    max_attempts: Mapped[int] = mapped_column(Integer, default=5)
    backoff_seconds: Mapped[int] = mapped_column(Integer, default=30)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class EventWebhookDelivery(Base):
    __tablename__ = "event_webhook_deliveries"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    endpoint_id: Mapped[int] = mapped_column(ForeignKey("event_webhook_endpoints.id"), index=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("company_events.id"), index=True)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    response_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_body: Mapped[str] = mapped_column(Text, default="")
    error: Mapped[str] = mapped_column(Text, default="")
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
