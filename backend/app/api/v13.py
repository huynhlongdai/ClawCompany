from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.authz import Principal, enforce_org, require_human, require_role, require_scope
from app.core.tenancy import active_org, ensure_agent, ensure_company, ensure_member, ensure_project
from app.db.session import get_db
from app.models import (
    BuildProvenance, BuildRecord, CICDNodeRun, CICDPipelineGraph, CICDRun, DeploymentEnvironment,
    DeploymentHealthPolicy, DeploymentHealthRun, DeploymentStrategyRun, DevWorkspace, EngineeringInitiative,
    PreviewEnvironment, PreviewRoute, Release, ReleaseManagerRun, Repository, SBOMDocument, SecurityFinding,
    SecurityReview, WorkspaceGatewayOperation, WorkspaceGatewaySession,
)
from app.schemas.v13 import (
    BuildEvidenceCreate, CICDGraphCreate, CICDRunCreate, EngineeringInitiativeCreate,
    EngineeringInitiativeRun, HealthPolicyCreate, PreviewRouteCreate, ProgressiveDeployRequest,
    ReleaseManagerAssessRequest, SecurityReviewCreate, WorkspaceGatewaySessionCreate,
    WorkspaceGatewaySnapshot, WorkspaceGatewayWrite,
)
from app.services.build_evidence import BuildEvidenceError, generate_build_evidence
from app.services.cicd import CICDError, create_graph, execute_run, start_run, validate_graph
from app.services.engineering_orchestrator import EngineeringOrchestrationError, run_initiative
from app.services.execution_fabric import providers as execution_providers
from app.services.progressive_delivery import ProgressiveDeliveryError, progressive_deploy
from app.services.release_manager import assess_release
from app.services.security_review import SecurityReviewError, scan_repository_commit
from app.services.workspace_gateway import (
    WorkspaceGatewayError, close_gateway_session, open_gateway_session, read_text, snapshot_workspace, write_text,
)

router = APIRouter(prefix="/v13", tags=["v13-ai-engineering-org"])


def _repo(db: Session, item_id: int, principal: Principal) -> Repository:
    item = db.get(Repository, item_id)
    if not item: raise HTTPException(404, "Repository not found")
    enforce_org(item.organization_id, principal); return item


def _workspace(db: Session, item_id: int, principal: Principal) -> DevWorkspace:
    item = db.get(DevWorkspace, item_id)
    if not item: raise HTTPException(404, "Workspace not found")
    enforce_org(item.organization_id, principal); return item


def _gateway_session(db: Session, item_id: int, principal: Principal) -> WorkspaceGatewaySession:
    item = db.get(WorkspaceGatewaySession, item_id)
    if not item: raise HTTPException(404, "Workspace Gateway session not found")
    enforce_org(item.organization_id, principal)
    if principal.auth_type == "api_key" and item.member_id != principal.member_id:
        raise HTTPException(403, "Workspace Gateway session belongs to another identity")
    return item


def _graph(db: Session, item_id: int, principal: Principal) -> CICDPipelineGraph:
    item = db.get(CICDPipelineGraph, item_id)
    if not item: raise HTTPException(404, "CI/CD graph not found")
    enforce_org(item.organization_id, principal); return item


def _release(db: Session, item_id: int, principal: Principal) -> Release:
    item = db.get(Release, item_id)
    if not item: raise HTTPException(404, "Release not found")
    enforce_org(item.organization_id, principal); return item


def _environment(db: Session, item_id: int, principal: Principal) -> DeploymentEnvironment:
    item = db.get(DeploymentEnvironment, item_id)
    if not item: raise HTTPException(404, "Deployment environment not found")
    enforce_org(item.organization_id, principal); return item


