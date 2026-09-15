import json
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.authz import Principal, enforce_org, require_human, require_role, require_scope
from app.core.tenancy import active_org, ensure_agent, ensure_company, ensure_member, ensure_project, ensure_task
from app.db.session import get_db
from app.models import (
    Agent, DeliveryArtifact, DeliveryPipeline, DeliveryRun, Member, Project, Repository,
    EventWebhookDelivery, EventWebhookEndpoint, RepositoryConflict, RepositoryIdentityCredential, RepositoryMergeRequest, RepositoryReview,
    RepositoryRollback, RepositoryTestProfile, RepositoryTestRun,
)
from app.schemas.v11 import (
    ConflictResolutionRequest, DeliveryPipelineCreate, DeliveryRunCreate, MergeRequestCreate, RepositoryCreate,
    RepositoryCredentialCreate, ReviewCreate, ReviewDecision, RollbackRequest, TestProfileCreate, WebhookEndpointCreate,
)
from app.services.event_webhooks import WebhookDeliveryError, deliver_webhook, validate_webhook_url
from app.services.repository_providers import RepositoryProviderError, find_credential, git_http_auth_env
from app.services.repository_delivery import (
    RepositoryDeliveryError, cleanup_worktree, create_merge_request, create_review, credential_allows,
    decide_review, delivery_gate, initialize_repository, merge_delivery, prepare_delivery,
    repository_state, resolve_delivery_conflicts, rollback_merge, run_tests, sync_repository_checkout,
)

router = APIRouter(prefix="/v11", tags=["v11-repository-delivery"])


def _repo(db: Session, repo_id: int, principal: Principal) -> Repository:
    item = db.get(Repository, repo_id)
    if not item:
        raise HTTPException(404, "Repository not found")
    enforce_org(item.organization_id, principal)
    return item


def _delivery(db: Session, run_id: int, principal: Principal) -> DeliveryRun:
    item = db.get(DeliveryRun, run_id)
    if not item:
        raise HTTPException(404, "Delivery run not found")
    enforce_org(item.organization_id, principal)
    return item


def _member_has_permission(db: Session, principal: Principal, repo: Repository, permission: str, branch: str = "") -> bool:
    # Admin/owner human users are repository operators by default. All agent/API-key access
    # must be explicitly bound to an identity credential.
    if principal.auth_type == "jwt" and principal.role in {"admin", "owner"}:
        return True
    if principal.member_id is None:
        return False
    credentials = db.query(RepositoryIdentityCredential).filter(
        RepositoryIdentityCredential.organization_id == repo.organization_id,
        RepositoryIdentityCredential.repository_id == repo.id,
        RepositoryIdentityCredential.member_id == principal.member_id,
        RepositoryIdentityCredential.is_active == True,  # noqa: E712
    ).all()
    return any(credential_allows(x, permission, branch) for x in credentials)




def _provider_credential(db: Session, principal: Principal, repo: Repository, permission: str, branch: str = ""):
    if repo.provider == "local":
        return None
    if principal.member_id is None:
        raise HTTPException(403, "Remote repository actions require a credential bound to the current member identity")
    try:
        return find_credential(db, repo, permission=permission, branch=branch, member_id=principal.member_id)
    except RepositoryProviderError as exc:
        raise HTTPException(403, str(exc))

def _require_repo_permission(db: Session, principal: Principal, repo: Repository, permission: str, branch: str = ""):
    if not _member_has_permission(db, principal, repo, permission, branch):
        raise HTTPException(403, f"Repository permission required: {permission}")


