import fnmatch
import json
import os
import re
import shlex
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Iterable

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import (
    Artifact, DeliveryArtifact, DeliveryPipeline, DeliveryRun, Repository, RepositoryConflict,
    RepositoryIdentityCredential, RepositoryMergeRequest, RepositoryReview, RepositoryRollback,
    RepositoryTestProfile, RepositoryTestRun,
)
from app.services.artifacts import register_artifact
from app.services.company_event_bus import emit_event

_REF_RE = re.compile(r"^[A-Za-z0-9._/-]{1,180}$")


class RepositoryDeliveryError(RuntimeError):
    pass


def _slug(value: str) -> str:
    out = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-.")
    return (out or "repository")[:120]


def validate_ref(value: str) -> str:
    if not _REF_RE.match(value) or ".." in value or value.startswith("/") or value.endswith("/") or "//" in value:
        raise RepositoryDeliveryError(f"Unsafe git ref: {value}")
    return value


def _root() -> Path:
    return Path(settings.repository_workspace_root).expanduser().resolve()


def _ensure_under(path: Path, root: Path) -> Path:
    path = path.expanduser().resolve()
    if path != root and root not in path.parents:
        raise RepositoryDeliveryError("Repository path escapes configured workspace root")
    return path


def _repo_path(repo: Repository) -> Path:
    if not repo.local_path:
        raise RepositoryDeliveryError("Repository has no local checkout")
    return _ensure_under(Path(repo.local_path), _root())


def _run(argv: list[str], *, cwd: Path, timeout: int | None = None, check: bool = True, env: dict | None = None) -> subprocess.CompletedProcess:
    proc = subprocess.run(
        argv, cwd=str(cwd), text=True, capture_output=True,
        timeout=timeout or settings.repository_git_timeout_seconds,
        env={**os.environ, **(env or {})},
    )
    if check and proc.returncode != 0:
        msg = (proc.stderr or proc.stdout or "command failed").strip()
        raise RepositoryDeliveryError(msg[-12000:])
    return proc


def git(repo_path: Path, *args: str, check: bool = True) -> str:
    return _run(["git", *args], cwd=repo_path, check=check).stdout.strip()


def initialize_repository(repo: Repository, git_env: dict | None = None) -> str:
    root = _root()
    root.mkdir(parents=True, exist_ok=True)
    path = _ensure_under(root / str(repo.organization_id) / "repos" / f"{repo.id}-{_slug(repo.name)}", root)
    if (path / ".git").exists():
        repo.local_path = str(path)
        return str(path)
    if path.exists() and any(path.iterdir()):
        raise RepositoryDeliveryError("Repository target path exists and is not empty")
    path.mkdir(parents=True, exist_ok=True)
    branch = validate_ref(repo.default_branch or "main")
    if repo.remote_url and repo.provider in {"github", "generic_git"}:
        path.rmdir()
        parent = path.parent
        _run(["git", "clone", "--branch", branch, "--single-branch", repo.remote_url, str(path)], cwd=parent, env=git_env)
    else:
        proc = _run(["git", "init", "-b", branch], cwd=path, check=False)
        if proc.returncode != 0:
            _run(["git", "init"], cwd=path)
            git(path, "checkout", "-b", branch)
        (path / "README.md").write_text(f"# {repo.name}\n\nManaged by ClawCompany Repository Delivery.\n", encoding="utf-8")
        git(path, "add", "README.md")
        _run(["git", "-c", "user.name=ClawCompany", "-c", "user.email=delivery@clawcompany.local", "commit", "-m", "Initialize repository"], cwd=path)
    repo.local_path = str(path)
    return str(path)




def sync_repository_checkout(repo: Repository, git_env: dict | None = None) -> dict:
    if not repo.local_path:
        initialize_repository(repo, git_env=git_env)
    path = _repo_path(repo)
    if repo.remote_url and repo.provider in {"github", "generic_git"}:
        _run(["git", "fetch", "--prune", "origin"], cwd=path, env=git_env, timeout=180)
    return repository_state(repo)


