import json
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from sqlalchemy.orm import Session
from app.models import Artifact, EvidenceSignature, EvidenceTrustPolicy, EvidenceVerification
from app.services.supply_chain_signing import verify_signature, SupplyChainSigningError


class EvidenceTrustError(RuntimeError):
    pass


def utcnow(): return datetime.now(timezone.utc).replace(tzinfo=None)


def verify_evidence(db: Session, signature: EvidenceSignature, policy: EvidenceTrustPolicy | None = None) -> EvidenceVerification:
    if policy and (policy.organization_id != signature.organization_id or not policy.enabled):
        raise EvidenceTrustError("Evidence trust policy is unavailable")
    if policy and policy.signature_type and policy.signature_type != signature.signature_type:
        result = EvidenceVerification(organization_id=signature.organization_id, signature_id=signature.id, policy_id=policy.id,
                                      status="failed", reason="signature_type_mismatch", detail_json="{}", verified_at=utcnow())
        db.add(result); db.commit(); db.refresh(result); return result
    if policy and policy.expected_signer and policy.expected_signer != signature.signer:
        result = EvidenceVerification(organization_id=signature.organization_id, signature_id=signature.id, policy_id=policy.id,
                                      status="failed", reason="signer_mismatch", detail_json=json.dumps({"actual": signature.signer}), verified_at=utcnow())
        db.add(result); db.commit(); db.refresh(result); return result
    ok = False; reason = ""; detail = {}
    try:
        if signature.signature_type == "hmac-sha256":
            verified = verify_signature(db, signature); ok = bool(verified.verified); reason = "verified" if ok else "digest_or_signature_mismatch"
        elif signature.signature_type == "cosign":
            artifact = db.get(Artifact, signature.artifact_id)
            if not artifact or artifact.organization_id != signature.organization_id or not artifact.content_text:
                raise EvidenceTrustError("Cosign verification requires inline artifact bytes")
            key_ref = (policy.key_ref if policy and policy.key_ref else signature.key_ref).strip()
            if not key_ref or key_ref == "keyless":
                raise EvidenceTrustError("Keyless Sigstore verification requires certificate/transparency policy and is fail-closed")
            exe = shutil.which("cosign")
            if not exe: raise EvidenceTrustError("cosign executable is unavailable")
            with tempfile.TemporaryDirectory(prefix="cc-cosign-verify-") as td:
                root = Path(td); blob = root / "artifact.bin"; sig = root / "signature.txt"
                blob.write_text(artifact.content_text, encoding="utf-8"); sig.write_text(signature.signature, encoding="utf-8")
                args = [exe, "verify-blob", "--key", key_ref, "--signature", str(sig), str(blob)]
                p = subprocess.run(args, capture_output=True, text=True, timeout=120, shell=False)
                detail = {"exit_code": p.returncode, "stdout": p.stdout[-2000:], "stderr": p.stderr[-2000:]}
                ok = p.returncode == 0; reason = "verified" if ok else "cosign_verify_failed"
                signature.verified = ok; signature.verified_at = utcnow() if ok else None; db.add(signature); db.commit()
        else:
            raise EvidenceTrustError(f"Unsupported signature type: {signature.signature_type}")
    except (EvidenceTrustError, SupplyChainSigningError) as exc:
        reason = str(exc); ok = False
    result = EvidenceVerification(organization_id=signature.organization_id, signature_id=signature.id,
                                  policy_id=policy.id if policy else None, status="verified" if ok else "failed",
                                  reason=reason, detail_json=json.dumps(detail, default=str), verified_at=utcnow())
    db.add(result); db.commit(); db.refresh(result); return result
