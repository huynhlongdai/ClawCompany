from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, AsyncIterator

@dataclass
class RuntimeRun:
    task_id: str
    run_id: str
    session_key: str
    status: str
    raw: dict[str, Any]

class AgentRuntime(ABC):
    @abstractmethod
    async def create_agent(self, runtime_agent_id: str, config: dict) -> dict: ...

    @abstractmethod
    async def run_agent(self, runtime_agent_id: str, input_text: str, metadata: dict | None = None, session_key: str | None = None) -> RuntimeRun: ...

    @abstractmethod
    async def cancel_run(self, run_id: str) -> dict: ...

    @abstractmethod
    async def health(self) -> dict: ...

    @abstractmethod
    async def stream_run(self, run_id: str) -> AsyncIterator[dict]: ...
