import asyncio
import json
import uuid
from typing import AsyncIterator
import websockets
from app.core.config import settings
from app.runtime.base import AgentRuntime, RuntimeRun

class OpenClawGatewayRuntime(AgentRuntime):
    """Version-isolated OpenClaw Gateway adapter.

    RPC names are environment-configurable so Company Core does not depend on one
    OpenClaw release. Set the OPENCLAW_RPC_* values to the exact Gateway contract
    exposed by the OpenClaw build you deploy.
    """
    def __init__(self):
        self.url = settings.openclaw_gateway_ws
        self.token = settings.openclaw_api_token
        self.timeout = settings.openclaw_timeout_seconds

    def _headers(self):
        return {"Authorization": f"Bearer {self.token}"} if self.token else None

    async def _rpc(self, method: str, params: dict) -> dict:
        request_id = str(uuid.uuid4())
        payload = {"id": request_id, "method": method, "params": params}
        async with websockets.connect(self.url, additional_headers=self._headers()) as ws:
            await ws.send(json.dumps(payload))
            while True:
                raw = await asyncio.wait_for(ws.recv(), timeout=self.timeout)
                msg = json.loads(raw)
                if str(msg.get("id")) == request_id:
                    if msg.get("error"):
                        raise RuntimeError(msg["error"])
                    return msg.get("result") or msg

    async def create_agent(self, runtime_agent_id: str, config: dict) -> dict:
        return await self._rpc(settings.openclaw_rpc_create_agent, {"agentId": runtime_agent_id, **config})

    async def run_agent(self, runtime_agent_id: str, input_text: str, metadata: dict | None = None, session_key: str | None = None) -> RuntimeRun:
        result = await self._rpc(settings.openclaw_rpc_run_agent, {
            "agentId": runtime_agent_id,
            "input": input_text,
            "metadata": metadata or {},
            **({"sessionKey": session_key} if session_key else {}),
        })
        return RuntimeRun(
            task_id=str(result.get("taskId") or result.get("task_id") or ""),
            run_id=str(result.get("runId") or result.get("run_id") or ""),
            session_key=str(result.get("sessionKey") or result.get("session_key") or ""),
            status=str(result.get("status") or "queued"),
            raw=result,
        )

    async def cancel_run(self, run_id: str) -> dict:
        return await self._rpc(settings.openclaw_rpc_cancel_run, {"runId": run_id})

    async def health(self) -> dict:
        try:
            result = await self._rpc(settings.openclaw_rpc_gateway_status, {})
            return {"provider": "openclaw", "mode": "gateway", "status": "healthy", "result": result}
        except Exception as exc:
            return {"provider": "openclaw", "mode": "gateway", "status": "unhealthy", "error": str(exc)}

    async def stream_run(self, run_id: str) -> AsyncIterator[dict]:
        """Subscribe and forward events for a single run.

        The subscribe method name and event key names are configurable. This keeps
        the adapter usable across OpenClaw versions without leaking protocol details.
        """
        request_id = str(uuid.uuid4())
        payload = {"id": request_id, "method": settings.openclaw_rpc_subscribe_run, "params": {"runId": run_id}}
        async with websockets.connect(self.url, additional_headers=self._headers()) as ws:
            await ws.send(json.dumps(payload))
            while True:
                raw = await asyncio.wait_for(ws.recv(), timeout=max(self.timeout, 60))
                msg = json.loads(raw)
                # Ignore the subscription acknowledgement, then forward matching events.
                if str(msg.get("id")) == request_id and msg.get("error"):
                    raise RuntimeError(msg["error"])
                event = msg.get("event") if isinstance(msg.get("event"), dict) else msg
                event_run = event.get(settings.openclaw_event_run_id_key)
                if event_run is None or str(event_run) == str(run_id):
                    yield event
                    typ = str(event.get(settings.openclaw_event_type_key) or "")
                    if typ in {"run.completed", "run.failed", "run.cancelled", "completed", "failed", "cancelled"}:
                        break
