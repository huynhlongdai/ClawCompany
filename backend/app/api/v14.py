import json
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.core.authz import Principal, enforce_org, require_role, require_scope
from app.core.tenancy import active_org, ensure_company, ensure_member, ensure_agent
from app.core.config import settings
from app.models import (
    RunnerPool, RunnerNode, RunnerLease, RunnerJob, WorkloadIdentityToken, Artifact, EvidenceSignature,
    ScannerProvider, ExternalScanRun, Repository, DeploymentEnvironment, Release, TrafficRouter, TrafficShift,
    TelemetryMetricSample, SLODefinition, SLOEvaluation, Incident, IncidentEvent, PortfolioObjective, PortfolioReview,
)
from app.schemas.v14 import *
from app.services.runner_broker import register_node, heartbeat, acquire_lease, release_lease, enqueue_job, claim_next_job, complete_job, RunnerBrokerError
from app.services.workload_identity import issue_workload_token, verify_workload_token, jwks_document, WorkloadIdentityError
from app.services.supply_chain_signing import sign_artifact, verify_signature, SupplyChainSigningError
from app.services.scanner_adapters import run_scanner, ScannerAdapterError
from app.services.traffic_router import apply_shift, TrafficRouterError
from app.services.telemetry_slo import ingest_metric, evaluate_slo, SLOError
from app.services.incidents import create_incident, add_incident_event, update_incident_status, IncidentError
from app.services.canary_delivery import run_canary, CanaryDeliveryError
from app.services.nina_portfolio import review_portfolio

router = APIRouter(prefix="/v14", tags=["v14-distributed-execution"])


def _pool(db, item_id, p):
    x = db.get(RunnerPool, item_id)
    if not x: raise HTTPException(404, "Runner pool not found")
    enforce_org(x.organization_id, p); return x


def _node(db, item_id, p):
    x = db.get(RunnerNode, item_id)
    if not x: raise HTTPException(404, "Runner node not found")
    enforce_org(x.organization_id, p); return x


def _lease(db, item_id, p):
    x = db.get(RunnerLease, item_id)
    if not x: raise HTTPException(404, "Runner lease not found")
    enforce_org(x.organization_id, p); return x


def _repo(db, item_id, p):
    x = db.get(Repository, item_id)
    if not x: raise HTTPException(404, "Repository not found")
    enforce_org(x.organization_id, p); return x


def _env(db, item_id, p):
    x = db.get(DeploymentEnvironment, item_id)
    if not x: raise HTTPException(404, "Deployment environment not found")
    enforce_org(x.organization_id, p); return x


def _release(db, item_id, p):
    x = db.get(Release, item_id)
    if not x: raise HTTPException(404, "Release not found")
    enforce_org(x.organization_id, p); return x


@router.post("/runner-pools")
def create_runner_pool(payload: RunnerPoolCreate, principal: Principal = Depends(require_role("admin")), db: Session = Depends(get_db)):
    enforce_org(payload.organization_id, principal)
    if payload.company_id is not None: ensure_company(db, payload.company_id, principal)
    item = RunnerPool(organization_id=payload.organization_id, company_id=payload.company_id, name=payload.name, provider=payload.provider,
                      capabilities_json=json.dumps(payload.capabilities), selectors_json=json.dumps(payload.selectors), max_concurrency=payload.max_concurrency)
    db.add(item); db.commit(); db.refresh(item); return item


@router.get("/runner-pools")
def list_runner_pools(principal: Principal = Depends(require_scope("company.runners:read")), db: Session = Depends(get_db)):
    return db.query(RunnerPool).filter(RunnerPool.organization_id == active_org(principal)).order_by(RunnerPool.id.desc()).all()


@router.post("/runner-nodes/register")
def api_register_node(payload: RunnerNodeRegister, principal: Principal = Depends(require_scope("company.runners:write")), db: Session = Depends(get_db)):
    enforce_org(payload.organization_id, principal); pool = _pool(db, payload.pool_id, principal)
    try: return register_node(db, pool, node_key=payload.node_key, provider=payload.provider, endpoint=payload.endpoint,
                              capabilities=payload.capabilities, labels=payload.labels, capacity=payload.capacity)
    except RunnerBrokerError as exc: raise HTTPException(409, str(exc))


@router.get("/runner-nodes")
def list_runner_nodes(principal: Principal = Depends(require_scope("company.runners:read")), db: Session = Depends(get_db)):
    return db.query(RunnerNode).filter(RunnerNode.organization_id == active_org(principal)).order_by(RunnerNode.id.desc()).all()


