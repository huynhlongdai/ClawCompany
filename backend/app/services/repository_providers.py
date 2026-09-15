import base64
import os
import re
from dataclasses import dataclass
from pathlib import Path

import httpx
from sqlalchemy.orm import Session

from app.models import Repository, RepositoryIdentityCredential
from app.services.repository_delivery import RepositoryDeliveryError, credential_allows


@dataclass
class ProviderMergeRequest:
    external_id: str
    url: str
    status: str = "open"


class RepositoryProviderError(RepositoryDeliveryError):
    pass


def resolve_secret_ref(secret_ref: str) -> str:
    if not secret_ref:
        return ""
    if not secret_ref.startswith("env:"):
        raise RepositoryProviderError("Only env: secret references are supported; tokens are never stored in the database")
    name = secret_ref[4:]
    if not name or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
        raise RepositoryProviderError("Invalid environment secret reference")
    value = os.getenv(name, "")
    if not value:
        raise RepositoryProviderError(f"Repository credential secret is unavailable: {name}")
    return value


def github_slug(remote_url: str) -> tuple[str, str]:
    patterns = [
        r"^https://github\.com/([^/]+)/([^/]+?)(?:\.git)?$",
        r"^git@github\.com:([^/]+)/([^/]+?)(?:\.git)?$",
        r"^ssh://git@github\.com/([^/]+)/([^/]+?)(?:\.git)?$",
    ]
    for pattern in patterns:
        match = re.match(pattern, remote_url.strip())
        if match:
            return match.group(1), match.group(2)
    raise RepositoryProviderError("GitHub remote_url must point to github.com/owner/repository")


def find_credential(db: Session, repo: Repository, *, permission: str, branch: str = "", member_id: int | None = None,
                    agent_id: int | None = None) -> RepositoryIdentityCredential:
    q = db.query(RepositoryIdentityCredential).filter(
        RepositoryIdentityCredential.organization_id == repo.organization_id,
        RepositoryIdentityCredential.repository_id == repo.id,
        RepositoryIdentityCredential.is_active == True,  # noqa: E712
    )
    if member_id is not None:
        q = q.filter(RepositoryIdentityCredential.member_id == member_id)
    elif agent_id is not None:
        q = q.filter(RepositoryIdentityCredential.agent_id == agent_id)
    else:
        raise RepositoryProviderError("A bound member or agent identity is required for repository credentials")
    for item in q.order_by(RepositoryIdentityCredential.id.desc()).all():
        if credential_allows(item, permission, branch):
            return item
    raise RepositoryProviderError(f"No identity credential grants repository permission: {permission}")


def git_http_auth_env(credential: RepositoryIdentityCredential) -> dict[str, str]:
    token = resolve_secret_ref(credential.secret_ref)
    if not token:
        return {}
    encoded = base64.b64encode(f"x-access-token:{token}".encode("utf-8")).decode("ascii")
    # Git reads this as transient process configuration. It keeps the token out of command arguments,
    # repository config and persisted remote URLs.
    return {
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "http.extraHeader",
        "GIT_CONFIG_VALUE_0": f"Authorization: Basic {encoded}",
        "GIT_TERMINAL_PROMPT": "0",
    }


def push_github_branch(repo: Repository, worktree: Path, source_branch: str, credential: RepositoryIdentityCredential) -> None:
    from app.services.repository_delivery import _run
    if repo.provider != "github":
        raise RepositoryProviderError("GitHub push requested for a non-GitHub repository")
    github_slug(repo.remote_url)
    env = git_http_auth_env(credential)
    _run(["git", "push", "origin", f"{source_branch}:{source_branch}"], cwd=worktree, env=env, timeout=180)


def create_github_pull_request(repo: Repository, *, source_branch: str, target_branch: str, title: str,
                               credential: RepositoryIdentityCredential, body: str = "") -> ProviderMergeRequest:
    owner, name = github_slug(repo.remote_url)
    token = resolve_secret_ref(credential.secret_ref)
    if not token:
        raise RepositoryProviderError("GitHub API token is required to create a pull request")
    response = httpx.post(
        f"https://api.github.com/repos/{owner}/{name}/pulls",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"},
        json={"title": title, "head": source_branch, "base": target_branch, "body": body},
        timeout=20,
    )
    if response.status_code not in {200, 201}:
        raise RepositoryProviderError(f"GitHub create PR failed ({response.status_code}): {response.text[:4000]}")
    data = response.json()
    return ProviderMergeRequest(external_id=str(data.get("number", "")), url=str(data.get("html_url", "")), status="open")


def merge_github_pull_request(repo: Repository, *, external_id: str, strategy: str,
                              credential: RepositoryIdentityCredential) -> tuple[str, str]:
    owner, name = github_slug(repo.remote_url)
    token = resolve_secret_ref(credential.secret_ref)
    if not token:
        raise RepositoryProviderError("GitHub API token is required to merge a pull request")
    method = {"merge": "merge", "squash": "squash", "rebase": "rebase"}.get(strategy, "merge")
    response = httpx.put(
        f"https://api.github.com/repos/{owner}/{name}/pulls/{external_id}/merge",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"},
        json={"merge_method": method},
        timeout=20,
    )
    if response.status_code not in {200, 201}:
        raise RepositoryProviderError(f"GitHub merge PR failed ({response.status_code}): {response.text[:4000]}")
    data = response.json()
    if not data.get("merged"):
        raise RepositoryProviderError(f"GitHub did not merge PR: {data.get('message','unknown error')}")
    return str(data.get("sha", "")), str(data.get("message", "merged"))
