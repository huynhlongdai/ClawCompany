"""Dò adapter native của ClawCompany với một gateway OpenClaw thật."""
import asyncio, json, os, sys
sys.path.insert(0, ".")
os.environ.setdefault("DATABASE_URL", "sqlite:///./_probe.db")
os.environ["OPENCLAW_MODE"] = "native"
os.environ["OPENCLAW_GATEWAY_WS"] = "ws://127.0.0.1:18789"

from app.runtime.openclaw_native import NativeOpenClawRuntime, OpenClawProtocolError

async def main():
    rt = NativeOpenClawRuntime()
    print("url:", rt.url)
    print("--- health() ---")
    print(json.dumps(await rt.health(), ensure_ascii=False)[:600])
    print("--- list_agents() ---")
    try:
        print(json.dumps(await rt.list_agents(), ensure_ascii=False)[:400])
    except Exception as exc:
        print("FAIL:", type(exc).__name__, str(exc)[:300])

asyncio.run(main())
