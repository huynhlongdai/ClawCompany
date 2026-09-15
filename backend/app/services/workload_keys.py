from datetime import datetime, timezone
from pathlib import Path
import os
from sqlalchemy.orm import Session
from app.models import WorkloadSigningKey


class WorkloadKeyError(RuntimeError):
    pass


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _private_bytes(ref: str) -> bytes:
    if ref.startswith("env:"):
        value = os.environ.get(ref.split(":", 1)[1], "")
        if not value: raise WorkloadKeyError(f"Private key reference unavailable: {ref}")
        return value.encode()
    if ref.startswith("file:"):
        path = Path(ref.split(":", 1)[1]).expanduser().resolve()
        if not path.exists(): raise WorkloadKeyError(f"Private key file unavailable: {path}")
        return path.read_bytes()
    raise WorkloadKeyError("Private key reference must use env: or file:")


def validate_signing_key(algorithm: str, public_key_pem: str, private_key_ref: str):
    alg = algorithm.upper()
    if alg == "HS256":
        if not private_key_ref.startswith("env:"):
            raise WorkloadKeyError("HS256 database-managed keys require env: secret reference")
        _private_bytes(private_key_ref); return
    if alg != "RS256": raise WorkloadKeyError("Only RS256 or HS256 are supported")
    if not public_key_pem: raise WorkloadKeyError("RS256 public key PEM is required")
    try:
        from cryptography.hazmat.primitives import serialization
        pub = serialization.load_pem_public_key(public_key_pem.encode())
        prv = serialization.load_pem_private_key(_private_bytes(private_key_ref), password=None)
        if pub.public_numbers() != prv.public_key().public_numbers():
            raise WorkloadKeyError("Public key does not match private key reference")
    except WorkloadKeyError: raise
    except Exception as exc: raise WorkloadKeyError("Invalid workload signing key") from exc


def create_signing_key(db: Session, *, organization_id: int, kid: str, algorithm: str, public_key_pem: str,
                       private_key_ref: str, not_before=None, not_after=None, activate: bool = True) -> WorkloadSigningKey:
    validate_signing_key(algorithm, public_key_pem, private_key_ref)
    if db.query(WorkloadSigningKey).filter_by(organization_id=organization_id, kid=kid).first():
        raise WorkloadKeyError("Signing key id already exists in organization")
    if activate:
        for old in db.query(WorkloadSigningKey).filter_by(organization_id=organization_id, status="active").all():
            old.status = "retiring"; old.retired_at = utcnow(); db.add(old)
    item = WorkloadSigningKey(organization_id=organization_id, kid=kid, algorithm=algorithm.upper(),
                              public_key_pem=public_key_pem, private_key_ref=private_key_ref,
                              status="active" if activate else "retiring", not_before=not_before or utcnow(), not_after=not_after)
    db.add(item); db.commit(); db.refresh(item); return item


def set_key_status(db: Session, key: WorkloadSigningKey, status: str) -> WorkloadSigningKey:
    if status not in {"active", "retiring", "revoked"}: raise WorkloadKeyError("Invalid signing key status")
    if status == "active":
        for old in db.query(WorkloadSigningKey).filter(WorkloadSigningKey.organization_id == key.organization_id,
                                                        WorkloadSigningKey.id != key.id,
                                                        WorkloadSigningKey.status == "active").all():
            old.status = "retiring"; old.retired_at = utcnow(); db.add(old)
    key.status = status
    if status in {"retiring", "revoked"}: key.retired_at = utcnow()
    db.add(key); db.commit(); db.refresh(key); return key
