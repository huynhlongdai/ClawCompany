import json
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from app.models import SRERecoveryPolicy, SRERecoveryRun, SREDecision, Incident, Approval, Deployment, SLOEvaluation, SLODefinition
from app.services.incident_paging import queue_incident_notifications, dispatch_queued_notifications
from app.services.incidents import update_incident_status
from app.services.releases import rollback_environment, ReleaseError
from app.services.telemetry_slo import evaluate_slo
from app.services.company_event_bus import emit_event


class SRERecoveryError(RuntimeError): pass

def utcnow(): return datetime.now(timezone.utc).replace(tzinfo=None)

def _loads(value: str, fallback):
    try: return json.loads(value or "")
    except Exception: return fallback

def select_policy(db: Session, incident: Incident) -> SRERecoveryPolicy | None:
    candidates = db.query(SRERecoveryPolicy).filter(SRERecoveryPolicy.organization_id == incident.organization_id,
                                                     SRERecoveryPolicy.enabled == True).order_by(SRERecoveryPolicy.company_id.desc(), SRERecoveryPolicy.id.asc()).all()  # noqa: E712
    for p in candidates:
        if p.company_id is not None and p.company_id != incident.company_id: continue
        if incident.severity in set(_loads(p.severities_json, [])): return p
    return None

def plan_recovery(db: Session, incident: Incident, *, nina_member_id: int | None = None) -> SRERecoveryRun:
    if incident.status == "resolved": raise SRERecoveryError("Incident is already resolved")
    existing = db.query(SRERecoveryRun).filter(SRERecoveryRun.incident_id == incident.id,
                                               SRERecoveryRun.status.in_(["planned","approval_required","running"])).first()
    if existing: return existing
    policy = select_policy(db, incident)
    if not policy: raise SRERecoveryError("No recovery policy matches this incident")
    attempts = db.query(SRERecoveryRun).filter_by(incident_id=incident.id, policy_id=policy.id).count()
    if attempts >= policy.max_attempts: raise SRERecoveryError("Recovery policy attempt limit reached")
    actions = list(_loads(policy.actions_json, [])); approval_required = incident.severity in set(_loads(policy.approval_required_for_json, []))
    run = SRERecoveryRun(organization_id=incident.organization_id, policy_id=policy.id, incident_id=incident.id,
                         status="approval_required" if approval_required else "planned", attempt=attempts + 1,
                         plan_json=json.dumps({"actions": actions, "severity": incident.severity}, sort_keys=True))
    db.add(run); db.commit(); db.refresh(run)
    approval = None
    if approval_required:
        approval = Approval(organization_id=incident.organization_id, company_id=incident.company_id,
                            requester_member_id=nina_member_id, action=f"sre.recovery.execute:{incident.id}", risk=incident.severity,
                            policy_key=f"sre_recovery:{policy.id}", status="pending",
                            evidence=json.dumps({"incident_id":incident.id,"run_id":run.id,"actions":actions}))
        db.add(approval); db.commit(); db.refresh(approval); run.approval_id = approval.id; db.add(run); db.commit(); db.refresh(run)
    decision = SREDecision(organization_id=incident.organization_id, incident_id=incident.id, recovery_run_id=run.id,
                           nina_member_id=nina_member_id, risk=incident.severity,
                           decision="request_approval" if approval_required else "execute_recovery",
                           rationale=f"Matched deterministic SRE policy '{policy.name}' for {incident.severity} incident.",
                           evidence_json=json.dumps({"incident_status":incident.status,"policy_id":policy.id}),
                           action_json=json.dumps({"actions":actions,"approval_id":approval.id if approval else None}), status="recorded")
    db.add(decision); db.commit()
    emit_event(db, organization_id=incident.organization_id, company_id=incident.company_id, event_type="sre.recovery.planned",
               source="nina_sre", aggregate_type="sre_recovery_run", aggregate_id=str(run.id), actor_member_id=nina_member_id,
               payload={"incident_id":incident.id,"run_id":run.id,"approval_required":approval_required})
    return run

