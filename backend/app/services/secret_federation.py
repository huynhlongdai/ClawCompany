import json
import os
import re
import shutil
import subprocess
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlparse
import httpx
from sqlalchemy.orm import Session
from app.core.config import settings
from app.models import SecretReference, SecretProviderConnection, SecretAccessLease, RunnerLease


class SecretFederationError(RuntimeError): pass
_SAFE_NAME = re.compile(r"^[A-Za-z0-9._-]{1,180}$")

def utcnow(): return datetime.now(timezone.utc).replace(tzinfo=None)

def _env_ref(ref: str) -> str:
    if not ref.startswith("env:"): raise SecretFederationError("Secret auth reference must use env:NAME")
    value = os.environ.get(ref.split(":", 1)[1], "")
    if not value: raise SecretFederationError(f"Secret auth reference is unavailable: {ref}")
    return value

def _allowed_host(url: str) -> bool:
    p = urlparse(url)
    if p.scheme not in {"http", "https"} or not p.hostname: return False
    allowed = {x.strip().lower() for x in settings.secret_provider_allowed_hosts.split(",") if x.strip()}
    return p.hostname.lower() in allowed

def resolve_secret(db: Session, ref: SecretReference, connection: SecretProviderConnection | None = None) -> str:
    if not ref.is_active: raise SecretFederationError("Secret reference is inactive")
    provider = connection.provider if connection else ref.provider
    if connection and (not connection.enabled or connection.organization_id != ref.organization_id):
        raise SecretFederationError("Secret provider connection is unavailable")
    external_ref = ref.external_ref
    if provider == "env":
        name = external_ref.split(":", 1)[1] if external_ref.startswith("env:") else external_ref
        value = os.environ.get(name, "")
        if not value: raise SecretFederationError(f"Environment secret is unavailable: {name}")
        return value
    if provider == "vault_http":
        if not connection or not _allowed_host(connection.endpoint): raise SecretFederationError("Vault endpoint is not allowlisted")
        token = _env_ref(connection.auth_ref)
        path = external_ref.split(":", 1)[1] if external_ref.startswith("vault:") else external_ref
        url = connection.endpoint.rstrip("/") + "/v1/" + path.lstrip("/")
        with httpx.Client(timeout=settings.secret_provider_timeout_seconds) as client:
            r = client.get(url, headers={"X-Vault-Token": token});
        if r.status_code >= 300: raise SecretFederationError(f"Vault returned HTTP {r.status_code}")
        body = r.json(); cfg = json.loads(connection.config_json or "{}")
        key = cfg.get("value_key", "value")
        data = body.get("data", {}); data = data.get("data", data)
        value = data.get(key)
        if value is None: raise SecretFederationError(f"Vault response has no configured key '{key}'")
        return str(value)
    if provider in {"aws_sm_cli", "gcp_sm_cli", "azure_kv_cli"}:
        return _resolve_cli(provider, external_ref, connection)
    raise SecretFederationError(f"Unsupported secret provider: {provider}")

def _resolve_cli(provider: str, external_ref: str, connection: SecretProviderConnection | None) -> str:
    if provider == "aws_sm_cli":
        exe = shutil.which("aws"); args = [exe or "aws", "secretsmanager", "get-secret-value", "--secret-id", external_ref, "--query", "SecretString", "--output", "text"]
    elif provider == "gcp_sm_cli":
        exe = shutil.which("gcloud"); args = [exe or "gcloud", "secrets", "versions", "access", "latest", "--secret", external_ref]
    else:
        exe = shutil.which("az");
        cfg = json.loads(connection.config_json or "{}") if connection else {}; vault = cfg.get("vault_name", "")
        if not vault: raise SecretFederationError("azure_kv_cli requires config.vault_name")
        args = [exe or "az", "keyvault", "secret", "show", "--vault-name", vault, "--name", external_ref, "--query", "value", "-o", "tsv"]
    if not exe: raise SecretFederationError(f"Provider executable is unavailable: {args[0]}")
    env = {"PATH": os.getenv("PATH", ""), "HOME": os.getenv("HOME", "/tmp")}
    p = subprocess.run(args, capture_output=True, text=True, timeout=settings.secret_provider_timeout_seconds, shell=False, env=env)
    if p.returncode != 0: raise SecretFederationError((p.stderr or p.stdout or "secret CLI failed")[:2000])
    value = p.stdout.rstrip("\r\n")
    if not value: raise SecretFederationError("Secret provider returned an empty value")
    return value

def issue_secret_lease(db: Session, *, organization_id: int, secret_reference_id: int, provider_connection_id: int | None = None,
                       runner_lease_id: int | None = None, member_id: int | None = None, agent_id: int | None = None,
                       mount_name: str = "", ttl_seconds: int = 300) -> SecretAccessLease:
    ref = db.get(SecretReference, secret_reference_id)
    if not ref or ref.organization_id != organization_id or not ref.is_active: raise SecretFederationError("Secret reference is unavailable")
    conn = db.get(SecretProviderConnection, provider_connection_id) if provider_connection_id else None
    if conn and (conn.organization_id != organization_id or not conn.enabled): raise SecretFederationError("Secret provider connection is unavailable")
    now = utcnow(); ttl = max(30, min(int(ttl_seconds), 3600))
    runner = db.get(RunnerLease, runner_lease_id) if runner_lease_id else None
    if runner:
        if runner.organization_id != organization_id or runner.status != "active" or runner.expires_at <= now: raise SecretFederationError("Runner lease is unavailable")
        ttl = min(ttl, max(1, int((runner.expires_at - now).total_seconds())))
    if mount_name and not _SAFE_NAME.match(mount_name): raise SecretFederationError("Unsafe secret mount name")
    item = SecretAccessLease(organization_id=organization_id, secret_reference_id=ref.id,
                             provider_connection_id=conn.id if conn else None, runner_lease_id=runner.id if runner else None,
                             member_id=member_id, agent_id=agent_id, mount_name=mount_name, status="active",
                             expires_at=now + timedelta(seconds=ttl))
    db.add(item); db.commit(); db.refresh(item); return item

def revoke_secret_lease(db: Session, lease: SecretAccessLease) -> SecretAccessLease:
    if lease.status == "active": lease.status = "revoked"; lease.revoked_at = utcnow(); db.add(lease); db.commit(); db.refresh(lease)
    return lease

@contextmanager
def mounted_leased_secret(db: Session, lease: SecretAccessLease):
    now = utcnow()
    if lease.status != "active" or lease.expires_at <= now: raise SecretFederationError("Secret access lease is expired/revoked")
    if lease.runner_lease_id:
        runner = db.get(RunnerLease, lease.runner_lease_id)
        if not runner or runner.status != "active" or runner.expires_at <= now: raise SecretFederationError("Bound runner lease is no longer active")
    ref = db.get(SecretReference, lease.secret_reference_id); conn = db.get(SecretProviderConnection, lease.provider_connection_id) if lease.provider_connection_id else None
    if not ref: raise SecretFederationError("Secret reference is unavailable")
    value = resolve_secret(db, ref, conn)
    with TemporaryDirectory(prefix="cc-federated-secret-") as td:
        root = Path(td); name = lease.mount_name or ref.name
        if not _SAFE_NAME.match(name): raise SecretFederationError("Unsafe secret mount name")
        path = root / name; path.write_text(value, encoding="utf-8"); path.chmod(0o600)
        try: yield root
        finally: value = ""  # best-effort local reference release; file is deleted by TemporaryDirectory
