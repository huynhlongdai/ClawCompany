"""v19 OpenClaw core alignment API.

Everything ClawCompany does with the OpenClaw runtime is exposed here in terms
of the *real* upstream contract: sessions and chat turns, an operator handshake
with narrow scopes, the roster of configured agents, and the guarded
/tools/invoke passthrough.

Security notes:
- The gateway token never leaves the backend. Clients call these endpoints with
  a ClawCompany credential; the backend holds the OpenClaw bearer.
- A bearer on the gateway is full operator access upstream, so the tools
  passthrough is admin-gated and additionally refuses the upstream deny list.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.authz import Principal, require_role, require_scope
from app.core.tenancy import active_org, ensure_member, ensure_task
from app.db.session import get_db
from app.models import Agent, Member
from app.runtime import openclaw_protocol as ocp
from app.runtime.factory import get_runtime
from app.runtime.openclaw_native import NativeOpenClawRuntime, OpenClawToolDenied
from app.services import agent_dispatch, openclaw_alignment as align

router = APIRouter(prefix="/v19", tags=["v19-openclaw"])

READ = "company.context:read"
WRITE = "company.runtime:write"


def writer(minimum_role: str = "member"):
    """Humans are checked by role, API keys by scope (same rule as v18)."""
    def dep(principal: Principal = Depends(require_scope(WRITE))) -> Principal:
        if principal.auth_type != "api_key":
            return require_role(minimum_role)(principal)
        return principal
    return dep


# --------------------------------------------------------------------------- models

class BindIn(BaseModel):
    member_id: int
    runtime_agent_id: str = Field(min_length=1, max_length=120)


class StartIn(BaseModel):
    instructions: str | None = Field(default=None, max_length=4000)


class AbortIn(BaseModel):
    back_to: str = "todo"


class ToolInvokeIn(BaseModel):
    tool: str = Field(min_length=1, max_length=120)
    args: dict = Field(default_factory=dict)
    session_key: str | None = None
    agent_id: str | None = None
    idempotency_key: str | None = None


# --------------------------------------------------------------------------- protocol

@router.get("/openclaw/protocol")
def protocol(principal: Principal = Depends(require_scope(READ))):
    """What contract this deployment speaks, and where the old one was wrong."""
    return {
        "runtime": align.runtime_descriptor(),
        "methods": {
            "session_control": [
                ocp.M_SESSIONS_LIST, ocp.M_SESSIONS_CREATE, ocp.M_SESSIONS_DESCRIBE,
                ocp.M_SESSIONS_ABORT, ocp.M_SESSIONS_MESSAGES_SUBSCRIBE,
                ocp.M_SESSIONS_MESSAGES_UNSUBSCRIBE,
            ],
            "chat": [ocp.M_CHAT_SEND, ocp.M_CHAT_ABORT, ocp.M_CHAT_HISTORY],
            "system": [ocp.M_STATUS],
        },
        "events": [
            ocp.E_CHAT, ocp.E_SESSION_MESSAGE, ocp.E_SESSION_OPERATION,
            ocp.E_SESSION_TOOL, ocp.E_SESSIONS_CHANGED,
        ],
        "session_keys": {
            "main": ocp.main_session_key("<agentId>"),
            "company_task": ocp.task_session_key("<agentId>", "<taskId>"),
        },
        "upstream": "https://github.com/openclaw/openclaw",
    }


@router.get("/openclaw/health")
async def health(principal: Principal = Depends(require_scope(READ))):
    runtime = get_runtime()
    return {"runtime": align.runtime_descriptor(), "health": await runtime.health()}


# --------------------------------------------------------------------------- roster

@router.get("/openclaw/agents")
async def gateway_agents(principal: Principal = Depends(require_scope(READ))):
    runtime = get_runtime()
    if not isinstance(runtime, NativeOpenClawRuntime):
        return {"mode": align.runtime_descriptor()["mode"], "agents": [], "native": False}
    try:
        agents = await runtime.list_agents()
    except Exception as exc:  # noqa: BLE001 - surface gateway trouble as 502
        raise HTTPException(status_code=502, detail=f"OpenClaw gateway unreachable: {exc}")
    return {"mode": "native", "native": True, "agents": agents}


@router.get("/openclaw/seats")
def seats(db: Session = Depends(get_db), principal: Principal = Depends(require_scope(READ))):
    return {"seats": align.company_agent_index(db, active_org(principal))}


@router.post("/openclaw/reconcile")
async def reconcile(db: Session = Depends(get_db), principal: Principal = Depends(writer("manager"))):
    """Compare the company roster with the gateway and flag drift."""
    runtime = get_runtime()
    gateway_agents_list: list[dict] = []
    if isinstance(runtime, NativeOpenClawRuntime):
        try:
            gateway_agents_list = await runtime.list_agents()
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=f"OpenClaw gateway unreachable: {exc}")
    return align.reconcile(db, active_org(principal), gateway_agents_list)


@router.post("/openclaw/bind")
def bind(body: BindIn, db: Session = Depends(get_db), principal: Principal = Depends(writer("manager"))):
    ensure_member(db, body.member_id, principal)
    try:
        agent = align.bind_seat(db, active_org(principal), body.member_id, body.runtime_agent_id.strip())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {
        "agent_id": agent.id,
        "member_id": agent.member_id,
        "runtime_agent_id": agent.runtime_agent_id,
        "main_session_key": ocp.main_session_key(agent.runtime_agent_id),
    }


# --------------------------------------------------------------------------- task runs

@router.post("/tasks/{task_id}/start")
async def start_task(task_id: int, body: StartIn | None = None, db: Session = Depends(get_db),
                     principal: Principal = Depends(writer("member"))):
    """Hand a task to its agent's OpenClaw session and move it to in_progress."""
    task = ensure_task(db, task_id, principal)
    if body is not None and body.instructions:
        # Extra instructions are appended to the stored description so the brief
        # the agent receives is the same text a human can read on the task.
        task.description = f"{task.description or ''}\n\n{body.instructions}".strip()
        db.add(task)
        db.commit()
        db.refresh(task)
    try:
        task = await agent_dispatch.dispatch_task(db, task)
    except agent_dispatch.DispatchError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"OpenClaw dispatch failed: {exc}")
    return {
        "task_id": task.id,
        "status": task.status,
        "run_id": task.runtime_run_id,
        "session_key": task.runtime_session_key,
    }


