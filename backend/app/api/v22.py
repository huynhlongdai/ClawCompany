"""v22 cluster runtime: shared stream registry and automatic session takeover.

v21 made ownership safe but left two things half-answered:

- ``GET /api/v20/streams`` described one worker's memory. With two workers
  each answer was half the truth and neither admitted it. The registry here
  is shared, and when it cannot be (no Redis) the response says
  ``process_local: true`` instead of implying cluster coverage.
- A follower that lost its lease stopped, correctly, but the session then sat
  unattended until a human pressed "resume". Takeover is now a sweep that any
  worker can run; the lease still decides the single winner.
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.authz import Principal, require_role, require_scope
from app.core.config import settings
from app.core.tenancy import active_org
from app.db.session import get_db
from app.services import runtime_stream as stream
from app.services.runtime_leases import store as lease_store
from app.services.stream_registry import registry

router = APIRouter(prefix="/v22", tags=["v22-cluster-runtime"])

READ = "company.context:read"
WRITE = "company.runtime:write"


def writer(minimum_role: str = "member"):
    def dep(principal: Principal = Depends(require_scope(WRITE))) -> Principal:
        if principal.auth_type != "api_key":
            return require_role(minimum_role)(principal)
        return principal
    return dep


class ClaimIn(BaseModel):
    limit: int = Field(default=50, ge=1, le=200)


@router.get("/runtime/streams")
def streams(principal: Principal = Depends(require_scope(READ))):
    """Every follower any worker reported, scoped to the caller's tenant."""
    return stream.cluster_snapshot(active_org(principal))


@router.get("/runtime/registry")
def registry_status(principal: Principal = Depends(require_scope(READ))):
    """Is the run view cluster-wide, and if not, why not?"""
    return {
        "registry": registry.status(),
        "lease": lease_store.status(),
        "sweep_seconds": settings.openclaw_claim_sweep_seconds,
        "sweep_enabled": settings.openclaw_claim_sweep_seconds > 0,
        # Carried here because the v22 stream list replaced the v20 response
        # that used to report it; the UI still needs to show it.
        "auto_dispatch": settings.openclaw_auto_dispatch,
    }


@router.get("/runtime/orphans")
def orphans(principal: Principal = Depends(require_scope(READ)), db: Session = Depends(get_db)):
    """Mid-run sessions that currently have no lease holder at all.

    Distinct from v21's resumable list, which also includes sessions another
    worker is following perfectly well.
    """
    org_id = active_org(principal)
    tasks = stream.claimable_sessions(db)
    return {
        "orphans": [
            {"task_id": t.id, "title": t.title, "status": t.status,
             "session_key": t.runtime_session_key, "run_id": t.runtime_run_id}
            for t in tasks
        ],
        "lease": lease_store.status(),
        "registry": registry.status(),
        "organization_id": org_id,
    }


@router.post("/runtime/claim")
def claim(body: ClaimIn, principal: Principal = Depends(writer("manager")),
          db: Session = Depends(get_db)):
    """Take over unattended sessions for this tenant now."""
    return stream.claim_orphans(db, organization_id=active_org(principal), limit=body.limit)