def repository_state(repo: Repository) -> dict:
    path = _repo_path(repo)
    return {
        "path": str(path),
        "branch": git(path, "branch", "--show-current"),
        "head": git(path, "rev-parse", "HEAD"),
        "status": git(path, "status", "--porcelain"),
    }


def credential_allows(credential: RepositoryIdentityCredential, permission: str, branch: str = "") -> bool:
    if credential.is_active is False:
        return False
    try:
        permissions = set(json.loads(credential.permissions_json or "[]"))
    except Exception:
        permissions = set()
    if "*" not in permissions and permission not in permissions:
        return False
    return not branch or fnmatch.fnmatch(branch, credential.branch_pattern or "*")


def _safe_relative_path(value: str) -> Path:
    normalized = (value or "").replace("\\", "/").lstrip("/")
    path = Path(normalized)
    if not normalized or path.is_absolute() or ".." in path.parts or ".git" in path.parts:
        raise RepositoryDeliveryError(f"Unsafe artifact path: {value}")
    return path


def _latest_bundle_artifacts(db: Session, organization_id: int, bundle_key: str) -> list[Artifact]:
    items = db.query(Artifact).filter(
        Artifact.organization_id == organization_id,
        Artifact.bundle_key == bundle_key,
        Artifact.status.in_(["ready", "approved", "accepted"]),
    ).order_by(Artifact.logical_path.asc(), Artifact.version.desc(), Artifact.id.desc()).all()
    latest: dict[str, Artifact] = {}
    for item in items:
        key = item.logical_path or item.name
        latest.setdefault(key, item)
    return list(latest.values())


def _worktree_path(run: DeliveryRun) -> Path:
    root = _root()
    return _ensure_under(root / str(run.organization_id) / "worktrees" / f"delivery-{run.id}", root)


def prepare_delivery(db: Session, run: DeliveryRun) -> DeliveryRun:
    repo = db.get(Repository, run.repository_id)
    if not repo or repo.organization_id != run.organization_id:
        raise RepositoryDeliveryError("Repository not found")
    if not repo.local_path:
        initialize_repository(repo)
        db.add(repo); db.commit(); db.refresh(repo)
    repo_path = _repo_path(repo)
    target = validate_ref(run.target_branch or repo.default_branch)
    source = validate_ref(run.source_branch or f"cc/delivery-{run.id}")
    run.target_branch, run.source_branch = target, source
    run.status = "preparing"; run.started_at = run.started_at or datetime.utcnow(); run.error = ""
    db.add(run); db.commit(); db.refresh(run)

    if _run(["git", "show-ref", "--verify", "--quiet", f"refs/heads/{target}"], cwd=repo_path, check=False).returncode != 0:
        raise RepositoryDeliveryError(f"Target branch does not exist: {target}")
    if _run(["git", "show-ref", "--verify", "--quiet", f"refs/heads/{source}"], cwd=repo_path, check=False).returncode == 0:
        raise RepositoryDeliveryError(f"Source branch already exists: {source}")

    run.base_commit_sha = git(repo_path, "rev-parse", target)
    wt = _worktree_path(run)
    if wt.exists():
        shutil.rmtree(wt)
    wt.parent.mkdir(parents=True, exist_ok=True)
    git(repo_path, "worktree", "add", "-b", source, str(wt), target)
    run.worktree_path = str(wt)

    artifacts = _latest_bundle_artifacts(db, run.organization_id, run.artifact_bundle_key)
    if not artifacts:
        raise RepositoryDeliveryError("No ready artifacts found for bundle")
    for artifact in artifacts:
        if not artifact.content_text:
            raise RepositoryDeliveryError(f"Artifact {artifact.id} is not inline and cannot be materialized by the local delivery runner")
        rel = _safe_relative_path(artifact.logical_path or artifact.name)
        target_path = (wt / rel).resolve()
        if wt not in target_path.parents:
            raise RepositoryDeliveryError("Artifact path escapes worktree")
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(artifact.content_text, encoding="utf-8")
        db.add(DeliveryArtifact(
            organization_id=run.organization_id, delivery_run_id=run.id, artifact_id=artifact.id,
            logical_path=str(rel), status="materialized",
        ))

    git(wt, "add", "-A")
    changed = _run(["git", "diff", "--cached", "--quiet"], cwd=wt, check=False).returncode != 0
    if not changed:
        run.status = "no_changes"; run.completed_at = datetime.utcnow(); db.add(run); db.commit(); db.refresh(run)
        return run
    commit_title = f"ClawCompany delivery #{run.id}: {run.artifact_bundle_key}"
    _run(["git", "-c", "user.name=ClawCompany Commit Agent", "-c", "user.email=commit-agent@clawcompany.local", "commit", "-m", commit_title], cwd=wt)
    run.head_commit_sha = git(wt, "rev-parse", "HEAD")
    patch = git(wt, "show", "--format=fuller", "--binary", "HEAD")
    patch_artifact = register_artifact(
        db, organization_id=run.organization_id, company_id=repo.company_id, project_id=run.project_id,
        task_id=run.task_id, created_by_member_id=run.initiated_by_member_id,
        created_by_agent_id=run.initiated_by_agent_id, bundle_key=f"delivery:{run.id}:patch",
        logical_path=f"delivery-{run.id}.patch", name=f"Delivery {run.id} patch",
        artifact_type="git_patch", mime_type="text/x-diff", content_text=patch,
        metadata={"repository_id": repo.id, "delivery_run_id": run.id, "base": run.base_commit_sha, "head": run.head_commit_sha},
    )
    run.patch_artifact_id = patch_artifact.id
    run.status = "prepared"
    db.add(run); db.commit(); db.refresh(run)
    emit_event(db, organization_id=run.organization_id, company_id=repo.company_id,
               event_type="repository.delivery.prepared", source="repository_delivery",
               aggregate_type="delivery_run", aggregate_id=str(run.id),
               actor_member_id=run.initiated_by_member_id,
               payload={"repository_id": repo.id, "delivery_run_id": run.id, "source_branch": source,
                        "target_branch": target, "head_commit": run.head_commit_sha})
    return run


