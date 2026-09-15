"""v35 spend & push API: delegation budget reconciliation and an SSE live channel.

Two debts named in the v34 handover:

- ``max_cost_usd`` on a delegation contract was decoration. It is now compared
  with metered usage, with the weakness of that attribution reported in every
  response rather than buried.
- The cockpit polled ``/app/live-runs``. It can now hold one SSE connection
  instead. The browser stops polling; the server still does, and says so.

Flagging an overrun writes to the event bus, so it defaults to a dry run and
sits at admin. Everything else here is read-only.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.authz import Principal, require_role, require_scope
from app.core.tenancy import active_org, ensure_company
from app.db.session import SessionLocal, get_db
from app.services import delegation_spend, live_channel

router = APIRouter(prefix="/v35", tags=["v35-spend-push"])

READ = "company.context:read"
WRITE = "company.workspace:write"  # same scope as v18 and v27-v34


def writer(minimum_role: str = "admin"):
    """API keys pass on scope alone, exactly as in v18-v34."""
    def dep(principal: Principal = Depends(require_scope(WRITE))) -> Principal:
        if principal.auth_type != "api_key":
            return require_role(minimum_role)(principal)
        return principal
    return dep


class FlagIn(BaseModel):
    dry_run: bool = True
    company_id: int | None = None
    include_warnings: bool = False
    limit: int = Field(default=delegation_spend.MAX_SCAN, ge=1, le=delegation_spend.MAX_SCAN)


def _company(db: Session, principal: Principal, company_id: int | None) -> int | None:
    if company_id is None:
        return None
    return ensure_company(db, company_id, principal).id


# --------------------------------------------------------------------------- coverage

@router.get("/coverage")
def coverage(principal: Principal = Depends(require_scope(READ))):
    """Both ceilings in one place, so a reviewer never has to trust the UI."""
    return {"spend_attribution": delegation_spend.attribution(),
            "live_channel": live_channel.readiness()}


# --------------------------------------------------------------------------- spend

@router.get("/spend/report")
def spend_report(company_id: int | None = None,
                 statuses: str = ",".join(delegation_spend.OPEN_STATUSES),
                 limit: int = Query(default=delegation_spend.MAX_SCAN, ge=1,
                                    le=delegation_spend.MAX_SCAN),
                 principal: Principal = Depends(require_scope(READ)),
                 db: Session = Depends(get_db)):
    wanted = tuple(item.strip() for item in (statuses or "").split(",") if item.strip())
    return delegation_spend.report(db, active_org(principal), statuses=wanted,
                                   company_id=_company(db, principal, company_id), limit=limit)


@router.get("/spend/rollup")
def spend_rollup(company_id: int | None = None,
                 limit: int = Query(default=delegation_spend.MAX_SCAN, ge=1,
                                    le=delegation_spend.MAX_SCAN),
                 principal: Principal = Depends(require_scope(READ)),
                 db: Session = Depends(get_db)):
    return delegation_spend.rollup(db, active_org(principal),
                                   company_id=_company(db, principal, company_id), limit=limit)


@router.get("/spend/overruns")
def spend_overruns(company_id: int | None = None, include_warnings: bool = False,
                   limit: int = Query(default=delegation_spend.MAX_SCAN, ge=1,
                                      le=delegation_spend.MAX_SCAN),
                   principal: Principal = Depends(require_scope(READ)),
                   db: Session = Depends(get_db)):
    rows = delegation_spend.overruns(db, active_org(principal),
                                     company_id=_company(db, principal, company_id),
                                     include_warnings=include_warnings, limit=limit)
    return {"count": len(rows), "include_warnings": include_warnings, "contracts": rows,
            "attribution": delegation_spend.attribution()}


@router.get("/spend/delegations/{delegation_id}")
def spend_detail(delegation_id: int, principal: Principal = Depends(require_scope(READ)),
                 db: Session = Depends(get_db)):
    try:
        return delegation_spend.explain(db, active_org(principal), delegation_id)
    except delegation_spend.SpendError as exc:
        raise HTTPException(404, str(exc))


@router.post("/spend/flag-overruns")
def flag_overruns(payload: FlagIn, principal: Principal = Depends(writer("admin")),
                  db: Session = Depends(get_db)):
    """Raise one bus event per contract over budget. Never blocks work."""
    return delegation_spend.flag_overruns(db, active_org(principal),
                                          company_id=_company(db, principal, payload.company_id),
                                          dry_run=payload.dry_run, limit=payload.limit)


# --------------------------------------------------------------------------- live channel

@router.get("/live/readiness")
def live_readiness(principal: Principal = Depends(require_scope(READ))):
    return live_channel.readiness()


@router.get("/live/snapshot")
def live_snapshot(cursor: int = 0, principal: Principal = Depends(require_scope(READ)),
                  db: Session = Depends(get_db)):
    """One frame to render immediately; then open the stream with this cursor."""
    return live_channel.snapshot(db, active_org(principal), cursor=cursor)


@router.get("/live/events")
def live_events(cursor: int = 0, run_id: str | None = None,
                limit: int = Query(default=live_channel.MAX_BATCH, ge=1,
                                   le=live_channel.MAX_BATCH),
                principal: Principal = Depends(require_scope(READ)),
                db: Session = Depends(get_db)):
    """Cursor-based catch-up, kept for clients that cannot hold an SSE
    connection (and for tests, which cannot run an event loop forever)."""
    return live_channel.events_since(db, active_org(principal), cursor=cursor,
                                     limit=limit, run_id=run_id)


@router.get("/live/tasks")
def live_task_list(limit: int = Query(default=50, ge=1, le=200),
                   principal: Principal = Depends(require_scope(READ)),
                   db: Session = Depends(get_db)):
    return {"statuses": list(live_channel.LIVE_TASK_STATUSES),
            "tasks": live_channel.live_tasks(db, active_org(principal), limit=limit)}


@router.get("/live/stream")
async def live_stream(cursor: int = 0, run_id: str | None = None,
                      seconds: int = Query(default=live_channel.MAX_DURATION_SECONDS, ge=5,
                                           le=live_channel.MAX_DURATION_SECONDS),
                      principal: Principal = Depends(require_scope(READ))):
    """Server-sent events for one organization.

    The generator opens a short-lived session per tick instead of holding the
    request session, because a session held for minutes would never see rows
    written by other workers. The stream closes itself after ``seconds`` and
    hands back the cursor to reconnect with.
    """
    organization_id = active_org(principal)
    generator = live_channel.stream_frames(SessionLocal, organization_id, cursor=cursor,
                                           run_id=run_id, max_duration_seconds=seconds)
    return StreamingResponse(generator, media_type="text/event-stream",
                             headers={"Cache-Control": "no-store",
                                      "X-Accel-Buffering": "no",
                                      "Connection": "keep-alive"})
