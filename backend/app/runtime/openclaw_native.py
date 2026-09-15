"""Adapter that speaks the real OpenClaw Gateway protocol.

The older ``OpenClawGatewayRuntime`` was written against a guessed contract
(``agents.create`` / ``agents.run`` / ``runs.subscribe``). Those RPCs do not
exist upstream. This adapter implements the actual contract documented in
``openclaw_protocol.py`` and is selected with ``OPENCLAW_MODE=native``.

Design choices worth stating:

* One WebSocket connection per call, like the legacy adapter. The gateway is a
  local control plane, so reconnect cost is small and a per-call connection
  avoids owning a background reconnect loop inside a request handler.
* ``create_agent`` does **not** create anything upstream. OpenClaw agents are
  operator-owned config entries. We verify the agent exists and report that
  honestly instead of pretending to provision it.
* A run id is only known once the gateway reports one. We return whatever the
  send result carries and fall back to the session key, which is always
  addressable for abort.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any, AsyncIterator

import httpx
import websockets

from app.core.config import settings
from app.runtime import openclaw_protocol as ocp
from app.runtime.base import AgentRuntime, RuntimeRun


class OpenClawProtocolError(RuntimeError):
    pass


class OpenClawToolDenied(RuntimeError):
    pass


class NativeOpenClawRuntime(AgentRuntime):
    def __init__(self) -> None:
        self.url = settings.openclaw_gateway_ws
        self.http_url = settings.openclaw_gateway_http or _ws_to_http(self.url)
        self.token = settings.openclaw_api_token
        self.timeout = settings.openclaw_timeout_seconds
        self.client_name = settings.openclaw_client_name
        self.protocol_version = settings.openclaw_protocol_version

    # -- transport ---------------------------------------------------------

    def _headers(self) -> dict[str, str] | None:
        return {"Authorization": f"Bearer {self.token}"} if self.token else None

    def scopes(self) -> list[str]:
        """Narrow by default; approvals only when the operator opts in (v21)."""
        scopes = list(ocp.COMPANY_SCOPES)
        if settings.openclaw_request_approvals_scope and ocp.SCOPE_APPROVALS not in scopes:
            scopes.append(ocp.SCOPE_APPROVALS)
        return scopes

    def _connect_frame(self) -> dict[str, Any]:
        """Handshake frame: declare role and the narrow scope set we need."""
        return {
            "type": "connect",
            "role": ocp.ROLE_OPERATOR,
            "scopes": self.scopes(),
            "protocolVersion": self.protocol_version,
            "client": {"name": self.client_name, "version": settings.app_version},
            **({"token": self.token} if self.token else {}),
        }

    async def _handshake(self, ws) -> dict[str, Any]:
        await ws.send(json.dumps(self._connect_frame()))
        raw = await asyncio.wait_for(ws.recv(), timeout=self.timeout)
        hello = json.loads(raw)
        if hello.get("error"):
            raise OpenClawProtocolError(str(hello["error"]))
        return hello

    async def _rpc(self, method: str, params: dict | None = None) -> dict[str, Any]:
        request_id = str(uuid.uuid4())
        async with websockets.connect(self.url, additional_headers=self._headers()) as ws:
            await self._handshake(ws)
            await ws.send(json.dumps({"id": request_id, "method": method, "params": params or {}}))
            while True:
                raw = await asyncio.wait_for(ws.recv(), timeout=self.timeout)
                msg = json.loads(raw)
                if str(msg.get("id")) != request_id:
                    continue  # broadcast event arriving on the same socket
                if msg.get("error"):
                    raise OpenClawProtocolError(str(msg["error"]))
                result = msg.get("result")
                return result if isinstance(result, dict) else {"result": result}

    # -- AgentRuntime ------------------------------------------------------

    async def create_agent(self, runtime_agent_id: str, config: dict) -> dict:
        """Bind to an existing OpenClaw agent; never pretends to provision one."""
        roster = await self.list_agents()
        known = {str(a.get("id") or a.get("agentId")) for a in roster}
        if runtime_agent_id not in known:
            return {
                "id": runtime_agent_id,
                "status": "missing",
                "bound": False,
                "known_agents": sorted(known),
                "hint": f"Run `openclaw agents add {runtime_agent_id}` on the gateway host, then retry.",
            }
        return {"id": runtime_agent_id, "status": "bound", "bound": True, "config": config}

    async def run_agent(
        self,
        runtime_agent_id: str,
        input_text: str,
        metadata: dict | None = None,
        session_key: str | None = None,
    ) -> RuntimeRun:
        key = session_key or ocp.main_session_key(runtime_agent_id)
        meta = metadata or {}
        # sessions.create is idempotent enough for our use: adopting an existing
        # key is allowed upstream, and a failure here should not block the send.
        try:
            await self._rpc(
                ocp.M_SESSIONS_CREATE,
                {"key": key, "agentId": runtime_agent_id, "label": str(meta.get("label") or key)},
            )
        except OpenClawProtocolError:
            pass
        result = await self._rpc(
            ocp.M_CHAT_SEND,
            {
                "sessionKey": key,
                "agentId": runtime_agent_id,
                "message": input_text,
                "metadata": meta,
            },
        )
        run_id = str(result.get("runId") or result.get("run_id") or "")
        return RuntimeRun(
            task_id=str(meta.get("company_task_id") or result.get("messageId") or ""),
            run_id=run_id or key,
            session_key=str(result.get("sessionKey") or key),
            status=str(result.get("state") or result.get("status") or "running"),
            raw=result,
        )

    async def cancel_run(self, run_id: str) -> dict:
        """Abort by run id, or by session key when that is all we hold."""
        if run_id.startswith("agent:"):
            return await self._rpc(ocp.M_SESSIONS_ABORT, {"key": run_id})
        return await self._rpc(ocp.M_SESSIONS_ABORT, {"runId": run_id})

    async def health(self) -> dict:
        try:
            result = await self._rpc(ocp.M_STATUS, {})
            return {"provider": "openclaw", "mode": "native", "status": "healthy", "result": result}
        except Exception as exc:  # noqa: BLE001 - health must never raise
            return {"provider": "openclaw", "mode": "native", "status": "unhealthy", "error": str(exc)}

    async def stream_run(self, run_id: str) -> AsyncIterator[dict]:
        """Stream one run by subscribing to its session.

        Upstream subscriptions are per session, so the caller passes a session
        key (or a run id that we cannot resolve alone). Events for other runs on
        the same session are filtered out.
        """
        session_key = run_id if run_id.startswith("agent:") else ""
        if not session_key:
            raise OpenClawProtocolError(
                "stream_run needs a session key; OpenClaw subscriptions are per session, not per run"
            )
        request_id = str(uuid.uuid4())
        async with websockets.connect(self.url, additional_headers=self._headers()) as ws:
            await self._handshake(ws)
            await ws.send(
                json.dumps(
                    {
                        "id": request_id,
                        "method": ocp.M_SESSIONS_MESSAGES_SUBSCRIBE,
                        "params": {"sessionKey": session_key},
                    }
                )
            )
            while True:
                raw = await asyncio.wait_for(ws.recv(), timeout=max(self.timeout, 60))
                msg = json.loads(raw)
                if str(msg.get("id")) == request_id:
                    if msg.get("error"):
                        raise OpenClawProtocolError(str(msg["error"]))
                    continue  # subscription acknowledgement
                event = normalize_event(msg)
                if not event:
                    continue
                yield event
                if event.get("terminal"):
                    break

    # -- openclaw-specific surface ----------------------------------------

    async def list_agents(self) -> list[dict]:
        """Roster of configured agents, derived from the session index.

        Agent-qualified session keys carry the agent id, so the session list is
        a dependable roster source even on gateways that do not expose an
        agent-list method to our scope set.
        """
        result = await self._rpc(ocp.M_SESSIONS_LIST, {"limit": 200})
        rows = result.get("sessions") or result.get("items") or []
        agents: dict[str, dict] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            agent_id = str(row.get("agentId") or ocp.agent_id_from_session_key(str(row.get("key") or "")) or "")
            if not agent_id:
                continue
            entry = agents.setdefault(agent_id, {"id": agent_id, "sessions": 0, "active": False})
            entry["sessions"] += 1
            if row.get("hasActiveRun"):
                entry["active"] = True
        return sorted(agents.values(), key=lambda a: a["id"])

    async def invoke_tool(
        self,
        tool: str,
        args: dict | None = None,
        session_key: str | None = None,
        agent_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict:
        """Call POST /tools/invoke for a single tool, no agent turn.

        The gateway's own deny list is mirrored locally so a blocked tool fails
        with an explicit reason instead of an opaque 404.
        """
        if tool in ocp.HTTP_DENIED_TOOLS:
            raise OpenClawToolDenied(
                f"Tool '{tool}' is on the OpenClaw gateway HTTP deny list (host-mutating or control-plane surface)."
            )
        body: dict[str, Any] = {"tool": tool, "args": args or {}}
        if session_key:
            body["sessionKey"] = session_key
        if agent_id:
            body["agentId"] = agent_id
        if idempotency_key:
            body["idempotencyKey"] = idempotency_key
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.http_url.rstrip('/')}/tools/invoke",
                json=body,
                headers=self._headers() or {},
            )
        try:
            payload = response.json()
        except Exception:  # noqa: BLE001
            payload = {"ok": False, "error": {"type": "non_json", "message": response.text[:500]}}
        return {"status_code": response.status_code, **payload}

    async def respond_approval(
        self,
        *,
        request_id: str,
        decision: str,
        session_key: str = "",
    ) -> dict:
        """Answer an approval prompt the gateway raised (v21, corrected in v23).

        v21 shipped a guessed payload: ``sessionKey`` + ``requestId`` +
        ``approved: bool`` + ``note``. The upstream docs say otherwise, so v23
        sends what the gateway actually accepts:

        - the method is ``exec.approval.resolve`` and needs ``operator.approvals``;
        - approvals are resolved **by id**, not by session key;
        - the decision is three-valued (``allow-once`` / ``allow-always`` /
          ``deny``), not a boolean;
        - there is no resolution-reason field on the gateway record, so a note
          cannot be delivered and is kept local instead of being faked.

        The method name stays configurable. It is now documented rather than
        invented, which is why it has a default; that is the one difference
        from v21's refusal to guess.
        """
        method = settings.openclaw_approval_reply_method
        if not method:
            raise OpenClawProtocolError(
                "OPENCLAW_APPROVAL_REPLY_METHOD is unset; refusing to guess the approval RPC name"
            )
        if not settings.openclaw_request_approvals_scope:
            raise OpenClawProtocolError(
                "OPENCLAW_REQUEST_APPROVALS_SCOPE is off, so this connection never asked for "
                "operator.approvals; the gateway would reject the reply"
            )
        if decision not in ocp.APPROVAL_DECISIONS:
            raise OpenClawProtocolError(
                f"Decision must be one of {sorted(ocp.APPROVAL_DECISIONS)}, got {decision!r}"
            )
        # v35.1: kiểm chứng trực tiếp với schema upstream
        # packages/gateway-protocol/src/schema/exec-approvals.ts:
        #
        #   ExecApprovalResolveParamsSchema = closedObject({
        #     id, decision, reviewer?, grantExpiresInDays?
        #   })
        #
        # ``closedObject`` nghĩa là additionalProperties: false. Bản v23 gửi
        # thêm ``sessionKey`` "như một disambiguator", nhưng field đó không
        # nằm trong schema, nên MỌI lượt trả lời có session_key đều bị gateway
        # từ chối bằng INVALID_REQUEST trước khi tới handler. Bỏ hẳn.
        #
        # Lưu ý: ``kind: "exec"`` là của method hợp nhất ``approvals.resolve``
        # (ApprovalResolveParamsSchema), KHÔNG phải của exec.approval.resolve.
        # Thêm ``kind`` vào đây sẽ vi phạm closedObject theo chiều ngược lại.
        params: dict[str, Any] = {"id": request_id, "decision": decision}
        return await self._rpc(method, params)

    async def list_approvals(self, *, session_key: str = "") -> dict:
        """List approval prompts the gateway is holding (v24).

        The upstream docs tell clients to backfill with ``exec.approval.list``
        on connect and reconcile live events by approval id. Without this we
        only ever saw prompts raised while a follower happened to be attached.

        Same scope gate as answering: listing is an operator.approvals action,
        and a connection that never asked for the scope would be rejected.
        Note that complete, operator-wide enumeration is documented as needing
        ``operator.admin``, which ClawCompany never requests — so this returns
        what this connection is allowed to see, not everything that exists.
        """
        if not settings.openclaw_request_approvals_scope:
            raise OpenClawProtocolError(
                "OPENCLAW_REQUEST_APPROVALS_SCOPE is off, so this connection never asked for "
                "operator.approvals; the gateway would reject the listing"
            )
        # v35.1: handler upstream của exec.approval.list là
        # ``async ({ respond, client, context })`` -- không nhận params và
        # không có schema filter. Bộ lọc ``sessionKey`` mà v24 suy đoán không
        # tồn tại: gửi lên thì bị bỏ qua, và việc lọc phải làm ở phía
        # ClawCompany sau khi nhận danh sách.
        if session_key:
            LOG_SESSION_FILTER_UNSUPPORTED.add(session_key)
        return await self._rpc(ocp.M_EXEC_APPROVAL_LIST, {})

    async def history(self, session_key: str, limit: int = 50) -> dict:
        return await self._rpc(ocp.M_CHAT_HISTORY, {"sessionKey": session_key, "limit": limit})


def normalize_event(msg: dict) -> dict | None:
    """Flatten an upstream gateway frame into ClawCompany's event shape.

    ClawCompany persists runtime events with a ``type`` and optional
    ``progress``. OpenClaw emits typed families (``session.message``, ``chat``,
    ``session.tool``) whose lifecycle lives in a ``state`` field, so terminality
    is derived from that rather than from invented event names.
    """
    family = str(msg.get("event") or msg.get("type") or "")
    if not family:
        return None
    payload = msg.get("payload") if isinstance(msg.get("payload"), dict) else msg
    state = str(payload.get("state") or "")
    event = {
        "type": f"{family}.{state}" if state else family,
        "family": family,
        "state": state,
        "runId": payload.get("runId"),
        "sessionKey": payload.get("sessionKey"),
        "terminal": state in ocp.TERMINAL_STATES,
        "error": state in ocp.ERROR_STATES,
        "raw": payload,
    }
    text = payload.get("deltaText") or payload.get("message") or payload.get("text")
    if isinstance(text, str):
        event["content"] = text
    if state in ocp.ERROR_STATES:
        detail = payload.get("errorDetail") if isinstance(payload.get("errorDetail"), dict) else {}
        event["errorKind"] = payload.get("errorKind")
        event["errorMessage"] = payload.get("errorMessage")
        event["errorDetail"] = detail
    return event


def _ws_to_http(ws_url: str) -> str:
    if ws_url.startswith("wss://"):
        return "https://" + ws_url[len("wss://") :]
    if ws_url.startswith("ws://"):
        return "http://" + ws_url[len("ws://") :]
    return ws_url
