import asyncio
import pytest
from app.runtime.mock import MockOpenClawRuntime
from app.services.workflow_graph import validate_graph


def test_workflow_graph_accepts_dag():
    validate_graph({
        "nodes": [{"id": "a"}, {"id": "b"}, {"id": "c"}],
        "edges": [{"source": "a", "target": "b"}, {"source": "b", "target": "c"}],
    })


def test_workflow_graph_rejects_cycle():
    with pytest.raises(ValueError):
        validate_graph({
            "nodes": [{"id": "a"}, {"id": "b"}],
            "edges": [{"source": "a", "target": "b"}, {"source": "b", "target": "a"}],
        })


def test_mock_runtime_keeps_customer_session():
    async def run():
        runtime = MockOpenClawRuntime()
        first = await runtime.run_agent("mia", "hello")
        second = await runtime.run_agent("mia", "continue", session_key=first.session_key)
        assert second.session_key == first.session_key
        events = [event async for event in runtime.stream_run(second.run_id)]
        assert events[-1]["type"] == "run.completed"
        assert "continue" in events[-1]["result"]["output"]
    asyncio.run(run())
