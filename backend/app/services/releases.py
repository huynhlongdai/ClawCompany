import io
import json
import os
import shutil
import subprocess
import tarfile
from datetime import datetime
from pathlib import Path
from sqlalchemy.orm import Session
from app.core.config import settings
from app.models import (
    Approval, Deployment, DeploymentEnvironment, DeploymentRollback, PreviewEnvironment,
    Release, ReleaseArtifact, Repository, RepositoryMergeRequest,
)
from app.services.company_event_bus import emit_event


class ReleaseError(RuntimeError):
    pass


def _deploy_root() -> Path:
    root = Path(settings.deployment_workspace_root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _safe_slug(value: str) -> str:
    value = "".join(ch if ch.isalnum() or ch in "-_." else "-" for ch in (value or "env"))
    return value.strip("-.")[:120] or "env"


def release_commit(db: Session, release: Release) -> str:
    if release.commit_sha:
        return release.commit_sha
    if release.merge_request_id:
        mr = db.get(RepositoryMergeRequest, release.merge_request_id)
        if mr and mr.status == "merged" and mr.merge_commit_sha:
            release.commit_sha = mr.merge_commit_sha
            db.add(release); db.commit(); db.refresh(release)
            return release.commit_sha
    raise ReleaseError("Release has no immutable commit SHA")


def ensure_release_approval(db: Session, release: Release, env: DeploymentEnvironment, requester_member_id: int | None) -> Approval | None:
    if not env.require_approval:
        return None
    approval = db.get(Approval, release.approval_id) if release.approval_id else None
    if not approval:
        repo = db.get(Repository, release.repository_id)
        approval = Approval(
            organization_id=release.organization_id,
            company_id=repo.company_id if repo else None,
            requester_member_id=requester_member_id or release.created_by_member_id,
            action=f"deploy.release:{release.id}:environment:{env.slug}",
            risk=env.approval_risk or "high",
            policy_key="release.deploy",
            status="pending",
            evidence=json.dumps({"release_id": release.id, "environment_id": env.id, "commit_sha": release.commit_sha}),
        )
        db.add(approval); db.commit(); db.refresh(approval)
        release.approval_id = approval.id
        release.status = "waiting_approval"
        db.add(release); db.commit(); db.refresh(release)
    return approval


def deployment_gate(db: Session, release: Release, env: DeploymentEnvironment, requester_member_id: int | None = None) -> dict:
    commit = release_commit(db, release)
    approval = ensure_release_approval(db, release, env, requester_member_id)
    allowed = approval is None or approval.status == "approved"
    return {
        "allowed": allowed,
        "commit_sha": commit,
        "approval_required": bool(env.require_approval),
        "approval_id": approval.id if approval else None,
        "approval_status": approval.status if approval else "not_required",
        "environment_type": env.environment_type,
    }


def _archive_commit(repo_path: Path, commit_sha: str, destination: Path):
    proc = subprocess.run(["git", "archive", "--format=tar", commit_sha], cwd=repo_path, capture_output=True)
    if proc.returncode != 0:
        raise ReleaseError((proc.stderr.decode("utf-8", "replace") or "git archive failed")[-8000:])
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(proc.stdout), mode="r:") as tf:
        dest = destination.resolve()
        for member in tf.getmembers():
            target = (dest / member.name).resolve()
            if target != dest and dest not in target.parents:
                raise ReleaseError("Archive contains a path traversal entry")
            if member.issym() or member.islnk():
                # Fail closed for local filesystem deploys. Providers may support links explicitly.
                raise ReleaseError("Archive contains links; filesystem deploy refuses them")
        tf.extractall(dest)


