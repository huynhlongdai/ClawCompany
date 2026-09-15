import json
import os
from datetime import datetime, timezone
from urllib.parse import urlparse
import httpx
from sqlalchemy.orm import Session
from app.core.config import settings
from app.models import TelemetryMetricSample, TelemetryExporter, TelemetryExportAttempt, Incident, RunnerNode, RunnerLease, SLOEvaluation
from app.services.telemetry_slo import ingest_metric


class TelemetryExportError(RuntimeError): pass

def utcnow(): return datetime.now(timezone.utc).replace(tzinfo=None)

def _esc(value: str) -> str: return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")

def render_prometheus(db: Session, organization_id: int) -> str:
    lines = ["# HELP clawcompany_info ClawCompany control plane info", "# TYPE clawcompany_info gauge", f'clawcompany_info{{organization_id="{organization_id}"}} 1']
    counts = {
        "runner_nodes_online": db.query(RunnerNode).filter(RunnerNode.organization_id == organization_id, RunnerNode.status == "online").count(),
        "runner_leases_active": db.query(RunnerLease).filter(RunnerLease.organization_id == organization_id, RunnerLease.status == "active").count(),
        "incidents_open": db.query(Incident).filter(Incident.organization_id == organization_id, Incident.status != "resolved").count(),
        "slo_breaches_recent": db.query(SLOEvaluation).filter(SLOEvaluation.organization_id == organization_id, SLOEvaluation.status == "breached").count(),
    }
    for name, value in counts.items():
        lines += [f"# TYPE clawcompany_{name} gauge", f'clawcompany_{name}{{organization_id="{organization_id}"}} {value}']
    latest = db.query(TelemetryMetricSample).filter(TelemetryMetricSample.organization_id == organization_id).order_by(TelemetryMetricSample.id.desc()).limit(500).all()
    seen = set()
    for row in latest:
        labels = json.loads(row.labels_json or "{}")
        key = (row.metric_name, row.environment_id, row.release_id, tuple(sorted(labels.items())))
        if key in seen: continue
        seen.add(key)
        metric = "clawcompany_external_" + "".join(c if c.isalnum() or c == "_" else "_" for c in row.metric_name)
        parts = [f'organization_id="{organization_id}"']
        if row.environment_id is not None: parts.append(f'environment_id="{row.environment_id}"')
        if row.release_id is not None: parts.append(f'release_id="{row.release_id}"')
        for k, v in sorted(labels.items()): parts.append(f'{_esc(str(k))}="{_esc(str(v))}"')
        lines.append(f"{metric}{{{','.join(parts)}}} {row.value}")
    return "\n".join(lines) + "\n"


def ingest_otlp_json(db: Session, *, organization_id: int, payload: dict, environment_id: int | None = None,
                     deployment_id: int | None = None, release_id: int | None = None) -> int:
    count = 0
    for rm in payload.get("resourceMetrics", []) or []:
        resource_attrs = {a.get("key"): _otlp_value(a.get("value", {})) for a in (rm.get("resource", {}).get("attributes", []) or [])}
        for sm in rm.get("scopeMetrics", []) or []:
            for metric in sm.get("metrics", []) or []:
                name = metric.get("name") or "unnamed"
                points = []
                if "gauge" in metric: points = metric["gauge"].get("dataPoints", []) or []
                elif "sum" in metric: points = metric["sum"].get("dataPoints", []) or []
                elif "histogram" in metric: points = metric["histogram"].get("dataPoints", []) or []
                for point in points:
                    value = point.get("asDouble", point.get("asInt", point.get("sum")))
                    if value is None: continue
                    attrs = dict(resource_attrs)
                    attrs.update({a.get("key"): _otlp_value(a.get("value", {})) for a in (point.get("attributes", []) or [])})
                    ingest_metric(db, organization_id=organization_id, environment_id=environment_id,
                                  deployment_id=deployment_id, release_id=release_id, metric_name=name,
                                  value=float(value), unit=metric.get("unit", ""), labels=attrs)
                    count += 1
    return count


def _otlp_value(value: dict):
    for k in ("stringValue", "intValue", "doubleValue", "boolValue"):
        if k in value: return value[k]
    return json.dumps(value, sort_keys=True)


def _allowed_endpoint(url: str) -> bool:
    p = urlparse(url)
    if p.scheme not in {"http", "https"} or not p.hostname: return False
    allowed = {x.strip().lower() for x in settings.telemetry_export_allowed_hosts.split(",") if x.strip()}
    return p.hostname.lower() in allowed


def _auth_headers(ref: str) -> dict:
    if not ref: return {}
    if not ref.startswith("env:"): raise TelemetryExportError("Telemetry exporter auth uses env: secret references only")
    value = os.environ.get(ref.split(":", 1)[1], "")
    if not value: raise TelemetryExportError("Telemetry exporter auth secret is unavailable")
    return {"Authorization": f"Bearer {value}"}


def dispatch_exporter(db: Session, exporter: TelemetryExporter, *, limit: int = 500) -> TelemetryExportAttempt:
    if not exporter.enabled: raise TelemetryExportError("Telemetry exporter is disabled")
    attempt = TelemetryExportAttempt(organization_id=exporter.organization_id, exporter_id=exporter.id, status="running")
    db.add(attempt); db.commit(); db.refresh(attempt)
    try:
        if exporter.provider == "prometheus_pull":
            raise TelemetryExportError("prometheus_pull is scraped from /api/v15/metrics; it is not pushed")
        if not _allowed_endpoint(exporter.endpoint): raise TelemetryExportError("Telemetry exporter endpoint host is not allowlisted")
        rows = db.query(TelemetryMetricSample).filter(TelemetryMetricSample.organization_id == exporter.organization_id).order_by(TelemetryMetricSample.id.desc()).limit(limit).all()
        attempt.batch_size = len(rows); headers = _auth_headers(exporter.auth_secret_ref)
        with httpx.Client(timeout=settings.telemetry_export_timeout_seconds) as client:
            if exporter.provider == "prometheus_pushgateway":
                body = render_prometheus(db, exporter.organization_id); r = client.put(exporter.endpoint, content=body, headers={**headers, "Content-Type":"text/plain; version=0.0.4"})
            elif exporter.provider == "otlp_http_json":
                data = {"resourceMetrics":[{"resource":{"attributes":[{"key":"service.name","value":{"stringValue":"clawcompany"}}]},"scopeMetrics":[{"scope":{"name":"clawcompany.v15"},"metrics":[{"name":x.metric_name,"unit":x.unit,"gauge":{"dataPoints":[{"asDouble":x.value,"attributes":[]}]}} for x in rows]}]}]}
                r = client.post(exporter.endpoint, json=data, headers={**headers, "Content-Type":"application/json"})
            else: raise TelemetryExportError(f"Unsupported telemetry exporter: {exporter.provider}")
        attempt.response_code = r.status_code
        if r.status_code >= 300: raise TelemetryExportError(f"Exporter returned HTTP {r.status_code}: {r.text[:1000]}")
        attempt.status = "completed"; exporter.last_success_at = utcnow(); exporter.last_error = ""
    except Exception as exc:
        attempt.status = "failed"; attempt.error = str(exc)[:4000]; exporter.last_error = attempt.error
    attempt.completed_at = utcnow(); db.add_all([attempt, exporter]); db.commit(); db.refresh(attempt); return attempt
