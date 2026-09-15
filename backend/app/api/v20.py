"""v20 live-run API: long-lived session streams, auto-dispatch, approval bridge.

v19 made ClawCompany speak the real OpenClaw protocol. v20 makes a dispatched
task keep behaving like a real piece of work after the HTTP request ends:

- A follower keeps the session subscription open, persists every event, moves
  the task when the run finishes, and turns gateway permission prompts into
  rows in the company approval queue.
- Moving a task to `in_progress` can dispatch it automatically (opt-in via
  `OPENCLAW_AUTO_DISPATCH`), so the board is the control surface rather than a
  separate "start" button.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.authz import Principal, require_role, require_scope
from app.core.config import settings
from app.core.tenancy import active_org, ensure_project, ensure_task
from app.db.session import get_db
from app.models import Approval, RuntimeEvent
from app.services import agent_dispatch, workspace_ops as ops
from app.services.runtime_stream import supervisor

router = APIRouter(prefix="/v20", tags=["v20-live-runs"])

READ = "company.context:read"
WRITE = "company.runtime:write"


def writer(minimum_role: str = "member"):
    def dep(principal: Principal = Depends(require_scope(WRITE))) -> Principal:
        if principal.auth_type != "api_key":
            return require_role(minimum_role)(principal)
        return principal
    return dep


class FollowIn(BaseModel):
    session_key: str | None = Field(default=None, max_length=200)


class MoveIn(BaseModel):
    status: str
    dispatch: bool | None = None  # None = follow the server default


def _task_state(task) -> dict:
    return {"id": task.id, "project_id": task.project_id, "title": task.title,
            "status": task.status, "assignee_member_id": task.assignee_member_id,
            "runtime_run_id": task.runtime_run_id, "runtime_session_key": task.runtime_session_key}


# --------------------------------------------------------------------------- streams

@router.get("/streams")
def list_streams(principal: Principal = Depends(require_scope(READ))):
    """Followers running in *this* API process.

    Deliberately honest: with more than one worker each process reports only
    its own followers.
    """
    return {"process_local": True, "auto_dispatch": settings.openclaw_auto_dispatch,
            "streams": supervisor.snapshot(active_org(principal))}


@router.post("/tasks/{task_id}/follow")
async def follow_task(task_id: int, payload: FollowIn, principal: Principal = Depends(writer("member")),
                      db: Session = Depends(get_db)):
    """Bắt đầu theo dõi một phiên.

    Phải là ``async def``: ``supervisor.follow()`` gọi
    ``asyncio.create_task()``, và FastAPI chạy endpoint ĐỒNG BỘ trong
    threadpool — nơi không có event loop nào đang chạy. Bản trước là ``def``,
    nên endpoint này LUÔN trả 500 ``RuntimeError: no running event loop``, tức
    cả tính năng "theo dõi phiên" mà v20 đến v26 dựng lên không thể gọi được
    qua API của chính nó. 16 test của v20 không thấy vì chúng gọi thẳng
    service bên trong một test asyncio, không đi qua endpoint.

    Cùng file, ``move_task`` vốn đã là ``async def`` nên đường auto-dispatch
    không bị lỗi này — đó là lý do lỗi sống sót lâu.
    """
    task = ensure_task(db, task_id, principal)
    session_key = payload.session_key or task.runtime_session_key
    if not session_key:
        raise HTTPException(409, "Task has no session yet. Start it first.")
    state = supervisor.follow(session_key=session_key, organization_id=active_org(principal), task_id=task.id)
    return state.public()


@router.post("/tasks/{task_id}/unfollow")
def unfollow_task(task_id: int, principal: Principal = Depends(writer("member")),
                  db: Session = Depends(get_db)):
    task = ensure_task(db, task_id, principal)
    if not task.runtime_session_key:
        raise HTTPException(409, "Task has no session")
    return {"stopped": supervisor.stop(task.runtime_session_key), "session_key": task.runtime_session_key}


@router.get("/tasks/{task_id}/events")
def task_events(task_id: int, limit: int = 50, principal: Principal = Depends(require_scope(READ)),
                db: Session = Depends(get_db)):
    task = ensure_task(db, task_id, principal)
    limit = max(1, min(limit, 200))
    rows = (db.query(RuntimeEvent)
            .filter(RuntimeEvent.organization_id == active_org(principal), RuntimeEvent.task_id == task.id)
            .order_by(RuntimeEvent.id.desc()).limit(limit).all())
    return {"task": _task_state(task), "following": supervisor.is_following(task.runtime_session_key or ""),
            "events": [{"id": r.id, "type": r.event_type, "progress": r.progress,
                        "session_key": r.runtime_session_key, "created_at": r.created_at} for r in rows]}


# --------------------------------------------------------------------------- board control

@router.post("/board/tasks/{task_id}/move")
async def move_task(task_id: int, payload: MoveIn, principal: Principal = Depends(writer("member")),
                    db: Session = Depends(get_db)):
    """Move a task and, for agent-owned work entering progress, start it.

    The move itself reuses the v18 transition rules, so the board vocabulary
    and guard rails stay in one place. Dispatch failures do not roll back the
    move; they are reported so a human can fix the binding and retry.
    """
    task = ensure_task(db, task_id, principal)
    project = ensure_project(db, task.project_id, principal)
    task = ops.move_task(db, task, project, active_org(principal), status=payload.status,
                         actor_member_id=principal.member_id)

    wants = settings.openclaw_auto_dispatch if payload.dispatch is None else payload.dispatch
    result = {"task": _task_state(task), "dispatched": False, "followed": False, "dispatch_error": None}
    if not (wants and payload.status == "in_progress" and not task.runtime_run_id):
        return result
    try:
        task = await agent_dispatch.dispatch_task(db, task)
    except agent_dispatch.DispatchError as exc:
        result["dispatch_error"] = str(exc)
        return result
    result["task"] = _task_state(task)
    result["dispatched"] = True
    if task.runtime_session_key:
        supervisor.follow(session_key=task.runtime_session_key,
                          organization_id=active_org(principal), task_id=task.id)
        result["followed"] = True
    return result


# --------------------------------------------------------------------------- approvals

@router.get("/approvals/openclaw")
def openclaw_approvals(status: str = "pending", limit: int = 50,
                       principal: Principal = Depends(require_scope(READ)),
                       db: Session = Depends(get_db)):
    """Approval rows that originated from gateway permission prompts."""
    limit = max(1, min(limit, 200))
    q = (db.query(Approval)
         .filter(Approval.organization_id == active_org(principal),
                 Approval.policy_key.like("openclaw:%")))
    if status != "all":
        q = q.filter(Approval.status == status)
    rows = q.order_by(Approval.id.desc()).limit(limit).all()
    return [{"id": r.id, "action": r.action, "risk": r.risk, "status": r.status,
             "policy_key": r.policy_key, "company_id": r.company_id,
             "requester_member_id": r.requester_member_id,
             "resolution_note": r.resolution_note} for r in rows]
