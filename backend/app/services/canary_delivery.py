import json
from datetime import datetime
from sqlalchemy.orm import Session
from app.models import Release, DeploymentEnvironment, TrafficRouter, SLODefinition, DeploymentStrategyRun, Deployment
from app.services.traffic_router import apply_shift, TrafficRouterError
from app.services.telemetry_slo import evaluate_slo
from app.services.releases import rollback_environment, ReleaseError
from app.services.company_event_bus import emit_event


class CanaryDeliveryError(RuntimeError):
    pass


def run_canary(db: Session, release: Release, env: DeploymentEnvironment, router: TrafficRouter, *,
               slo_ids: list[int] | None = None, steps: list[int] | None = None, requested_by_member_id: int | None = None) -> DeploymentStrategyRun:
    if release.organization_id != env.organization_id or release.repository_id != env.repository_id:
        raise CanaryDeliveryError("Release/environment mismatch")
    if router.organization_id != release.organization_id or router.environment_id != env.id:
        raise CanaryDeliveryError("Traffic router/environment mismatch")
    sequence = steps or [10, 25, 50, 100]
    if not sequence or sequence[-1] != 100 or any(x < 1 or x > 100 for x in sequence) or sequence != sorted(set(sequence)):
        raise CanaryDeliveryError("Canary steps must be unique ascending percentages ending at 100")
    slos = []
    for sid in slo_ids or []:
        slo = db.get(SLODefinition, sid)
        if not slo or slo.organization_id != release.organization_id or slo.environment_id != env.id or not slo.enabled:
            raise CanaryDeliveryError(f"SLO {sid} is unavailable")
        slos.append(slo)
    previous_deployment = db.query(Deployment).filter(Deployment.environment_id == env.id, Deployment.status == "deployed",
                                                       Deployment.release_id != release.id).order_by(Deployment.id.desc()).first()
    candidate_deployment = db.query(Deployment).filter(Deployment.environment_id == env.id, Deployment.release_id == release.id,
                                                        Deployment.status == "deployed").order_by(Deployment.id.desc()).first()
    from_release = db.get(Release, previous_deployment.release_id) if previous_deployment else None
    if from_release is None:
        # A traffic router can already point at a stable release even when its deployment
        # was provisioned outside ClawCompany. Recover that baseline from router weights.
        try:
            current_weights = json.loads(router.current_weights_json or "{}")
        except Exception:
            current_weights = {}
        candidates = [(int(weight), int(rid)) for rid, weight in current_weights.items()
                      if str(rid).isdigit() and int(rid) != release.id and int(weight) > 0]
        if candidates:
            _, stable_release_id = max(candidates)
            candidate = db.get(Release, stable_release_id)
            if candidate and candidate.organization_id == release.organization_id:
                from_release = candidate
    item = DeploymentStrategyRun(
        organization_id=release.organization_id, environment_id=env.id, release_id=release.id,
        deployment_id=candidate_deployment.id if candidate_deployment else None,
        requested_by_member_id=requested_by_member_id, strategy="canary", traffic_percent=sequence[0],
        status="running", phase_json=json.dumps({"phase":"starting", "steps":sequence}),
    )
    db.add(item); db.commit(); db.refresh(item)
    history = []
    try:
        for weight in sequence:
            shift = apply_shift(db, router, release, to_weight=weight, from_release=from_release, strategy_run_id=item.id)
            evaluations = [evaluate_slo(db, slo, deployment_id=candidate_deployment.id if candidate_deployment else None,
                                        release_id=release.id) for slo in slos]
            breached = [e for e in evaluations if e.status == "breached"]
            insufficient = [e for e in evaluations if e.status == "insufficient_data"]
            history.append({"weight": weight, "shift_id": shift.id, "evaluations": [{"id":e.id,"status":e.status,"value":e.aggregate_value} for e in evaluations]})
            item.traffic_percent = weight
            item.phase_json = json.dumps({"phase":"verify", "current_weight":weight, "history":history}, default=str)
            db.add(item); db.commit()
            if insufficient:
                apply_shift(db, router, release, to_weight=0, from_release=from_release, strategy_run_id=item.id)
                item.status = "waiting_metrics"; item.error = "Canary halted: insufficient SLO telemetry"
                item.phase_json = json.dumps({"phase":"metrics_required", "history":history}, default=str); break
            if breached:
                apply_shift(db, router, release, to_weight=0, from_release=from_release, strategy_run_id=item.id)
                item.status = "rolled_back"; item.error = "Canary SLO breached"
                if candidate_deployment and candidate_deployment.previous_deployment_id and any(s.auto_rollback for s in slos):
                    try:
                        rollback = rollback_environment(db, candidate_deployment, requested_by_member_id, "Automatic rollback: canary SLO breach")
                        item.rollback_id = rollback.id
                    except ReleaseError:
                        pass
                item.phase_json = json.dumps({"phase":"rolled_back", "history":history}, default=str); break
        else:
            item.status = "completed"; item.phase_json = json.dumps({"phase":"promoted", "history":history}, default=str)
        item.completed_at = datetime.utcnow(); db.add(item); db.commit(); db.refresh(item)
        emit_event(db, organization_id=item.organization_id, event_type="deployment.canary.completed", source="distributed_execution",
                   aggregate_type="deployment_strategy_run", aggregate_id=str(item.id), actor_member_id=requested_by_member_id,
                   payload={"strategy_run_id":item.id,"release_id":release.id,"status":item.status,"traffic_percent":item.traffic_percent})
        return item
    except (TrafficRouterError, Exception) as exc:
        item.status = "failed"; item.error = str(exc)[:8000]; item.completed_at = datetime.utcnow(); db.add(item); db.commit(); db.refresh(item)
        return item