@router.post("/runner-nodes/{node_id}/heartbeat")
def node_heartbeat(node_id: int, payload: RunnerHeartbeat, principal: Principal = Depends(require_scope("company.runners:execute")), db: Session = Depends(get_db)):
    return heartbeat(db, _node(db, node_id, principal), status=payload.status, active_leases=payload.active_leases, capabilities=payload.capabilities)


@router.post("/runner-leases")
def create_runner_lease(payload: RunnerLeaseRequest, principal: Principal = Depends(require_scope("company.runners:execute")), db: Session = Depends(get_db)):
    enforce_org(payload.organization_id, principal); pool = _pool(db, payload.pool_id, principal)
    if payload.member_id is not None: ensure_member(db, payload.member_id, principal)
    if payload.agent_id is not None: ensure_agent(db, payload.agent_id, principal)
    try: return acquire_lease(db, pool, member_id=payload.member_id, agent_id=payload.agent_id, workload_type=payload.workload_type,
                              workload_ref=payload.workload_ref, required_capabilities=payload.required_capabilities, scopes=payload.scopes, ttl_seconds=payload.ttl_seconds)
    except RunnerBrokerError as exc: raise HTTPException(409, str(exc))


@router.get("/runner-leases")
def list_runner_leases(principal: Principal = Depends(require_scope("company.runners:read")), db: Session = Depends(get_db)):
    return db.query(RunnerLease).filter(RunnerLease.organization_id == active_org(principal)).order_by(RunnerLease.id.desc()).limit(500).all()


@router.post("/runner-leases/{lease_id}/release")
def api_release_lease(lease_id: int, principal: Principal = Depends(require_scope("company.runners:execute")), db: Session = Depends(get_db)):
    return release_lease(db, _lease(db, lease_id, principal))


@router.post("/runner-jobs")
def create_runner_job(payload: RunnerJobCreate, principal: Principal = Depends(require_scope("company.runners:execute")), db: Session = Depends(get_db)):
    lease = _lease(db, payload.lease_id, principal)
    try: return enqueue_job(db, lease, workspace_id=payload.workspace_id, sandbox_run_id=payload.sandbox_run_id, job_type=payload.job_type, payload=payload.payload)
    except RunnerBrokerError as exc: raise HTTPException(409, str(exc))


@router.get("/runner-jobs/next")
def next_runner_job(node_id: int, principal: Principal = Depends(require_scope("company.runners:execute")), db: Session = Depends(get_db)):
    return claim_next_job(db, _node(db, node_id, principal))


@router.post("/runner-jobs/{job_id}/complete")
def finish_runner_job(job_id: int, payload: RunnerJobComplete, principal: Principal = Depends(require_scope("company.runners:execute")), db: Session = Depends(get_db)):
    job = db.get(RunnerJob, job_id)
    if not job: raise HTTPException(404, "Runner job not found")
    enforce_org(job.organization_id, principal)
    return complete_job(db, job, result=payload.result, error=payload.error)


@router.get("/workload-identity/.well-known/openid-configuration")
def workload_discovery():
    return {"issuer": settings.workload_identity_issuer,
            "jwks_uri": f"{settings.app_base_url.rstrip('/')}/api/v14/workload-identity/jwks.json",
            "id_token_signing_alg_values_supported": [settings.workload_identity_algorithm.upper()],
            "claims_supported": ["iss","sub","aud","exp","iat","jti","org_id","lease_id","member_id","agent_id","scope"]}


@router.get("/workload-identity/jwks.json")
def workload_jwks(): return jwks_document()


@router.post("/workload-identity/token")
def workload_token(payload: WorkloadTokenRequest, principal: Principal = Depends(require_scope("company.runners:execute")), db: Session = Depends(get_db)):
    try: return issue_workload_token(db, _lease(db, payload.lease_id, principal), audience=payload.audience, ttl_seconds=payload.ttl_seconds)
    except WorkloadIdentityError as exc: raise HTTPException(409, str(exc))


@router.post("/workload-identity/verify")
def workload_verify(payload: WorkloadTokenVerify, principal: Principal = Depends(require_scope("company.runners:execute")), db: Session = Depends(get_db)):
    try:
        claims = verify_workload_token(db, payload.token, audience=payload.audience); enforce_org(int(claims["org_id"]), principal); return {"valid": True, "claims": claims}
    except WorkloadIdentityError as exc: raise HTTPException(401, str(exc))


