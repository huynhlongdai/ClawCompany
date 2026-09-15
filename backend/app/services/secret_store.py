import os
import re
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from contextlib import contextmanager
from sqlalchemy.orm import Session
from app.models import SecretGrant, SecretReference

_SAFE_NAME = re.compile(r"^[A-Za-z0-9._-]{1,180}$")


class SecretAccessError(RuntimeError):
    pass


def grant_is_active(grant: SecretGrant, now: datetime | None = None) -> bool:
    now = now or datetime.utcnow()
    return bool(grant.is_active and (grant.expires_at is None or grant.expires_at > now))


def _resolve_value(ref: SecretReference) -> str:
    if not ref.is_active:
        raise SecretAccessError("Secret reference is inactive")
    if ref.provider != "env":
        raise SecretAccessError(f"Secret provider '{ref.provider}' needs an external provider adapter")
    key = ref.external_ref[4:] if ref.external_ref.startswith("env:") else ref.external_ref
    if not key or key not in os.environ:
        raise SecretAccessError(f"Environment secret is unavailable: {key}")
    return os.environ[key]


def secret_metadata(ref: SecretReference) -> dict:
    return {
        "id": ref.id,
        "name": ref.name,
        "provider": ref.provider,
        "external_ref": ref.external_ref,
        "classification": ref.classification,
        "is_active": ref.is_active,
        "value": "***redacted***",
    }


def validate_grants(db: Session, organization_id: int, grant_ids: list[int], *, member_id: int | None = None,
                    agent_id: int | None = None, sandbox_profile_id: int | None = None,
                    environment_id: int | None = None) -> list[tuple[SecretGrant, SecretReference]]:
    out: list[tuple[SecretGrant, SecretReference]] = []
    for grant_id in grant_ids:
        grant = db.get(SecretGrant, grant_id)
        if not grant or grant.organization_id != organization_id or not grant_is_active(grant):
            raise SecretAccessError(f"Secret grant is unavailable: {grant_id}")
        if grant.member_id is not None and grant.member_id != member_id:
            raise SecretAccessError(f"Secret grant {grant_id} is bound to another member")
        if grant.agent_id is not None and grant.agent_id != agent_id:
            raise SecretAccessError(f"Secret grant {grant_id} is bound to another agent")
        if grant.sandbox_profile_id is not None and grant.sandbox_profile_id != sandbox_profile_id:
            raise SecretAccessError(f"Secret grant {grant_id} is not valid for this sandbox profile")
        if grant.environment_id is not None and grant.environment_id != environment_id:
            raise SecretAccessError(f"Secret grant {grant_id} is not valid for this environment")
        ref = db.get(SecretReference, grant.secret_reference_id)
        if not ref or ref.organization_id != organization_id or not ref.is_active:
            raise SecretAccessError(f"Secret reference is unavailable for grant {grant_id}")
        out.append((grant, ref))
    return out


@contextmanager
def mounted_secret_directory(pairs: list[tuple[SecretGrant, SecretReference]]):
    """Resolve values only at execution time and expose them as short-lived files.

    The caller gets a path, never a dictionary containing secret values. Files are deleted
    when the context exits. This is suitable for a local Docker adapter; remote providers
    should use native secret injection instead.
    """
    with TemporaryDirectory(prefix="clawcompany-secrets-") as tmp:
        root = Path(tmp)
        for grant, ref in pairs:
            name = grant.mount_name or ref.name
            if not _SAFE_NAME.match(name):
                raise SecretAccessError(f"Unsafe secret mount name: {name}")
            path = root / name
            path.write_text(_resolve_value(ref), encoding="utf-8")
            path.chmod(0o600)
        yield root
