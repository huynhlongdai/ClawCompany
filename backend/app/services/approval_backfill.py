"""v24: pull approval prompts that were raised before we were listening.

The upstream docs are explicit that a client backfills with
``exec.approval.list`` on connect and then reconciles live
``exec.approval.requested`` / ``exec.approval.resolved`` events by approval id.
ClawCompany only ever did the second half, so a prompt raised while no
follower was attached never reached the company queue — it just expired.

This is the natural partner of ``runtime_gap``: that module reports what was
missed, this one recovers the part that is actually recoverable.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import Member, Task
from app.runtime import openclaw_protocol as ocp
from app.runtime.factory import get_runtime
from app.services import runtime_stream as stream

SOURCE = "approval_backfill"


class ApprovalBackfillError(RuntimeError):
    pass


def readiness() -> dict:
    """Can we ask the gateway for its pending prompts?

    Listing needs the same ``operator.approvals`` scope that answering does,
    and the runtime has to actually implement the call. Mock runtimes do not,
    and reporting that plainly beats an empty list that looks like "nothing
    pending".
    """
    runtime = get_runtime()
    lister = getattr(runtime, "list_approvals", None)
    missing = []
    if not settings.openclaw_request_approvals_scope:
        missing.append("OPENCLAW_REQUEST_APPROVALS_SCOPE")
    if not callable(lister):
        missing.append(f"runtime {type(runtime).__name__} has no list_approvals")
    return {
        "ready": not missing,
        "missing": missing,
        "method": ocp.M_EXEC_APPROVAL_LIST,
        "scope": ocp.SCOPE_APPROVALS,
        "runtime": type(runtime).__name__,
    }


def entries_from(result: object) -> list[dict]:
    """Normalize the shapes a gateway list response might arrive in.

    We accept a bare list or the common wrapper keys rather than pinning one
    shape, because the wrapper is the part of the contract we have not read a
    schema for. Anything that is not a mapping is dropped instead of being
    coerced into a fake approval.
    """
    raw: object = result
    if isinstance(result, dict):
        for key in ("approvals", "items", "pending", "result", "data"):
            if isinstance(result.get(key), list):
                raw = result[key]
                break
        else:
            raw = []
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


def _state_for(db: Session, *, organization_id: int, session_key: str,
               task_id: int | None) -> stream.ConsumerState:
    """A consumer state that exists only to reuse the live recording path.

    Backfilled prompts must land in the queue by exactly the same rules as
    live ones — same policy key, same idempotency, same risk defaults — so we
    reuse ``record_approval`` rather than writing a second, subtly different
    inserter that would drift.
    """
    return stream.ConsumerState(
        session_key=session_key, task_id=task_id, organization_id=organization_id
    )


def apply_entries(
    db: Session,
    entries: list[dict],
    *,
    organization_id: int,
    session_key: str,
    task_id: int | None = None,
) -> dict:
    """Reconcile listed prompts into the company queue. Safe to repeat."""
    state = _state_for(db, organization_id=organization_id, session_key=session_key, task_id=task_id)
    member = None
    if task_id:
        task = db.get(Task, task_id)
        if task is not None and task.assignee_member_id:
            member = db.get(Member, task.assignee_member_id)

    recorded, ignored = [], 0
    for entry in entries:
        # Present it exactly as a live approval event would arrive, so the
        # existing normalization applies unchanged.
        event = {"type": ocp.M_EXEC_APPROVAL_LIST, "family": "approval", "raw": entry}
        approval = stream.record_approval(db, state, event, member=member)
        if approval is None:
            ignored += 1
            continue
        recorded.append(approval.id)
    # Duplicates are expected: re-running a backfill returns the same rows.
    return {
        "session_key": session_key,
        "task_id": task_id,
        "seen": len(entries),
        "recorded": sorted(set(recorded)),
        "ignored": ignored,
    }


async def backfill_session(
    db: Session,
    *,
    organization_id: int,
    session_key: str,
    task_id: int | None = None,
) -> dict:
    """Ask the gateway what is pending for one session and record it."""
    ready = readiness()
    if not ready["ready"]:
        return {"supported": False, "session_key": session_key, "task_id": task_id,
                "readiness": ready, "seen": 0, "recorded": [], "ignored": 0}
    runtime = get_runtime()
    result = await runtime.list_approvals(session_key=session_key)
    outcome = apply_entries(
        db, entries_from(result), organization_id=organization_id,
        session_key=session_key, task_id=task_id,
    )
    outcome.update({"supported": True, "readiness": ready})
    return outcome