@router.get("/engineering-dashboard")
def engineering_dashboard(principal: Principal = Depends(require_human()), db: Session = Depends(get_db)):
    org = active_org(principal)
    return {
        "metrics": {
            "gateway_sessions": db.query(WorkspaceGatewaySession).filter(WorkspaceGatewaySession.organization_id == org, WorkspaceGatewaySession.status == "active").count(),
            "pipeline_graphs": db.query(CICDPipelineGraph).filter(CICDPipelineGraph.organization_id == org, CICDPipelineGraph.status == "active").count(),
            "ci_running": db.query(CICDRun).filter(CICDRun.organization_id == org, CICDRun.status.in_(["queued", "running"])).count(),
            "builds": db.query(BuildRecord).filter(BuildRecord.organization_id == org).count(),
            "security_blocked": db.query(SecurityReview).filter(SecurityReview.organization_id == org, SecurityReview.verdict == "blocked").count(),
            "release_holds": db.query(ReleaseManagerRun).filter(ReleaseManagerRun.organization_id == org, ReleaseManagerRun.decision == "hold").count(),
            "initiatives_active": db.query(EngineeringInitiative).filter(EngineeringInitiative.organization_id == org, EngineeringInitiative.status.in_(["planned", "running", "waiting_approval", "waiting_router"])).count(),
        },
        "ci_runs": db.query(CICDRun).filter(CICDRun.organization_id == org).order_by(CICDRun.id.desc()).limit(10).all(),
        "security_reviews": db.query(SecurityReview).filter(SecurityReview.organization_id == org).order_by(SecurityReview.id.desc()).limit(10).all(),
        "strategies": db.query(DeploymentStrategyRun).filter(DeploymentStrategyRun.organization_id == org).order_by(DeploymentStrategyRun.id.desc()).limit(10).all(),
        "initiatives": db.query(EngineeringInitiative).filter(EngineeringInitiative.organization_id == org).order_by(EngineeringInitiative.id.desc()).limit(10).all(),
    }


@router.get("/execution-fabric/providers")
def list_execution_fabric(principal: Principal = Depends(require_scope("company.devcloud:read"))):
    return execution_providers()


@router.post("/workspace-gateway/sessions")
def create_gateway_session(payload: WorkspaceGatewaySessionCreate, principal: Principal = Depends(require_scope("company.workspace:write")), db: Session = Depends(get_db)):
    ws = _workspace(db, payload.workspace_id, principal)
    member_id = payload.member_id or principal.member_id
    if member_id is not None: ensure_member(db, member_id, principal)
    if payload.agent_id is not None:
        agent = ensure_agent(db, payload.agent_id, principal)
        if member_id is not None and agent.member_id != member_id: raise HTTPException(403, "Agent/member identity mismatch")
    if principal.auth_type == "api_key" and member_id != principal.member_id:
        raise HTTPException(403, "API key cannot open a session for another identity")
    try:
        return open_gateway_session(db, ws, member_id=member_id, agent_id=payload.agent_id,
                                    provider=payload.provider, provider_session_id=payload.provider_session_id,
                                    capabilities=payload.capabilities, ttl_minutes=payload.ttl_minutes)
    except WorkspaceGatewayError as exc: raise HTTPException(409, str(exc))


@router.get("/workspace-gateway/sessions")
def list_gateway_sessions(status: str | None = None, principal: Principal = Depends(require_scope("company.workspace:read")), db: Session = Depends(get_db)):
    q = db.query(WorkspaceGatewaySession).filter(WorkspaceGatewaySession.organization_id == active_org(principal))
    if principal.auth_type == "api_key": q = q.filter(WorkspaceGatewaySession.member_id == principal.member_id)
    if status: q = q.filter(WorkspaceGatewaySession.status == status)
    return q.order_by(WorkspaceGatewaySession.id.desc()).limit(250).all()


@router.post("/workspace-gateway/sessions/{session_id}/write")
def gateway_write(session_id: int, payload: WorkspaceGatewayWrite, principal: Principal = Depends(require_scope("company.workspace:write")), db: Session = Depends(get_db)):
    session = _gateway_session(db, session_id, principal); ws = _workspace(db, session.workspace_id, principal)
    try: return write_text(db, session, ws, payload.logical_path, payload.content)
    except WorkspaceGatewayError as exc: raise HTTPException(400, str(exc))


