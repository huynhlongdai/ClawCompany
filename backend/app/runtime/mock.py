import asyncio
import uuid
from app.runtime.base import AgentRuntime, RuntimeRun

class MockOpenClawRuntime(AgentRuntime):
    def __init__(self):
        self.runs: dict[str, dict] = {}

    async def create_agent(self, runtime_agent_id: str, config: dict) -> dict:
        return {"id": runtime_agent_id, "status": "created", "config": config}

    async def run_agent(self, runtime_agent_id: str, input_text: str, metadata: dict | None = None, session_key: str | None = None) -> RuntimeRun:
        task_id = f"task_{uuid.uuid4().hex[:10]}"
        run_id = f"run_{uuid.uuid4().hex[:10]}"
        session_key = session_key or f"session_{runtime_agent_id}_{uuid.uuid4().hex[:8]}"
        self.runs[run_id] = {"agent_id": runtime_agent_id, "input": input_text, "metadata": metadata or {}, "session_key": session_key}
        return RuntimeRun(task_id=task_id, run_id=run_id, session_key=session_key, status="queued", raw=self.runs[run_id])

    async def cancel_run(self, run_id: str) -> dict:
        return {"run_id": run_id, "status": "cancelled"}

    async def health(self) -> dict:
        return {"provider": "openclaw", "mode": "mock", "status": "healthy"}

    async def stream_run(self, run_id: str):
        context = self.runs.get(run_id, {})
        text = str(context.get("input") or "")
        events = [
            {"type": "run.started", "runId": run_id, "progress": 0},
            {"type": "run.progress", "runId": run_id, "progress": 25, "message": "Planning"},
            {"type": "run.progress", "runId": run_id, "progress": 60, "message": "Executing"},
            {"type": "run.progress", "runId": run_id, "progress": 90, "message": "Reviewing"},
            {"type": "run.completed", "runId": run_id, "progress": 100, "result": {"ok": True, "output": f"Mock OpenClaw response for: {text[:180]}"}},
        ]
        for event in events:
            await asyncio.sleep(0.05)
            yield event