@router.post("/repositories")
def create_repository(payload: RepositoryCreate, principal: Principal = Depends(require_role("admin")), db: Session = Depends(get_db)):
    enforce_org(payload.organization_id, principal)
    if payload.company_id is not None:
        ensure_company(db, payload.company_id, principal)
    if payload.project_id is not None:
        ensure_project(db, payload.project_id, principal)
    item = Repository(
        organization_id=payload.organization_id, company_id=payload.company_id, project_id=payload.project_id,
        name=payload.name, provider=payload.provider, remote_url=payload.remote_url,
        default_branch=payload.default_branch, status="active",
    )
    db.add(item); db.commit(); db.refresh(item)
    if payload.initialize:
        try:
            initialize_repository(item); db.add(item); db.commit(); db.refresh(item)
        except RepositoryDeliveryError as exc:
            item.status = "setup_failed"; db.add(item); db.commit()
            raise HTTPException(400, str(exc))
    return item


@router.get("/repositories")
def list_repositories(principal: Principal = Depends(require_scope("company.repositories:read")), db: Session = Depends(get_db)):
    return db.query(Repository).filter(Repository.organization_id == active_org(principal)).order_by(Repository.id.desc()).all()


@router.get("/repositories/{repository_id}")
def repository_detail(repository_id: int, principal: Principal = Depends(require_scope("company.repositories:read")), db: Session = Depends(get_db)):
    repo = _repo(db, repository_id, principal)
    try:
        state = repository_state(repo) if repo.local_path else None
    except RepositoryDeliveryError as exc:
        state = {"error": str(exc)}
    pipelines = db.query(DeliveryPipeline).filter(DeliveryPipeline.repository_id == repo.id).order_by(DeliveryPipeline.id.desc()).all()
    credentials = db.query(RepositoryIdentityCredential).filter(RepositoryIdentityCredential.repository_id == repo.id).order_by(RepositoryIdentityCredential.id.desc()).all()
    return {"repository": repo, "state": state, "pipelines": pipelines, "credential_bindings": credentials}


@router.post("/repositories/{repository_id}/sync")
def sync_repository(repository_id: int, principal: Principal = Depends(require_scope("company.repositories:read")), db: Session = Depends(get_db)):
    repo = _repo(db, repository_id, principal)
    credential = _provider_credential(db, principal, repo, "read", repo.default_branch) if repo.provider != "local" else None
    try:
        state = sync_repository_checkout(repo, git_http_auth_env(credential) if credential else None)
        db.add(repo); db.commit(); db.refresh(repo)
        return {"repository": repo, "state": state}
    except (RepositoryDeliveryError, RepositoryProviderError) as exc:
        raise HTTPException(400, str(exc))


@router.post("/repositories/{repository_id}/credentials")
def bind_credential(repository_id: int, payload: RepositoryCredentialCreate, principal: Principal = Depends(require_role("admin")), db: Session = Depends(get_db)):
    repo = _repo(db, repository_id, principal)
    if payload.member_id is None and payload.agent_id is None:
        raise HTTPException(400, "member_id or agent_id is required")
    if payload.member_id is not None:
        ensure_member(db, payload.member_id, principal)
    if payload.agent_id is not None:
        agent = db.get(Agent, payload.agent_id)
        if not agent:
            raise HTTPException(404, "Agent not found")
        member = db.get(Member, agent.member_id)
        if not member or member.organization_id != repo.organization_id:
            raise HTTPException(400, "Agent does not belong to repository organization")
    item = RepositoryIdentityCredential(
        organization_id=repo.organization_id, repository_id=repo.id, member_id=payload.member_id,
        agent_id=payload.agent_id, provider_subject=payload.provider_subject, secret_ref=payload.secret_ref,
        permissions_json=json.dumps(payload.permissions), branch_pattern=payload.branch_pattern, is_active=True,
    )
    db.add(item); db.commit(); db.refresh(item)
    return item


@router.post("/repositories/{repository_id}/test-profiles")
def create_test_profile(repository_id: int, payload: TestProfileCreate, principal: Principal = Depends(require_role("admin")), db: Session = Depends(get_db)):
    repo = _repo(db, repository_id, principal)
    item = RepositoryTestProfile(
        organization_id=repo.organization_id, repository_id=repo.id, name=payload.name,
        commands_json=json.dumps(payload.commands), timeout_seconds=payload.timeout_seconds, enabled=payload.enabled,
    )
    db.add(item); db.commit(); db.refresh(item)
    return item