def _allowed_command(command: str) -> list[str]:
    argv = shlex.split(command)
    if not argv:
        raise RepositoryDeliveryError("Empty test command")
    allowed = {x.strip() for x in settings.repository_test_allowed_executables.split(",") if x.strip()}
    exe = Path(argv[0]).name
    if exe not in allowed:
        raise RepositoryDeliveryError(f"Executable not allowed by repository test policy: {exe}")
    return argv


def run_tests(db: Session, run: DeliveryRun, profile: RepositoryTestProfile) -> RepositoryTestRun:
    if not run.worktree_path:
        raise RepositoryDeliveryError("Delivery has no worktree")
    wt = _ensure_under(Path(run.worktree_path), _root())
    item = RepositoryTestRun(
        organization_id=run.organization_id, delivery_run_id=run.id, profile_id=profile.id,
        status="running", started_at=datetime.utcnow(),
    )
    db.add(item); db.commit(); db.refresh(item)
    try:
        commands = json.loads(profile.commands_json or "[]")
    except Exception as exc:
        commands = []
    results = []
    logs = []
    passed = True
    for raw in commands:
        argv = _allowed_command(str(raw))
        started = datetime.utcnow()
        proc = _run(argv, cwd=wt, timeout=profile.timeout_seconds, check=False, env={"CI": "1"})
        elapsed = (datetime.utcnow() - started).total_seconds()
        output = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        logs.append(f"$ {raw}\n{output}".strip())
        results.append({"command": raw, "exit_code": proc.returncode, "seconds": round(elapsed, 3)})
        if proc.returncode != 0:
            passed = False
            break
    item.status = "passed" if passed else "failed"
    item.summary_json = json.dumps({"commands": results, "passed": passed}, ensure_ascii=False)
    item.log_text = "\n\n".join(logs)[-300000:]
    item.completed_at = datetime.utcnow()
    run.status = "tests_passed" if passed else "tests_failed"
    db.add_all([item, run]); db.commit(); db.refresh(item)
    repo = db.get(Repository, run.repository_id)
    emit_event(db, organization_id=run.organization_id, company_id=repo.company_id if repo else None,
               event_type=f"repository.tests.{item.status}", source="repository_delivery",
               aggregate_type="repository_test_run", aggregate_id=str(item.id),
               payload={"delivery_run_id": run.id, "test_run_id": item.id})
    return item


