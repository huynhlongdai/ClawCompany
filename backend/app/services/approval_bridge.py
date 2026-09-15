"""v21: answer an OpenClaw approval prompt from the company approval queue.

v20 could only *show* gateway prompts. Deciding them still meant opening the
OpenClaw operator UI, which defeats the point of having a company approval
queue. This module closes the loop, with two deliberate refusals:

1. We do not guess the upstream RPC name. v19 existed because an earlier
   version invented ``agents.run`` and friends. If
   ``OPENCLAW_APPROVAL_REPLY_METHOD`` is unset, answering upstream is reported
   as unsupported instead of firing a made-up method at the gateway.
2. Answering upstream needs the ``operator.approvals`` scope, which the
   handshake only requests when ``OPENCLAW_REQUEST_APPROVALS_SCOPE`` is on.
   Without it the gateway would reject the call, so we say that up front.

Either way the local decision is recorded, because a human did decide. The
result reports ``delivered`` separately from ``recorded`` so nobody mistakes a
locally-stored decision for one the agent actually received.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import Approval
from app.runtime import openclaw_protocol as ocp
from app.runtime.factory import get_runtime
from app.services.company_event_bus import emit_event
from app.services.runtime_stream import SOURCE as STREAM_SOURCE

SOURCE = "approval_bridge"

# v23: our queue speaks approved/denied; the gateway speaks a three-valued
# vocabulary. "approved" maps to allow-once deliberately — a standing grant is
# a different, wider act and must be asked for by name.
DECISIONS = {
    "approved": ocp.D_ALLOW_ONCE,
    "approved_always": ocp.D_ALLOW_ALWAYS,
    "denied": ocp.D_DENY,
}
# What gets stored in Approval.status. allow-always is still an approval.
LOCAL_STATUS = {
    "approved": "approved",
    "approved_always": "approved",
    "denied": "denied",
}


class ApprovalBridgeError(RuntimeError):
    pass


def parse_policy_key(policy_key: str) -> tuple[str, str]:
    """Split ``openclaw:<session key>:<request id>`` back into its parts.

    Session keys contain colons (``agent:<id>:main``), so we split from the
    right: the last segment is the request id, the middle is the session key.
    """
    if not policy_key.startswith("openclaw:"):
        raise ApprovalBridgeError(f"Approval {policy_key!r} did not come from OpenClaw")
    body = policy_key[len("openclaw:"):]
    session_key, _, request_id = body.rpartition(":")
    if not session_key or not request_id:
        raise ApprovalBridgeError(f"Malformed OpenClaw policy key: {policy_key!r}")
    return session_key, request_id


def upstream_readiness() -> dict:
    """Can we answer upstream at all? Checked before any decision is taken."""
    missing = []
    if not settings.openclaw_approval_reply_method:
        missing.append("OPENCLAW_APPROVAL_REPLY_METHOD")
    if not settings.openclaw_request_approvals_scope:
        missing.append("OPENCLAW_REQUEST_APPROVALS_SCOPE")
    method = settings.openclaw_approval_reply_method
    return {
        "ready": not missing,
        "missing": missing,
        "method": method,
        # v23: the default is documented upstream rather than guessed. Say which
        # one the operator is running on, because a custom value is unverified.
        "method_source": "documented default" if method == ocp.M_EXEC_APPROVAL_RESOLVE else (
            "operator override" if method else "unset"
        ),
        "decisions": sorted(DECISIONS),
        "allow_always_enabled": settings.openclaw_approval_allow_always_enabled,
        "note_delivered_upstream": False,
        "scope": ocp.SCOPE_APPROVALS if settings.openclaw_request_approvals_scope else "",
        "mode": settings.openclaw_mode,
        "hint": (
            "Turn on OPENCLAW_REQUEST_APPROVALS_SCOPE so the handshake asks for "
            f"{ocp.SCOPE_APPROVALS}; without it the gateway rejects the reply."
        ) if missing else "",
    }


async def decide(
    db: Session,
    approval: Approval,
    *,
    decision: str,
    note: str = "",
    actor_member_id: int | None = None,
) -> dict:
    """Record a decision locally and relay it upstream when possible."""
    if decision not in DECISIONS:
        raise ApprovalBridgeError(f"Decision must be one of {sorted(DECISIONS)}, got {decision!r}")
    if approval.status != "pending":
        raise ApprovalBridgeError(f"Approval {approval.id} is already {approval.status}")
    if decision == "approved_always" and not settings.openclaw_approval_allow_always_enabled:
        raise ApprovalBridgeError(
            "allow-always mints a standing grant on the gateway host and is off by default; "
            "set OPENCLAW_APPROVAL_ALLOW_ALWAYS_ENABLED to use it"
        )

    session_key, request_id = parse_policy_key(approval.policy_key or "")
    readiness = upstream_readiness()
    delivered, delivery_error, upstream = False, "", None

    if readiness["ready"]:
        runtime = get_runtime()
        responder = getattr(runtime, "respond_approval", None)
        if responder is None:
            delivery_error = f"Runtime mode '{settings.openclaw_mode}' cannot answer approvals"
        else:
            try:
                # v23: resolved by approval id with a three-valued decision.
                # The note is NOT sent: the gateway approval record has no
                # resolution-reason field, so it stays in our audit trail only.
                upstream = await responder(
                    request_id=request_id,
                    decision=DECISIONS[decision],
                    session_key=session_key,
                )
                delivered = True
            except Exception as exc:  # noqa: BLE001 - the local decision still stands
                delivery_error = str(exc)[:500]
    else:
        delivery_error = "Upstream reply not configured: " + ", ".join(readiness["missing"])

    approval.status = LOCAL_STATUS[decision]
    approval.resolution_note = _note(note, delivered, delivery_error)
    if actor_member_id is not None and approval.approver_member_id is None:
        approval.approver_member_id = actor_member_id
    db.add(approval)
    db.commit()
    db.refresh(approval)

    emit_event(
        db,
        organization_id=approval.organization_id,
        company_id=approval.company_id,
        event_type="openclaw.approval.decided",
        source=SOURCE,
        aggregate_type="approval",
        aggregate_id=str(approval.id),
        actor_member_id=actor_member_id,
        payload={
            "decision": decision,
            "upstream_decision": DECISIONS[decision],
            "session_key": session_key,
            "request_id": request_id,
            "delivered": delivered,
            "delivery_error": delivery_error,
            "stream_source": STREAM_SOURCE,
        },
    )
    return {
        "approval_id": approval.id,
        "status": approval.status,
        "recorded": True,
        "upstream_decision": DECISIONS[decision],
        "note_delivered_upstream": False,
        "delivered": delivered,
        "delivery_error": delivery_error,
        "session_key": session_key,
        "request_id": request_id,
        "upstream": upstream,
        "readiness": readiness,
    }


def _note(note: str, delivered: bool, delivery_error: str) -> str:
    """Keep the audit trail honest about whether the agent heard us.

    v23: when delivery succeeds, only the *decision* reached OpenClaw. The note
    never does — there is no field for it upstream — so the wording says so
    rather than implying the reviewer's reasoning travelled with it.
    """
    suffix = (
        "decision relayed to OpenClaw; this note stayed in ClawCompany"
        if delivered
        else f"recorded locally only ({delivery_error})"
    )
    return f"{note} [{suffix}]".strip()
