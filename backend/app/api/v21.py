"""v21 durable runtime control: shared leases, boot resume, approval replies.

v20 shipped session followers with two stated holes. This closes them:

- Followers claim a session through a Redis lease, so running several API
  workers no longer means two processes writing the same events twice. When
  Redis is absent the lease degrades to process memory and says so, instead of
  pretending to be distributed.
- Followers can be re-attached after a restart, either on boot
  (OPENCLAW_RESUME_ON_BOOT) or on demand from here.
- A gateway permission prompt can be decided from the company queue. The reply
  needs the operator.approvals scope and an RPC name from configuration; we do
  not guess the method, and we never claim delivery we did not get.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.authz import Principal, enforce_org, require_role, require_scope
from app.core.config import settings
from app.core.tenancy import active_org
from app.db.session import get_db
from app.models import Approval
from app.services import approval_bridge, runtime_stream as stream
from app.services.runtime_leases import store as lease_store

router = APIRouter(prefix="/v21", tags=["v21-durable-runtime"])

READ = "company.context:read"
WRITE = "company.runtime:write"


def writer(minimum_role: str = "member"):
    def dep(principal: Principal = Depends(require_scope(WRITE))) -> Principal:
        if principal.auth_type != "api_key":
            return require_role(minimum_role)(principal)
        return principal
    return dep


class DecideIn(BaseModel):
    # v23: approved -> allow-once upstream. approved_always -> allow-always,
    # which mints a standing grant on the gateway host and stays behind a
    # separate setting, so it is a distinct word here rather than a flag.
    decision: str = Field(pattern="^(approved|approved_always|denied)$")
    note: str = Field(default="", max_length=2000)


class ResumeIn(BaseModel):
    limit: int = Field(default=50, ge=1, le=200)


@router.get("/runtime/leases")
def leases(principal: Principal = Depends(require_scope(READ))):
    """Lease backend plus the sessions this process currently owns."""
    snapshot = stream.supervisor.snapshot(active_org(principal))
    return {
        "lease": lease_store.status(),
        "followed_here": snapshot,
        "holders": {
            row["session_key"]: lease_store.holder(row["session_key"]) for row in snapshot
        },
    }


@router.get("/runtime/resumable")
def resumable(principal: Principal = Depends(require_scope(READ)), db: Session = Depends(get_db)):
    """Tasks that are mid-run but currently unobserved in this process."""
    org_id = active_org(principal)
    rows = []
    for task in stream.resumable_sessions(db):
        member_org = getattr(task, "organization_id", None)
        rows.append({
            "task_id": task.id,
            "title": task.title,
            "session_key": task.runtime_session_key,
            "following_here": stream.supervisor.is_following(task.runtime_session_key or ""),
            "lease_holder": lease_store.holder(task.runtime_session_key or ""),
            "organization_id": member_org or org_id,
        })
    return {"count": len(rows), "resume_on_boot": settings.openclaw_resume_on_boot, "tasks": rows}


@router.post("/runtime/resume")
def resume(payload: ResumeIn, principal: Principal = Depends(writer("manager")),
           db: Session = Depends(get_db)):
    """Re-attach followers for this organization's in-flight sessions.

    Safe to call repeatedly and from every worker: the lease decides who wins,
    the rest come back as declined.
    """
    return stream.resume_followers(db, organization_id=active_org(principal), limit=payload.limit)


@router.get("/approvals/readiness")
def approval_readiness(principal: Principal = Depends(require_scope(READ))):
    """Whether a decision made here can actually reach the gateway."""
    return approval_bridge.upstream_readiness()


@router.post("/approvals/{approval_id}/decide")
async def decide(approval_id: int, payload: DecideIn,
                 principal: Principal = Depends(writer("manager")),
                 db: Session = Depends(get_db)):
    """Decide a gateway approval prompt from the company queue.

    The response separates recorded from delivered on purpose: a decision kept
    only in ClawCompany must never look like one the agent received.
    """
    approval = db.get(Approval, approval_id)
    if approval is None:
        raise HTTPException(404, "Approval not found")
    enforce_org(approval.organization_id, principal)
    try:
        return await approval_bridge.decide(
            db, approval, decision=payload.decision, note=payload.note,
            actor_member_id=principal.member_id,
        )
    except approval_bridge.ApprovalBridgeError as exc:
        raise HTTPException(409, str(exc))
