import json
import os
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from sqlalchemy.orm import Session
from app.core.config import settings
from app.models import TrafficRouter, TrafficShift, Release


class TrafficRouterError(RuntimeError):
    pass


def _config(router: TrafficRouter) -> dict:
    try: return json.loads(router.config_json or "{}")
    except Exception: return {}


def _weights(router: TrafficRouter) -> dict[str, int]:
    try: return {str(k): int(v) for k, v in json.loads(router.current_weights_json or "{}").items()}
    except Exception: return {}


def _safe_name(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9_.-]+", "-", value or "router")[:160]
    return value or "router"


def _persist_file(router: TrafficRouter, weights: dict[str, int]) -> str:
    cfg = _config(router)
    root = Path(settings.traffic_router_config_root).expanduser().resolve()
    custom = cfg.get("path", "")
    target = Path(custom).expanduser().resolve() if custom else (root / str(router.organization_id) / f"{_safe_name(router.name)}.json").resolve()
    if not settings.traffic_router_allow_external_path and target != root and root not in target.parents:
        raise TrafficRouterError("Traffic router config path escapes configured root")
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {"router_id": router.id, "environment_id": router.environment_id, "weights": weights, "updated_at": datetime.utcnow().isoformat()}
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"); os.replace(tmp, target)
    return str(target)


def _persist_kubernetes(router: TrafficRouter, weights: dict[str, int]) -> str:
    if not settings.traffic_router_kubernetes_enabled:
        raise TrafficRouterError("Kubernetes traffic router is disabled")
    exe = shutil.which(settings.traffic_router_kubectl_executable)
    if not exe: raise TrafficRouterError("kubectl executable is unavailable")
    cfg = _config(router); name = cfg.get("httproute_name"); namespace = cfg.get("namespace", "default")
    services = cfg.get("release_services", {})
    if not name or not services: raise TrafficRouterError("Kubernetes router needs httproute_name and release_services")
    backend_refs = []
    for release_id, weight in weights.items():
        svc = services.get(str(release_id))
        if svc and weight > 0: backend_refs.append({"name": svc, "port": int(cfg.get("port", 80)), "weight": int(weight)})
    if not backend_refs: raise TrafficRouterError("No Kubernetes backendRefs resolved for current weights")
    patch = {"spec": {"rules": [{"backendRefs": backend_refs}]}}
    p = subprocess.run([exe, "-n", namespace, "patch", "httproute", name, "--type=merge", "-p", json.dumps(patch)],
                       capture_output=True, text=True, timeout=60)
    if p.returncode != 0: raise TrafficRouterError((p.stderr or p.stdout or "kubectl patch failed")[:4000])
    return f"kubernetes://{namespace}/httproute/{name}"


def apply_shift(db: Session, router: TrafficRouter, release: Release, *, to_weight: int,
                from_release: Release | None = None, strategy_run_id: int | None = None) -> TrafficShift:
    if not router.enabled or router.organization_id != release.organization_id:
        raise TrafficRouterError("Traffic router is unavailable for release organization")
    weight = max(0, min(100, int(to_weight)))
    weights = _weights(router)
    previous_weight = int(weights.get(str(release.id), 0))
    weights[str(release.id)] = weight
    if from_release:
        if from_release.organization_id != release.organization_id:
            raise TrafficRouterError("Source release belongs to another organization")
        weights[str(from_release.id)] = max(0, 100 - weight)
    # Normalize only the explicitly managed pair; unrelated backends remain untouched for advanced router policies.
    if router.provider == "database":
        provider_ref = f"database://traffic-router/{router.id}"
    elif router.provider == "file":
        provider_ref = _persist_file(router, weights)
    elif router.provider == "kubernetes":
        provider_ref = _persist_kubernetes(router, weights)
    else:
        raise TrafficRouterError(f"Unsupported traffic router provider: {router.provider}")
    router.current_weights_json = json.dumps(weights, sort_keys=True); db.add(router)
    shift = TrafficShift(
        organization_id=router.organization_id, router_id=router.id, strategy_run_id=strategy_run_id,
        release_id=release.id, from_release_id=from_release.id if from_release else None,
        from_weight=previous_weight, to_weight=weight, status="applied", provider_ref=provider_ref,
        detail_json=json.dumps({"weights": weights}, sort_keys=True),
    )
    db.add(shift); db.commit(); db.refresh(shift)
    return shift
