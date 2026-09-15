import os
from app.worker import celery_app
from app.db.session import SessionLocal
from app.models import Organization, TelemetryExporter
from app.core.config import settings
from app.services.scheduler_ha import register_scheduler_node, acquire_leadership
from app.services.incident_paging import dispatch_queued_notifications
from app.services.sre_recovery import tick_sre_recovery
from app.services.telemetry_export import dispatch_exporter


@celery_app.task(name="v15.control_plane_tick")
def control_plane_tick():
    db = SessionLocal(); summary = {"leaders":0,"sre":{},"paging":{},"exports":0}
    try:
        for org in db.query(Organization).all():
            node = register_scheduler_node(db, organization_id=org.id, node_key=settings.scheduler_node_key,
                                           capacity=1, labels={"role":"v15-control-plane"})
            lease, acquired = acquire_leadership(db, node, lease_name="v15-sre-control-loop", ttl_seconds=45)
            if not acquired: continue
            summary["leaders"] += 1
            summary["sre"][str(org.id)] = tick_sre_recovery(db, organization_id=org.id)
            summary["paging"][str(org.id)] = dispatch_queued_notifications(db, organization_id=org.id)
        return summary
    finally: db.close()


@celery_app.task(name="v15.export_telemetry")
def export_telemetry():
    db = SessionLocal(); completed = failed = 0
    try:
        rows = db.query(TelemetryExporter).filter(TelemetryExporter.enabled == True, TelemetryExporter.provider != "prometheus_pull").all()  # noqa: E712
        for exporter in rows:
            attempt = dispatch_exporter(db, exporter)
            if attempt.status == "completed": completed += 1
            else: failed += 1
        return {"completed":completed,"failed":failed}
    finally: db.close()
