"""v35 live channel: server-sent events instead of browser polling.

Since v20 the cockpit learned about live runs by asking again every few
seconds. That is one HTTP request per client per tick, and the latency floor
is the poll interval. v35 keeps one connection open per viewer and pushes
frames down it.

What this is, precisely:

- Transport is **SSE** (``text/event-stream``), not WebSocket. SSE is one-way
  server to client, which is all the cockpit needs, and it survives plain HTTP
  proxies. Bi-directional WebSocket is still not implemented.
- The push is real for the *browser*: the client stops polling. The server
  still polls its own database on a short interval, because ``RuntimeEvent``
  rows are written by other processes and there is no LISTEN/NOTIFY here.
  So this removes client fan-out, not server-side polling.
- Cursors are ``RuntimeEvent.id``. A client that reconnects with its last
  cursor gets every row it missed, as long as the row still exists; v32
  retention deletes runtime events after 14 days.
"""
import asyncio
import json
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models import Company, Project, RuntimeEvent, Task
from app.services.runtime_stream import supervisor
from app.services.stream_registry import registry

SOURCE = "live_channel"
TRANSPORT = "sse"
POLL_SECONDS = 2.0
HEARTBEAT_SECONDS = 15.0
MAX_BATCH = 100
MAX_DURATION_SECONDS = 300
LIVE_TASK_STATUSES = ("in_progress", "review")


class ChannelError(Exception):
    pass


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def readiness() -> dict:
    """What the channel does and what it still cannot claim."""
    return {
        "transport": TRANSPORT,
        "websocket_implemented": False,
        "removes_client_polling": True,
        "removes_server_polling": False,
        "server_poll_seconds": POLL_SECONDS,
        "heartbeat_seconds": HEARTBEAT_SECONDS,
        "max_duration_seconds": MAX_DURATION_SECONDS,
        "cursor": "runtime_event.id",
        "replay_limited_by_retention_days": 14,
        "cluster_wide_followers": bool(getattr(registry, "cluster_wide", False)),
        "observed_in_production": False,
        "note": ("SSE m\u1ed9t chi\u1ec1u: tr\u00ecnh duy\u1ec7t kh\u00f4ng c\u00f2n poll, nh\u01b0ng server v\u1eabn poll DB m\u1ed7i "
                 f"{POLL_SECONDS}s v\u00ec kh\u00f4ng c\u00f3 k\u00eanh th\u00f4ng b\u00e1o t\u1eeb ti\u1ebfn tr\u00ecnh kh\u00e1c."),
    }


def _event_payload(item: RuntimeEvent) -> dict:
    try:
        body = json.loads(item.event_json or "{}")
    except (TypeError, ValueError):
        body = {"unparsed": True}
    return {"id": item.id, "runtime_run_id": item.runtime_run_id,
            "runtime_session_key": item.runtime_session_key,
            "event_type": item.event_type, "progress": item.progress,
            "created_at": item.created_at.isoformat() if item.created_at else None,
            "event": body}


def _org_tasks(db: Session, organization_id: int, *entities):
    """Tasks thuộc một organization.

    Bảng ``tasks`` KHÔNG có cột ``organization_id``: quan hệ là
    task -> project -> company -> organization. Bản v35 lọc thẳng
    ``Task.organization_id``, một thuộc tính không tồn tại trên model, nên
    mọi lời gọi tới kênh live đều nổ AttributeError trước khi chạm tới SQL.
    Đường join này giống ``simulation.py`` và ``sla.py`` đã dùng từ trước.
    """
    return (db.query(*entities)
            .join(Project, Task.project_id == Project.id)
            .join(Company, Project.company_id == Company.id)
            .filter(Company.organization_id == organization_id))


def _run_ids(db: Session, organization_id: int) -> list[str]:
    """Runs belonging to this organization, via the tasks that own them.

    ``runtime_events`` has no ``organization_id`` column, so scoping has to go
    through ``tasks``. A run whose task row was deleted becomes invisible here
    rather than leaking across tenants.
    """
    rows = (_org_tasks(db, organization_id, Task.runtime_run_id)
            .filter(Task.runtime_run_id.isnot(None),
                    Task.runtime_run_id != "")
            .order_by(Task.id.desc()).limit(500).all())
    return [row[0] for row in rows if row[0]]


