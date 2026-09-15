"""v26: the shared Redis fabric, made inspectable.

There is nothing new to operate here. These endpoints exist because v21, v22
and v25 each reported their own backend independently, and an operator had no
way to answer two questions that actually matter: is this worker really
talking to Redis, and is the runtime state I am looking at cluster-wide or
just this process?
"""
from fastapi import APIRouter, Depends

from app.core.authz import Principal, require_role, require_scope
from app.core.tenancy import active_org
from app.services import stream_reconcile
from app.services.redis_pool import RETRY_SECONDS, pool
from app.services.runtime_leases import store as lease_store
from app.services.stream_registry import registry

router = APIRouter(prefix="/v26", tags=["v26-shared-fabric"])

READ = "company.context:read"
WRITE = "company.runtime:write"


def writer(minimum_role: str = "member"):
    def dep(principal: Principal = Depends(require_scope(WRITE))) -> Principal:
        if principal.auth_type != "api_key":
            return require_role(minimum_role)(principal)
        return principal
    return dep


@router.get("/runtime/fabric")
def fabric(principal: Principal = Depends(require_scope(READ))):
    """One answer for the whole worker instead of three separate guesses.

    ``consistent`` is the point of this endpoint: before v26 the lease store
    and the registry could disagree about whether Redis existed, and both
    were reporting truthfully about their own private connection.
    """
    shared = pool.status()
    lease = lease_store.status()
    reg = registry.status()
    available = shared["available"]
    return {
        "pool": shared,
        "lease": lease,
        "registry": reg,
        "reconcile_ledger": {
            "cluster_wide": stream_reconcile.cluster_wide(),
            "ttl_seconds": stream_reconcile.LEDGER_TTL,
            "cooldown_seconds": stream_reconcile.COOLDOWN_SECONDS,
            "index_key": stream_reconcile.LEDGER_INDEX,
        },
        "consistent": (
            (lease["backend"] == "redis") == available
            and reg["cluster_wide"] == available
        ),
        "cluster_wide": available,
        "retry_seconds": RETRY_SECONDS,
        "organization_id": active_org(principal),
    }


@router.get("/runtime/index")
def index_health(principal: Principal = Depends(require_scope(READ))):
    """Index sets replaced keyspace walks; this is how you check they are sane.

    ``scan()`` prunes members whose lease has already expired, so calling
    this endpoint is also the repair: the count you get back is post-prune.
    """
    held = lease_store.scan()
    published = registry.snapshot()
    return {
        "leases": len(held),
        "lease_index_key": lease_store.status()["index_key"],
        "lease_index_pruned": lease_store.status()["index_pruned"],
        "registry_rows": len(published),
        "registry_index_key": registry.status()["index_key"],
        "registry_index_pruned": registry.status()["index_pruned"],
        "cluster_wide": pool.available,
        "method": "index_set" if pool.available else "process_memory",
    }


@router.post("/runtime/fabric/reconnect")
def reconnect(principal: Principal = Depends(writer("manager"))):
    """Drop the backoff window and dial Redis now.

    The pool already retries by itself every few seconds; this exists for the
    operator who just fixed Redis and does not want to wonder whether the
    next request will be the lucky one.
    """
    before = pool.status()
    pool.drop("manual reconnect requested")
    pool._next_attempt = 0.0  # skip the backoff we just set for ourselves
    after = pool.status()
    return {"before": before, "after": after, "connected": after["available"]}
