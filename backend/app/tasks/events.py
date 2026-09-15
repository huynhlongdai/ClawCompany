from app.worker import celery_app
from app.db.session import SessionLocal
from app.models import CompanyEvent
from app.services.trigger_engine import process_event
from app.services.sla import monitor_sla
from app.services.decision_loop import tick_due_loops


@celery_app.task(name="events.dispatch_pending")
def dispatch_pending_events():
    db = SessionLocal()
    results = []
    try:
        rows = db.query(CompanyEvent).filter(CompanyEvent.status == "pending").order_by(CompanyEvent.id).limit(100).all()
        for item in rows:
            try:
                summary = process_event(db, item)
                results.append({"event_id": item.id, "status": summary["event"].status, "executions": len(summary["executions"])})
            except Exception as exc:
                item.status = "error"; item.error = str(exc); db.add(item); db.commit()
                results.append({"event_id": item.id, "error": str(exc)})
        return {"processed": len(results), "results": results}
    finally:
        db.close()


@celery_app.task(name="events.monitor_sla")
def monitor_company_sla():
    db = SessionLocal()
    try:
        rows = monitor_sla(db)
        return {"created": len(rows), "incident_ids": [x.id for x in rows]}
    finally:
        db.close()


@celery_app.task(name="events.tick_decision_loops")
def tick_company_decision_loops():
    db = SessionLocal()
    try:
        rows = tick_due_loops(db)
        return {"processed": len(rows), "run_ids": [x.id for x in rows]}
    finally:
        db.close()
