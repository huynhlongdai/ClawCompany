"""Deprecated dispatch entry point, kept as a thin shim (v21).

This module used to own task dispatch. It set task.status = "running", a value
that is not in the board vocabulary, so any task dispatched through the older
callers (api/tasks.py, services/orchestration.py, services/nina_planner.py,
tasks/runtime.py) silently fell out of the Kanban transition table. It also let
the runtime choose the session key, so company work landed in the agent's main
chat next to the operator's own conversation.

Rather than migrate five call sites by hand and risk missing one, the function
now delegates to services.agent_dispatch. Every caller gets per-task sessions,
in_progress status, metering and company events for free, and there is exactly
one dispatch implementation to reason about.

New code should import app.services.agent_dispatch directly.
"""

from __future__ import annotations

import warnings

from sqlalchemy.orm import Session

from app.models import Task
from app.services.agent_dispatch import DispatchError, dispatch_task as _dispatch_task

__all__ = ["dispatch_task", "DispatchError"]


async def dispatch_task(db: Session, task: Task) -> Task:
    """Dispatch a task through the v19 pipeline.

    DispatchError subclasses ValueError, which is what the old callers already
    caught, so this shim does not change their error handling.
    """
    warnings.warn(
        "services.tasks.dispatch_task is deprecated; use services.agent_dispatch.dispatch_task",
        DeprecationWarning,
        stacklevel=2,
    )
    return await _dispatch_task(db, task)
