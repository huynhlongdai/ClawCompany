import json
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from app.models import RunnerPool, RunnerNode, RunnerLease, RunnerJob


class RunnerBrokerError(RuntimeError):
    pass


def _loads(value: str, fallback):
    try:
        return json.loads(value or "")
    except Exception:
        return fallback


def register_node(db: Session, pool: RunnerPool, *, node_key: str, provider: str = "remote", endpoint: str = "",
                  capabilities: list[str] | None = None, labels: dict | None = None, capacity: int = 1) -> RunnerNode:
    if not pool.enabled:
        raise RunnerBrokerError("Runner pool is disabled")
    node = db.query(RunnerNode).filter(RunnerNode.organization_id == pool.organization_id, RunnerNode.node_key == node_key).first()
    if node is None:
        node = RunnerNode(organization_id=pool.organization_id, pool_id=pool.id, node_key=node_key)
    elif node.pool_id != pool.id:
        raise RunnerBrokerError("Runner node key already belongs to another pool")
    node.provider = provider or pool.provider
    node.endpoint = endpoint
    node.capabilities_json = json.dumps(sorted(set(capabilities or [])))
    node.labels_json = json.dumps(labels or {}, sort_keys=True)
    node.capacity = max(1, int(capacity))
    node.status = "online"
    node.last_heartbeat_at = datetime.utcnow()
    db.add(node); db.commit(); db.refresh(node)
    return node


def heartbeat(db: Session, node: RunnerNode, *, status: str = "online", active_leases: int | None = None,
              capabilities: list[str] | None = None) -> RunnerNode:
    node.status = status
    node.last_heartbeat_at = datetime.utcnow()
    if active_leases is not None:
        node.active_leases = max(0, int(active_leases))
    if capabilities is not None:
        node.capabilities_json = json.dumps(sorted(set(capabilities)))
    db.add(node); db.commit(); db.refresh(node)
    return node


def _node_matches(node: RunnerNode, required: set[str]) -> bool:
    caps = set(_loads(node.capabilities_json, []))
    return required.issubset(caps)


def acquire_lease(db: Session, pool: RunnerPool, *, member_id: int | None = None, agent_id: int | None = None,
                  workload_type: str = "sandbox", workload_ref: str = "", required_capabilities: list[str] | None = None,
                  scopes: list[str] | None = None, ttl_seconds: int = 600) -> RunnerLease:
    if not pool.enabled:
        raise RunnerBrokerError("Runner pool is disabled")
    now = datetime.utcnow()
    required = set(required_capabilities or [])
    nodes = db.query(RunnerNode).filter(RunnerNode.pool_id == pool.id, RunnerNode.status == "online").order_by(RunnerNode.active_leases.asc(), RunnerNode.id.asc()).all()
    candidates = [n for n in nodes if n.active_leases < n.capacity and _node_matches(n, required)]
    if not candidates:
        raise RunnerBrokerError("No runner has the required capacity/capabilities")
    node = candidates[0]
    ttl = min(max(int(ttl_seconds), 60), 3600)
    lease = RunnerLease(
        organization_id=pool.organization_id, pool_id=pool.id, runner_node_id=node.id,
        member_id=member_id, agent_id=agent_id, workload_type=workload_type, workload_ref=workload_ref,
        requested_capabilities_json=json.dumps(sorted(required)), scopes_json=json.dumps(sorted(set(scopes or []))),
        status="active", expires_at=now + timedelta(seconds=ttl),
    )
    node.active_leases += 1
    db.add_all([lease, node]); db.commit(); db.refresh(lease)
    return lease


def release_lease(db: Session, lease: RunnerLease, *, status: str = "released") -> RunnerLease:
    if lease.status in {"released", "expired"}:
        return lease
    node = db.get(RunnerNode, lease.runner_node_id)
    lease.status = status
    lease.released_at = datetime.utcnow()
    if node:
        node.active_leases = max(0, node.active_leases - 1)
        db.add(node)
    db.add(lease); db.commit(); db.refresh(lease)
    return lease


def reap_expired_leases(db: Session) -> int:
    now = datetime.utcnow(); count = 0
    items = db.query(RunnerLease).filter(RunnerLease.status == "active", RunnerLease.expires_at <= now).all()
    for item in items:
        release_lease(db, item, status="expired"); count += 1
    return count


def enqueue_job(db: Session, lease: RunnerLease, *, workspace_id: int | None = None, sandbox_run_id: int | None = None,
                job_type: str = "command", payload: dict | None = None) -> RunnerJob:
    if lease.status != "active" or lease.expires_at <= datetime.utcnow():
        raise RunnerBrokerError("Runner lease is not active")
    job = RunnerJob(
        organization_id=lease.organization_id, lease_id=lease.id, workspace_id=workspace_id,
        sandbox_run_id=sandbox_run_id, job_type=job_type, payload_json=json.dumps(payload or {}, sort_keys=True), status="queued",
    )
    db.add(job); db.commit(); db.refresh(job)
    return job


def claim_next_job(db: Session, node: RunnerNode) -> RunnerJob | None:
    now = datetime.utcnow()
    job = db.query(RunnerJob).join(RunnerLease, RunnerLease.id == RunnerJob.lease_id).filter(
        RunnerLease.runner_node_id == node.id, RunnerLease.status == "active", RunnerLease.expires_at > now,
        RunnerJob.status == "queued",
    ).order_by(RunnerJob.id.asc()).first()
    if not job:
        return None
    job.status = "running"; job.attempt += 1; job.started_at = now
    db.add(job); db.commit(); db.refresh(job)
    return job


def complete_job(db: Session, job: RunnerJob, *, result: dict | None = None, error: str = "") -> RunnerJob:
    job.status = "failed" if error else "completed"
    job.result_json = json.dumps(result or {}, sort_keys=True)
    job.error = error[:8000]
    job.completed_at = datetime.utcnow()
    db.add(job); db.commit(); db.refresh(job)
    return job