def deploy_release(db: Session, release: Release, env: DeploymentEnvironment, requested_by_member_id: int | None = None) -> Deployment:
    if release.organization_id != env.organization_id or release.repository_id != env.repository_id:
        raise ReleaseError("Release and deployment environment do not match")
    gate = deployment_gate(db, release, env, requested_by_member_id)
    if not gate["allowed"]:
        raise ReleaseError(f"Deployment approval required: {gate['approval_id']}")
    repo = db.get(Repository, release.repository_id)
    if not repo or not repo.local_path:
        raise ReleaseError("Repository checkout is unavailable")
    if env.provider != "filesystem":
        raise ReleaseError(f"Deployment provider '{env.provider}' needs a provider adapter")
    previous = db.query(Deployment).filter(
        Deployment.environment_id == env.id, Deployment.status == "deployed"
    ).order_by(Deployment.id.desc()).first()
    deployment = Deployment(
        organization_id=release.organization_id, environment_id=env.id, release_id=release.id,
        requested_by_member_id=requested_by_member_id, status="deploying",
        previous_deployment_id=previous.id if previous else None, started_at=datetime.utcnow(),
    )
    db.add(deployment); db.commit(); db.refresh(deployment)
    root = _deploy_root() / str(release.organization_id) / _safe_slug(env.slug)
    version_dir = (root / "releases" / f"{release.id}-{_safe_slug(release.version)}").resolve()
    root_resolved = root.resolve()
    if root_resolved not in version_dir.parents:
        raise ReleaseError("Deployment path escapes configured root")
    try:
        if version_dir.exists():
            shutil.rmtree(version_dir)
        _archive_commit(Path(repo.local_path).resolve(), gate["commit_sha"], version_dir)
        current = root / "current"
        root.mkdir(parents=True, exist_ok=True)
        tmp_link = root / f".current-{deployment.id}.tmp"
        if tmp_link.exists() or tmp_link.is_symlink():
            tmp_link.unlink()
        tmp_link.symlink_to(version_dir, target_is_directory=True)
        os.replace(tmp_link, current)
        deployment.status = "deployed"; deployment.deployed_path = str(version_dir)
        deployment.provider_ref = str(current); deployment.completed_at = datetime.utcnow()
        release.status = "released"; release.released_at = release.released_at or datetime.utcnow()
        db.add_all([deployment, release]); db.commit(); db.refresh(deployment)
        emit_event(db, organization_id=release.organization_id, event_type="release.deployed", source="dev_cloud",
                   aggregate_type="deployment", aggregate_id=str(deployment.id), actor_member_id=requested_by_member_id,
                   payload={"deployment_id": deployment.id, "release_id": release.id, "environment_id": env.id,
                            "commit_sha": gate["commit_sha"], "path": str(version_dir)})
        return deployment
    except Exception as exc:
        deployment.status = "failed"; deployment.error = str(exc); deployment.completed_at = datetime.utcnow()
        db.add(deployment); db.commit(); db.refresh(deployment)
        if isinstance(exc, ReleaseError):
            raise
        raise ReleaseError(str(exc)) from exc


def create_preview(db: Session, release: Release, env: DeploymentEnvironment, ttl_minutes: int = 1440,
                   requested_by_member_id: int | None = None) -> PreviewEnvironment:
    from datetime import timedelta
    if env.environment_type != "preview":
        raise ReleaseError("Preview can only be created in a preview environment")
    deployment = deploy_release(db, release, env, requested_by_member_id=requested_by_member_id)
    url = f"{env.base_url.rstrip('/')}/{release.id}" if env.base_url else f"file://{deployment.deployed_path}"
    item = PreviewEnvironment(
        organization_id=release.organization_id, environment_id=env.id, release_id=release.id,
        delivery_run_id=release.delivery_run_id, name=f"{env.slug}-r{release.id}", status="ready",
        url=url, provider_ref=deployment.provider_ref, expires_at=datetime.utcnow() + timedelta(minutes=ttl_minutes),
    )
    db.add(item); db.commit(); db.refresh(item)
    return item


def rollback_environment(db: Session, deployment: Deployment, requested_by_member_id: int | None = None, reason: str = "") -> DeploymentRollback:
    if deployment.status != "deployed" or not deployment.previous_deployment_id:
        raise ReleaseError("Deployment has no previous successful deployment")
    previous = db.get(Deployment, deployment.previous_deployment_id)
    env = db.get(DeploymentEnvironment, deployment.environment_id)
    if not previous or previous.status != "deployed" or not env:
        raise ReleaseError("Previous deployment is unavailable")
    if env.provider != "filesystem":
        raise ReleaseError("Rollback provider adapter is unavailable")
    target = Path(previous.deployed_path).resolve()
    if not target.exists():
        raise ReleaseError("Previous deployment files no longer exist")
    root = _deploy_root() / str(deployment.organization_id) / _safe_slug(env.slug)
    current = root / "current"; tmp = root / f".rollback-{deployment.id}.tmp"
    if tmp.exists() or tmp.is_symlink():
        tmp.unlink()
    tmp.symlink_to(target, target_is_directory=True); os.replace(tmp, current)
    item = DeploymentRollback(
        organization_id=deployment.organization_id, environment_id=env.id,
        from_deployment_id=deployment.id, to_deployment_id=previous.id,
        requested_by_member_id=requested_by_member_id, status="completed", reason=reason,
        completed_at=datetime.utcnow(),
    )
    db.add(item); db.commit(); db.refresh(item)
    emit_event(db, organization_id=deployment.organization_id, event_type="deployment.rolled_back", source="dev_cloud",
               aggregate_type="deployment_rollback", aggregate_id=str(item.id), actor_member_id=requested_by_member_id,
               payload={"rollback_id": item.id, "from_deployment_id": deployment.id, "to_deployment_id": previous.id})
    return item
