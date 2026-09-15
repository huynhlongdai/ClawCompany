import json
from sqlalchemy.orm import Session
from app.models import RuntimeEvent, UsageEvent, UsageMeterRule
from app.services.metering import record_usage
from app.services.company_event_bus import emit_event


def run_context(db: Session, organization_id: int, run_id: str):
    usage = db.query(UsageEvent).filter(UsageEvent.organization_id == organization_id, UsageEvent.runtime_run_id == run_id).order_by(UsageEvent.id.desc()).first()
    if not usage: return None
    return {"organization_id": usage.organization_id, "agent_id": usage.agent_id, "customer_id": usage.customer_id, "task_id": usage.task_id}


def persist_runtime_event(db: Session, *, organization_id: int, run_id: str, event: dict, agent_id: int | None = None,
                          customer_id: int | None = None, task_id: int | None = None, session_key: str = ""):
    typ = str(event.get("type") or event.get("event") or "runtime.event")
    try: progress = float(event.get("progress")) if event.get("progress") is not None else None
    except Exception: progress = None
    item = RuntimeEvent(organization_id=organization_id, agent_id=agent_id, customer_id=customer_id, task_id=task_id,
                        runtime_run_id=run_id, runtime_session_key=session_key, event_type=typ, progress=progress,
                        event_json=json.dumps(event, ensure_ascii=False, default=str))
    db.add(item); db.commit(); db.refresh(item)
    rule = db.query(UsageMeterRule).filter(UsageMeterRule.organization_id == organization_id, UsageMeterRule.event_type == typ, UsageMeterRule.enabled == True).first()  # noqa: E712
    if rule:
        record_usage(db, organization_id=organization_id, customer_id=customer_id, agent_id=agent_id, task_id=task_id,
                     runtime_run_id=run_id, event_type=typ, quantity=1, unit=rule.unit, unit_cost=rule.unit_cost,
                     metadata={"runtime_event_id": item.id, "customer_billable": rule.customer_billable, "customer_unit_price": rule.customer_unit_price})
    emit_event(
        db, organization_id=organization_id, event_type=f"runtime.{typ}", source="openclaw_runtime",
        aggregate_type="runtime_run", aggregate_id=run_id,
        payload={"runtime_event_id": item.id, "run_id": run_id, "agent_id": agent_id, "customer_id": customer_id,
                 "task_id": task_id, "session_key": session_key, "event": event},
    )
    return item
