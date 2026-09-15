import json
from fastapi import APIRouter, Depends, HTTPException, Header
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.core.authz import Principal, enforce_org, require_role, require_scope
from app.core.tenancy import active_org, ensure_company, ensure_member, ensure_agent
from app.core.runner_transport import enforce_runner_transport
from app.models import *
from app.schemas.v15 import *
from app.services.runner_trust import create_authority, sign_runner_csr, revoke_runner_certificate, RunnerTrustError
from app.services.runner_broker import heartbeat, claim_next_job, complete_job
from app.services.workload_keys import create_signing_key, set_key_status, WorkloadKeyError
from app.services.workload_identity import jwks_document
from app.services.evidence_trust import verify_evidence, EvidenceTrustError
from app.services.telemetry_export import render_prometheus, ingest_otlp_json, dispatch_exporter, TelemetryExportError
from app.services.secret_federation import issue_secret_lease, revoke_secret_lease, resolve_secret, SecretFederationError
from app.services.incident_paging import queue_incident_notifications, deliver_notification, dispatch_queued_notifications, IncidentPagingError
from app.services.scheduler_ha import register_scheduler_node, heartbeat_scheduler_node, acquire_leadership, release_leadership
from app.services.sre_recovery import plan_recovery, execute_recovery, tick_sre_recovery, SRERecoveryError

router = APIRouter(prefix="/v15", tags=["v15-production-trust-sre"])


def _node(db, node_id, p):
    x = db.get(RunnerNode, node_id)
    if not x: raise HTTPException(404, "Runner node not found")
    enforce_org(x.organization_id, p); return x


def _incident(db, item_id, p):
    x = db.get(Incident, item_id)
    if not x: raise HTTPException(404, "Incident not found")
    enforce_org(x.organization_id, p); return x


@router.post("/runner-trust/authorities")
def api_create_authority(payload: RunnerTrustAuthorityCreate, principal: Principal = Depends(require_role("admin")), db: Session = Depends(get_db)):
    enforce_org(payload.organization_id, principal)
    try: return create_authority(db, **payload.model_dump())
    except RunnerTrustError as exc: raise HTTPException(409, str(exc))


@router.get("/runner-trust/authorities")
def list_authorities(principal: Principal = Depends(require_scope("company.runners:read")), db: Session = Depends(get_db)):
    return db.query(RunnerTrustAuthority).filter(RunnerTrustAuthority.organization_id == active_org(principal)).order_by(RunnerTrustAuthority.id.desc()).all()


@router.post("/runner-trust/authorities/{authority_id}/sign-csr")
def api_sign_csr(authority_id: int, payload: RunnerCSRSignRequest, principal: Principal = Depends(require_role("admin")), db: Session = Depends(get_db)):
    authority = db.get(RunnerTrustAuthority, authority_id)
    if not authority: raise HTTPException(404, "Runner trust authority not found")
    enforce_org(authority.organization_id, principal); node = _node(db, payload.runner_node_id, principal)
    try: return sign_runner_csr(db, authority, node, csr_pem=payload.csr_pem, ttl_hours=payload.ttl_hours, previous_certificate_id=payload.previous_certificate_id)
    except RunnerTrustError as exc: raise HTTPException(409, str(exc))


@router.get("/runner-trust/certificates")
def list_runner_certificates(principal: Principal = Depends(require_scope("company.runners:read")), db: Session = Depends(get_db)):
    return db.query(RunnerCertificate).filter(RunnerCertificate.organization_id == active_org(principal)).order_by(RunnerCertificate.id.desc()).limit(500).all()


@router.post("/runner-trust/certificates/{certificate_id}/revoke")
def api_revoke_cert(certificate_id: int, payload: RunnerCertificateRevokeRequest, principal: Principal = Depends(require_role("admin")), db: Session = Depends(get_db)):
    item = db.get(RunnerCertificate, certificate_id)
    if not item: raise HTTPException(404, "Runner certificate not found")
    enforce_org(item.organization_id, principal); return revoke_runner_certificate(db, item)


@router.post("/runner/{node_id}/heartbeat")
def secure_runner_heartbeat(node_id: int, principal: Principal = Depends(require_scope("company.runners:execute")), db: Session = Depends(get_db),
                            x_runner_cert_fingerprint: str | None = Header(default=None, alias="X-Runner-Cert-Fingerprint"),
                            x_clawcompany_mtls_verified: str | None = Header(default=None, alias="X-ClawCompany-MTLS-Verified")):
    node = _node(db, node_id, principal); enforce_runner_transport(db, node, fingerprint=x_runner_cert_fingerprint, proxy_verified=x_clawcompany_mtls_verified)
    return heartbeat(db, node, status="online")


