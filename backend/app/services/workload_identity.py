import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from sqlalchemy.orm import Session
from app.core.config import settings
from app.models import RunnerLease, WorkloadIdentityToken, WorkloadSigningKey


class WorkloadIdentityError(RuntimeError):
    pass


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _encode_part(data: dict) -> str:
    return _b64(json.dumps(data, separators=(",", ":"), sort_keys=True).encode())


def _hs256_sign(signing_input: bytes, key: str) -> str:
    return _b64(hmac.new(key.encode(), signing_input, hashlib.sha256).digest())


def _read_ref(ref: str) -> bytes:
    if ref.startswith("env:"):
        value = os.environ.get(ref.split(":", 1)[1], "")
        if not value:
            raise WorkloadIdentityError(f"Signing key reference is unavailable: {ref}")
        return value.encode()
    if ref.startswith("file:"):
        path = Path(ref.split(":", 1)[1]).expanduser().resolve()
        if not path.exists():
            raise WorkloadIdentityError(f"Signing key file is unavailable: {path}")
        return path.read_bytes()
    raise WorkloadIdentityError("Signing key references must use env: or file:")


def _active_db_key(db: Session, organization_id: int) -> WorkloadSigningKey | None:
    now = utcnow()
    return db.query(WorkloadSigningKey).filter(
        WorkloadSigningKey.organization_id == organization_id,
        WorkloadSigningKey.status == "active",
        WorkloadSigningKey.not_before <= now,
    ).filter(
        (WorkloadSigningKey.not_after.is_(None)) | (WorkloadSigningKey.not_after > now)
    ).order_by(WorkloadSigningKey.id.desc()).first()


def _signing_config(db: Session, organization_id: int) -> tuple[str, str, str, str]:
    """Returns alg, kid, private_ref, public_pem. DB-managed key wins; settings remain v14 fallback."""
    key = _active_db_key(db, organization_id)
    if key:
        return key.algorithm.upper(), key.kid, key.private_key_ref, key.public_key_pem
    alg = settings.workload_identity_algorithm.upper()
    private_ref = f"file:{settings.workload_identity_private_key_path}" if settings.workload_identity_private_key_path else ""
    return alg, settings.workload_identity_key_id, private_ref, ""


def issue_workload_token(db: Session, lease: RunnerLease, *, audience: str = "clawcompany-runner", ttl_seconds: int = 300) -> dict:
    now_dt = utcnow(); now = int(time.time())
    if lease.status != "active" or lease.expires_at <= now_dt:
        raise WorkloadIdentityError("Lease is not active")
    remaining = max(1, int((lease.expires_at - now_dt).total_seconds()))
    ttl = min(max(int(ttl_seconds), 30), 900, remaining)
    jti = secrets.token_urlsafe(24)
    alg, kid, private_ref, _ = _signing_config(db, lease.organization_id)
    claims = {
        "iss": settings.workload_identity_issuer,
        "sub": f"lease:{lease.id}",
        "aud": audience,
        "iat": now,
        "nbf": now - 5,
        "exp": now + ttl,
        "jti": jti,
        "org_id": lease.organization_id,
        "lease_id": lease.id,
        "member_id": lease.member_id,
        "agent_id": lease.agent_id,
        "scope": " ".join(json.loads(lease.scopes_json or "[]")),
        "workload_type": lease.workload_type,
        "workload_ref": lease.workload_ref,
    }
    header = {"typ": "JWT", "alg": alg, "kid": kid}
    encoded = f"{_encode_part(header)}.{_encode_part(claims)}"
    if alg == "HS256":
        if private_ref:
            secret = _read_ref(private_ref).decode()
        else:
            secret = settings.workload_identity_dev_secret
        signature = _hs256_sign(encoded.encode(), secret)
    elif alg == "RS256":
        if not private_ref:
            raise WorkloadIdentityError("RS256 private key reference is not configured")
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding
        key = serialization.load_pem_private_key(_read_ref(private_ref), password=None)
        signature = _b64(key.sign(encoded.encode(), padding.PKCS1v15(), hashes.SHA256()))
    else:
        raise WorkloadIdentityError(f"Unsupported workload identity algorithm: {alg}")
    token = f"{encoded}.{signature}"
    record = WorkloadIdentityToken(
        organization_id=lease.organization_id, lease_id=lease.id, member_id=lease.member_id, agent_id=lease.agent_id,
        jti=jti, issuer=settings.workload_identity_issuer, audience=audience,
        scopes_json=lease.scopes_json, signing_alg=alg, status="active", expires_at=now_dt + timedelta(seconds=ttl),
    )
    db.add(record); db.commit(); db.refresh(record)
    return {"access_token": token, "token_type": "Bearer", "expires_in": ttl, "jti": jti, "kid": kid, "claims": claims}