@router.post("/evidence-signatures")
def create_signature(payload: EvidenceSignRequest, principal: Principal = Depends(require_scope("company.supply_chain:write")), db: Session = Depends(get_db)):
    artifact = db.get(Artifact, payload.artifact_id)
    if not artifact: raise HTTPException(404, "Artifact not found")
    enforce_org(artifact.organization_id, principal)
    try: return sign_artifact(db, artifact, build_id=payload.build_id, provider=payload.provider, key_ref=payload.key_ref)
    except SupplyChainSigningError as exc: raise HTTPException(409, str(exc))


@router.post("/evidence-signatures/verify")
def verify_evidence(payload: EvidenceVerifyRequest, principal: Principal = Depends(require_scope("company.supply_chain:read")), db: Session = Depends(get_db)):
    item = db.get(EvidenceSignature, payload.signature_id)
    if not item: raise HTTPException(404, "Evidence signature not found")
    enforce_org(item.organization_id, principal)
    try: return verify_signature(db, item)
    except SupplyChainSigningError as exc: raise HTTPException(409, str(exc))


@router.get("/evidence-signatures")
def list_signatures(principal: Principal = Depends(require_scope("company.supply_chain:read")), db: Session = Depends(get_db)):
    return db.query(EvidenceSignature).filter(EvidenceSignature.organization_id == active_org(principal)).order_by(EvidenceSignature.id.desc()).limit(500).all()


@router.post("/scanner-providers")
def create_scanner(payload: ScannerProviderCreate, principal: Principal = Depends(require_role("admin")), db: Session = Depends(get_db)):
    enforce_org(payload.organization_id, principal)
    item = ScannerProvider(organization_id=payload.organization_id, name=payload.name, provider_type=payload.provider_type,
                           executable=payload.executable, config_json=json.dumps(payload.config), block_on=payload.block_on)
    db.add(item); db.commit(); db.refresh(item); return item


@router.get("/scanner-providers")
def list_scanners(principal: Principal = Depends(require_scope("company.security:read")), db: Session = Depends(get_db)):
    return db.query(ScannerProvider).filter(ScannerProvider.organization_id == active_org(principal)).order_by(ScannerProvider.id.desc()).all()


@router.post("/scanner-runs")
def create_scan_run(payload: ScanRunCreate, principal: Principal = Depends(require_scope("company.security:execute")), db: Session = Depends(get_db)):
    provider = db.get(ScannerProvider, payload.provider_id)
    if not provider: raise HTTPException(404, "Scanner provider not found")
    enforce_org(provider.organization_id, principal); repo = _repo(db, payload.repository_id, principal)
    try: return run_scanner(db, provider, repo, payload.commit_sha, ci_run_id=payload.ci_run_id)
    except ScannerAdapterError as exc: raise HTTPException(409, str(exc))


@router.get("/scanner-runs")
def list_scan_runs(principal: Principal = Depends(require_scope("company.security:read")), db: Session = Depends(get_db)):
    return db.query(ExternalScanRun).filter(ExternalScanRun.organization_id == active_org(principal)).order_by(ExternalScanRun.id.desc()).limit(500).all()


@router.post("/traffic-routers")
def create_router(payload: TrafficRouterCreate, principal: Principal = Depends(require_role("admin")), db: Session = Depends(get_db)):
    enforce_org(payload.organization_id, principal); env = _env(db, payload.environment_id, principal)
    item = TrafficRouter(organization_id=payload.organization_id, environment_id=env.id, name=payload.name,
                         provider=payload.provider, config_json=json.dumps(payload.config), current_weights_json="{}")
    db.add(item); db.commit(); db.refresh(item); return item


@router.get("/traffic-routers")
def list_routers(principal: Principal = Depends(require_scope("company.deployments:read")), db: Session = Depends(get_db)):
    return db.query(TrafficRouter).filter(TrafficRouter.organization_id == active_org(principal)).order_by(TrafficRouter.id.desc()).all()


@router.post("/traffic-shifts")
def create_shift(payload: TrafficShiftRequest, principal: Principal = Depends(require_scope("company.deployments:write")), db: Session = Depends(get_db)):
    router = db.get(TrafficRouter, payload.router_id)
    if not router: raise HTTPException(404, "Traffic router not found")
    enforce_org(router.organization_id, principal); rel = _release(db, payload.release_id, principal)
    old = _release(db, payload.from_release_id, principal) if payload.from_release_id else None
    try: return apply_shift(db, router, rel, to_weight=payload.to_weight, from_release=old, strategy_run_id=payload.strategy_run_id)
    except TrafficRouterError as exc: raise HTTPException(409, str(exc))