@router.get("/runner/{node_id}/jobs/next")
def secure_runner_next_job(node_id: int, principal: Principal = Depends(require_scope("company.runners:execute")), db: Session = Depends(get_db),
                           x_runner_cert_fingerprint: str | None = Header(default=None, alias="X-Runner-Cert-Fingerprint"),
                           x_clawcompany_mtls_verified: str | None = Header(default=None, alias="X-ClawCompany-MTLS-Verified")):
    node = _node(db, node_id, principal); enforce_runner_transport(db, node, fingerprint=x_runner_cert_fingerprint, proxy_verified=x_clawcompany_mtls_verified)
    return claim_next_job(db, node)


@router.post("/runner/{node_id}/jobs/{job_id}/complete")
def secure_runner_complete_job(node_id: int, job_id: int, payload: dict, principal: Principal = Depends(require_scope("company.runners:execute")), db: Session = Depends(get_db),
                               x_runner_cert_fingerprint: str | None = Header(default=None, alias="X-Runner-Cert-Fingerprint"),
                               x_clawcompany_mtls_verified: str | None = Header(default=None, alias="X-ClawCompany-MTLS-Verified")):
    node = _node(db, node_id, principal); enforce_runner_transport(db, node, fingerprint=x_runner_cert_fingerprint, proxy_verified=x_clawcompany_mtls_verified)
    job = db.get(RunnerJob, job_id)
    if not job or job.organization_id != node.organization_id: raise HTTPException(404, "Runner job not found")
    lease = db.get(RunnerLease, job.lease_id)
    if not lease or lease.runner_node_id != node.id: raise HTTPException(403, "Runner job belongs to another node")
    return complete_job(db, job, result=payload.get("result") or {}, error=str(payload.get("error") or ""))


@router.post("/workload-signing-keys")
def api_create_workload_key(payload: WorkloadSigningKeyCreate, principal: Principal = Depends(require_role("admin")), db: Session = Depends(get_db)):
    enforce_org(payload.organization_id, principal)
    try: return create_signing_key(db, **payload.model_dump())
    except WorkloadKeyError as exc: raise HTTPException(409, str(exc))


@router.get("/workload-signing-keys")
def list_workload_keys(principal: Principal = Depends(require_role("admin")), db: Session = Depends(get_db)):
    return db.query(WorkloadSigningKey).filter(WorkloadSigningKey.organization_id == active_org(principal)).order_by(WorkloadSigningKey.id.desc()).all()


@router.post("/workload-signing-keys/{key_id}/status")
def workload_key_status(key_id: int, payload: WorkloadSigningKeyStatus, principal: Principal = Depends(require_role("admin")), db: Session = Depends(get_db)):
    item = db.get(WorkloadSigningKey, key_id)
    if not item: raise HTTPException(404, "Workload signing key not found")
    enforce_org(item.organization_id, principal)
    try: return set_key_status(db, item, payload.status)
    except WorkloadKeyError as exc: raise HTTPException(409, str(exc))


@router.get("/workload-identity/{organization_id}/jwks.json")
def org_jwks(organization_id: int, principal: Principal = Depends(require_scope("company.runners:read")), db: Session = Depends(get_db)):
    enforce_org(organization_id, principal); return jwks_document(db, organization_id)


@router.post("/evidence-trust/policies")
def create_evidence_policy(payload: EvidenceTrustPolicyCreate, principal: Principal = Depends(require_role("admin")), db: Session = Depends(get_db)):
    enforce_org(payload.organization_id, principal)
    item = EvidenceTrustPolicy(organization_id=payload.organization_id, name=payload.name, signature_type=payload.signature_type,
                               key_ref=payload.key_ref, expected_signer=payload.expected_signer, expected_issuer=payload.expected_issuer,
                               config_json=json.dumps(payload.config), enabled=payload.enabled)
    db.add(item); db.commit(); db.refresh(item); return item


@router.get("/evidence-trust/policies")
def list_evidence_policies(principal: Principal = Depends(require_scope("company.supply_chain:read")), db: Session = Depends(get_db)):
    return db.query(EvidenceTrustPolicy).filter(EvidenceTrustPolicy.organization_id == active_org(principal)).all()