@router.post("/pipelines")
def create_pipeline(payload: DeliveryPipelineCreate, principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    repo = _repo(db, payload.repository_id, principal)
    _require_repo_permission(db, principal, repo, "write_branch", payload.target_branch)
    if payload.require_tests and payload.test_profile_id is None:
        raise HTTPException(400, "test_profile_id is required when require_tests=true")
    if payload.test_profile_id is not None:
        profile = db.get(RepositoryTestProfile, payload.test_profile_id)
        if not profile or profile.organization_id != repo.organization_id or profile.repository_id != repo.id:
            raise HTTPException(400, "Invalid test profile")
    item = DeliveryPipeline(organization_id=repo.organization_id, **payload.model_dump())
    db.add(item); db.commit(); db.refresh(item)
    return item


@router.get("/pipelines")
def list_pipelines(repository_id: int | None = None, principal: Principal = Depends(require_scope("company.repositories:read")), db: Session = Depends(get_db)):
    q = db.query(DeliveryPipeline).filter(DeliveryPipeline.organization_id == active_org(principal))
    if repository_id is not None:
        _repo(db, repository_id, principal); q = q.filter(DeliveryPipeline.repository_id == repository_id)
    return q.order_by(DeliveryPipeline.id.desc()).all()


@router.post("/deliveries")
def create_delivery(payload: DeliveryRunCreate, principal: Principal = Depends(require_scope("company.delivery:write")), db: Session = Depends(get_db)):
    repo = _repo(db, payload.repository_id, principal)
    pipeline = None
    if payload.pipeline_id is not None:
        pipeline = db.get(DeliveryPipeline, payload.pipeline_id)
        if not pipeline or pipeline.organization_id != repo.organization_id or pipeline.repository_id != repo.id:
            raise HTTPException(400, "Invalid delivery pipeline")
    target = payload.target_branch or (pipeline.target_branch if pipeline else repo.default_branch)
    _require_repo_permission(db, principal, repo, "write_branch", target)
    if payload.task_id is not None:
        ensure_task(db, payload.task_id, principal)
    if payload.initiated_by_member_id is not None:
        ensure_member(db, payload.initiated_by_member_id, principal)
    if payload.initiated_by_agent_id is not None:
        agent = ensure_agent(db, payload.initiated_by_agent_id, principal)
        if payload.initiated_by_member_id is not None and agent.member_id != payload.initiated_by_member_id:
            raise HTTPException(400, "initiated_by_agent_id does not match initiated_by_member_id")
    # API keys are identity-bound: they may not claim a different member.
    if principal.auth_type == "api_key" and principal.member_id != payload.initiated_by_member_id:
        raise HTTPException(403, "API key may only initiate delivery as its bound member identity")
    item = DeliveryRun(
        organization_id=repo.organization_id, repository_id=repo.id, pipeline_id=payload.pipeline_id,
        project_id=payload.project_id or repo.project_id, task_id=payload.task_id,
        artifact_bundle_key=payload.artifact_bundle_key, target_branch=target,
        source_branch=payload.source_branch or "", initiated_by_member_id=payload.initiated_by_member_id or principal.member_id,
        initiated_by_agent_id=payload.initiated_by_agent_id, status="queued",
    )
    db.add(item); db.commit(); db.refresh(item)
    return item


@router.get("/deliveries")
def list_deliveries(status: str | None = None, repository_id: int | None = None, limit: int = Query(default=100, ge=1, le=500),
                    principal: Principal = Depends(require_scope("company.repositories:read")), db: Session = Depends(get_db)):
    q = db.query(DeliveryRun).filter(DeliveryRun.organization_id == active_org(principal))
    if status: q = q.filter(DeliveryRun.status == status)
    if repository_id is not None:
        _repo(db, repository_id, principal); q = q.filter(DeliveryRun.repository_id == repository_id)
    return q.order_by(DeliveryRun.id.desc()).limit(limit).all()


@router.get("/deliveries/{run_id}")
def delivery_detail(run_id: int, principal: Principal = Depends(require_scope("company.repositories:read")), db: Session = Depends(get_db)):
    run = _delivery(db, run_id, principal)
    return {
        "delivery": run,
        "gate": delivery_gate(db, run),
        "artifacts": db.query(DeliveryArtifact).filter(DeliveryArtifact.delivery_run_id == run.id).all(),
        "tests": db.query(RepositoryTestRun).filter(RepositoryTestRun.delivery_run_id == run.id).order_by(RepositoryTestRun.id.desc()).all(),
        "reviews": db.query(RepositoryReview).filter(RepositoryReview.delivery_run_id == run.id).order_by(RepositoryReview.id.desc()).all(),
        "conflicts": db.query(RepositoryConflict).filter(RepositoryConflict.delivery_run_id == run.id).order_by(RepositoryConflict.id.desc()).all(),
        "merge_request": db.query(RepositoryMergeRequest).filter(RepositoryMergeRequest.delivery_run_id == run.id).first(),
    }


@router.post("/deliveries/{run_id}/prepare")
def prepare(run_id: int, principal: Principal = Depends(require_scope("company.delivery:write")), db: Session = Depends(get_db)):
    run = _delivery(db, run_id, principal); repo = _repo(db, run.repository_id, principal)
    _require_repo_permission(db, principal, repo, "write_branch", run.target_branch)
    try:
        return prepare_delivery(db, run)
    except RepositoryDeliveryError as exc:
        run.status = "failed"; run.error = str(exc); db.add(run); db.commit()
        raise HTTPException(400, str(exc))


@router.post("/deliveries/{run_id}/enqueue")
def enqueue_stage(run_id: int, stage: str = Query(pattern="^(prepare|tests)$"), principal: Principal = Depends(require_scope("company.delivery:write")), db: Session = Depends(get_db)):
    run = _delivery(db, run_id, principal); repo = _repo(db, run.repository_id, principal)
    _require_repo_permission(db, principal, repo, "write_branch", run.target_branch)
    from app.tasks.delivery import prepare_delivery_task, run_delivery_tests_task
    job = prepare_delivery_task.delay(run.id) if stage == "prepare" else run_delivery_tests_task.delay(run.id)
    return {"queued": True, "stage": stage, "delivery_run_id": run.id, "celery_task_id": job.id}


@router.post("/deliveries/{run_id}/tests")
def execute_tests(run_id: int, principal: Principal = Depends(require_scope("company.delivery:write")), db: Session = Depends(get_db)):
    run = _delivery(db, run_id, principal); repo = _repo(db, run.repository_id, principal)
    _require_repo_permission(db, principal, repo, "write_branch", run.source_branch)
    pipeline = db.get(DeliveryPipeline, run.pipeline_id) if run.pipeline_id else None
    profile = db.get(RepositoryTestProfile, pipeline.test_profile_id) if pipeline and pipeline.test_profile_id else None
    if not profile:
        raise HTTPException(400, "Delivery pipeline has no test profile")
    try:
        return run_tests(db, run, profile)
    except RepositoryDeliveryError as exc:
        raise HTTPException(400, str(exc))


@router.post("/deliveries/{run_id}/reviews")
def request_review(run_id: int, payload: ReviewCreate, principal: Principal = Depends(require_scope("company.delivery:write")), db: Session = Depends(get_db)):
    run = _delivery(db, run_id, principal)
    if payload.reviewer_member_id is not None:
        ensure_member(db, payload.reviewer_member_id, principal)
    if payload.reviewer_agent_id is not None:
        ensure_agent(db, payload.reviewer_agent_id, principal)
    try:
        return create_review(db, run, payload.reviewer_member_id, payload.reviewer_agent_id)
    except RepositoryDeliveryError as exc:
        raise HTTPException(400, str(exc))


@router.post("/reviews/{review_id}/decision")
def review_decision(review_id: int, payload: ReviewDecision, principal: Principal = Depends(require_scope("company.delivery:review")), db: Session = Depends(get_db)):
    review = db.get(RepositoryReview, review_id)
    if not review:
        raise HTTPException(404, "Review not found")
    enforce_org(review.organization_id, principal)
    if principal.auth_type == "api_key" and review.reviewer_member_id != principal.member_id:
        raise HTTPException(403, "API key is not bound to this reviewer")
    if principal.auth_type == "jwt" and review.reviewer_member_id and principal.member_id and review.reviewer_member_id != principal.member_id and principal.role not in {"admin", "owner"}:
        raise HTTPException(403, "Review is assigned to another member")
    return decide_review(db, review, **payload.model_dump())


@router.post("/deliveries/{run_id}/merge-request")
def open_merge_request(run_id: int, payload: MergeRequestCreate, principal: Principal = Depends(require_scope("company.delivery:write")), db: Session = Depends(get_db)):
    run = _delivery(db, run_id, principal); repo = _repo(db, run.repository_id, principal)
    _require_repo_permission(db, principal, repo, "create_pr", run.target_branch)
    credential = _provider_credential(db, principal, repo, "create_pr", run.target_branch) if repo.provider != "local" else None
    try:
        return create_merge_request(db, run, payload.title, provider_credential=credential)
    except RepositoryDeliveryError as exc:
        raise HTTPException(400, str(exc))


@router.post("/deliveries/{run_id}/merge")
def merge(run_id: int, principal: Principal = Depends(require_scope("company.delivery:merge")), db: Session = Depends(get_db)):
    run = _delivery(db, run_id, principal); repo = _repo(db, run.repository_id, principal)
    _require_repo_permission(db, principal, repo, "merge", run.target_branch)
    credential = _provider_credential(db, principal, repo, "merge", run.target_branch) if repo.provider != "local" else None
    try:
        return merge_delivery(db, run, provider_credential=credential)
    except RepositoryDeliveryError as exc:
        raise HTTPException(409, str(exc))


@router.post("/deliveries/{run_id}/resolve-conflicts")
def resolve_conflicts(run_id: int, payload: ConflictResolutionRequest, principal: Principal = Depends(require_scope("company.delivery:write")), db: Session = Depends(get_db)):
    run = _delivery(db, run_id, principal); repo = _repo(db, run.repository_id, principal)
    _require_repo_permission(db, principal, repo, "write_branch", run.source_branch or run.target_branch)
    try:
        return resolve_delivery_conflicts(db, run, resolutions=payload.resolutions, note=payload.note)
    except RepositoryDeliveryError as exc:
        raise HTTPException(409, str(exc))


@router.post("/deliveries/{run_id}/cleanup")
def cleanup(run_id: int, principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    run = _delivery(db, run_id, principal); repo = _repo(db, run.repository_id, principal)
    try:
        cleanup_worktree(repo, run)
    except RepositoryDeliveryError as exc:
        raise HTTPException(400, str(exc))
    return {"ok": True}


@router.post("/merge-requests/{merge_request_id}/rollback")
def rollback(merge_request_id: int, payload: RollbackRequest, principal: Principal = Depends(require_scope("company.delivery:rollback")), db: Session = Depends(get_db)):
    mr = db.get(RepositoryMergeRequest, merge_request_id)
    if not mr:
        raise HTTPException(404, "Merge request not found")
    enforce_org(mr.organization_id, principal)
    repo = _repo(db, mr.repository_id, principal)
    _require_repo_permission(db, principal, repo, "rollback", mr.target_branch)
    try:
        return rollback_merge(db, mr, requested_by_member_id=principal.member_id, reason=payload.reason)
    except RepositoryDeliveryError as exc:
        raise HTTPException(409, str(exc))


@router.get("/rollbacks")
def list_rollbacks(principal: Principal = Depends(require_scope("company.repositories:read")), db: Session = Depends(get_db)):
    return db.query(RepositoryRollback).filter(RepositoryRollback.organization_id == active_org(principal)).order_by(RepositoryRollback.id.desc()).limit(200).all()


@router.get("/delivery-dashboard")
def delivery_dashboard(principal: Principal = Depends(require_human()), db: Session = Depends(get_db)):
    org = active_org(principal)
    repositories = db.query(Repository).filter(Repository.organization_id == org).count()
    active = db.query(DeliveryRun).filter(DeliveryRun.organization_id == org, DeliveryRun.status.notin_(["merged", "failed", "no_changes"])).count()
    merged = db.query(DeliveryRun).filter(DeliveryRun.organization_id == org, DeliveryRun.status == "merged").count()
    failed = db.query(DeliveryRun).filter(DeliveryRun.organization_id == org, DeliveryRun.status.in_(["failed", "tests_failed", "conflict"])).count()
    pending_reviews = db.query(RepositoryReview).filter(RepositoryReview.organization_id == org, RepositoryReview.status == "pending").count()
    conflicts = db.query(RepositoryConflict).filter(RepositoryConflict.organization_id == org, RepositoryConflict.status == "open").count()
    recent = db.query(DeliveryRun).filter(DeliveryRun.organization_id == org).order_by(DeliveryRun.id.desc()).limit(12).all()
    return {"repositories": repositories, "active_deliveries": active, "merged": merged, "failed": failed,
            "pending_reviews": pending_reviews, "open_conflicts": conflicts, "recent": recent}


@router.post("/webhook-endpoints")
def create_webhook_endpoint(payload: WebhookEndpointCreate, principal: Principal = Depends(require_role("admin")), db: Session = Depends(get_db)):
    enforce_org(payload.organization_id, principal)
    if payload.company_id is not None:
        ensure_company(db, payload.company_id, principal)
    try:
        validate_webhook_url(payload.target_url)
    except WebhookDeliveryError as exc:
        raise HTTPException(400, str(exc))
    item = EventWebhookEndpoint(
        organization_id=payload.organization_id, company_id=payload.company_id, name=payload.name,
        target_url=payload.target_url, event_pattern=payload.event_pattern, secret_ref=payload.secret_ref,
        max_attempts=payload.max_attempts, backoff_seconds=payload.backoff_seconds, enabled=payload.enabled,
    )
    db.add(item); db.commit(); db.refresh(item)
    return item


@router.get("/webhook-endpoints")
def list_webhook_endpoints(principal: Principal = Depends(require_human()), db: Session = Depends(get_db)):
    return db.query(EventWebhookEndpoint).filter(EventWebhookEndpoint.organization_id == active_org(principal)).order_by(EventWebhookEndpoint.id.desc()).all()


@router.get("/webhook-deliveries")
def list_webhook_deliveries(status: str | None = None, limit: int = Query(default=100, ge=1, le=500), principal: Principal = Depends(require_human()), db: Session = Depends(get_db)):
    q = db.query(EventWebhookDelivery).filter(EventWebhookDelivery.organization_id == active_org(principal))
    if status:
        q = q.filter(EventWebhookDelivery.status == status)
    return q.order_by(EventWebhookDelivery.id.desc()).limit(limit).all()


@router.post("/webhook-deliveries/{delivery_id}/retry")
def retry_webhook_delivery(delivery_id: int, principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    item = db.get(EventWebhookDelivery, delivery_id)
    if not item:
        raise HTTPException(404, "Webhook delivery not found")
    enforce_org(item.organization_id, principal)
    endpoint = db.get(EventWebhookEndpoint, item.endpoint_id)
    if not endpoint:
        raise HTTPException(404, "Webhook endpoint not found")
    item.status = "pending"; item.error = ""; item.next_attempt_at = None
    db.add(item); db.commit(); db.refresh(item)
    try:
        return deliver_webhook(db, item)
    except WebhookDeliveryError as exc:
        raise HTTPException(400, str(exc))
