import asyncio, json, os, sys
sys.path.insert(0, ".")
os.environ.setdefault("DATABASE_URL", "sqlite:///./_probe.db")
os.environ["OPENCLAW_MODE"] = "native"
os.environ["OPENCLAW_GATEWAY_WS"] = "ws://127.0.0.1:18789"
from app.runtime.openclaw_native import NativeOpenClawRuntime

async def main():
    rt = NativeOpenClawRuntime()
    try:
        run = await rt.run_agent("dev", "Say OK and stop.", metadata={"company_task_id": 4242, "label": "probe"})
        print("run_agent ->", json.dumps({"run_id": run.run_id, "session_key": run.session_key,
                                          "status": run.status, "task_id": run.task_id}, ensure_ascii=False))
        print("raw keys:", sorted(run.raw)[:12])
    except Exception as exc:
        print("run_agent FAIL:", type(exc).__name__, str(exc)[:400])

asyncio.run(main())
