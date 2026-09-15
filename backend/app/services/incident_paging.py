import hashlib
import hmac
import json
import os
from datetime import datetime, timezone
from urllib.parse import urlparse
import httpx
from sqlalchemy.orm import Session
from app.core.config import settings
from app.models import Incident, IncidentPagingRoute, IncidentNotification


class IncidentPagingError(RuntimeError): pass

def utcnow(): return datetime.now(timezone.utc).replace(tzinfo=None)

def queue_incident_notifications(db: Session, incident: Incident, *, event_type: str = "opened") -> list[IncidentNotification]:
    routes = db.query(IncidentPagingRoute).filter(
        IncidentPagingRoute.organization_id == incident.organization_id,
        IncidentPagingRoute.enabled == True,  # noqa: E712
    ).all()
    out = []
    for route in routes:
        if route.company_id is not None and route.company_id != incident.company_id: continue
        try: severities = set(json.loads(route.severities_json or "[]"))
        except Exception: severities = {"critical", "high"}
        if incident.severity not in severities: continue
        existing = db.query(IncidentNotification).filter_by(incident_id=incident.id, route_id=route.id, event_type=event_type).first()
        if existing: out.append(existing); continue
        item = IncidentNotification(organization_id=incident.organization_id, incident_id=incident.id,
                                    route_id=route.id, event_type=event_type, status="queued")
        db.add(item); out.append(item)
    db.commit()
    for item in out: db.refresh(item)
    return out

def _allowed(url: str) -> bool:
    p = urlparse(url)
    if p.scheme not in {"http", "https"} or not p.hostname: return False
    allowed = {x.strip().lower() for x in settings.incident_paging_allowed_hosts.split(",") if x.strip()}
    return p.hostname.lower() in allowed

def _secret(ref: str) -> str:
    if not ref: return ""
    if not ref.startswith("env:"): raise IncidentPagingError("Paging secret references must use env:NAME")
    value = os.environ.get(ref.split(":", 1)[1], "")
    if not value: raise IncidentPagingError("Paging secret is unavailable")
    return value

def deliver_notification(db: Session, notification: IncidentNotification) -> IncidentNotification:
    incident = db.get(Incident, notification.incident_id); route = db.get(IncidentPagingRoute, notification.route_id)
    if not incident or not route or not route.enabled: raise IncidentPagingError("Incident or paging route unavailable")
    notification.attempt += 1; payload = {
        "event": f"incident.{notification.event_type}", "incident_id": incident.id, "organization_id": incident.organization_id,
        "title": incident.title, "severity": incident.severity, "status": incident.status, "summary": incident.summary,
        "created_at": notification.created_at.isoformat() if notification.created_at else None,
    }
    try:
        if route.provider == "console":
            notification.status = "sent"; notification.response_excerpt = json.dumps(payload, ensure_ascii=False)[:2000]
        elif route.provider == "webhook":
            if not _allowed(route.endpoint): raise IncidentPagingError("Paging webhook host is not allowlisted")
            body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode(); headers = {"Content-Type":"application/json"}
            secret = _secret(route.secret_ref)
            if secret: headers["X-ClawCompany-Signature"] = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
            with httpx.Client(timeout=settings.incident_paging_timeout_seconds) as client:
                r = client.post(route.endpoint, content=body, headers=headers)
            notification.response_code = r.status_code; notification.response_excerpt = r.text[:2000]
            if r.status_code >= 300: raise IncidentPagingError(f"Paging webhook returned HTTP {r.status_code}")
            notification.status = "sent"
        else: raise IncidentPagingError(f"Unsupported paging provider: {route.provider}")
        notification.sent_at = utcnow(); notification.error = ""
    except Exception as exc:
        notification.status = "failed"; notification.error = str(exc)[:4000]
    db.add(notification); db.commit(); db.refresh(notification); return notification

def dispatch_queued_notifications(db: Session, organization_id: int | None = None, limit: int = 100) -> dict:
    q = db.query(IncidentNotification).filter(IncidentNotification.status.in_(["queued", "failed"]), IncidentNotification.attempt < 5)
    if organization_id is not None: q = q.filter(IncidentNotification.organization_id == organization_id)
    sent = failed = 0
    for item in q.order_by(IncidentNotification.id.asc()).limit(limit).all():
        deliver_notification(db, item)
        if item.status == "sent": sent += 1
        else: failed += 1
    return {"sent": sent, "failed": failed}
