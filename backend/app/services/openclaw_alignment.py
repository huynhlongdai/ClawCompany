"""Keep ClawCompany's agent roster aligned with the real OpenClaw gateway.

ClawCompany models an AI employee as a Member (member_type="agent") plus an
Agent row holding runtime_agent_id. Upstream OpenClaw models the same thing as
a config entry agents.entries.<agentId> with its own workspace, agentDir and
session store. Those two rosters drift the moment an operator runs
`openclaw agents add` or removes an entry, so this module reconciles them and
reports the drift instead of silently guessing.

It deliberately does not create OpenClaw agents. Upstream requires operator
approval for agent creation, and a company backend should not be able to mint
personas on the operator's machine.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import Agent, Member, Task
from app.runtime import openclaw_protocol as ocp
from app.services.company_event_bus import emit_event

SOURCE = "openclaw_alignment"


def company_agent_index(db: Session, organization_id: int) -> dict[str, dict]:
    """runtime_agent_id -> company seat facts."""
    rows = (
        db.query(Agent, Member)
        .join(Member, Agent.member_id == Member.id)
        .filter(Member.organization_id == organization_id)
        .all()
    )
    index: dict[str, dict] = {}
    for agent, member in rows:
        key = str(agent.runtime_agent_id or "")
        if not key:
            continue
        index[key] = {
            "agent_id": agent.id,
            "member_id": member.id,
            "name": member.name,
            "company_id": member.company_id,
            "member_status": member.status,
            "lifecycle": agent.lifecycle,
            "runtime_provider": agent.runtime_provider,
        }
    return index


def reconcile(db: Session, organization_id: int, gateway_agents: list[dict]) -> dict:
    """Compare both rosters and mark drift on the company side.

    Returns three buckets:
      matched  - present on both sides
      orphaned - a company seat whose OpenClaw agent no longer exists
      unbound  - an OpenClaw agent nobody in the company has claimed
    """
    gateway_index = {
        str(entry.get("id") or entry.get("agentId") or ""): entry
        for entry in gateway_agents
        if (entry.get("id") or entry.get("agentId"))
    }
    company_index = company_agent_index(db, organization_id)

    matched, orphaned, unbound = [], [], []
    for runtime_id, seat in sorted(company_index.items()):
        if runtime_id in gateway_index:
            matched.append({"runtime_agent_id": runtime_id, **seat, "gateway": gateway_index[runtime_id]})
        else:
            orphaned.append({"runtime_agent_id": runtime_id, **seat})
    for runtime_id, entry in sorted(gateway_index.items()):
        if runtime_id not in company_index:
            unbound.append({"runtime_agent_id": runtime_id, "gateway": entry})

    # Drift is recorded on the seat so the cockpit can show it, but a missing
    # gateway agent never deletes company data.
    changed = 0
    for item in orphaned:
        agent = db.get(Agent, item["agent_id"])
        if agent is not None and agent.lifecycle != "detached":
            agent.lifecycle = "detached"
            db.add(agent)
            changed += 1
    for item in matched:
        agent = db.get(Agent, item["agent_id"])
        if agent is not None and agent.lifecycle == "detached":
            agent.lifecycle = "active"
            db.add(agent)
            changed += 1
    if changed:
        db.commit()

    summary = {
        "matched": matched,
        "orphaned": orphaned,
        "unbound": unbound,
        "counts": {
            "matched": len(matched),
            "orphaned": len(orphaned),
            "unbound": len(unbound),
            "updated": changed,
        },
    }
    emit_event(
        db,
        organization_id=organization_id,
        event_type="openclaw.roster.reconciled",
        source=SOURCE,
        aggregate_type="organization",
        aggregate_id=str(organization_id),
        payload=summary["counts"],
    )
    return summary


def bind_seat(db: Session, organization_id: int, member_id: int, runtime_agent_id: str) -> Agent:
    """Point a company agent seat at an OpenClaw agentId."""
    member = db.get(Member, member_id)
    if member is None or member.organization_id != organization_id:
        raise ValueError("Member not found in this organization")
    if member.member_type != "agent":
        raise ValueError("Only agent seats can bind to an OpenClaw agent")
    clash = (
        db.query(Agent)
        .join(Member, Agent.member_id == Member.id)
        .filter(Member.organization_id == organization_id, Agent.runtime_agent_id == runtime_agent_id)
        .first()
    )
    if clash is not None and clash.member_id != member_id:
        raise ValueError(f"runtime_agent_id '{runtime_agent_id}' is already bound to another seat")

    agent = db.query(Agent).filter(Agent.member_id == member_id).first()
    if agent is None:
        agent = Agent(member_id=member_id, runtime_provider="openclaw", lifecycle="active")
    agent.runtime_agent_id = runtime_agent_id
    agent.runtime_provider = "openclaw"
    agent.lifecycle = "active"
    db.add(agent)
    db.commit()
    db.refresh(agent)
    emit_event(
        db,
        organization_id=organization_id,
        event_type="openclaw.seat.bound",
        source=SOURCE,
        company_id=member.company_id,
        aggregate_type="agent",
        aggregate_id=str(agent.id),
        payload={"member_id": member_id, "runtime_agent_id": runtime_agent_id},
    )
    return agent


def task_brief(db: Session, task: Task) -> str:
    """The prompt an OpenClaw session receives for a company task.

    Kept in one place because the wording is a contract: the agent is told what
    it may decide alone and what must come back to the company for approval.
    """
    lines = [
        f"Company task #{task.id}: {task.title}",
        "",
        (task.description or "No description provided.").strip(),
        "",
        "Working agreement:",
        "- Report progress as you go; the company records every gateway event.",
        "- Do not publish externally, purchase, delete production data, or change production systems without human approval.",
        "- Finish by stating the outcome and where the artifacts are.",
    ]
    return "\n".join(lines)


def session_key_for_task(runtime_agent_id: str, task_id: int) -> str:
    return ocp.task_session_key(runtime_agent_id, task_id)


def runtime_descriptor() -> dict:
    """What this deployment is actually pointed at."""
    mode = settings.openclaw_mode.lower()
    return {
        "mode": mode,
        "native": mode in ("native", "openclaw"),
        "gateway_ws": settings.openclaw_gateway_ws,
        "gateway_http": settings.openclaw_gateway_http or settings.openclaw_gateway_ws.replace("ws://", "http://").replace("wss://", "https://"),
        "protocol_version": settings.openclaw_protocol_version,
        "scopes_requested": list(ocp.COMPANY_SCOPES),
        "auto_dispatch": settings.openclaw_auto_dispatch,
        "token_configured": bool(settings.openclaw_api_token),
        "legacy_contract_map": ocp.LEGACY_CONTRACT_MAP,
        "notes": list(ocp.PROTOCOL_NOTES),
        "http_denied_tools": sorted(ocp.HTTP_DENIED_TOOLS),
    }
