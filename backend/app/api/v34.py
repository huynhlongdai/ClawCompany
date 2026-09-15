"""v34 replay & schedule API: event replay, scheduled progress sync, standing
grant expiry ledger.

All three close debts that earlier handovers named but did not fix. Two of them
have honest ceilings that the endpoints report rather than hide: replay cannot
recover an event the gateway produced while we were offline, and a grant expiry
date is a review deadline, not upstream enforcement.

Writes default to a dry run. Replaying events executes trigger actions and
revoking a grant changes the security record, so both sit at admin; registering
a schedule is a manager action.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.authz import Principal, require_role, require_scope
from app.core.tenancy import active_org, ensure_company
from app.db.session import get_db
from app.services import event_replay, grant_ledger, progress_schedule

router = APIRouter(prefix="/v34", tags=["v34-replay"])

READ = "company.context:read"
WRITE = "company.workspace:write"  # same scope as v18 and v27-v33


def writer(minimum_role: str = "admin"):
    """API keys pass on scope alone, exactly as in v18-v33."""
    def dep(principal: Principal = Depends(require_scope(WRITE))) -> Principal:
        if principal.auth_type != "api_key":
            return require_role(minimum_role)(principal)
        return principal
    return dep


class ReplayIn(BaseModel):
    dry_run: bool = True
    company_id: int | None = None
    limit: int = Field(default=event_replay.MAX_REPLAY, ge=1, le=event_replay.MAX_REPLAY)
    statuses: list[str] | None = None


class ReemitIn(BaseModel):
    runtime_event_ids: list[int] = Field(min_length=1, max_length=50)
    dry_run: bool = True


class ScheduleIn(BaseModel):
    company_id: int | None = None
    schedule: str = progress_schedule.DEFAULT_SCHEDULE
    timezone: str = progress_schedule.DEFAULT_TIMEZONE
    limit: int = Field(default=progress_schedule.DEFAULT_LIMIT, ge=1, le=300)
    dry_run_runs: bool = False
    enabled: bool = True
    name: str = ""


class ToggleIn(BaseModel):
    enabled: bool


class RevokeIn(BaseModel):
    grant_key: str
    note: str = ""
    confirmed_cleared_upstream: bool = False


# -- capability statements ---------------------------------------------------


@router.get("/coverage")
def coverage(principal: Principal = Depends(require_scope(READ))):
    """What v34 repairs, and where each piece stops."""
    return {
        "version": "v34",
        "theme": "replay & schedule",
        "event_replay": event_replay.explain(),
        "progress_schedule": progress_schedule.readiness(),
        "grant_expiry": grant_ledger.enforcement(),
    }


# -- event replay -----------------------------------------------------------


@router.get("/events/backlog")
def events_backlog(
    limit: int = Query(default=50, ge=1, le=event_replay.MAX_REPLAY),
    company_id: int | None = None,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_scope(READ)),
):
    organization_id = active_org(principal)
    if company_id is not None:
        ensure_company(db, company_id, organization_id)
    return event_replay.backlog(db, organization_id, limit=limit, company_id=company_id)


@router.get("/events/{event_id}")
def event_detail(
    event_id: int,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_scope(READ)),
):
    try:
        return event_replay.event_detail(db, active_org(principal), event_id)
    except event_replay.ReplayError as exc:
        raise HTTPException(404, str(exc))


@router.post("/events/replay")
def events_replay(
    body: ReplayIn,
    db: Session = Depends(get_db),
    principal: Principal = Depends(writer("admin")),
):
    organization_id = active_org(principal)
    if body.company_id is not None:
        ensure_company(db, body.company_id, organization_id)
    try:
        return event_replay.replay(
            db, organization_id, dry_run=body.dry_run, limit=body.limit,
            statuses=body.statuses, company_id=body.company_id,
            actor_member_id=principal.member_id,
        )
    except event_replay.ReplayError as exc:
        raise HTTPException(400, str(exc))


@router.get("/events/runtime/unmirrored")
def runtime_unmirrored(
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_scope(READ)),
):
    return event_replay.unmirrored_runtime_events(db, active_org(principal), limit=limit)


@router.post("/events/runtime/reemit")
def runtime_reemit(
    body: ReemitIn,
    db: Session = Depends(get_db),
    principal: Principal = Depends(writer("admin")),
):
    try:
        return event_replay.reemit_runtime_events(
            db, active_org(principal), runtime_event_ids=body.runtime_event_ids,
            dry_run=body.dry_run, actor_member_id=principal.member_id,
        )
    except event_replay.ReplayError as exc:
        raise HTTPException(400, str(exc))


# -- scheduled progress sync ------------------------------------------------


@router.get("/progress/schedules")
def progress_schedules(
    company_id: int | None = None,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_scope(READ)),
):
    organization_id = active_org(principal)
    if company_id is not None:
        ensure_company(db, company_id, organization_id)
    return progress_schedule.schedules(db, organization_id, company_id=company_id)


@router.post("/progress/schedules")
def create_progress_schedule(
    body: ScheduleIn,
    db: Session = Depends(get_db),
    principal: Principal = Depends(writer("manager")),
):
    organization_id = active_org(principal)
    if body.company_id is not None:
        ensure_company(db, body.company_id, organization_id)
    try:
        return progress_schedule.register(
            db, organization_id, company_id=body.company_id, schedule=body.schedule,
            timezone_name=body.timezone, limit=body.limit, dry_run_runs=body.dry_run_runs,
            enabled=body.enabled, name=body.name,
        )
    except progress_schedule.ScheduleError as exc:
        raise HTTPException(400, str(exc))


@router.post("/progress/schedules/{operation_id}/enabled")
def toggle_progress_schedule(
    operation_id: int,
    body: ToggleIn,
    db: Session = Depends(get_db),
    principal: Principal = Depends(writer("manager")),
):
    try:
        return progress_schedule.set_enabled(
            db, active_org(principal), operation_id, enabled=body.enabled
        )
    except progress_schedule.ScheduleError as exc:
        raise HTTPException(404, str(exc))


# -- standing grant expiry --------------------------------------------------


@router.get("/grants")
def grants(
    include_revoked: bool = False,
    company_id: int | None = None,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_scope(READ)),
):
    organization_id = active_org(principal)
    if company_id is not None:
        ensure_company(db, company_id, organization_id)
    return grant_ledger.ledger(
        db, organization_id, company_id=company_id, include_revoked=include_revoked
    )


@router.get("/grants/due")
def grants_due(
    within_days: int = Query(default=7, ge=0, le=grant_ledger.MAX_EXPIRES_IN_DAYS),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_scope(READ)),
):
    return grant_ledger.due_for_review(db, active_org(principal), within_days=within_days)


@router.post("/grants/revoke")
def revoke_grant(
    body: RevokeIn,
    db: Session = Depends(get_db),
    principal: Principal = Depends(writer("admin")),
):
    try:
        return grant_ledger.revoke(
            db, active_org(principal), grant_key=body.grant_key, note=body.note,
            actor_member_id=principal.member_id,
            confirmed_cleared_upstream=body.confirmed_cleared_upstream,
        )
    except grant_ledger.GrantError as exc:
        raise HTTPException(400, str(exc))
