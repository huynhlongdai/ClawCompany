import re
import shutil
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from sqlalchemy.orm import Session
from app.core.config import settings
from app.models import DevWorkspace, Repository


class WorkspaceError(RuntimeError):
    pass


def _safe_key(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9._-]+", "-", (value or "workspace").strip()).strip("-.")
    return (value or "workspace")[:160]


def workspace_root() -> Path:
    root = Path(settings.dev_workspace_root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def workspace_path(organization_id: int, workspace_key: str) -> Path:
    root = workspace_root()
    path = (root / str(organization_id) / _safe_key(workspace_key)).resolve()
    if root not in path.parents:
        raise WorkspaceError("Workspace escapes configured root")
    return path


def provision_workspace(db: Session, item: DevWorkspace, ttl_minutes: int | None = None) -> DevWorkspace:
    if item.root_path:
        existing = Path(item.root_path).resolve()
        expected_root = workspace_root()
        if expected_root not in existing.parents:
            raise WorkspaceError("Existing workspace path is outside configured root")
        if existing.exists():
            return item
    path = workspace_path(item.organization_id, item.workspace_key)
    if path.exists() and any(path.iterdir()):
        raise WorkspaceError("Workspace path already exists and is not empty")
    path.parent.mkdir(parents=True, exist_ok=True)
    repo = db.get(Repository, item.repository_id) if item.repository_id else None
    if repo and repo.local_path:
        repo_path = Path(repo.local_path).expanduser().resolve()
        if not (repo_path / ".git").exists():
            raise WorkspaceError("Repository checkout is not initialized")
        ref = item.base_ref or repo.default_branch or "main"
        proc = subprocess.run(["git", "worktree", "add", "--detach", str(path), ref], cwd=repo_path, text=True, capture_output=True)
        if proc.returncode != 0:
            raise WorkspaceError((proc.stderr or proc.stdout or "git worktree failed")[-8000:])
    else:
        path.mkdir(parents=True, exist_ok=True)
        (path / ".clawcompany-workspace").write_text("managed=true\n", encoding="utf-8")
    item.root_path = str(path)
    item.status = "ready"
    if ttl_minutes:
        item.expires_at = datetime.utcnow() + timedelta(minutes=ttl_minutes)
    db.add(item); db.commit(); db.refresh(item)
    return item


def destroy_workspace(db: Session, item: DevWorkspace) -> DevWorkspace:
    path = Path(item.root_path).resolve() if item.root_path else None
    repo = db.get(Repository, item.repository_id) if item.repository_id else None
    if path and path.exists():
        if repo and repo.local_path:
            repo_path = Path(repo.local_path).expanduser().resolve()
            subprocess.run(["git", "worktree", "remove", "--force", str(path)], cwd=repo_path, text=True, capture_output=True)
        elif workspace_root() in path.parents:
            shutil.rmtree(path)
    item.status = "destroyed"; item.root_path = ""
    db.add(item); db.commit(); db.refresh(item)
    return item
