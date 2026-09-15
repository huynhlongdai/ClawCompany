from app.worker import celery_app
from app.db.session import SessionLocal
from app.services.event_webhooks import deliver_webhook, due_deliveries


@celery_app.task(name="webhooks.dispatch_due")
def dispatch_due_webhooks():
    db = SessionLocal()
    try:
        rows = due_deliveries(db, 100)
        result = []
        for row in rows:
            delivered = deliver_webhook(db, row)
            result.append({"id": delivered.id, "status": delivered.status, "attempts": delivered.attempts})
        return {"processed": len(result), "deliveries": result}
    finally:
        db.close()
