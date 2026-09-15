"""v33 recovery API: member runtime repair, project progress sync, ranked
knowledge retrieval, lease index hygiene.

Three of these four endpoints close debts that were reported honestly in
earlier handovers rather than fixed: a member restore left dead runtime
sessions behind, project progress was typed by hand, and the mesh matched
substrings instead of ranking. The fourth stops the v26 lease index set from
growing forever in deployments that never call scan.

Writes default to a dry run. Parking runtime and rewriting a whole company's
progress column are operator actions, so the human floor is manager for the
board pass and admin for the runtime ones.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.authz import Principal, require_role, require_scope
from app.core.tenancy import active_org, ensure_company, ensure_member
from app.db.session import get_db
from app.services import member_reactivate, mesh_retrieval, progress_autosync
from app.services.runtime_leases import store as lease_store

router = APIRouter(prefix="/v33", tags=["v33-recovery"])

READ = "company.context:read"
WRITE = "company.workspace:write"  # same scope as v18 and v27-v32


def writer(minimum_role: str = "admin"):
    """API keys pass on scope alone, exactly as in v18-v32."""
    def dep(principal: Principal = Depends(require_scope(WRITE))) -> Principal:
        if principal.auth_type != "api_key":
            return require_role(minimum_role)(principal)
        return principal
    return dep


class ParkIn(BaseModel):
    dry_run: bool = True
    limit: int = Field(default=member_reactivate.MAX_PARK, ge=1,
                       le=member_reactivate.MAX_PARK)


class ProgressSyncIn(BaseModel):
    dry_run: bool = True
    company_id: int | None = None
    limit: int = Field(default=progress_autosync.MAX_SYNC, ge=1,
                       le=progress_autosync.MAX_SYNC)


class PruneIndexIn(BaseModel):
    dry_run: bool = True
    limit: int = Field(default=1000, ge=1, le=5000)


# -- what v33 does and does not repair --------------------------------------


@router.get("/coverage")
def coverage(principal: Principal = Depends(require_scope(READ))) -> dict:
    return {
        "member_runtime": member_reactivate.coverage(),
        "progress": progress_autosync.policy(),
        "retrieval": mesh_retrieval.explain(),
        "lease_index": {"max_remove_per_call": 5000, "dry_run_default": True},
    }


# -- member runtime repair --------------------------------------------------


@router.get("/members/{member_id}/runtime")
def member_runtime(member_id: int, principal: Principal = Depends(require_scope(READ)),
                   db: Session = Depends(get_db)) -> dict:
    member = ensure_member(db, member_id, principal)
    return member_reactivate.preview(db, member)


@router.get("/members/{member_id}/runtime/resume-plan")
def member_resume_plan(member_id: int, principal: Principal = Depends(require_scope(READ)),
                       db: Session = Depends(get_db)) -> dict:
    member = ensure_member(db, member_id, principal)
    return member_reactivate.resume_plan(db, member)


@router.post("/members/{member_id}/runtime/park")
def member_runtime_park(member_id: int, payload: ParkIn,
                        principal: Principal = Depends(writer("admin")),
                        db: Session = Depends(get_db)) -> dict:
    member = ensure_member(db, member_id, principal)
    try:
        return member_reactivate.park(db, member, active_org(principal),
                                      dry_run=payload.dry_run, limit=payload.limit,
                                      actor_member_id=principal.member_id)
    except member_reactivate.ReactivateError as exc:
        # 409: the caller asked for a repair that the current state forbids.
        raise HTTPException(409, detail={"error": str(exc), "member_id": member_id})


# -- project progress -------------------------------------------------------


@router.get("/progress/drift")
def progress_drift(company_id: int | None = Query(default=None),
                   principal: Principal = Depends(require_scope(READ)),
                   db: Session = Depends(get_db)) -> dict:
    if company_id is not None:
        ensure_company(db, company_id, principal)
    return progress_autosync.drift_report(db, organization_id=active_org(principal),
                                          company_id=company_id)


@router.post("/progress/sync")
def progress_sync(payload: ProgressSyncIn,
                  principal: Principal = Depends(writer("manager")),
                  db: Session = Depends(get_db)) -> dict:
    if payload.company_id is not None:
        ensure_company(db, payload.company_id, principal)
    return progress_autosync.sync(db, organization_id=active_org(principal),
                                  company_id=payload.company_id,
                                  dry_run=payload.dry_run, limit=payload.limit,
                                  actor_member_id=principal.member_id)


# -- ranked retrieval -------------------------------------------------------


@router.get("/knowledge/search")
def knowledge_search(q: str = Query(default="", max_length=500),
                     mode: str = Query(default=mesh_retrieval.HYBRID),
                     space_ids: str = Query(default=""),
                     limit: int = Query(default=20, ge=1, le=100),
                     principal: Principal = Depends(require_scope(READ)),
                     db: Session = Depends(get_db)) -> dict:
    if principal.member_id is None:
        # Retrieval is permission-filtered per member. An API key with no
        # member identity has no reading identity to filter by, so refuse
        # rather than quietly returning everything.
        raise HTTPException(400, detail={
            "error": "This endpoint needs a member identity to filter by",
            "hint": "Call it as a user, or attach a member to the key",
        })
    if mode not in mesh_retrieval.MODES:
        raise HTTPException(422, detail={"error": "Unknown mode",
                                         "allowed": list(mesh_retrieval.MODES)})
    wanted = [int(x) for x in space_ids.replace(",", " ").split() if x.strip().isdigit()]
    return mesh_retrieval.search(db, organization_id=active_org(principal),
                                 member_id=int(principal.member_id), query=q,
                                 space_ids=wanted or None, limit=limit, mode=mode)


@router.get("/knowledge/retrieval-quality")
def retrieval_quality(principal: Principal = Depends(require_scope(READ))) -> dict:
    return mesh_retrieval.explain()


# -- lease index hygiene ----------------------------------------------------


@router.get("/runtime/lease-index")
def lease_index(principal: Principal = Depends(require_scope(READ))) -> dict:
    status = lease_store.status()
    return {**status, "preview": lease_store.prune_index(dry_run=True)}


@router.post("/runtime/lease-index/prune")
def lease_index_prune(payload: PruneIndexIn,
                      principal: Principal = Depends(writer("admin"))) -> dict:
    return lease_store.prune_index(dry_run=payload.dry_run, limit=payload.limit)
