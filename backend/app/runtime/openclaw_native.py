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
import hashlib
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

    def _request_frame(self, method: str, params: dict | None = None,
                       request_id: str | None = None) -> dict[str, Any]:
        """Một request frame hợp lệ theo ``RequestFrameSchema``.

        v35.1 -- sửa lỗi chặn toàn bộ. Upstream
        ``packages/gateway-protocol/src/schema/frames.ts``:

            RequestFrameSchema = closedObject({
              type: Type.Literal("req"), id, method, params?, ...
            })

        ``type`` là literal BẮT BUỘC. v19-v35 gửi frame không có ``type``, nên
        gateway đóng kết nối với 1008 (policy violation, "invalid request
        frame") ngay ở frame đầu tiên. Đo được bằng một gateway
        OpenClaw 2026.9.4 thật: xem ``_reports/native-probe-before-fix.log``.
        """
        return {
            "type": "req",
            "id": request_id or str(uuid.uuid4()),
            "method": method,
            "params": params or {},
        }

    def _connect_params(self) -> dict[str, Any]:
        """Params của ``connect`` theo ``ConnectParamsSchema`` (closedObject).

        Những chỗ bản cũ sai:

        * ``connect`` là một METHOD trong request frame, không phải một frame
          riêng có ``type: "connect"``.
        * phiên bản giao thức khai bằng ``minProtocol``/``maxProtocol``, không
          phải ``protocolVersion``.
        * ``client`` yêu cầu ``id``, ``version``, ``platform``, ``mode`` --
          không có ``name``. Và ``id`` là ENUM ĐÓNG
          (``GATEWAY_CLIENT_IDS`` trong ``packages/gateway-protocol/src/client-info.ts``),
          nên chuỗi tự đặt như "clawcompany" bị từ chối. Một control plane
          backend đúng nghĩa là ``gateway-client`` + mode ``backend``; tên
          riêng của ClawCompany đi vào ``displayName``, trường chỉ dùng để
          chẩn đoán.
        * token nằm trong ``auth.token``, không ở cấp cao nhất. Header
          ``Authorization`` lúc upgrade HTTP không thay được field này.
        """
        params: dict[str, Any] = {
            "minProtocol": self.protocol_version,
            "maxProtocol": self.protocol_version,
            "client": {
                "id": ocp.CLIENT_ID,
                "displayName": self.client_name,
                "version": settings.app_version,
                "platform": "linux",
                "mode": ocp.CLIENT_MODE,
            },
            "role": ocp.ROLE_OPERATOR,
            "scopes": self.scopes(),
        }
        if self.token:
            params["auth"] = {"token": self.token}
        return params

    async def _handshake(self, ws) -> dict[str, Any]:
        """Gửi ``connect`` và đọc ``hello-ok``.

        Upstream trả về một frame ``{"type": "hello-ok", ...}`` (xem
        ``HelloOkSchema``), không phải một response frame thường, nên ở đây
        chấp nhận cả hai hình dạng thay vì ghim một cái.
        """
        request_id = str(uuid.uuid4())
        await ws.send(json.dumps(self._request_frame("connect", self._connect_params(), request_id)))
        # Không đọc đúng một frame rồi tin đó là hello-ok: gateway thật có thể
        # chen event/tick vào trước. Đọc tới khi thấy frame mang đúng id của
        # lời gọi connect (đo được với OpenClaw 2026.9.4).
        while True:
            raw = await asyncio.wait_for(ws.recv(), timeout=self.timeout)
            hello = json.loads(raw)
            if hello.get("id") is not None and str(hello.get("id")) != request_id:
                continue
            if hello.get("error"):
                raise OpenClawProtocolError(str(hello["error"]))
            if hello.get("ok") is False:
                raise OpenClawProtocolError(f"gateway refused the handshake: {hello}")
            if hello.get("id") is None and hello.get("type") not in ("hello-ok", "res"):
                continue  # event frame, chưa phải trả lời handshake
            return hello

    @staticmethod
    def _read_response(msg: dict[str, Any]) -> dict[str, Any]:
        """Bóc một ``ResponseFrameSchema``.

            ResponseFrameSchema = closedObject({
              type: "res", id, ok: boolean, payload?, error?
            })

        Kết quả nằm ở ``payload`` kèm cờ ``ok``. Bản cũ đọc ``result`` -- một
        khoá không tồn tại trong giao thức -- nên kể cả khi frame được chấp
        nhận thì mọi lời gọi cũng trả về rỗng, và ``run_agent`` sẽ bịa ra
        ``status="running"`` với ``run_id=""``. Cũng vậy, bản cũ chỉ kiểm
        ``error`` nên một lỗi có ``ok: false`` mà không kèm ``error`` sẽ bị
        đọc thành thành công.
        """
        if msg.get("error"):
            raise OpenClawProtocolError(str(msg["error"]))
        if msg.get("ok") is False:
            raise OpenClawProtocolError(f"gateway returned ok=false: {msg}")
        payload = msg.get("payload", msg.get("result"))
        return payload if isinstance(payload, dict) else {"payload": payload}

    async def _rpc(self, method: str, params: dict | None = None) -> dict[str, Any]:
        request_id = str(uuid.uuid4())
        async with websockets.connect(self.url, additional_headers=self._headers()) as ws:
            await self._handshake(ws)
            await ws.send(json.dumps(self._request_frame(method, params, request_id)))
            while True:
                raw = await asyncio.wait_for(ws.recv(), timeout=self.timeout)
                msg = json.loads(raw)
                if str(msg.get("id")) != request_id:
                    continue  # broadcast event arriving on the same socket
                return self._read_response(msg)

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
        # v35.1: ChatSendParamsSchema là closedObject,
        # required = ["sessionKey", "message", "idempotencyKey"], và KHÔNG có
        # thuộc tính "metadata". Bản cũ gửi metadata và thiếu idempotencyKey,
        # nên gateway thật trả:
        #   INVALID_REQUEST: must have required property 'idempotencyKey';
        #   at root: unexpected property 'metadata'
        # Tức đường gửi việc chính của cả sản phẩm chưa từng chạy được.
        # Đo với OpenClaw 2026.9.4 -- xem _reports/native-probe-after-fix.log.
        #
        # idempotencyKey nên ổn định theo *lần gửi logic*, không phải ngẫu
        # nhiên mỗi lần, vì mục đích của nó là để retry transport không sinh
        # hai lượt chạy. Có task id thì khoá theo task; không thì đành dùng
        # uuid và nói thẳng là lượt này không dedupe được.
        # Khoá idempotency phải ổn định theo MỘT LẦN GỬI LOGIC, không theo
        # task. Bản v35.1 khoá theo task id, nên lượt gửi thứ hai cho cùng
        # task — một chỉ thị khác hẳn — bị gateway chặn:
        #   INVALID_REQUEST: This message ID was already used for different
        #   input (reason: chat-request-conflict)
        # Đo được khi gửi lượt thứ hai vào task #5. Nay khoá gồm cả vân tay
        # nội dung: gửi lại đúng chữ đó thì dedupe (đúng mục đích của
        # idempotency), còn chỉ thị mới là một lần gửi mới.
        task_ref = str(meta.get("company_task_id") or "")
        fingerprint = hashlib.sha256(input_text.encode("utf-8")).hexdigest()[:12]
        idempotency_key = (
            f"clawcompany:{key}:task-{task_ref}:{fingerprint}" if task_ref
            else f"clawcompany:{key}:{fingerprint}:{uuid.uuid4().hex[:8]}"
        )
        result = await self._rpc(
            ocp.M_CHAT_SEND,
            {
                "sessionKey": key,
                "agentId": runtime_agent_id,
                "message": input_text,
                "idempotencyKey": idempotency_key,
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
                # v35.1: tham số là ``key``, không phải ``sessionKey``.
                # Upstream dùng ``{ key: ... }`` nhất quán ở
                # src/gateway/session-message-events.test.ts,
                # packages/gateway-client, client Android/Swift và bench script.
                # Schema đóng ⇒ bản cũ bị từ chối, nên /app/live-runs và toàn
                # bộ v20-v26 (follower, lease, takeover, reconcile) chưa từng
                # nhận được một event nào từ gateway thật.
                # Nghịch lý phải nhớ: ``chat.send`` thì ĐÚNG là ``sessionKey``.
                json.dumps(
                    self._request_frame(
                        ocp.M_SESSIONS_MESSAGES_SUBSCRIBE,
                        {"key": session_key},
                        request_id,
                    )
                )
            )
            while True:
                raw = await asyncio.wait_for(ws.recv(), timeout=max(self.timeout, 60))
                msg = json.loads(raw)
                if str(msg.get("id")) == request_id:
                    self._read_response(msg)  # raises on error / ok=false
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