@router.post("/evidence-trust/verify")
def api_verify_evidence(payload: EvidenceVerifyRequest, principal: Principal = Depends(require_scope("company.supply_chain:read")), db: Session = Depends(get_db)):
    sig = db.get(EvidenceSignature, payload.signature_id)
    if not sig: raise HTTPException(404, "Evidence signature not found")
    enforce_org(sig.organization_id, principal); policy = db.get(EvidenceTrustPolicy, payload.policy_id) if payload.policy_id else None
    if policy: enforce_org(policy.organization_id, principal)
    try: return verify_evidence(db, sig, policy)
    except EvidenceTrustError as exc: raise HTTPException(409, str(exc))


@router.get("/evidence-trust/verifications")
def list_evidence_verifications(principal: Principal = Depends(require_scope("company.supply_chain:read")), db: Session = Depends(get_db)):
    return db.query(EvidenceVerification).filter(EvidenceVerification.organization_id == active_org(principal)).order_by(EvidenceVerification.id.desc()).limit(500).all()


@router.get("/metrics", response_class=PlainTextResponse)
def prometheus_metrics(principal: Principal = Depends(require_scope("company.telemetry:read")), db: Session = Depends(get_db)):
    return render_prometheus(db, active_org(principal))


@router.post("/telemetry/otlp-json")
def ingest_otlp(payload: OTLPMetricsIngest, principal: Principal = Depends(require_scope("company.telemetry:write")), db: Session = Depends(get_db)):
    enforce_org(payload.organization_id, principal)
    return {"ingested": ingest_otlp_json(db, **payload.model_dump())}


@router.post("/telemetry/exporters")
def create_exporter(payload: TelemetryExporterCreate, principal: Principal = Depends(require_role("admin")), db: Session = Depends(get_db)):
    enforce_org(payload.organization_id, principal)
    item = TelemetryExporter(organization_id=payload.organization_id, name=payload.name, provider=payload.provider, endpoint=payload.endpoint,
                             auth_secret_ref=payload.auth_secret_ref, config_json=json.dumps(payload.config), enabled=payload.enabled)
    db.add(item); db.commit(); db.refresh(item); return item


@router.get("/telemetry/exporters")
def list_exporters(principal: Principal = Depends(require_scope("company.telemetry:read")), db: Session = Depends(get_db)):
    return db.query(TelemetryExporter).filter(TelemetryExporter.organization_id == active_org(principal)).all()


@router.post("/telemetry/exporters/{exporter_id}/dispatch")
def export_telemetry(exporter_id: int, payload: TelemetryExportRequest, principal: Principal = Depends(require_scope("company.telemetry:write")), db: Session = Depends(get_db)):
    item = db.get(TelemetryExporter, exporter_id)
    if not item: raise HTTPException(404, "Telemetry exporter not found")
    enforce_org(item.organization_id, principal)
    try: return dispatch_exporter(db, item, limit=payload.limit)
    except TelemetryExportError as exc: raise HTTPException(409, str(exc))


@router.post("/secret-providers")
def create_secret_provider(payload: SecretProviderConnectionCreate, principal: Principal = Depends(require_role("admin")), db: Session = Depends(get_db)):
    enforce_org(payload.organization_id, principal)
    if payload.company_id is not None: ensure_company(db, payload.company_id, principal)
    item = SecretProviderConnection(organization_id=payload.organization_id, company_id=payload.company_id, name=payload.name,
                                    provider=payload.provider, endpoint=payload.endpoint, auth_ref=payload.auth_ref,
                                    config_json=json.dumps(payload.config), enabled=payload.enabled)
    db.add(item); db.commit(); db.refresh(item); return item


@router.get("/secret-providers")
def list_secret_providers(principal: Principal = Depends(require_role("admin")), db: Session = Depends(get_db)):
    return db.query(SecretProviderConnection).filter(SecretProviderConnection.organization_id == active_org(principal)).all()


@router.post("/secret-providers/{connection_id}/verify")
def verify_secret_provider(connection_id: int, payload: SecretProviderVerifyRequest, principal: Principal = Depends(require_role("admin")), db: Session = Depends(get_db)):
    conn = db.get(SecretProviderConnection, connection_id)
    if not conn: raise HTTPException(404, "Secret provider connection not found")
    enforce_org(conn.organization_id, principal)
    if payload.secret_reference_id is None: return {"valid": True, "note":"Connection metadata is valid; provide secret_reference_id for live resolution check."}
    ref = db.get(SecretReference, payload.secret_reference_id)
    if not ref or ref.organization_id != conn.organization_id: raise HTTPException(404, "Secret reference not found")
    try:
        resolve_secret(db, ref, conn); conn.last_verified_at = __import__("datetime").datetime.utcnow(); db.add(conn); db.commit(); return {"valid":True,"value":"***redacted***"}
    except SecretFederationError as exc: raise HTTPException(409, str(exc))