def execute_recovery(db: Session, run: SRERecoveryRun, *, force: bool = False) -> SRERecoveryRun:
    incident = db.get(Incident, run.incident_id); policy = db.get(SRERecoveryPolicy, run.policy_id)
    if not incident or not policy: raise SRERecoveryError("Recovery context is unavailable")
    if run.status in {"completed","failed","blocked"}: return run
    if run.approval_id and not force:
        approval = db.get(Approval, run.approval_id)
        if not approval or approval.status == "pending": run.status = "approval_required"; db.add(run); db.commit(); return run
        if approval.status != "approved": run.status = "blocked"; run.error = f"Approval status: {approval.status}"; run.completed_at = utcnow(); db.add(run); db.commit(); db.refresh(run); return run
    actions = _loads(run.plan_json, {}).get("actions", []); results = []; run.status = "running"; run.started_at = utcnow(); db.add(run); db.commit()
    try:
        for action in actions:
            if action == "page":
                queued = queue_incident_notifications(db, incident, event_type="recovery"); results.append({"action":action,"queued":len(queued)})
            elif action == "mark_mitigating":
                if incident.status in {"open","acknowledged"}: update_incident_status(db, incident, "mitigating", message="Nina SRE recovery started")
                results.append({"action":action,"status":incident.status})
            elif action == "rollback":
                if not incident.deployment_id: results.append({"action":action,"skipped":"incident has no deployment"}); continue
                dep = db.get(Deployment, incident.deployment_id)
                if not dep or not dep.previous_deployment_id: results.append({"action":action,"skipped":"no previous deployment"}); continue
                rb = rollback_environment(db, dep, None, "Nina SRE automatic recovery")
                results.append({"action":action,"rollback_id":rb.id})
            elif action == "re_evaluate_slo":
                if not incident.slo_evaluation_id: results.append({"action":action,"skipped":"no SLO evaluation"}); continue
                ev = db.get(SLOEvaluation, incident.slo_evaluation_id); slo = db.get(SLODefinition, ev.slo_id) if ev else None
                if not slo: results.append({"action":action,"skipped":"SLO unavailable"}); continue
                new_ev = evaluate_slo(db, slo, deployment_id=incident.deployment_id, release_id=incident.release_id)
                results.append({"action":action,"evaluation_id":new_ev.id,"status":new_ev.status})
            else: results.append({"action":action,"skipped":"unsupported action"})
        dispatch_queued_notifications(db, organization_id=incident.organization_id)
        run.status = "completed"; run.result_json = json.dumps(results, default=str); run.completed_at = utcnow(); run.error = ""
    except Exception as exc:
        run.status = "failed"; run.error = str(exc)[:8000]; run.result_json = json.dumps(results, default=str); run.completed_at = utcnow()
    db.add(run); db.commit(); db.refresh(run)
    emit_event(db, organization_id=incident.organization_id, company_id=incident.company_id,
               event_type=f"sre.recovery.{run.status}", source="nina_sre", aggregate_type="sre_recovery_run",
               aggregate_id=str(run.id), payload={"incident_id":incident.id,"run_id":run.id,"status":run.status})
    return run

def tick_sre_recovery(db: Session, organization_id: int | None = None) -> dict:
    q = db.query(Incident).filter(Incident.status.in_(["open","acknowledged","mitigating"]))
    if organization_id is not None: q = q.filter(Incident.organization_id == organization_id)
    planned = executed = errors = 0
    for incident in q.order_by(Incident.id.asc()).limit(100).all():
        try:
            run = plan_recovery(db, incident)
            planned += 1
            if run.status == "planned": execute_recovery(db, run); executed += 1
            elif run.status == "approval_required" and run.approval_id:
                approval = db.get(Approval, run.approval_id)
                if approval and approval.status == "approved": execute_recovery(db, run); executed += 1
        except SRERecoveryError:
            errors += 1
    return {"planned":planned,"executed":executed,"errors":errors}
