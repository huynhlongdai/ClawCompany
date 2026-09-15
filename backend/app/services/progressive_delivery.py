import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
from sqlalchemy.orm import Session

from app.models import (
    Deployment, DeploymentEnvironment, DeploymentHealthPolicy, DeploymentHealthRun,
    DeploymentStrategyRun, Release, Repository,
)
from app.services.company_event_bus import emit_event
from app.services.releases import ReleaseError, _archive_commit, _deploy_root, _safe_slug, deploy_release, release_commit, rollback_environment


class ProgressiveDeliveryError(RuntimeError):
    pass


def _health_once(policy: DeploymentHealthPolicy, deployment: Deployment, env: DeploymentEnvironment) -> tuple[bool, dict]:
    if policy.check_type == "filesystem_marker":
        root = Path(deployment.deployed_path).resolve()
        if not root.exists():
            return False, {"reason": "deployment path missing", "path": str(root)}
        if not policy.target:
            return True, {"path": str(root), "exists": True}
        target = (root / policy.target.lstrip("/")).resolve()
        if target != root and root not in target.parents:
            return False, {"reason": "health target escapes deployment root"}
        return target.exists(), {"path": str(target), "exists": target.exists()}
    if policy.check_type == "http":
        if not env.base_url:
            return False, {"reason": "environment base_url is required for HTTP health checks"}
        base = urlparse(env.base_url)
        url = urljoin(env.base_url.rstrip("/") + "/", policy.target.lstrip("/"))
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or parsed.hostname != base.hostname:
            return False, {"reason": "health URL must stay on the environment base host"}
        try:
            response = httpx.get(url, timeout=policy.timeout_seconds, follow_redirects=False)
            return response.status_code == policy.expected_status, {"url": url, "status_code": response.status_code}
        except Exception as exc:
            return False, {"url": url, "error": str(exc)[:1000]}
    return False, {"reason": f"unsupported health check type: {policy.check_type}"}


def run_health_check(db: Session, policy: DeploymentHealthPolicy, deployment: Deployment) -> DeploymentHealthRun:
    env = db.get(DeploymentEnvironment, deployment.environment_id)
    if not env or env.organization_id != policy.organization_id or policy.environment_id != env.id:
        raise ProgressiveDeliveryError("Health policy does not match deployment environment")
    run = DeploymentHealthRun(
        organization_id=policy.organization_id, policy_id=policy.id, deployment_id=deployment.id, status="running",
    )
    db.add(run); db.commit(); db.refresh(run)
    details: list[dict] = []
    max_attempts = max(policy.success_threshold, policy.failure_threshold, 1) + 2
    for attempt in range(max_attempts):
        ok, detail = _health_once(policy, deployment, env)
        run.attempts += 1; details.append({"attempt": attempt + 1, "ok": ok, **detail})
        if ok: run.successes += 1
        else: run.failures += 1
        if run.successes >= policy.success_threshold:
            run.status = "passed"; break
        if run.failures >= policy.failure_threshold:
            run.status = "failed"; break
    if run.status == "running":
        run.status = "failed"
    run.detail_json = json.dumps({"checks": details}, default=str); run.completed_at = datetime.utcnow()
    db.add(run); db.commit(); db.refresh(run)
    emit_event(
        db, organization_id=run.organization_id, event_type="deployment.health.completed", source="engineering_org",
        aggregate_type="deployment_health_run", aggregate_id=str(run.id),
        payload={"health_run_id": run.id, "deployment_id": deployment.id, "status": run.status,
                 "successes": run.successes, "failures": run.failures},
    )
    return run


