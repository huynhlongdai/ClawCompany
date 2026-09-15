import hashlib
import hmac
import os
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from sqlalchemy.orm import Session
from app.models import Artifact, EvidenceSignature


class SupplyChainSigningError(RuntimeError):
    pass


def _digest(artifact: Artifact) -> str:
    # Recompute inline bytes instead of trusting stored digest metadata. This lets
    # verification detect accidental/tampered content changes after signing.
    if artifact.content_text:
        return hashlib.sha256(artifact.content_text.encode()).hexdigest()
    if artifact.content_sha256:
        return artifact.content_sha256
    raise SupplyChainSigningError("Artifact has no digestable content")


def _resolve_env_key(key_ref: str) -> bytes:
    if not key_ref.startswith("env:"):
        raise SupplyChainSigningError("Local signing accepts env:KEY references only")
    name = key_ref.split(":", 1)[1]
    value = os.environ.get(name, "")
    if not value:
        raise SupplyChainSigningError(f"Signing key reference {key_ref} is unavailable")
    return value.encode()


def sign_artifact(db: Session, artifact: Artifact, *, build_id: int | None = None,
                  provider: str = "local_hmac", key_ref: str = "env:SUPPLY_CHAIN_SIGNING_KEY") -> EvidenceSignature:
    digest = _digest(artifact)
    if provider == "local_hmac":
        key = _resolve_env_key(key_ref)
        sig = hmac.new(key, digest.encode(), hashlib.sha256).hexdigest()
        kind = "hmac-sha256"; signer = "clawcompany://signer/local-hmac"
    elif provider == "cosign_cli":
        exe = shutil.which("cosign")
        if not exe:
            raise SupplyChainSigningError("cosign executable is unavailable")
        if not artifact.content_text:
            raise SupplyChainSigningError("cosign_cli currently signs inline artifact bytes only")
        with tempfile.TemporaryDirectory(prefix="cc-cosign-") as td:
            blob = Path(td) / "artifact.bin"; out = Path(td) / "signature.txt"
            blob.write_bytes(artifact.content_text.encode())
            args = [exe, "sign-blob", "--yes", "--output-signature", str(out)]
            if key_ref and key_ref != "keyless":
                args += ["--key", key_ref]
            args += [str(blob)]
            p = subprocess.run(args, capture_output=True, text=True, timeout=120)
            if p.returncode != 0 or not out.exists():
                raise SupplyChainSigningError((p.stderr or p.stdout or "cosign signing failed")[:4000])
            sig = out.read_text().strip()
        kind = "cosign"; signer = "sigstore://cosign"
    else:
        raise SupplyChainSigningError(f"Unsupported signing provider: {provider}")
    item = EvidenceSignature(
        organization_id=artifact.organization_id, artifact_id=artifact.id, build_id=build_id,
        signature_type=kind, signer=signer, key_ref=key_ref, subject_digest=digest,
        signature=sig, verified=False,
    )
    db.add(item); db.commit(); db.refresh(item)
    return item


def verify_signature(db: Session, item: EvidenceSignature) -> EvidenceSignature:
    artifact = db.get(Artifact, item.artifact_id)
    if not artifact or artifact.organization_id != item.organization_id:
        raise SupplyChainSigningError("Artifact is unavailable")
    digest = _digest(artifact)
    if digest != item.subject_digest:
        ok = False
    elif item.signature_type == "hmac-sha256":
        key = _resolve_env_key(item.key_ref)
        expected = hmac.new(key, digest.encode(), hashlib.sha256).hexdigest()
        ok = hmac.compare_digest(expected, item.signature)
    elif item.signature_type == "cosign":
        # Offline verification of keyless/certificate identities needs the exact trust policy and bundle.
        # Fail closed rather than pretending the stored signature is sufficient.
        raise SupplyChainSigningError("Cosign verification requires a configured trust policy/bundle adapter")
    else:
        raise SupplyChainSigningError("Unsupported signature type")
    item.verified = bool(ok); item.verified_at = datetime.utcnow() if ok else None
    db.add(item); db.commit(); db.refresh(item)
    return item