@router.get("/traffic-shifts")
def list_shifts(principal: Principal = Depends(require_scope("company.deployments:read")), db: Session = Depends(get_db)):
    return db.query(TrafficShift).filter(TrafficShift.organization_id == active_org(principal)).order_by(TrafficShift.id.desc()).limit(500).all()


@router.post("/telemetry/metrics")
def api_ingest_metric(payload: TelemetryIngest, principal: Principal = Depends(require_scope("company.telemetry:write")), db: Session = Depends(get_db)):
    enforce_org(payload.organization_id, principal)
    if payload.environment_id is not None: _env(db, payload.environment_id, principal)
    if payload.release_id is not None: _release(db, payload.release_id, principal)
    return ingest_metric(db, organization_id=payload.organization_id, environment_id=payload.environment_id, deployment_id=payload.deployment_id,
                         release_id=payload.release_id, metric_name=payload.metric_name, value=payload.value, unit=payload.unit,
                         labels=payload.labels, observed_at=payload.observed_at)


@router.get("/telemetry/metrics")
def list_metrics(metric_name: str = "", principal: Principal = Depends(require_scope("company.telemetry:read")), db: Session = Depends(get_db)):
    q = db.query(TelemetryMetricSample).filter(TelemetryMetricSample.organization_id == active_org(principal))
    if metric_name: q = q.filter(TelemetryMetricSample.metric_name == metric_name)
    return q.order_by(TelemetryMetricSample.id.desc()).limit(1000).all()


@router.post("/slos")
def create_slo(payload: SLOCreate, principal: Principal = Depends(require_role("admin")), db: Session = Depends(get_db)):
    enforce_org(payload.organization_id, principal); _env(db, payload.environment_id, principal)
    if payload.comparator not in {"lte","gte"}: raise HTTPException(400, "Comparator must be lte or gte")
    item = SLODefinition(organization_id=payload.organization_id, environment_id=payload.environment_id, name=payload.name,
                         metric_name=payload.metric_name, comparator=payload.comparator, threshold=payload.threshold,
                         window_minutes=payload.window_minutes, min_samples=payload.min_samples, auto_incident=payload.auto_incident,
                         auto_rollback=payload.auto_rollback, severity=payload.severity)
    db.add(item); db.commit(); db.refresh(item); return item


@router.get("/slos")
def list_slos(principal: Principal = Depends(require_scope("company.telemetry:read")), db: Session = Depends(get_db)):
    return db.query(SLODefinition).filter(SLODefinition.organization_id == active_org(principal)).order_by(SLODefinition.id.desc()).all()


@router.post("/slos/{slo_id}/evaluate")
def api_evaluate_slo(slo_id: int, payload: SLOEvaluateRequest, principal: Principal = Depends(require_scope("company.telemetry:read")), db: Session = Depends(get_db)):
    slo = db.get(SLODefinition, slo_id)
    if not slo: raise HTTPException(404, "SLO not found")
    enforce_org(slo.organization_id, principal)
    try: return evaluate_slo(db, slo, deployment_id=payload.deployment_id, release_id=payload.release_id)
    except SLOError as exc: raise HTTPException(409, str(exc))


@router.get("/slo-evaluations")
def list_slo_evaluations(principal: Principal = Depends(require_scope("company.telemetry:read")), db: Session = Depends(get_db)):
    return db.query(SLOEvaluation).filter(SLOEvaluation.organization_id == active_org(principal)).order_by(SLOEvaluation.id.desc()).limit(500).all()


@router.post("/incidents")
def api_create_incident(payload: IncidentCreate, principal: Principal = Depends(require_scope("company.incidents:write")), db: Session = Depends(get_db)):
    enforce_org(payload.organization_id, principal)
    if payload.company_id is not None: ensure_company(db, payload.company_id, principal)
    if payload.environment_id is not None: _env(db, payload.environment_id, principal)
    if payload.release_id is not None: _release(db, payload.release_id, principal)
    if payload.owner_member_id is not None: ensure_member(db, payload.owner_member_id, principal)
    return create_incident(db, **payload.model_dump())


