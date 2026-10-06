"""M1: bắt kịp một lượt đã xong trong lúc không ai nghe.

Follower chỉ đổi trạng thái task khi thấy frame cuối (``chat`` state
``final``). Gắn muộn — sau restart, qua ``POST /runtime/resume``, hay khi lượt
xong trước lúc subscribe — thì frame đó đã trôi qua và task kẹt ở
``in_progress`` mãi, chi phí của lượt cũng không được ghi. Đo trên gateway thật
2026.9.8 (task 5, e2e4): agent đã trả lời, resume trả 200, task vẫn kẹt.

Nguồn sự thật dùng ở đây đều đo được trên gateway thật:

- ``sessions.describe {key}`` → ``session.status`` (``done`` khi lượt xong),
  ``session.lastRunId``, ``session.abortedLastRun``.
- ``chat.history`` → message assistant có ``usage`` và ``__openclaw.id`` — trùng
  ``messageId`` của ``session.message`` trên stream, nên ghi chi phí ở đây
  không bao giờ trùng với ghi từ stream (``record_message_usage`` khử trùng
  theo message_id).

Chỉ hành động khi ``lastRunId`` đúng là run của task: phiên ``done`` của lượt
TRƯỚC không được phép đóng lượt hiện tại. Không bao giờ raise.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import Agent, Task
from app.runtime import openclaw_protocol as ocp
from app.services import cost_ledger

# Trạng thái phiên (sessions.describe) → state của frame cuối (TERMINAL_STATUS).
DONE_STATES = {"done": "final", "completed": "final", "failed": "error", "error": "error",
               "aborted": "aborted", "cancelled": "aborted"}


def _session_terminal(session: dict) -> str | None:
    status = str(session.get("status") or "").lower()
    if session.get("abortedLastRun") is True and status in DONE_STATES:
        return "aborted"
    return DONE_STATES.get(status)


def history_usage_raw(msg: dict, session_key: str) -> dict | None:
    """Dựng lại khung ``session.message`` từ một message của ``chat.history``."""
    if not isinstance(msg, dict) or msg.get("role") != "assistant":
        return None
    meta = msg.get("__openclaw") if isinstance(msg.get("__openclaw"), dict) else {}
    message_id = str(meta.get("id") or "")
    if not message_id:
        return None
    return {"messageId": message_id, "runId": str(meta.get("runId") or ""),
            "sessionKey": session_key, "message": msg}


async def catch_up(db: Session, runtime, state, apply_terminal) -> dict:
    """Trả ``{"terminal": bool, "recorded": n, ...}``; ``terminal`` thì follower dừng."""
    out = {"terminal": False, "recorded": 0, "status": "", "skipped": ""}
    try:
        task = db.get(Task, state.task_id) if state.task_id else None
        if task is None or task.status != "in_progress" or not task.runtime_run_id:
            out["skipped"] = "task không chờ lượt nào"
            return out
        if not hasattr(runtime, "rpc"):
            out["skipped"] = "runtime không phải gateway thật"
            return out
        described = await runtime.rpc(ocp.M_SESSIONS_DESCRIBE, {"key": state.session_key})
        session = described.get("session") if isinstance(described.get("session"), dict) else {}
        out["status"] = str(session.get("status") or "")
        if str(session.get("lastRunId") or "") != task.runtime_run_id:
            out["skipped"] = "lượt trên gateway không phải lượt của task"
            return out
        terminal = _session_terminal(session)
        if terminal is None:
            out["skipped"] = "lượt còn đang chạy"
            return out
        agent = (db.query(Agent).filter(Agent.member_id == task.assignee_member_id).first()
                 if task.assignee_member_id else None)
        history = await runtime.history(state.session_key, limit=200)
        for msg in history.get("messages") or []:
            raw = history_usage_raw(msg, state.session_key)
            if raw is None or raw["runId"] != task.runtime_run_id:
                continue
            if cost_ledger.record_message_usage(
                    db, organization_id=state.organization_id, task=task,
                    agent_id=agent.id if agent else None,
                    session_key=state.session_key, raw=raw) is not None:
                out["recorded"] += 1
        apply_terminal(db, task, state, {"state": terminal, "terminal": True,
                                         "type": "chat", "source": "catch_up"})
        out["terminal"] = True
    except Exception as exc:  # noqa: BLE001 - bắt kịp hỏng thì vẫn nghe stream sống
        out["skipped"] = f"error: {str(exc)[:200]}"
    return out
