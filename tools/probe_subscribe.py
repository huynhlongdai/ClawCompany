"""Chứng minh tham số subscribe: 'key' được chấp nhận, 'sessionKey' bị từ chối."""
import asyncio, json, os, sys, uuid
sys.path.insert(0, ".")
os.environ.setdefault("DATABASE_URL", "sqlite:///./_probe.db")
os.environ["OPENCLAW_MODE"] = "native"
os.environ["OPENCLAW_GATEWAY_WS"] = "ws://127.0.0.1:18789"
import websockets
from app.runtime import openclaw_protocol as ocp
from app.runtime.openclaw_native import NativeOpenClawRuntime

async def call(ws, rt, method, params):
    rid = str(uuid.uuid4())
    await ws.send(json.dumps(rt._request_frame(method, params, rid)))
    while True:
        msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=20))
        if str(msg.get("id")) != rid:
            continue
        return msg

async def main():
    rt = NativeOpenClawRuntime()
    key = ocp.task_session_key("dev", 4242)
    async with websockets.connect(rt.url) as ws:
        hello = await rt._handshake(ws)
        payload = hello.get("payload") or hello
        print("handshake:", payload.get("type"), "protocol", payload.get("protocol"),
              "| role", (payload.get("auth") or {}).get("role"),
              "| scopes", (payload.get("auth") or {}).get("scopes"))
        for params in ({"key": key}, {"sessionKey": key}):
            msg = await call(ws, rt, ocp.M_SESSIONS_MESSAGES_SUBSCRIBE, params)
            label = list(params)[0]
            err = msg.get("error") or {}
            print(f"subscribe {{{label}}}: ok={msg.get('ok')} "
                  f"code={err.get('code','-')} msg={str(err.get('message',''))[:90]}")

asyncio.run(main())