def _filesystem_blue_green(db: Session, release: Release, env: DeploymentEnvironment, requester: int | None,
                           policy: DeploymentHealthPolicy | None) -> tuple[Deployment, DeploymentHealthRun | None]:
    commit = release_commit(db, release)
    repo = db.get(Repository, release.repository_id)
    if not repo or not repo.local_path:
        raise ProgressiveDeliveryError("Repository checkout is unavailable")
    if env.provider != "filesystem":
        raise ProgressiveDeliveryError("Built-in blue/green currently supports filesystem environments only")
    previous = db.query(Deployment).filter(
        Deployment.environment_id == env.id, Deployment.status == "deployed"
    ).order_by(Deployment.id.desc()).first()
    deployment = Deployment(
        organization_id=release.organization_id, environment_id=env.id, release_id=release.id,
        requested_by_member_id=requester, status="verifying", previous_deployment_id=previous.id if previous else None,
        started_at=datetime.utcnow(),
    )
    db.add(deployment); db.commit(); db.refresh(deployment)
    root = _deploy_root() / str(release.organization_id) / _safe_slug(env.slug)
    version_dir = (root / "releases" / f"{release.id}-{_safe_slug(release.version)}-bg").resolve()
    try:
        if version_dir.exists(): shutil.rmtree(version_dir)
        _archive_commit(Path(repo.local_path).resolve(), commit, version_dir)
        deployment.deployed_path = str(version_dir); deployment.provider_ref = str(root / "current")
        db.add(deployment); db.commit(); db.refresh(deployment)
        health = run_health_check(db, policy, deployment) if policy else None
        if health and health.status != "passed":
            deployment.status = "failed"; deployment.error = "Blue/green candidate failed health checks"
            deployment.completed_at = datetime.utcnow(); db.add(deployment); db.commit(); db.refresh(deployment)
            return deployment, health
        root.mkdir(parents=True, exist_ok=True)
        current = root / "current"; tmp = root / f".bluegreen-{deployment.id}.tmp"
        if tmp.exists() or tmp.is_symlink(): tmp.unlink()
        tmp.symlink_to(version_dir, target_is_directory=True); os.replace(tmp, current)
        deployment.status = "deployed"; deployment.completed_at = datetime.utcnow()
        release.status = "released"; release.released_at = release.released_at or datetime.utcnow()
        db.add_all([deployment, release]); db.commit(); db.refresh(deployment)
        return deployment, health
    except Exception as exc:
        deployment.status = "failed"; deployment.error = str(exc); deployment.completed_at = datetime.utcnow()
        db.add(deployment); db.commit(); db.refresh(deployment)
        if isinstance(exc, ProgressiveDeliveryError): raise
        raise ProgressiveDeliveryError(str(exc)) from exc


def progressive_deploy(db: Session, release: Release, env: DeploymentEnvironment, *, strategy: str = "rolling",
                       policy: DeploymentHealthPolicy | None = None, traffic_percent: int = 10,
                       requested_by_member_id: int | None = None) -> DeploymentStrategyRun:
    if release.organization_id != env.organization_id or release.repository_id != env.repository_id:
        raise ProgressiveDeliveryError("Release and environment do not match")
    if policy and (policy.organization_id != release.organization_id or policy.environment_id != env.id or not policy.enabled):
        raise ProgressiveDeliveryError("Health policy is unavailable for this environment")
    item = DeploymentStrategyRun(
        organization_id=release.organization_id, environment_id=env.id, release_id=release.id,
        requested_by_member_id=requested_by_member_id, strategy=strategy, traffic_percent=traffic_percent,
        status="running", phase_json=json.dumps({"phase": "prepare"}),
    )
    db.add(item); db.commit(); db.refresh(item)
    try:
        if strategy == "canary":
            # Weighted traffic requires an ingress/router adapter. We persist the strategy request and fail closed.
            item.status = "waiting_router"; item.error = "Canary needs a weighted traffic-router provider adapter"
            item.phase_json = json.dumps({"phase": "router_required", "traffic_percent": traffic_percent})
            db.add(item); db.commit(); db.refresh(item); return item
        if strategy == "blue_green":
            deployment, health = _filesystem_blue_green(db, release, env, requested_by_member_id, policy)
            item.deployment_id = deployment.id; item.health_run_id = health.id if health else None
            item.status = "completed" if deployment.status == "deployed" else "failed"
            item.phase_json = json.dumps({"phase": "cutover" if deployment.status == "deployed" else "preflight_failed"})
        else:
            deployment = deploy_release(db, release, env, requested_by_member_id)
            item.deployment_id = deployment.id
            health = run_health_check(db, policy, deployment) if policy else None
            item.health_run_id = health.id if health else None
            if health and health.status != "passed":
                if policy.auto_rollback and deployment.previous_deployment_id:
                    rollback = rollback_environment(db, deployment, requested_by_member_id, "Automatic rollback: deployment health failed")
                    item.rollback_id = rollback.id; item.status = "rolled_back"
                else:
                    item.status = "failed"
                item.error = "Deployment health check failed"
            else:
                item.status = "completed"
            item.phase_json = json.dumps({"phase": "verified" if item.status == "completed" else item.status})
        item.completed_at = datetime.utcnow(); db.add(item); db.commit(); db.refresh(item)
        emit_event(
            db, organization_id=item.organization_id, event_type="deployment.strategy.completed", source="engineering_org",
            aggregate_type="deployment_strategy_run", aggregate_id=str(item.id), actor_member_id=requested_by_member_id,
            payload={"strategy_run_id": item.id, "strategy": strategy, "status": item.status,
                     "deployment_id": item.deployment_id, "rollback_id": item.rollback_id},
        )
        return item
    except (ReleaseError, ProgressiveDeliveryError, Exception) as exc:
        item.status = "failed"; item.error = str(exc)[:8000]; item.completed_at = datetime.utcnow()
        db.add(item); db.commit(); db.refresh(item)
        return item