@router.post("/secret-access-leases")
def create_secret_access_lease(payload: SecretAccessLeaseCreate, principal: Principal = Depends(require_scope("company.secrets:use")), db: Session = Depends(get_db)):
    enforce_org(payload.organization_id, principal)
    if payload.member_id is not None: ensure_member(db, payload.member_id, principal)
    if payload.agent_id is not None: ensure_agent(db, payload.agent_id, principal)
    try: return issue_secret_lease(db, **payload.model_dump())
    except SecretFederationError as exc: raise HTTPException(409, str(exc))


@router.get("/secret-access-leases")
def list_secret_access_leases(principal: Principal = Depends(require_role("admin")), db: Session = Depends(get_db)):
    return db.query(SecretAccessLease).filter(SecretAccessLease.organization_id == active_org(principal)).order_by(SecretAccessLease.id.desc()).limit(500).all()


@router.post("/secret-access-leases/{lease_id}/revoke")
def api_revoke_secret_lease(lease_id: int, principal: Principal = Depends(require_role("admin")), db: Session = Depends(get_db)):
    item = db.get(SecretAccessLease, lease_id)
    if not item: raise HTTPException(404, "Secret access lease not found")
    enforce_org(item.organization_id, principal); return revoke_secret_lease(db, item)


@router.post("/paging/routes")
def create_paging_route(payload: IncidentPagingRouteCreate, principal: Principal = Depends(require_role("admin")), db: Session = Depends(get_db)):
    enforce_org(payload.organization_id, principal)
    if payload.company_id is not None: ensure_company(db, payload.company_id, principal)
    item = IncidentPagingRoute(organization_id=payload.organization_id, company_id=payload.company_id, name=payload.name,
                               provider=payload.provider, endpoint=payload.endpoint, secret_ref=payload.secret_ref,
                               severities_json=json.dumps(payload.severities), enabled=payload.enabled)
    db.add(item); db.commit(); db.refresh(item); return item


@router.get("/paging/routes")
def list_paging_routes(principal: Principal = Depends(require_scope("company.incidents:read")), db: Session = Depends(get_db)):
    return db.query(IncidentPagingRoute).filter(IncidentPagingRoute.organization_id == active_org(principal)).all()


@router.post("/incidents/{incident_id}/page")
def page_incident(incident_id: int, payload: IncidentPageRequest, principal: Principal = Depends(require_scope("company.incidents:write")), db: Session = Depends(get_db)):
    incident = _incident(db, incident_id, principal); queued = queue_incident_notifications(db, incident, event_type=payload.event_type)
    return {"queued": len(queued), "notification_ids":[x.id for x in queued]}


@router.post("/paging/dispatch")
def dispatch_paging(principal: Principal = Depends(require_scope("company.incidents:write")), db: Session = Depends(get_db)):
    return dispatch_queued_notifications(db, organization_id=active_org(principal))


@router.get("/paging/notifications")
def list_notifications(principal: Principal = Depends(require_scope("company.incidents:read")), db: Session = Depends(get_db)):
    return db.query(IncidentNotification).filter(IncidentNotification.organization_id == active_org(principal)).order_by(IncidentNotification.id.desc()).limit(500).all()


@router.post("/scheduler/nodes")
def api_register_scheduler(payload: SchedulerNodeRegister, principal: Principal = Depends(require_role("admin")), db: Session = Depends(get_db)):
    enforce_org(payload.organization_id, principal); return register_scheduler_node(db, **payload.model_dump())


@router.get("/scheduler/nodes")
def list_scheduler_nodes(principal: Principal = Depends(require_role("admin")), db: Session = Depends(get_db)):
    return db.query(SchedulerNode).filter(SchedulerNode.organization_id == active_org(principal)).all()


@router.post("/scheduler/nodes/{node_id}/leadership")
def api_acquire_leadership(node_id: int, payload: SchedulerLeadershipRequest, principal: Principal = Depends(require_role("admin")), db: Session = Depends(get_db)):
    node = db.get(SchedulerNode, node_id)
    if not node: raise HTTPException(404, "Scheduler node not found")
    enforce_org(node.organization_id, principal); lease, acquired = acquire_leadership(db, node, **payload.model_dump())
    return {"acquired": acquired, "lease": lease}


