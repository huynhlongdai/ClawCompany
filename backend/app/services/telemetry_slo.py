import json
from datetime import datetime, timedelta
from sqlalchemy import func
from sqlalchemy.orm import Session
from app.models import TelemetryMetricSample, SLODefinition, SLOEvaluation, Incident, IncidentEvent, DeploymentEnvironment
from app.services.company_event_bus import emit_event


class SLOError(RuntimeError):
    pass


def ingest_metric(db: Session, *, organization_id: int, metric_name: str, value: float,
                  environment_id: int | None = None, deployment_id: int | None = None, release_id: int | None = None,
                  unit: str = "", labels: dict | None = None, observed_at: datetime | None = None) -> TelemetryMetricSample:
    item = TelemetryMetricSample(
        organization_id=organization_id, environment_id=environment_id, deployment_id=deployment_id, release_id=release_id,
        metric_name=metric_name, value=float(value), unit=unit, labels_json=json.dumps(labels or {}, sort_keys=True),
        observed_at=observed_at or datetime.utcnow(),
    )
    db.add(item); db.commit(); db.refresh(item)
    return item


def create_incident_from_slo(db: Session, slo: SLODefinition, evaluation: SLOEvaluation) -> Incident:
    existing = db.query(Incident).filter(
        Incident.organization_id == slo.organization_id, Incident.slo_evaluation_id == evaluation.id
    ).first()
    if existing:
        return existing
    env = db.get(DeploymentEnvironment, slo.environment_id)
    item = Incident(
        organization_id=slo.organization_id, company_id=env.company_id if env else None,
        environment_id=slo.environment_id, deployment_id=evaluation.deployment_id, release_id=evaluation.release_id,
        slo_evaluation_id=evaluation.id, title=f"SLO breach: {slo.name}", severity=slo.severity,
        source="slo", summary=f"{slo.metric_name}={evaluation.aggregate_value} breached {slo.comparator} {slo.threshold}",
    )
    db.add(item); db.commit(); db.refresh(item)
    db.add(IncidentEvent(organization_id=item.organization_id, incident_id=item.id, event_type="opened",
                         message=item.summary, data_json=json.dumps({"slo_id": slo.id, "evaluation_id": evaluation.id})))
    db.commit()
    emit_event(db, organization_id=item.organization_id, company_id=item.company_id, event_type="incident.opened",
               source="observability", aggregate_type="incident", aggregate_id=str(item.id),
               payload={"incident_id": item.id, "severity": item.severity, "slo_id": slo.id})
    try:
        from app.services.incident_paging import queue_incident_notifications
        queue_incident_notifications(db, item, event_type="opened")
    except Exception:
        pass
    return item


def evaluate_slo(db: Session, slo: SLODefinition, *, deployment_id: int | None = None,
                 release_id: int | None = None, now: datetime | None = None) -> SLOEvaluation:
    if not slo.enabled:
        raise SLOError("SLO is disabled")
    now = now or datetime.utcnow(); start = now - timedelta(minutes=slo.window_minutes)
    q = db.query(TelemetryMetricSample).filter(
        TelemetryMetricSample.organization_id == slo.organization_id,
        TelemetryMetricSample.environment_id == slo.environment_id,
        TelemetryMetricSample.metric_name == slo.metric_name,
        TelemetryMetricSample.observed_at >= start,
        TelemetryMetricSample.observed_at <= now,
    )
    if deployment_id is not None: q = q.filter(TelemetryMetricSample.deployment_id == deployment_id)
    if release_id is not None: q = q.filter(TelemetryMetricSample.release_id == release_id)
    rows = q.all(); count = len(rows)
    aggregate = (sum(x.value for x in rows) / count) if count else None
    status = "insufficient_data"
    if count >= slo.min_samples and aggregate is not None:
        if slo.comparator == "lte": ok = aggregate <= slo.threshold
        elif slo.comparator == "gte": ok = aggregate >= slo.threshold
        else: raise SLOError("Unsupported SLO comparator")
        status = "passed" if ok else "breached"
    item = SLOEvaluation(
        organization_id=slo.organization_id, slo_id=slo.id, deployment_id=deployment_id, release_id=release_id,
        status=status, sample_count=count, aggregate_value=aggregate, threshold=slo.threshold,
        detail_json=json.dumps({"window_start": start.isoformat(), "window_end": now.isoformat(), "comparator": slo.comparator}),
        evaluated_at=now,
    )
    db.add(item); db.commit(); db.refresh(item)
    if item.status == "breached" and slo.auto_incident:
        create_incident_from_slo(db, slo, item)
    return item


def evaluate_due_slos(db: Session, organization_id: int | None = None) -> int:
    q = db.query(SLODefinition).filter(SLODefinition.enabled == True)  # noqa: E712
    if organization_id is not None: q = q.filter(SLODefinition.organization_id == organization_id)
    count = 0
    for slo in q.all():
        evaluate_slo(db, slo); count += 1
    return count