def _verification_key(db: Session, claims: dict, header: dict) -> tuple[str, bytes | str]:
    alg = str(header.get("alg", "")).upper(); kid = str(header.get("kid", "")); org_id = int(claims.get("org_id", 0) or 0)
    key = None
    if org_id and kid:
        key = db.query(WorkloadSigningKey).filter(
            WorkloadSigningKey.organization_id == org_id,
            WorkloadSigningKey.kid == kid,
        ).first()
    if key:
        now = utcnow()
        if key.status == "revoked" or key.not_before > now or (key.not_after and key.not_after <= now):
            raise WorkloadIdentityError("Workload signing key is not trusted")
        if key.algorithm.upper() != alg:
            raise WorkloadIdentityError("Workload token algorithm/key mismatch")
        if alg == "HS256":
            return alg, _read_ref(key.private_key_ref).decode()
        if alg == "RS256":
            if not key.public_key_pem:
                raise WorkloadIdentityError("Workload signing key has no public key")
            return alg, key.public_key_pem.encode()
    # v14 compatibility fallback
    if kid != settings.workload_identity_key_id:
        raise WorkloadIdentityError("Unknown workload signing key")
    if alg == "HS256":
        return alg, settings.workload_identity_dev_secret
    if alg == "RS256":
        path = Path(settings.workload_identity_public_key_path)
        if not path.exists():
            raise WorkloadIdentityError("RS256 public key path is not configured")
        return alg, path.read_bytes()
    raise WorkloadIdentityError("Unsupported workload token algorithm")


def verify_workload_token(db: Session, token: str, *, audience: str = "clawcompany-runner") -> dict:
    try:
        h, p, s = token.split(".")
        header = json.loads(_unb64(h)); claims = json.loads(_unb64(p)); signature = _unb64(s)
    except Exception as exc:
        raise WorkloadIdentityError("Malformed workload token") from exc
    alg, material = _verification_key(db, claims, header)
    signing_input = f"{h}.{p}".encode()
    if alg == "HS256":
        expected = hmac.new(str(material).encode(), signing_input, hashlib.sha256).digest()
        if not hmac.compare_digest(signature, expected):
            raise WorkloadIdentityError("Invalid workload token signature")
    elif alg == "RS256":
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding
        try:
            key = serialization.load_pem_public_key(material if isinstance(material, bytes) else material.encode())
            key.verify(signature, signing_input, padding.PKCS1v15(), hashes.SHA256())
        except Exception as exc:
            raise WorkloadIdentityError("Invalid workload token signature") from exc
    now = int(time.time())
    if claims.get("iss") != settings.workload_identity_issuer or claims.get("aud") != audience:
        raise WorkloadIdentityError("Issuer or audience mismatch")
    if int(claims.get("exp", 0)) <= now or int(claims.get("nbf", 0)) > now:
        raise WorkloadIdentityError("Workload token expired or not yet valid")
    record = db.query(WorkloadIdentityToken).filter(WorkloadIdentityToken.jti == claims.get("jti")).first()
    now_dt = utcnow()
    if not record or record.status != "active" or record.expires_at <= now_dt:
        raise WorkloadIdentityError("Workload token is revoked or expired")
    lease = db.get(RunnerLease, record.lease_id)
    if not lease or lease.status != "active" or lease.expires_at <= now_dt:
        raise WorkloadIdentityError("Runner lease is no longer active")
    if lease.organization_id != int(claims.get("org_id", 0)) or lease.id != int(claims.get("lease_id", 0)):
        raise WorkloadIdentityError("Lease binding mismatch")
    return claims


def _rsa_jwk(public_pem: bytes, *, kid: str) -> dict:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    key = serialization.load_pem_public_key(public_pem)
    if not isinstance(key, rsa.RSAPublicKey):
        raise WorkloadIdentityError("Configured public key is not RSA")
    nums = key.public_numbers()
    n = _b64(nums.n.to_bytes((nums.n.bit_length() + 7) // 8, "big"))
    e = _b64(nums.e.to_bytes((nums.e.bit_length() + 7) // 8, "big"))
    return {"kty": "RSA", "use": "sig", "alg": "RS256", "kid": kid, "n": n, "e": e}


def jwks_document(db: Session | None = None, organization_id: int | None = None) -> dict:
    keys: list[dict] = []
    if db is not None and organization_id is not None:
        now = utcnow()
        rows = db.query(WorkloadSigningKey).filter(
            WorkloadSigningKey.organization_id == organization_id,
            WorkloadSigningKey.status.in_(["active", "retiring"]),
            WorkloadSigningKey.not_before <= now,
        ).filter((WorkloadSigningKey.not_after.is_(None)) | (WorkloadSigningKey.not_after > now)).all()
        for row in rows:
            if row.algorithm.upper() == "RS256" and row.public_key_pem:
                keys.append(_rsa_jwk(row.public_key_pem.encode(), kid=row.kid))
        if keys:
            return {"keys": keys}
    if settings.workload_identity_algorithm.upper() != "RS256":
        return {"keys": []}
    path = Path(settings.workload_identity_public_key_path)
    if not path.exists():
        return {"keys": []}
    return {"keys": [_rsa_jwk(path.read_bytes(), kid=settings.workload_identity_key_id)]}