@router.get("/workspace-gateway/sessions/{session_id}/read")
def gateway_read(session_id: int, logical_path: str = Query(min_length=1, max_length=700), principal: Principal = Depends(require_scope("company.workspace:read")), db: Session = Depends(get_db)):
    session = _gateway_session(db, session_id, principal); ws = _workspace(db, session.workspace_id, principal)
    try: return read_text(db, session, ws, logical_path)
    except WorkspaceGatewayError as exc: raise HTTPException(400, str(exc))


@router.post("/workspace-gateway/sessions/{session_id}/snapshot")
def gateway_snapshot(session_id: int, payload: WorkspaceGatewaySnapshot, principal: Principal = Depends(require_scope("company.workspace:snapshot")), db: Session = Depends(get_db)):
    session = _gateway_session(db, session_id, principal); ws = _workspace(db, session.workspace_id, principal)
    try:
        ids = snapshot_workspace(db, session, ws, bundle_key=payload.bundle_key, artifact_type=payload.artifact_type,
                                 include_globs=payload.include_globs, max_files=payload.max_files)
        return {"session_id": session.id, "artifact_ids": ids, "count": len(ids)}
    except WorkspaceGatewayError as exc: raise HTTPException(400, str(exc))


@router.post("/workspace-gateway/sessions/{session_id}/close")
def gateway_close(session_id: int, principal: Principal = Depends(require_scope("company.workspace:write")), db: Session = Depends(get_db)):
    return close_gateway_session(db, _gateway_session(db, session_id, principal))


@router.get("/workspace-gateway/operations")
def gateway_operations(session_id: int | None = None, principal: Principal = Depends(require_scope("company.workspace:read")), db: Session = Depends(get_db)):
    q = db.query(WorkspaceGatewayOperation).filter(WorkspaceGatewayOperation.organization_id == active_org(principal))
    if session_id is not None: _gateway_session(db, session_id, principal); q = q.filter(WorkspaceGatewayOperation.session_id == session_id)
    return q.order_by(WorkspaceGatewayOperation.id.desc()).limit(500).all()


@router.post("/cicd/graphs")
def create_cicd_graph(payload: CICDGraphCreate, principal: Principal = Depends(require_scope("company.cicd:write")), db: Session = Depends(get_db)):
    enforce_org(payload.organization_id, principal); repo = _repo(db, payload.repository_id, principal)
    if payload.company_id is not None: ensure_company(db, payload.company_id, principal)
    if payload.project_id is not None: ensure_project(db, payload.project_id, principal)
    try:
        graph = create_graph(db, organization_id=payload.organization_id, repository_id=repo.id, company_id=payload.company_id,
                             project_id=payload.project_id, name=payload.name, trigger=payload.trigger, status=payload.status,
                             created_by_member_id=principal.member_id, nodes=[x.model_dump() for x in payload.nodes],
                             edges=[x.model_dump() for x in payload.edges])
        return {"graph": graph, "validation": validate_graph(db, graph)}
    except CICDError as exc: raise HTTPException(400, str(exc))


@router.get("/cicd/graphs")
def list_cicd_graphs(principal: Principal = Depends(require_scope("company.cicd:read")), db: Session = Depends(get_db)):
    return db.query(CICDPipelineGraph).filter(CICDPipelineGraph.organization_id == active_org(principal)).order_by(CICDPipelineGraph.id.desc()).all()


@router.get("/cicd/graphs/{graph_id}/validate")
def validate_cicd_graph(graph_id: int, principal: Principal = Depends(require_scope("company.cicd:read")), db: Session = Depends(get_db)):
    try: return validate_graph(db, _graph(db, graph_id, principal))
    except CICDError as exc: raise HTTPException(400, str(exc))


@router.post("/cicd/runs")
def create_cicd_run(payload: CICDRunCreate, principal: Principal = Depends(require_scope("company.cicd:execute")), db: Session = Depends(get_db)):
    graph = _graph(db, payload.graph_id, principal)
    member_id = payload.initiated_by_member_id or principal.member_id
    if payload.initiated_by_member_id is not None: ensure_member(db, payload.initiated_by_member_id, principal)
    if payload.initiated_by_agent_id is not None:
        agent = ensure_agent(db, payload.initiated_by_agent_id, principal)
        if member_id is not None and agent.member_id != member_id: raise HTTPException(403, "Agent/member identity mismatch")
    if principal.auth_type == "api_key" and member_id != principal.member_id: raise HTTPException(403, "API key identity mismatch")
    try:
        run = start_run(db, graph, ref=payload.ref, commit_sha=payload.commit_sha, member_id=member_id, agent_id=payload.initiated_by_agent_id)
        return execute_run(db, run) if payload.execute else run
    except CICDError as exc: raise HTTPException(409, str(exc))


