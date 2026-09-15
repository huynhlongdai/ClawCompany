import hashlib
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from sqlalchemy.orm import Session
from app.models import RunnerTrustAuthority, RunnerCertificate, RunnerNode


class RunnerTrustError(RuntimeError):
    pass


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _load_private_key(ref: str):
    if not ref:
        raise RunnerTrustError("Private key reference is required")
    if ref.startswith("env:"):
        value = os.environ.get(ref.split(":", 1)[1], "")
        if not value:
            raise RunnerTrustError(f"Private key reference is unavailable: {ref}")
        pem = value.encode()
    elif ref.startswith("file:"):
        path = Path(ref.split(":", 1)[1]).expanduser().resolve()
        if not path.exists():
            raise RunnerTrustError(f"Private key file is unavailable: {path}")
        pem = path.read_bytes()
    else:
        raise RunnerTrustError("Private key references must use env: or file:")
    try:
        from cryptography.hazmat.primitives import serialization
        return serialization.load_pem_private_key(pem, password=None)
    except Exception as exc:
        raise RunnerTrustError("Unable to load CA private key") from exc


def validate_authority_material(ca_cert_pem: str, private_key_ref: str):
    try:
        from cryptography import x509
        cert = x509.load_pem_x509_certificate(ca_cert_pem.encode())
        key = _load_private_key(private_key_ref)
        cert_pub = cert.public_key().public_numbers()
        key_pub = key.public_key().public_numbers()
        if cert_pub != key_pub:
            raise RunnerTrustError("CA certificate does not match referenced private key")
        constraints = cert.extensions.get_extension_for_class(x509.BasicConstraints).value
        if not constraints.ca:
            raise RunnerTrustError("Configured certificate is not a CA certificate")
        return cert
    except RunnerTrustError:
        raise
    except Exception as exc:
        raise RunnerTrustError("Invalid CA certificate material") from exc


def create_authority(db: Session, *, organization_id: int, name: str, issuer_cn: str, ca_cert_pem: str,
                     private_key_ref: str, expires_at: datetime | None = None) -> RunnerTrustAuthority:
    cert = validate_authority_material(ca_cert_pem, private_key_ref)
    cert_exp = cert.not_valid_after_utc.replace(tzinfo=None)
    item = RunnerTrustAuthority(
        organization_id=organization_id, name=name, issuer_cn=issuer_cn,
        ca_cert_pem=ca_cert_pem, private_key_ref=private_key_ref, status="active",
        expires_at=min(x for x in [expires_at, cert_exp] if x is not None) if expires_at else cert_exp,
    )
    db.add(item); db.commit(); db.refresh(item)
    return item


def sign_runner_csr(db: Session, authority: RunnerTrustAuthority, node: RunnerNode, *, csr_pem: str,
                    ttl_hours: int = 24, previous_certificate_id: int | None = None) -> RunnerCertificate:
    if authority.organization_id != node.organization_id:
        raise RunnerTrustError("Runner node and trust authority belong to different organizations")
    if authority.status != "active":
        raise RunnerTrustError("Runner trust authority is not active")
    now = utcnow()
    if authority.expires_at and authority.expires_at <= now:
        raise RunnerTrustError("Runner trust authority is expired")
    try:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes
        from cryptography.x509.oid import ExtendedKeyUsageOID
        csr = x509.load_pem_x509_csr(csr_pem.encode())
        if not csr.is_signature_valid:
            raise RunnerTrustError("CSR signature is invalid")
        ca = x509.load_pem_x509_certificate(authority.ca_cert_pem.encode())
        key = _load_private_key(authority.private_key_ref)
        not_before = now - timedelta(minutes=2)
        not_after = now + timedelta(hours=max(1, min(int(ttl_hours), 168)))
        ca_exp = ca.not_valid_after_utc.replace(tzinfo=None)
        if authority.expires_at:
            ca_exp = min(ca_exp, authority.expires_at)
        not_after = min(not_after, ca_exp)
        if not_after <= now:
            raise RunnerTrustError("CA expires before requested runner certificate")
        builder = (x509.CertificateBuilder()
                   .subject_name(csr.subject)
                   .issuer_name(ca.subject)
                   .public_key(csr.public_key())
                   .serial_number(x509.random_serial_number())
                   .not_valid_before(not_before.replace(tzinfo=timezone.utc))
                   .not_valid_after(not_after.replace(tzinfo=timezone.utc))
                   .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
                   .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.CLIENT_AUTH]), critical=False))
        try:
            san = csr.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
            builder = builder.add_extension(san, critical=False)
        except x509.ExtensionNotFound:
            pass
        cert = builder.sign(private_key=key, algorithm=hashes.SHA256())
        pem = cert.public_bytes(__import__("cryptography.hazmat.primitives.serialization", fromlist=["Encoding"]).Encoding.PEM).decode()
        fp = cert.fingerprint(hashes.SHA256()).hex()
    except RunnerTrustError:
        raise
    except Exception as exc:
        raise RunnerTrustError("Failed to sign runner CSR") from exc

    previous = None
    if previous_certificate_id is not None:
        previous = db.get(RunnerCertificate, previous_certificate_id)
        if not previous or previous.organization_id != node.organization_id or previous.runner_node_id != node.id:
            raise RunnerTrustError("Previous runner certificate is unavailable")
    item = RunnerCertificate(
        organization_id=node.organization_id, runner_node_id=node.id, trust_authority_id=authority.id,
        previous_certificate_id=previous.id if previous else None,
        serial_number=str(cert.serial_number), subject_dn=cert.subject.rfc4514_string(), certificate_pem=pem,
        fingerprint_sha256=fp, status="active", not_before=not_before, not_after=not_after,
    )
    if previous and previous.status == "active":
        previous.status = "rotated"; previous.revoked_at = now; db.add(previous)
    db.add(item); db.commit(); db.refresh(item)
    return item


def revoke_runner_certificate(db: Session, cert: RunnerCertificate) -> RunnerCertificate:
    if cert.status not in {"revoked", "rotated"}:
        cert.status = "revoked"; cert.revoked_at = utcnow(); db.add(cert); db.commit(); db.refresh(cert)
    return cert


def verify_runner_fingerprint(db: Session, *, organization_id: int, runner_node_id: int, fingerprint_sha256: str) -> RunnerCertificate:
    now = utcnow()
    fp = fingerprint_sha256.strip().lower().replace(":", "")
    item = db.query(RunnerCertificate).filter(
        RunnerCertificate.organization_id == organization_id,
        RunnerCertificate.runner_node_id == runner_node_id,
        RunnerCertificate.fingerprint_sha256 == fp,
        RunnerCertificate.status == "active",
        RunnerCertificate.not_before <= now,
        RunnerCertificate.not_after > now,
    ).order_by(RunnerCertificate.id.desc()).first()
    if not item:
        raise RunnerTrustError("Runner certificate is not active/trusted")
    return item


def certificate_fingerprint_from_pem(pem: str) -> str:
    try:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes
        return x509.load_pem_x509_certificate(pem.encode()).fingerprint(hashes.SHA256()).hex()
    except Exception as exc:
        raise RunnerTrustError("Invalid certificate PEM") from exc