@router.post("/tasks/{task_id}/abort")
async def abort_task(task_id: int, body: AbortIn | None = None, db: Session = Depends(get_db),
                     principal: Principal = Depends(writer("member"))):
    task = ensure_task(db, task_id, principal)
    try:
        return await agent_dispatch.abort_task(db, task, back_to=(body.back_to if body else "todo"))
    except agent_dispatch.DispatchError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"OpenClaw abort failed: {exc}")


@router.get("/tasks/{task_id}/transcript")
async def transcript(task_id: int, limit: int = 50, db: Session = Depends(get_db),
                     principal: Principal = Depends(require_scope(READ))):
    """Conversation of the task's OpenClaw session, when the runtime supports it."""
    task = ensure_task(db, task_id, principal)
    if not task.runtime_session_key:
        return {"task_id": task.id, "session_key": None, "messages": []}
    runtime = get_runtime()
    if not isinstance(runtime, NativeOpenClawRuntime):
        return {"task_id": task.id, "session_key": task.runtime_session_key, "messages": [], "native": False}
    try:
        history = await runtime.history(task.runtime_session_key, limit=min(max(limit, 1), 200))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"OpenClaw history failed: {exc}")
    return {"task_id": task.id, "session_key": task.runtime_session_key, "native": True, **history}


# --------------------------------------------------------------------------- tools bridge

@router.post("/openclaw/tools/invoke")
async def tools_invoke(body: ToolInvokeIn, db: Session = Depends(get_db),
                       principal: Principal = Depends(writer("admin"))):
    """Call one OpenClaw tool without spending a full agent turn.

    Admin-only on purpose: upstream treats a shared-secret bearer as full
    operator access, so this endpoint is effectively operator-level power.
    """
    if principal.auth_type == "api_key":
        # Agents must go through their own session tools, not the operator bridge.
        raise HTTPException(status_code=403, detail="Tool passthrough is restricted to human admins")
    if body.tool in ocp.HTTP_DENIED_TOOLS:
        raise HTTPException(
            status_code=403,
            detail=f"Tool '{body.tool}' is on the OpenClaw gateway deny list and cannot be called over HTTP",
        )
    runtime = get_runtime()
    if not isinstance(runtime, NativeOpenClawRuntime):
        raise HTTPException(status_code=409, detail="Tool passthrough requires OPENCLAW_MODE=native")

    agent_id = body.agent_id
    if agent_id:
        owned = (
            db.query(Agent)
            .join(Member, Agent.member_id == Member.id)
            .filter(Member.organization_id == active_org(principal), Agent.runtime_agent_id == agent_id)
            .first()
        )
        if owned is None:
            raise HTTPException(status_code=404, detail="No agent seat in this organization is bound to that agentId")
    try:
        result = await runtime.invoke_tool(
            body.tool, args=body.args, session_key=body.session_key,
            agent_id=agent_id, idempotency_key=body.idempotency_key,
        )
    except OpenClawToolDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"OpenClaw tool invoke failed: {exc}")
    return result