def create_review(db: Session, run: DeliveryRun, reviewer_member_id: int | None, reviewer_agent_id: int | None) -> RepositoryReview:
    if reviewer_member_id is None and reviewer_agent_id is None:
        raise RepositoryDeliveryError("Reviewer member or agent is required")
    item = RepositoryReview(
        organization_id=run.organization_id, delivery_run_id=run.id,
        reviewer_member_id=reviewer_member_id, reviewer_agent_id=reviewer_agent_id,
        status="pending", verdict="pending",
    )
    db.add(item); db.commit(); db.refresh(item)
    return item


def decide_review(db: Session, review: RepositoryReview, *, verdict: str, score: float, summary: str, findings: list[dict]) -> RepositoryReview:
    review.verdict = verdict; review.score = score; review.summary = summary
    review.findings_json = json.dumps(findings, ensure_ascii=False)
    review.status = "completed"; review.resolved_at = datetime.utcnow()
    db.add(review); db.commit(); db.refresh(review)
    return review


def delivery_gate(db: Session, run: DeliveryRun) -> dict:
    pipeline = db.get(DeliveryPipeline, run.pipeline_id) if run.pipeline_id else None
    require_tests = pipeline.require_tests if pipeline else True
    require_review = pipeline.require_review if pipeline else True
    required_approvals = pipeline.required_approvals if pipeline else 1
    latest_test = db.query(RepositoryTestRun).filter(RepositoryTestRun.delivery_run_id == run.id).order_by(RepositoryTestRun.id.desc()).first()
    approvals = db.query(RepositoryReview).filter(
        RepositoryReview.delivery_run_id == run.id,
        RepositoryReview.status == "completed",
        RepositoryReview.verdict == "approve",
    ).count()
    blocking_reviews = db.query(RepositoryReview).filter(
        RepositoryReview.delivery_run_id == run.id,
        RepositoryReview.status == "completed",
        RepositoryReview.verdict.in_(["changes_requested", "reject"]),
    ).count()
    checks = {
        "prepared": bool(run.head_commit_sha),
        "tests": (not require_tests) or bool(latest_test and latest_test.status == "passed"),
        "reviews": (not require_review) or (approvals >= required_approvals and blocking_reviews == 0),
    }
    return {"allowed": all(checks.values()), "checks": checks, "approvals": approvals,
            "required_approvals": required_approvals, "latest_test_status": latest_test.status if latest_test else None}


def create_merge_request(db: Session, run: DeliveryRun, title: str = "", provider_credential=None) -> RepositoryMergeRequest:
    existing = db.query(RepositoryMergeRequest).filter(RepositoryMergeRequest.delivery_run_id == run.id).first()
    if existing:
        return existing
    repo = db.get(Repository, run.repository_id)
    if not repo:
        raise RepositoryDeliveryError("Repository not found")
    mr_title = title or f"Delivery #{run.id}: {run.artifact_bundle_key}"
    external_id = ""
    url = f"local://repository/{repo.id}/merge-requests/delivery-{run.id}" if repo.provider == "local" else ""
    status = "open"
    if repo.provider == "github":
        if provider_credential is None:
            raise RepositoryDeliveryError("GitHub delivery requires an identity-bound repository credential")
        from app.services.repository_providers import push_github_branch, create_github_pull_request
        wt = _ensure_under(Path(run.worktree_path), _root())
        push_github_branch(repo, wt, run.source_branch, provider_credential)
        remote = create_github_pull_request(
            repo, source_branch=run.source_branch, target_branch=run.target_branch, title=mr_title,
            credential=provider_credential, body=f"Created by ClawCompany delivery run #{run.id}."
        )
        external_id, url, status = remote.external_id, remote.url, remote.status
    elif repo.provider not in {"local", "generic_git"}:
        raise RepositoryDeliveryError(f"Unsupported repository provider: {repo.provider}")
    item = RepositoryMergeRequest(
        organization_id=run.organization_id, repository_id=repo.id, delivery_run_id=run.id,
        provider=repo.provider, external_id=external_id, title=mr_title,
        source_branch=run.source_branch, target_branch=run.target_branch, status=status, url=url,
    )
    db.add(item); db.commit(); db.refresh(item)
    run.merge_request_id = item.id; run.status = "reviewing"; db.add(run); db.commit(); db.refresh(run)
    return item


