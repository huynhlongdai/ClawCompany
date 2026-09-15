"""v32 housekeeping API: audit coverage, event retention, revision adoption,
runtime pool metrics.

The write endpoints here default to a dry run and require an admin role for
human callers. Pruning an audit table and adopting revision counters are
operator actions, not member actions, which is why this router raises the
minimum role above the v31 default.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.authz import Principal, require_role, require_scope
from app.db.session import get_db
from app.services import (
    event_retention,
    revision_backfill,
    runtime_leases,
    stream_registry,
    write_trail,
)
from app.services.redis_pool import pool

router = APIRouter(prefix="/v32", tags=["v32-housekeeping"])

READ = "company.context:read"
WRITE = "company.workspace:write"  # same scope as v18 and v27-v31


def writer(minimum_role: str = "admin"):
    """Housekeeping writes are operator actions, so the floor is admin.

    API keys keep passing on scope alone, exactly as in v18-v31: a key has
    no human role to compare against.
    """
    def dep(principal: Principal = Depends(require_scope(WRITE))) -> Principal:
        if principal.auth_type != "api_key":
            return require_role(minimum_role)(principal)
        return principal
    return dep


class PruneIn(BaseModel):
    dry_run: bool = True
    limit: int = Field(default=event_retention.MAX_DELETE, ge=1,
                       le=event_retention.MAX_DELETE)


class BackfillIn(BaseModel):
    dry_run: bool = True
    kinds: list[str] | None = None
    quiet_seconds: int = Field(default=revision_backfill.QUIET_SECONDS, ge=0, le=86400)


@router.get("/coverage")
def coverage(principal: Principal = Depends(require_scope(READ))) -> dict:
    """Which write paths record before-values, plus the two policies.

    Read this before claiming a field history is complete: it names the paths
    that do not record previous values and why.
    """
    return {
        "write_values": write_trail.coverage(),
        "retention": event_retention.policy(),
        "revision_adoption": {
            "quiet_seconds": revision_backfill.QUIET_SECONDS,
            "start_at": revision_backfill.START_AT,
            "kinds": list(revision_backfill.MODELS),
            "never_renumbers_existing": True,
        },
    }


@router.get("/retention/policy")
def retention_policy(principal: Principal = Depends(require_scope(READ))) -> dict:
    return event_retention.policy()


@router.get("/retention/preview")
def retention_preview(
    limit: int = Query(default=event_retention.MAX_DELETE, ge=1,
                       le=event_retention.MAX_DELETE),
    principal: Principal = Depends(require_scope(READ)),
    db: Session = Depends(get_db),
) -> dict:
    try:
        return event_retention.preview(db, principal.organization_id, limit=limit)
    except event_retention.RetentionError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/retention/prune")
def retention_prune(
    body: PruneIn,
    principal: Principal = Depends(writer("admin")),
    db: Session = Depends(get_db),
) -> dict:
    try:
        return event_retention.prune(
            db,
            principal.organization_id,
            dry_run=body.dry_run,
            limit=body.limit,
            actor_member_id=principal.member_id,
        )
    except event_retention.RetentionError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/revisions/preview")
def revisions_preview(
    quiet_seconds: int = Query(default=revision_backfill.QUIET_SECONDS, ge=0, le=86400),
    principal: Principal = Depends(require_scope(READ)),
    db: Session = Depends(get_db),
) -> dict:
    return revision_backfill.preview(
        db, principal.organization_id, quiet_seconds=quiet_seconds
    )


@router.post("/revisions/backfill")
def revisions_backfill(
    body: BackfillIn,
    principal: Principal = Depends(writer("admin")),
    db: Session = Depends(get_db),
) -> dict:
    unknown = [k for k in (body.kinds or []) if k not in revision_backfill.MODELS]
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown kinds: {unknown}")
    return revision_backfill.backfill(
        db,
        principal.organization_id,
        kinds=body.kinds,
        dry_run=body.dry_run,
        quiet_seconds=body.quiet_seconds,
        actor_member_id=principal.member_id,
    )


@router.get("/runtime/pool")
def runtime_pool(principal: Principal = Depends(require_scope(READ))) -> dict:
    return {"pool": pool.status(), "leases": runtime_leases.store.status()}


def _metric_lines() -> list[str]:
    """Prometheus text exposition, hand-rolled.

    A client library would be a new dependency this build cannot verify, and
    the surface is a handful of gauges. Each block degrades to a *_scrape_ok 0
    gauge rather than a 500, because a monitoring endpoint that fails during a
    partial deploy is worse than one reporting a gap.
    """
    lines: list[str] = []

    def gauge(name: str, value, help_text: str) -> None:
        lines.append(f"# HELP {name} {help_text}")
        lines.append(f"# TYPE {name} gauge")
        lines.append(f"{name} {value}")

    try:
        status = pool.status()
        gauge("clawcompany_redis_available", 1 if status.get("available") else 0,
              "1 when the shared Redis pool is usable.")
        gauge("clawcompany_redis_connect_attempts_total",
              status.get("connect_attempts", 0), "Connection attempts since boot.")
        gauge("clawcompany_redis_failures_total",
              status.get("failures", 0), "Failed connection attempts since boot.")
        gauge("clawcompany_redis_reconnects_total",
              status.get("reconnects", 0), "Successful reconnects since boot.")
        gauge("clawcompany_redis_consecutive_failures",
              status.get("consecutive_failures", 0),
              "Consecutive failures driving the backoff.")
        gauge("clawcompany_redis_retry_delay_seconds",
              status.get("retry_delay", 0), "Current backoff delay.")
        gauge("clawcompany_redis_retry_in_seconds",
              status.get("retry_in", 0), "Seconds until the next attempt.")
    except Exception:  # noqa: BLE001
        gauge("clawcompany_redis_scrape_ok", 0, "0 when the pool could not be read.")

    try:
        leases = runtime_leases.store.status()
        gauge("clawcompany_leases_backend_shared",
              1 if leases.get("shared") else 0,
              "1 when leases are held in Redis rather than in process memory.")
        gauge("clawcompany_leases_held", leases.get("held", 0),
              "Stream leases currently held by this process.")
        gauge("clawcompany_leases_ttl_seconds", leases.get("ttl", 0),
              "Lease time to live.")
        gauge("clawcompany_leases_scrape_ok", 1, "1 when the lease store was read.")
    except Exception:  # noqa: BLE001
        gauge("clawcompany_leases_scrape_ok", 0,
              "0 when the lease store could not be read.")

    try:
        followers = stream_registry.registry.snapshot()
        gauge("clawcompany_stream_followers", len(followers),
              "Sessions with at least one follower.")
        gauge("clawcompany_stream_followers_scrape_ok", 1,
              "1 when the stream registry was read.")
    except Exception:  # noqa: BLE001
        gauge("clawcompany_stream_followers_scrape_ok", 0,
              "0 when the stream registry could not be read.")

    return lines


@router.get("/runtime/metrics", response_class=PlainTextResponse)
def runtime_metrics(principal: Principal = Depends(require_scope(READ))) -> PlainTextResponse:
    """Scope-protected on purpose: an open /metrics leaks deployment topology."""
    return PlainTextResponse("\n".join(_metric_lines()) + "\n")