@router.get("/cicd/runs")
def list_cicd_runs(status: str | None = None, principal: Principal = Depends(require_scope("company.cicd:read")), db: Session = Depends(get_db)):
    q = db.query(CICDRun).filter(CICDRun.organization_id == active_org(principal))
    if status: q = q.filter(CICDRun.status == status)
    return q.order_by(CICDRun.id.desc()).limit(250).all()


@router.get("/cicd/runs/{run_id}")
def cicd_run_detail(run_id: int, principal: Principal = Depends(require_scope("company.cicd:read")), db: Session = Depends(get_db)):
    run = db.get(CICDRun, run_id)
    if not run: raise HTTPException(404, "CI/CD run not found")
    enforce_org(run.organization_id, principal)
    return {"run": run, "node_runs": db.query(CICDNodeRun).filter(CICDNodeRun.ci_run_id == run.id).order_by(CICDNodeRun.id).all()}


@router.post("/builds/evidence")
def create_build_evidence(payload: BuildEvidenceCreate, principal: Principal = Depends(require_scope("company.cicd:execute")), db: Session = Depends(get_db)):
    repo = _repo(db, payload.repository_id, principal)
    if payload.producer_member_id is not None: ensure_member(db, payload.producer_member_id, principal)
    if payload.producer_agent_id is not None: ensure_agent(db, payload.producer_agent_id, principal)
    try: return generate_build_evidence(db, repo, payload.commit_sha, ci_run_id=payload.ci_run_id, release_id=payload.release_id,
                                        producer_member_id=payload.producer_member_id or principal.member_id,
                                        producer_agent_id=payload.producer_agent_id)
    except BuildEvidenceError as exc: raise HTTPException(400, str(exc))


@router.get("/builds")
def list_builds(principal: Principal = Depends(require_scope("company.cicd:read")), db: Session = Depends(get_db)):
    return db.query(BuildRecord).filter(BuildRecord.organization_id == active_org(principal)).order_by(BuildRecord.id.desc()).limit(250).all()


@router.get("/builds/{build_id}")
def build_detail(build_id: int, principal: Principal = Depends(require_scope("company.cicd:read")), db: Session = Depends(get_db)):
    item = db.get(BuildRecord, build_id)
    if not item: raise HTTPException(404, "Build not found")
    enforce_org(item.organization_id, principal)
    return {"build": item,
            "sbom": db.query(SBOMDocument).filter(SBOMDocument.build_id == item.id).first(),
            "provenance": db.query(BuildProvenance).filter(BuildProvenance.build_id == item.id).first()}


@router.post("/security-reviews")
def create_security_review(payload: SecurityReviewCreate, principal: Principal = Depends(require_scope("company.security:execute")), db: Session = Depends(get_db)):
    repo = _repo(db, payload.repository_id, principal)
    if payload.reviewer_member_id is not None: ensure_member(db, payload.reviewer_member_id, principal)
    if payload.reviewer_agent_id is not None: ensure_agent(db, payload.reviewer_agent_id, principal)
    try: return scan_repository_commit(db, repo, payload.commit_sha, ci_run_id=payload.ci_run_id, build_id=payload.build_id,
                                       reviewer_member_id=payload.reviewer_member_id or principal.member_id,
                                       reviewer_agent_id=payload.reviewer_agent_id, block_on=payload.block_on)
    except SecurityReviewError as exc: raise HTTPException(400, str(exc))


@router.get("/security-reviews")
def list_security_reviews(principal: Principal = Depends(require_scope("company.security:read")), db: Session = Depends(get_db)):
    return db.query(SecurityReview).filter(SecurityReview.organization_id == active_org(principal)).order_by(SecurityReview.id.desc()).limit(250).all()


