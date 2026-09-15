"""v25: automatic reconciliation on attach.

v24 exposed gap reporting and approval backfill as endpoints a human had to
call. This router does not add new recovery powers -- it reports on the ones
that now run by themselves, and keeps a manual override for the case where an
operator wants to force a pass without waiting for a re-attach.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.authz import Principal, require_role, require_scope
from app.core.config import settings
from app.core.tenancy import active_org, ensure_task
from app.db.session import get_db
from app.services import approval_backfill, stream_reconcile

router = APIRouter(prefix="/v25", tags=["v25-auto-reconcile"])

READ = "company.context:read"
WRITE = "company.runtime:write"


def writer(minimum_role: str = "member"):
    def dep(principal: Principal = Depends(require_scope(WRITE))) -> Principal:
        if principal.auth_type != "api_key":
            return require_role(minimum_role)(principal)
        return principal
    return dep


class ReconcileIn(BaseModel):
    task_id: int = Field(..., ge=1)


@router.get("/runtime/reconcile")
def reconcile_status(principal: Principal = Depends(require_scope(READ))):
    """What reconciliation has this worker done, and can it do anything?

    ``process_local`` is the honest caveat: the history lives in memory, so
    another worker's passes are not listed here. The durable trace of every
    pass is in the company event bus, not in this response.
    """
    org_id = active_org(principal)
    return {
        "history": stream_reconcile.history(org_id),
        "enabled": settings.openclaw_auto_reconcile,
        "cooldown_seconds": stream_reconcile.COOLDOWN_SECONDS,
        "event_type": stream_reconcile.RECONCILE_EVENT,
        "readiness": approval_backfill.readiness(),
        "process_local": True,
    }


@router.post("/runtime/reconcile")
async def reconcile_now(body: ReconcileIn, principal: Principal = Depends(writer("manager")),
                        db: Session = Depends(get_db)):
    """Force a reconciliation pass for one task's session.

    ``force`` bypasses both the feature flag and the cooldown: an operator
    asking for this explicitly has better context than our rate limit.
    """
    task = ensure_task(db, body.task_id, principal)
    if not task.runtime_session_key:
        raise HTTPException(status_code=400, detail="Task has no OpenClaw session")
    return await stream_reconcile.reconcile(
        db,
        organization_id=active_org(principal),
        session_key=task.runtime_session_key,
        task_id=task.id,
        reason="manual",
        force=True,
    )
