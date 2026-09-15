import fnmatch
import hashlib
import hmac
import json
import os
from datetime import datetime, timedelta
from urllib.parse import urlparse

import httpx
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import CompanyEvent, EventWebhookDelivery, EventWebhookEndpoint
from app.services.company_event_bus import payload_of


class WebhookDeliveryError(RuntimeError):
    pass


def _allowed_hosts() -> set[str]:
    return {x.strip().lower() for x in settings.event_webhook_allowed_hosts.split(",") if x.strip()}


def validate_webhook_url(url: str) -> str:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or not host:
        raise WebhookDeliveryError("Webhook URL must be http(s)")
    allowed = _allowed_hosts()
    if not allowed or host not in allowed:
        raise WebhookDeliveryError(f"Webhook host is not allowlisted: {host}")
    if parsed.scheme != "https" and host not in {"localhost", "127.0.0.1"}:
        raise WebhookDeliveryError("Non-local webhook endpoints must use HTTPS")
    return url


def _secret(secret_ref: str) -> str:
    if not secret_ref:
        return ""
    if not secret_ref.startswith("env:"):
        raise WebhookDeliveryError("Only env: secret references are supported in this snapshot")
    name = secret_ref[4:]
    if not name or not name.replace("_", "").isalnum():
        raise WebhookDeliveryError("Invalid environment secret reference")
    value = os.getenv(name, "")
    if not value:
        raise WebhookDeliveryError(f"Webhook signing secret is not available: {name}")
    return value


def enqueue_webhook_deliveries(db: Session, event: CompanyEvent) -> list[EventWebhookDelivery]:
    endpoints = db.query(EventWebhookEndpoint).filter(
        EventWebhookEndpoint.organization_id == event.organization_id,
        EventWebhookEndpoint.enabled == True,  # noqa: E712
    ).all()
    out = []
    for endpoint in endpoints:
        if endpoint.company_id is not None and endpoint.company_id != event.company_id:
            continue
        if not fnmatch.fnmatch(event.event_type, endpoint.event_pattern or "*"):
            continue
        exists = db.query(EventWebhookDelivery).filter(
            EventWebhookDelivery.endpoint_id == endpoint.id,
            EventWebhookDelivery.event_id == event.id,
        ).first()
        if exists:
            continue
        item = EventWebhookDelivery(
            organization_id=event.organization_id, endpoint_id=endpoint.id, event_id=event.id,
            status="pending", attempts=0, next_attempt_at=datetime.utcnow(),
        )
        db.add(item); out.append(item)
    if out:
        db.commit()
        for item in out: db.refresh(item)
    return out


def _body(event: CompanyEvent) -> bytes:
    payload = {
        "id": event.id,
        "organization_id": event.organization_id,
        "company_id": event.company_id,
        "type": event.event_type,
        "source": event.source,
        "aggregate_type": event.aggregate_type,
        "aggregate_id": event.aggregate_id,
        "correlation_id": event.correlation_id,
        "causation_id": event.causation_id,
        "payload": payload_of(event),
        "occurred_at": event.occurred_at.isoformat() if event.occurred_at else None,
    }
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False, default=str).encode("utf-8")


def deliver_webhook(db: Session, delivery: EventWebhookDelivery) -> EventWebhookDelivery:
    endpoint = db.get(EventWebhookEndpoint, delivery.endpoint_id)
    event = db.get(CompanyEvent, delivery.event_id)
    if not endpoint or not event or endpoint.organization_id != delivery.organization_id or event.organization_id != delivery.organization_id:
        delivery.status = "dead_letter"; delivery.error = "Endpoint/event tenant mismatch or missing"
        db.add(delivery); db.commit(); db.refresh(delivery); return delivery
    if not endpoint.enabled:
        delivery.status = "disabled"; db.add(delivery); db.commit(); db.refresh(delivery); return delivery
    try:
        validate_webhook_url(endpoint.target_url)
        body = _body(event)
        secret = _secret(endpoint.secret_ref)
        headers = {"Content-Type": "application/json", "X-ClawCompany-Event": event.event_type,
                   "X-ClawCompany-Delivery": str(delivery.id)}
        if secret:
            digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
            headers["X-ClawCompany-Signature"] = f"sha256={digest}"
        delivery.attempts += 1
        response = httpx.post(endpoint.target_url, content=body, headers=headers, timeout=settings.event_webhook_timeout_seconds)
        delivery.response_code = response.status_code
        delivery.response_body = response.text[:12000]
        if 200 <= response.status_code < 300:
            delivery.status = "delivered"; delivery.error = ""; delivery.delivered_at = datetime.utcnow(); delivery.next_attempt_at = None
        else:
            raise WebhookDeliveryError(f"Webhook returned HTTP {response.status_code}")
    except Exception as exc:
        delivery.error = str(exc)[:12000]
        if delivery.attempts >= endpoint.max_attempts:
            delivery.status = "dead_letter"; delivery.next_attempt_at = None
        else:
            delivery.status = "retrying"
            delay = endpoint.backoff_seconds * (2 ** max(0, delivery.attempts - 1))
            delivery.next_attempt_at = datetime.utcnow() + timedelta(seconds=min(delay, 86400))
    db.add(delivery); db.commit(); db.refresh(delivery)
    return delivery


def due_deliveries(db: Session, limit: int = 100) -> list[EventWebhookDelivery]:
    now = datetime.utcnow()
    return db.query(EventWebhookDelivery).filter(
        EventWebhookDelivery.status.in_(["pending", "retrying"]),
        EventWebhookDelivery.next_attempt_at <= now,
    ).order_by(EventWebhookDelivery.id).limit(limit).all()
