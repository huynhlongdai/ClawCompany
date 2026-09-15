from fastapi import Header, HTTPException
from sqlalchemy.orm import Session
from app.core.config import settings
from app.models import RunnerNode
from app.services.runner_trust import verify_runner_fingerprint, RunnerTrustError


def enforce_runner_transport(db: Session, node: RunnerNode, *, fingerprint: str | None, proxy_verified: str | None):
    """Validate the certificate identity asserted by a trusted TLS terminator.

    Production topology: runner mTLS -> Envoy/NGINX -> private API network. The proxy
    validates the client certificate and injects fingerprint + a shared verification header.
    The application never treats a raw client-supplied fingerprint as mTLS proof.
    """
    if not settings.runner_mtls_required:
        return None
    if not settings.runner_mtls_proxy_shared_secret:
        raise HTTPException(503, "Runner mTLS is required but trusted proxy secret is not configured")
    if proxy_verified != settings.runner_mtls_proxy_shared_secret:
        raise HTTPException(401, "Trusted mTLS proxy verification is missing")
    if not fingerprint:
        raise HTTPException(401, "Runner certificate fingerprint is missing")
    try:
        return verify_runner_fingerprint(db, organization_id=node.organization_id, runner_node_id=node.id, fingerprint_sha256=fingerprint)
    except RunnerTrustError as exc:
        raise HTTPException(401, str(exc))