def _record_conflicts(db: Session, run: DeliveryRun, repo_path: Path) -> list[RepositoryConflict]:
    names = git(repo_path, "diff", "--name-only", "--diff-filter=U", check=False).splitlines()
    out = []
    for name in names:
        item = RepositoryConflict(organization_id=run.organization_id, delivery_run_id=run.id, path=name, status="open")
        db.add(item); out.append(item)
    db.commit()
    return out


def merge_delivery(db: Session, run: DeliveryRun, provider_credential=None) -> RepositoryMergeRequest:
    gate = delivery_gate(db, run)
    if not gate["allowed"]:
        raise RepositoryDeliveryError(f"Merge gate blocked: {json.dumps(gate, ensure_ascii=False)}")
    repo = db.get(Repository, run.repository_id)
    if not repo:
        raise RepositoryDeliveryError("Repository not found")
    pipeline = db.get(DeliveryPipeline, run.pipeline_id) if run.pipeline_id else None
    strategy = pipeline.merge_strategy if pipeline else "merge"
    mr = create_merge_request(db, run, provider_credential=provider_credential)
    if repo.provider == "github":
        if provider_credential is None:
            raise RepositoryDeliveryError("GitHub merge requires an identity-bound repository credential")
        if not mr.external_id:
            raise RepositoryDeliveryError("GitHub merge request has no external pull request id")
        from app.services.repository_providers import merge_github_pull_request
        sha, _message = merge_github_pull_request(
            repo, external_id=mr.external_id, strategy=strategy, credential=provider_credential
        )
        mr.status = "merged"; mr.merge_commit_sha = sha; mr.merged_at = datetime.utcnow()
        run.status = "merged"; run.completed_at = datetime.utcnow(); run.error = ""
        db.add_all([mr, run]); db.commit(); db.refresh(mr)
        emit_event(db, organization_id=run.organization_id, company_id=repo.company_id,
                   event_type="repository.delivery.merged", source="repository_delivery",
                   aggregate_type="delivery_run", aggregate_id=str(run.id),
                   actor_member_id=run.initiated_by_member_id,
                   payload={"repository_id": repo.id, "delivery_run_id": run.id, "merge_commit": sha,
                            "target_branch": run.target_branch, "provider": "github", "pull_request": mr.external_id})
        return mr
    if repo.provider != "local":
        raise RepositoryDeliveryError("generic_git can push branches but has no merge-request adapter configured")
    repo_path = _repo_path(repo)
    try:
        git(repo_path, "checkout", run.target_branch)
        if strategy == "squash":
            git(repo_path, "merge", "--squash", run.source_branch)
            _run(["git", "-c", "user.name=ClawCompany Merge Agent", "-c", "user.email=merge-agent@clawcompany.local", "commit", "-m", mr.title], cwd=repo_path)
        elif strategy == "rebase":
            wt = _ensure_under(Path(run.worktree_path), _root())
            git(wt, "rebase", run.target_branch)
            git(repo_path, "merge", "--ff-only", run.source_branch)
        else:
            _run(["git", "-c", "user.name=ClawCompany Merge Agent", "-c", "user.email=merge-agent@clawcompany.local", "merge", "--no-ff", run.source_branch, "-m", mr.title], cwd=repo_path)
    except RepositoryDeliveryError as exc:
        _record_conflicts(db, run, repo_path)
        git(repo_path, "merge", "--abort", check=False)
        wt = Path(run.worktree_path) if run.worktree_path else None
        if wt and wt.exists(): git(wt, "rebase", "--abort", check=False)
        run.status = "conflict"; run.error = str(exc); db.add(run); db.commit()
        raise
    sha = git(repo_path, "rev-parse", "HEAD")
    mr.status = "merged"; mr.merge_commit_sha = sha; mr.merged_at = datetime.utcnow()
    run.status = "merged"; run.completed_at = datetime.utcnow(); run.error = ""
    db.add_all([mr, run]); db.commit(); db.refresh(mr)
    emit_event(db, organization_id=run.organization_id, company_id=repo.company_id,
               event_type="repository.delivery.merged", source="repository_delivery",
               aggregate_type="delivery_run", aggregate_id=str(run.id),
               actor_member_id=run.initiated_by_member_id,
               payload={"repository_id": repo.id, "delivery_run_id": run.id, "merge_commit": sha,
                        "target_branch": run.target_branch})
    return mr