@router.get("/incidents")
def list_incidents(principal: Principal = Depends(require_scope("company.incidents:read")), db: Session = Depends(get_db)):
    return db.query(Incident).filter(Incident.organization_id == active_org(principal)).order_by(Incident.id.desc()).limit(500).all()


@router.get("/incidents/{incident_id}")
def incident_detail(incident_id: int, principal: Principal = Depends(require_scope("company.incidents:read")), db: Session = Depends(get_db)):
    item = db.get(Incident, incident_id)
    if not item: raise HTTPException(404, "Incident not found")
    enforce_org(item.organization_id, principal)
    return {"incident": item, "events": db.query(IncidentEvent).filter(IncidentEvent.incident_id == item.id).order_by(IncidentEvent.id).all()}


@router.post("/incidents/{incident_id}/events")
def incident_event(incident_id: int, payload: IncidentEventCreate, principal: Principal = Depends(require_scope("company.incidents:write")), db: Session = Depends(get_db)):
    item = db.get(Incident, incident_id)
    if not item: raise HTTPException(404, "Incident not found")
    enforce_org(item.organization_id, principal)
    return add_incident_event(db, item, event_type=payload.event_type, message=payload.message, data=payload.data, actor_member_id=principal.member_id)


@router.post("/incidents/{incident_id}/status")
def incident_status(incident_id: int, payload: IncidentStatusUpdate, principal: Principal = Depends(require_scope("company.incidents:write")), db: Session = Depends(get_db)):
    item = db.get(Incident, incident_id)
    if not item: raise HTTPException(404, "Incident not found")
    enforce_org(item.organization_id, principal)
    try: return update_incident_status(db, item, payload.status, message=payload.message, actor_member_id=principal.member_id)
    except IncidentError as exc: raise HTTPException(400, str(exc))


@router.post("/canary-runs")
def api_run_canary(payload: CanaryRunRequest, principal: Principal = Depends(require_scope("company.deployments:write")), db: Session = Depends(get_db)):
    release = _release(db, payload.release_id, principal); env = _env(db, payload.environment_id, principal)
    router = db.get(TrafficRouter, payload.router_id)
    if not router: raise HTTPException(404, "Traffic router not found")
    enforce_org(router.organization_id, principal)
    if payload.requested_by_member_id is not None: ensure_member(db, payload.requested_by_member_id, principal)
    try: return run_canary(db, release, env, router, slo_ids=payload.slo_ids, steps=payload.steps,
                           requested_by_member_id=payload.requested_by_member_id or principal.member_id)
    except CanaryDeliveryError as exc: raise HTTPException(409, str(exc))


@router.post("/portfolio/objectives")
def create_portfolio_objective(payload: PortfolioObjectiveCreate, principal: Principal = Depends(require_scope("company.portfolio:write")), db: Session = Depends(get_db)):
    enforce_org(payload.organization_id, principal)
    if payload.company_id is not None: ensure_company(db, payload.company_id, principal)
    if payload.owner_member_id is not None: ensure_member(db, payload.owner_member_id, principal)
    item = PortfolioObjective(organization_id=payload.organization_id, company_id=payload.company_id, owner_member_id=payload.owner_member_id,
                              title=payload.title, objective=payload.objective, priority=payload.priority, target_json=json.dumps(payload.targets))
    db.add(item); db.commit(); db.refresh(item); return item


@router.get("/portfolio/objectives")
def list_portfolio_objectives(principal: Principal = Depends(require_scope("company.portfolio:read")), db: Session = Depends(get_db)):
    return db.query(PortfolioObjective).filter(PortfolioObjective.organization_id == active_org(principal)).order_by(PortfolioObjective.id.desc()).all()


@router.post("/portfolio/reviews")
def create_portfolio_review(payload: PortfolioReviewRequest, principal: Principal = Depends(require_scope("company.portfolio:read")), db: Session = Depends(get_db)):
    objective = db.get(PortfolioObjective, payload.objective_id) if payload.objective_id else None
    if objective: enforce_org(objective.organization_id, principal)
    if payload.nina_member_id is not None: ensure_member(db, payload.nina_member_id, principal)
    return review_portfolio(db, organization_id=active_org(principal), objective=objective, nina_member_id=payload.nina_member_id)


@router.get("/portfolio/reviews")
def list_portfolio_reviews(principal: Principal = Depends(require_scope("company.portfolio:read")), db: Session = Depends(get_db)):
    return db.query(PortfolioReview).filter(PortfolioReview.organization_id == active_org(principal)).order_by(PortfolioReview.id.desc()).limit(250).all()