def events_since(db: Session, organization_id: int, *, cursor: int = 0,
                 limit: int = MAX_BATCH, run_id: str | None = None) -> dict:
    capped = max(1, min(int(limit or MAX_BATCH), MAX_BATCH))
    query = db.query(RuntimeEvent).filter(RuntimeEvent.id > int(cursor or 0))
    if run_id:
        query = query.filter(RuntimeEvent.runtime_run_id == run_id)
    else:
        allowed = _run_ids(db, organization_id)
        if not allowed:
            return {"cursor": int(cursor or 0), "events": [], "scoped_runs": 0,
                    "truncated": False}
        query = query.filter(RuntimeEvent.runtime_run_id.in_(allowed))
    items = query.order_by(RuntimeEvent.id.asc()).limit(capped).all()
    events = [_event_payload(item) for item in items]
    next_cursor = events[-1]["id"] if events else int(cursor or 0)
    return {"cursor": next_cursor, "events": events,
            "scoped_runs": None if run_id else len(_run_ids(db, organization_id)),
            "truncated": len(events) == capped}


def live_tasks(db: Session, organization_id: int, limit: int = 50) -> list[dict]:
    items = (_org_tasks(db, organization_id, Task)
             .filter(Task.status.in_(LIVE_TASK_STATUSES))
             .order_by(Task.id.desc()).limit(max(1, min(int(limit or 50), 200))).all())
    return [{"id": item.id, "title": item.title, "status": item.status,
             "project_id": item.project_id, "assignee_member_id": item.assignee_member_id,
             "runtime_run_id": item.runtime_run_id,
             "runtime_session_key": item.runtime_session_key} for item in items]


def snapshot(db: Session, organization_id: int, *, cursor: int = 0) -> dict:
    """One frame a client can render before any push arrives."""
    batch = events_since(db, organization_id, cursor=cursor)
    return {"type": "snapshot", "at": utcnow().isoformat(), "cursor": batch["cursor"],
            "events": batch["events"], "tasks": live_tasks(db, organization_id),
            "followers": supervisor.snapshot(organization_id),
            "registry": registry.status(), "readiness": readiness()}


def frame(kind: str, data: dict) -> str:
    """Encode one SSE frame. Newlines inside the payload would break the
    protocol, so the JSON is emitted on a single line."""
    body = json.dumps(data, ensure_ascii=False, default=str, separators=(",", ":"))
    return f"event: {kind}\ndata: {body}\n\n"


async def stream_frames(session_factory, organization_id: int, *, cursor: int = 0,
                        run_id: str | None = None,
                        max_duration_seconds: int = MAX_DURATION_SECONDS,
                        poll_seconds: float = POLL_SECONDS,
                        clock=None):
    """Async generator of SSE frames.

    A fresh session per tick on purpose: a long-lived session would pin a
    snapshot of the database and never see rows written by other workers.
    The stream always ends by itself after ``max_duration_seconds`` so a lost
    client cannot hold a connection and a session open forever; the client is
    told to reconnect with the cursor it already has.
    """
    now = clock or (lambda: asyncio.get_event_loop().time())
    started = now()
    position = int(cursor or 0)
    last_push = started
    session: Session = session_factory()
    try:
        first = snapshot(session, organization_id, cursor=position)
        position = int(first["cursor"])
        yield frame("snapshot", first)
    finally:
        session.close()
    while now() - started < max_duration_seconds:
        await asyncio.sleep(poll_seconds)
        session = session_factory()
        try:
            batch = events_since(session, organization_id, cursor=position, run_id=run_id)
        finally:
            session.close()
        if batch["events"]:
            position = int(batch["cursor"])
            last_push = now()
            yield frame("events", {"cursor": position, "events": batch["events"],
                                   "truncated": batch["truncated"]})
        elif now() - last_push >= HEARTBEAT_SECONDS:
            last_push = now()
            yield frame("heartbeat", {"cursor": position, "at": utcnow().isoformat()})
    yield frame("closed", {"cursor": position, "reason": "max_duration_reached",
                           "reconnect_with_cursor": position})
