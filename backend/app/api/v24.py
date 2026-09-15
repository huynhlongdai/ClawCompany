"""v24 observability of what we missed: session gaps and approval backfill.

v22 shipped automatic takeover and then admitted, in a docs footnote, that
re-subscribing does not replay anything. v23 verified the approval contract
and noted that we never called ``exec.approval.list``. Both gaps were real and
both were invisible in the product. This router makes them visible and, where
recovery is possible, recoverable.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.authz import Principal, require_role, require_scope
from app.core.tenancy import active_org, ensure_task
from app.db.session import get_db
from app.services import approval_backfill, runtime_gap
from app.services import runtime_stream as stream

router = APIRouter(prefix="/v24", tags=["v24-gap-awareness"])

READ = "company.context:read"
WRITE = "company.runtime:write"


def writer(minimum_role: str = "member"):
    def dep(principal: Principal = Depends(require_scope(WRITE))) -> Principal:
        if principal.auth_type != "api_key":
            return require_role(minimum_role)(principal)
        return principal
    return dep


class BackfillIn(BaseModel):
    task_id: int = Field(..., ge=1)


@router.get("/runtime/gaps")
def gaps(principal: Principal = Depends(require_scope(READ)), db: Session = Depends(get_db)):
    """Unattended sessions and how long they have gone unobserved.

    A session with no recorded events reports ``observed: false`` rather than
    a gap of zero: we do not know how long it has been running blind.
    """
    org_id = active_org(principal)
    rows = []
    for task in stream.claimable_sessions(db):
        measurement = runtime_gap.measure(db, task.runtime_session_key)
        measurement.update({"task_id": task.id, "title": task.title, "status": task.status})
        rows.append(measurement)
    return {
        "gaps": rows,
        "organization_id": org_id,
        "min_gap_seconds": runtime_gap.MIN_GAP_SECONDS,
        # Said here as well as in the payloads, because an operator reading a
        # list of gaps will want to know whether they can be filled.
        "replay_supported": False,
    }


@router.get("/approvals/backfill/readiness")
def backfill_readiness(principal: Principal = Depends(require_scope(READ))):
    """Can we ask the gateway for prompts raised while we were away?"""
    return approval_backfill.readiness()


@router.post("/approvals/backfill")
async def backfill(body: BackfillIn, principal: Principal = Depends(writer("manager")),
                   db: Session = Depends(get_db)):
    """Reconcile the gateway's pending prompts for one task's session."""
    task = ensure_task(db, body.task_id, principal)
    if not task.runtime_session_key:
        raise HTTPException(status_code=400, detail="Task has no OpenClaw session")
    return await approval_backfill.backfill_session(
        db,
        organization_id=active_org(principal),
        session_key=task.runtime_session_key,
        task_id=task.id,
    )