@router.get("/security-reviews/{review_id}")
def security_review_detail(review_id: int, principal: Principal = Depends(require_scope("company.security:read")), db: Session = Depends(get_db)):
    review = db.get(SecurityReview, review_id)
    if not review: raise HTTPException(404, "Security review not found")
    enforce_org(review.organization_id, principal)
    return {"review": review, "findings": db.query(SecurityFinding).filter(SecurityFinding.review_id == review.id).order_by(SecurityFinding.id).all()}


@router.post("/preview-routes")
def create_preview_route(payload: PreviewRouteCreate, principal: Principal = Depends(require_scope("company.deployments:write")), db: Session = Depends(get_db)):
    preview = db.get(PreviewEnvironment, payload.preview_environment_id)
    if not preview: raise HTTPException(404, "Preview environment not found")
    enforce_org(preview.organization_id, principal)
    item = PreviewRoute(organization_id=preview.organization_id, preview_environment_id=preview.id,
                        hostname=payload.hostname, slug=payload.slug, path_prefix=payload.path_prefix,
                        target_url=payload.target_url, status="active", expires_at=payload.expires_at or preview.expires_at)
    db.add(item); db.commit(); db.refresh(item); return item


@router.get("/preview-routes")
def list_preview_routes(principal: Principal = Depends(require_scope("company.deployments:read")), db: Session = Depends(get_db)):
    return db.query(PreviewRoute).filter(PreviewRoute.organization_id == active_org(principal)).order_by(PreviewRoute.id.desc()).all()


@router.get("/preview-routes/resolve")
def resolve_preview_route(hostname: str = "", path: str = "/", principal: Principal = Depends(require_scope("company.deployments:read")), db: Session = Depends(get_db)):
    q = db.query(PreviewRoute).filter(PreviewRoute.organization_id == active_org(principal), PreviewRoute.status == "active")
    if hostname: q = q.filter(PreviewRoute.hostname == hostname)
    candidates = q.order_by(PreviewRoute.id.desc()).all()
    now = datetime.utcnow()
    for item in candidates:
        if item.expires_at and item.expires_at <= now: continue
        if path.startswith(item.path_prefix or "/"):
            return item
    raise HTTPException(404, "Preview route not found")


@router.post("/health-policies")
def create_health_policy(payload: HealthPolicyCreate, principal: Principal = Depends(require_role("admin")), db: Session = Depends(get_db)):
    env = _environment(db, payload.environment_id, principal)
    item = DeploymentHealthPolicy(organization_id=env.organization_id, environment_id=env.id, **payload.model_dump(exclude={"environment_id"}))
    db.add(item); db.commit(); db.refresh(item); return item


@router.get("/health-policies")
def list_health_policies(principal: Principal = Depends(require_scope("company.deployments:read")), db: Session = Depends(get_db)):
    return db.query(DeploymentHealthPolicy).filter(DeploymentHealthPolicy.organization_id == active_org(principal)).order_by(DeploymentHealthPolicy.id.desc()).all()


@router.post("/deployment-strategies/run")
def run_deployment_strategy(payload: ProgressiveDeployRequest, principal: Principal = Depends(require_scope("company.deployments:write")), db: Session = Depends(get_db)):
    release = _release(db, payload.release_id, principal); env = _environment(db, payload.environment_id, principal)
    policy = db.get(DeploymentHealthPolicy, payload.health_policy_id) if payload.health_policy_id else None
    if policy: enforce_org(policy.organization_id, principal)
    requester = payload.requested_by_member_id or principal.member_id
    if payload.requested_by_member_id is not None: ensure_member(db, payload.requested_by_member_id, principal)
    try: return progressive_deploy(db, release, env, strategy=payload.strategy, policy=policy,
                                   traffic_percent=payload.traffic_percent, requested_by_member_id=requester)
    except ProgressiveDeliveryError as exc: raise HTTPException(409, str(exc))


@router.get("/deployment-strategies")
def list_deployment_strategies(principal: Principal = Depends(require_scope("company.deployments:read")), db: Session = Depends(get_db)):
    return db.query(DeploymentStrategyRun).filter(DeploymentStrategyRun.organization_id == active_org(principal)).order_by(DeploymentStrategyRun.id.desc()).limit(250).all()