@router.get("/scheduler/leases")
def list_scheduler_leases(principal: Principal = Depends(require_role("admin")), db: Session = Depends(get_db)):
    return db.query(SchedulerLeadershipLease).filter(SchedulerLeadershipLease.organization_id == active_org(principal)).all()


@router.post("/sre/policies")
def create_sre_policy(payload: SRERecoveryPolicyCreate, principal: Principal = Depends(require_role("admin")), db: Session = Depends(get_db)):
    enforce_org(payload.organization_id, principal)
    if payload.company_id is not None: ensure_company(db, payload.company_id, principal)
    item = SRERecoveryPolicy(organization_id=payload.organization_id, company_id=payload.company_id, name=payload.name,
                             severities_json=json.dumps(payload.severities), actions_json=json.dumps(payload.actions), max_attempts=payload.max_attempts,
                             approval_required_for_json=json.dumps(payload.approval_required_for), enabled=payload.enabled)
    db.add(item); db.commit(); db.refresh(item); return item


@router.get("/sre/policies")
def list_sre_policies(principal: Principal = Depends(require_scope("company.incidents:read")), db: Session = Depends(get_db)):
    return db.query(SRERecoveryPolicy).filter(SRERecoveryPolicy.organization_id == active_org(principal)).all()


@router.post("/sre/plan")
def api_plan_sre(payload: SREPlanRequest, principal: Principal = Depends(require_scope("company.incidents:write")), db: Session = Depends(get_db)):
    incident = _incident(db, payload.incident_id, principal)
    if payload.nina_member_id is not None: ensure_member(db, payload.nina_member_id, principal)
    try: return plan_recovery(db, incident, nina_member_id=payload.nina_member_id)
    except SRERecoveryError as exc: raise HTTPException(409, str(exc))


@router.post("/sre/runs/{run_id}/execute")
def api_execute_sre(run_id: int, payload: SREExecuteRequest, principal: Principal = Depends(require_scope("company.incidents:write")), db: Session = Depends(get_db)):
    run = db.get(SRERecoveryRun, run_id)
    if not run: raise HTTPException(404, "SRE recovery run not found")
    enforce_org(run.organization_id, principal)
    if payload.force and principal.role not in {"owner","admin"}: raise HTTPException(403, "Admin role required to force recovery")
    try: return execute_recovery(db, run, force=payload.force)
    except SRERecoveryError as exc: raise HTTPException(409, str(exc))


@router.post("/sre/tick")
def api_sre_tick(principal: Principal = Depends(require_scope("company.incidents:write")), db: Session = Depends(get_db)):
    return tick_sre_recovery(db, organization_id=active_org(principal))


@router.get("/sre/runs")
def list_sre_runs(principal: Principal = Depends(require_scope("company.incidents:read")), db: Session = Depends(get_db)):
    return db.query(SRERecoveryRun).filter(SRERecoveryRun.organization_id == active_org(principal)).order_by(SRERecoveryRun.id.desc()).limit(500).all()


@router.get("/sre/decisions")
def list_sre_decisions(principal: Principal = Depends(require_scope("company.incidents:read")), db: Session = Depends(get_db)):
    return db.query(SREDecision).filter(SREDecision.organization_id == active_org(principal)).order_by(SREDecision.id.desc()).limit(500).all()


@router.get("/control-plane/summary")
def v15_summary(principal: Principal = Depends(require_scope("company.portfolio:read")), db: Session = Depends(get_db)):
    org = active_org(principal)
    def count(model, *criteria): return db.query(model).filter(model.organization_id == org, *criteria).count()
    return {
        "runner_certificates_active": count(RunnerCertificate, RunnerCertificate.status == "active"),
        "workload_keys_active": count(WorkloadSigningKey, WorkloadSigningKey.status == "active"),
        "telemetry_exporters": count(TelemetryExporter, TelemetryExporter.enabled == True),  # noqa: E712
        "secret_providers": count(SecretProviderConnection, SecretProviderConnection.enabled == True),  # noqa: E712
        "paging_routes": count(IncidentPagingRoute, IncidentPagingRoute.enabled == True),  # noqa: E712
        "scheduler_nodes_online": count(SchedulerNode, SchedulerNode.status == "online"),
        "sre_runs_active": count(SRERecoveryRun, SRERecoveryRun.status.in_(["planned","approval_required","running"])),
        "open_incidents": count(Incident, Incident.status != "resolved"),
    }