def rollback_merge(db: Session, mr: RepositoryMergeRequest, *, requested_by_member_id: int | None, reason: str = "") -> RepositoryRollback:
    repo = db.get(Repository, mr.repository_id)
    if not repo or repo.provider != "local":
        raise RepositoryDeliveryError("Local repository rollback only is enabled in this snapshot")
    if not mr.merge_commit_sha:
        raise RepositoryDeliveryError("Merge request has no merge commit")
    item = RepositoryRollback(
        organization_id=mr.organization_id, repository_id=repo.id, merge_request_id=mr.id,
        requested_by_member_id=requested_by_member_id, reverted_commit_sha=mr.merge_commit_sha,
        status="running", reason=reason,
    )
    db.add(item); db.commit(); db.refresh(item)
    repo_path = _repo_path(repo)
    try:
        git(repo_path, "checkout", mr.target_branch)
        parents = git(repo_path, "rev-list", "--parents", "-n", "1", mr.merge_commit_sha).split()
        revert_args = ["git", "-c", "user.name=ClawCompany Rollback Agent", "-c", "user.email=rollback-agent@clawcompany.local", "revert"]
        if len(parents) > 2:
            revert_args += ["-m", "1"]
        revert_args += ["--no-edit", mr.merge_commit_sha]
        proc = _run(revert_args, cwd=repo_path, check=False)
        if proc.returncode != 0:
            git(repo_path, "revert", "--abort", check=False)
            raise RepositoryDeliveryError((proc.stderr or proc.stdout).strip())
        item.rollback_commit_sha = git(repo_path, "rev-parse", "HEAD")
        item.status = "completed"; item.completed_at = datetime.utcnow()
    except Exception as exc:
        item.status = "failed"; item.error = str(exc)
    db.add(item); db.commit(); db.refresh(item)
    return item


def cleanup_worktree(repo: Repository, run: DeliveryRun) -> None:
    if not run.worktree_path:
        return
    repo_path = _repo_path(repo)
    wt = _ensure_under(Path(run.worktree_path), _root())
    if wt.exists():
        git(repo_path, "worktree", "remove", "--force", str(wt), check=False)
    git(repo_path, "worktree", "prune", check=False)