@router.get("/health-runs")
def list_health_runs(principal: Principal = Depends(require_scope("company.deployments:read")), db: Session = Depends(get_db)):
    return db.query(DeploymentHealthRun).filter(DeploymentHealthRun.organization_id == active_org(principal)).order_by(DeploymentHealthRun.id.desc()).limit(250).all()


@router.post("/release-manager/assess")
def release_manager_assess(payload: ReleaseManagerAssessRequest, principal: Principal = Depends(require_scope("company.releases:write")), db: Session = Depends(get_db)):
    release = _release(db, payload.release_id, principal)
    ci_run = db.get(CICDRun, payload.ci_run_id) if payload.ci_run_id else None
    security = db.get(SecurityReview, payload.security_review_id) if payload.security_review_id else None
    strategy = db.get(DeploymentStrategyRun, payload.strategy_run_id) if payload.strategy_run_id else None
    for item in [ci_run, security, strategy]:
        if item is not None: enforce_org(item.organization_id, principal)
    if payload.requested_by_member_id is not None: ensure_member(db, payload.requested_by_member_id, principal)
    if payload.requested_by_agent_id is not None: ensure_agent(db, payload.requested_by_agent_id, principal)
    return assess_release(db, release, ci_run=ci_run, security_review=security, strategy_run=strategy,
                          requested_by_member_id=payload.requested_by_member_id or principal.member_id,
                          requested_by_agent_id=payload.requested_by_agent_id)


@router.get("/release-manager/runs")
def list_release_manager_runs(principal: Principal = Depends(require_scope("company.releases:read")), db: Session = Depends(get_db)):
    return db.query(ReleaseManagerRun).filter(ReleaseManagerRun.organization_id == active_org(principal)).order_by(ReleaseManagerRun.id.desc()).limit(250).all()


@router.post("/initiatives")
def create_initiative(payload: EngineeringInitiativeCreate, principal: Principal = Depends(require_scope("company.cicd:write")), db: Session = Depends(get_db)):
    enforce_org(payload.organization_id, principal); repo = _repo(db, payload.repository_id, principal); graph = _graph(db, payload.pipeline_graph_id, principal)
    if graph.repository_id != repo.id: raise HTTPException(400, "Pipeline graph belongs to another repository")
    if payload.company_id is not None: ensure_company(db, payload.company_id, principal)
    if payload.project_id is not None: ensure_project(db, payload.project_id, principal)
    if payload.nina_member_id is not None: ensure_member(db, payload.nina_member_id, principal)
    if payload.desired_environment_id is not None:
        env = _environment(db, payload.desired_environment_id, principal)
        if env.repository_id != repo.id: raise HTTPException(400, "Environment belongs to another repository")
    item = EngineeringInitiative(**payload.model_dump(), status="planned")
    db.add(item); db.commit(); db.refresh(item); return item


@router.get("/initiatives")
def list_initiatives(principal: Principal = Depends(require_scope("company.cicd:read")), db: Session = Depends(get_db)):
    return db.query(EngineeringInitiative).filter(EngineeringInitiative.organization_id == active_org(principal)).order_by(EngineeringInitiative.id.desc()).limit(250).all()


@router.post("/initiatives/{initiative_id}/run")
def run_engineering_initiative(initiative_id: int, payload: EngineeringInitiativeRun, principal: Principal = Depends(require_scope("company.cicd:execute")), db: Session = Depends(get_db)):
    item = db.get(EngineeringInitiative, initiative_id)
    if not item: raise HTTPException(404, "Engineering initiative not found")
    enforce_org(item.organization_id, principal)
    if principal.auth_type == "api_key" and item.nina_member_id not in {None, principal.member_id}:
        raise HTTPException(403, "API key identity cannot run this initiative")
    try: return run_initiative(db, item, execute_deployment=payload.execute_deployment, health_policy_id=payload.health_policy_id)
    except EngineeringOrchestrationError as exc: raise HTTPException(409, str(exc))
