import asyncio
import json
import uuid
from datetime import datetime
from sqlalchemy.orm import Session
from app.models import CompanyEvent
from app.realtime import broker


def emit_event(db: Session, *, organization_id: int, event_type: str, payload: dict | None = None,
               company_id: int | None = None, source: str = "company", aggregate_type: str = "",
               aggregate_id: str = "", actor_member_id: int | None = None, correlation_id: str = "",
               causation_id: str = "") -> CompanyEvent:
    item = CompanyEvent(
        organization_id=organization_id, company_id=company_id, event_type=event_type, source=source,
        aggregate_type=aggregate_type, aggregate_id=str(aggregate_id or ""), actor_member_id=actor_member_id,
        correlation_id=correlation_id or uuid.uuid4().hex, causation_id=causation_id,
        payload_json=json.dumps(payload or {}, ensure_ascii=False, default=str), status="pending",
        occurred_at=datetime.utcnow(),
    )
    db.add(item); db.commit(); db.refresh(item)
    event = {
        "id": item.id, "organization_id": organization_id, "company_id": company_id,
        "type": event_type, "source": source, "aggregate_type": aggregate_type,
        "aggregate_id": item.aggregate_id, "correlation_id": item.correlation_id,
        "payload": payload or {}, "occurred_at": item.occurred_at.isoformat(),
    }
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(broker.publish(f"org:{organization_id}", event))
        loop.create_task(broker.publish(f"company-events:{organization_id}", event))
    except RuntimeError:
        pass
    # Durable external delivery uses an outbox-style table. Import lazily to avoid
    # a service import cycle; failures here must not invalidate the company event itself.
    try:
        from app.services.event_webhooks import enqueue_webhook_deliveries
        enqueue_webhook_deliveries(db, item)
    except Exception:
        pass
    return item


def payload_of(item: CompanyEvent) -> dict:
    try:
        value = json.loads(item.payload_json or "{}")
        return value if isinstance(value, dict) else {"value": value}
    except Exception:
        return {}