def resolve_delivery_conflicts(db: Session, run: DeliveryRun, *, resolutions: dict[str, str], note: str = "") -> DeliveryRun:
    """Merge the current target into the delivery branch and resolve all conflicted paths.

    Any conflict resolution changes the delivery commit, so prior tests/reviews become stale and the
    run returns to `prepared`. The merge gate must be satisfied again before merge.
    """
    repo = db.get(Repository, run.repository_id)
    if not repo:
        raise RepositoryDeliveryError("Repository not found")
    if not run.worktree_path:
        raise RepositoryDeliveryError("Delivery has no worktree")
    wt = _ensure_under(Path(run.worktree_path), _root())
    if not wt.exists():
        raise RepositoryDeliveryError("Delivery worktree no longer exists")

    # Bring the latest target into the source branch. This either succeeds immediately or leaves
    # the worktree in a merge-conflict state for controlled resolution below.
    proc = _run(["git", "-c", "user.name=ClawCompany Conflict Resolver", "-c", "user.email=conflict-agent@clawcompany.local", "merge", run.target_branch], cwd=wt, check=False)
    unresolved = git(wt, "diff", "--name-only", "--diff-filter=U", check=False).splitlines()
    if proc.returncode == 0 and not unresolved:
        run.head_commit_sha = git(wt, "rev-parse", "HEAD")
        run.status = "prepared"; run.error = ""
        db.add(run); db.commit(); db.refresh(run)
        return run
    if not unresolved:
        git(wt, "merge", "--abort", check=False)
        raise RepositoryDeliveryError((proc.stderr or proc.stdout or "merge failed").strip())

    missing = [path for path in unresolved if path not in resolutions]
    if missing:
        git(wt, "merge", "--abort", check=False)
        raise RepositoryDeliveryError(f"Resolutions required for all conflicted paths: {missing}")

    for path in unresolved:
        rel = _safe_relative_path(path)
        target = (wt / rel).resolve()
        if wt not in target.parents:
            git(wt, "merge", "--abort", check=False)
            raise RepositoryDeliveryError("Conflict path escapes worktree")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(resolutions[path], encoding="utf-8")
        git(wt, "add", path)

    still_unresolved = git(wt, "diff", "--name-only", "--diff-filter=U", check=False).splitlines()
    if still_unresolved:
        git(wt, "merge", "--abort", check=False)
        raise RepositoryDeliveryError(f"Unresolved paths remain: {still_unresolved}")

    _run([
        "git", "-c", "user.name=ClawCompany Conflict Resolver",
        "-c", "user.email=conflict-agent@clawcompany.local", "commit",
        "-m", f"Resolve delivery #{run.id} conflicts against {run.target_branch}",
    ], cwd=wt)
    run.head_commit_sha = git(wt, "rev-parse", "HEAD")
    run.status = "prepared"; run.error = ""

    db.query(RepositoryConflict).filter(
        RepositoryConflict.delivery_run_id == run.id,
        RepositoryConflict.status == "open",
    ).update({
        RepositoryConflict.status: "resolved",
        RepositoryConflict.resolution: note or "Resolved with explicit merged file contents",
        RepositoryConflict.resolved_at: datetime.utcnow(),
    }, synchronize_session=False)

    # Invalidate prior gate evidence because the commit changed after review/test.
    db.query(RepositoryTestRun).filter(RepositoryTestRun.delivery_run_id == run.id).update(
        {RepositoryTestRun.status: "stale"}, synchronize_session=False)
    db.query(RepositoryReview).filter(RepositoryReview.delivery_run_id == run.id).update(
        {RepositoryReview.status: "stale"}, synchronize_session=False)

    patch = git(wt, "show", "--format=fuller", "--binary", "HEAD")
    patch_artifact = register_artifact(
        db, organization_id=run.organization_id, company_id=repo.company_id, project_id=run.project_id,
        task_id=run.task_id, created_by_member_id=run.initiated_by_member_id,
        created_by_agent_id=run.initiated_by_agent_id, bundle_key=f"delivery:{run.id}:patch",
        logical_path=f"delivery-{run.id}.patch", name=f"Delivery {run.id} resolved patch",
        artifact_type="git_patch", mime_type="text/x-diff", content_text=patch,
        metadata={"repository_id": repo.id, "delivery_run_id": run.id, "head": run.head_commit_sha, "conflict_resolution": True},
    )
    run.patch_artifact_id = patch_artifact.id
    db.add(run); db.commit(); db.refresh(run)
    emit_event(db, organization_id=run.organization_id, company_id=repo.company_id,
               event_type="repository.conflict.resolved", source="repository_delivery",
               aggregate_type="delivery_run", aggregate_id=str(run.id),
               actor_member_id=run.initiated_by_member_id,
               payload={"delivery_run_id": run.id, "head_commit": run.head_commit_sha, "paths": unresolved})
    return run
