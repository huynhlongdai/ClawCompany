"""Kiểm chứng end-to-end adapter native với gateway OpenClaw thật."""
import asyncio, json, os, sys
sys.path.insert(0, ".")
os.environ.setdefault("DATABASE_URL", "sqlite:///./_probe.db")
os.environ["OPENCLAW_MODE"] = "native"
os.environ["OPENCLAW_GATEWAY_WS"] = "ws://127.0.0.1:18789"
from app.runtime import openclaw_protocol as ocp
from app.runtime.openclaw_native import NativeOpenClawRuntime

async def main():
    rt = NativeOpenClawRuntime()
    print("1) status:", (await rt._rpc(ocp.M_STATUS, {})).get("runtimeVersion"))

    key = ocp.task_session_key("dev", 4242)
    print("2) session key:", key)
    try:
        created = await rt._rpc(ocp.M_SESSIONS_CREATE, {"key": key, "agentId": "dev", "label": "clawcompany probe"})
        print("   sessions.create ->", json.dumps(created, ensure_ascii=False)[:200])
    except Exception as exc:
        print("   sessions.create FAIL:", type(exc).__name__, str(exc)[:300])

    print("3) sessions.list:")
    lst = await rt._rpc(ocp.M_SESSIONS_LIST, {"limit": 20})
    rows = lst.get("sessions") or lst.get("items") or []
    print("   rows:", len(rows), [r.get("key") for r in rows if isinstance(r, dict)][:5])

    print("4) list_agents():", await rt.list_agents())

    print("5) sessions.messages.subscribe (tham số 'key'):")
    import websockets, uuid
    async with websockets.connect(rt.url) as ws:
        await rt._handshake(ws)
        rid = str(uuid.uuid4())
        await ws.send(json.dumps(rt._request_frame(ocp.M_SESSIONS_MESSAGES_SUBSCRIBE, {"key": key}, rid)))
        raw = await asyncio.wait_for(ws.recv(), timeout=20)
        msg = json.loads(raw)
        print("   ok=", msg.get("ok"), "payload=", json.dumps(msg.get("payload"), ensure_ascii=False)[:160])
        # và chứng minh tham số cũ bị từ chối
        rid2 = str(uuid.uuid4())
        await ws.send(json.dumps(rt._request_frame(ocp.M_SESSIONS_MESSAGES_SUBSCRIBE, {"sessionKey": key}, rid2)))
        raw2 = await asyncio.wait_for(ws.recv(), timeout=20)
        m2 = json.loads(raw2)
        print("   với 'sessionKey' (bản cũ): ok=", m2.get("ok"), "err=", str(m2.get("error"))[:160])

asyncio.run(main())
