import json
import secrets
from datetime import datetime, timedelta, timezone
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.models import SchedulerNode, SchedulerLeadershipLease


class SchedulerHAError(RuntimeError): pass

def utcnow(): return datetime.now(timezone.utc).replace(tzinfo=None)

def register_scheduler_node(db: Session, *, organization_id: int, node_key: str, capacity: int = 1, labels: dict | None = None) -> SchedulerNode:
    node = db.query(SchedulerNode).filter_by(organization_id=organization_id, node_key=node_key).first()
    if not node: node = SchedulerNode(organization_id=organization_id, node_key=node_key)
    node.status = "online"; node.capacity = max(1, int(capacity)); node.labels_json = json.dumps(labels or {}, sort_keys=True); node.last_heartbeat_at = utcnow()
    db.add(node); db.commit(); db.refresh(node); return node

def heartbeat_scheduler_node(db: Session, node: SchedulerNode) -> SchedulerNode:
    node.status = "online"; node.last_heartbeat_at = utcnow(); db.add(node); db.commit(); db.refresh(node); return node

def acquire_leadership(db: Session, node: SchedulerNode, *, lease_name: str, ttl_seconds: int = 30) -> tuple[SchedulerLeadershipLease, bool]:
    now = utcnow(); ttl = max(5, min(int(ttl_seconds), 300)); expires = now + timedelta(seconds=ttl)
    lease = db.query(SchedulerLeadershipLease).filter_by(organization_id=node.organization_id, lease_name=lease_name).first()
    if lease is None:
        lease = SchedulerLeadershipLease(organization_id=node.organization_id, lease_name=lease_name, holder_node_id=node.id,
                                         fencing_token=1, expires_at=expires, acquired_at=now, renewed_at=now)
        db.add(lease)
        try: db.commit(); db.refresh(lease); return lease, True
        except IntegrityError: db.rollback(); lease = db.query(SchedulerLeadershipLease).filter_by(organization_id=node.organization_id, lease_name=lease_name).one()
    if lease.holder_node_id == node.id or lease.expires_at <= now:
        if lease.holder_node_id != node.id: lease.fencing_token += 1; lease.acquired_at = now
        lease.holder_node_id = node.id; lease.expires_at = expires; lease.renewed_at = now
        db.add(lease); db.commit(); db.refresh(lease); return lease, True
    return lease, False

def release_leadership(db: Session, lease: SchedulerLeadershipLease, node: SchedulerNode) -> bool:
    if lease.holder_node_id != node.id: return False
    lease.expires_at = utcnow(); lease.renewed_at = utcnow(); db.add(lease); db.commit(); return True

def leader_is_current(lease: SchedulerLeadershipLease, node_id: int, fencing_token: int) -> bool:
    return lease.holder_node_id == node_id and lease.fencing_token == fencing_token and lease.expires_at > utcnow()
