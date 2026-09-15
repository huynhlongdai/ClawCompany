import json
from datetime import datetime, timedelta
from sqlalchemy import func
from sqlalchemy.orm import Session
from app.models import Approval, CompanyEvent, DecisionLoop, DecisionLoopRun, RecoveryIncident, SLAIncident
from app.services.agent_messaging import send_message
from app.services.company_event_bus import emit_event


def tick_decision_loop(db: Session, loop: DecisionLoop) -> DecisionLoopRun:
    now = datetime.utcnow()
    pending_events = db.query(CompanyEvent).filter(CompanyEvent.organization_id == loop.organization_id, CompanyEvent.status == "pending").count()
    open_incidents = db.query(RecoveryIncident).filter(RecoveryIncident.organization_id == loop.organization_id, RecoveryIncident.status.in_(["open", "retrying"])).count()
    sla_breaches = db.query(SLAIncident).filter(SLAIncident.organization_id == loop.organization_id, SLAIncident.status.in_(["open", "escalated"])).count()
    pending_approvals = db.query(Approval).filter(Approval.organization_id == loop.organization_id, Approval.status == "pending").count()
    snapshot = {
        "pending_events": pending_events, "open_recovery_incidents": open_incidents,
        "open_sla_breaches": sla_breaches, "pending_approvals": pending_approvals,
    }
    decisions = []
    policy = json.loads(loop.policy_json or "{}") if loop.policy_json else {}
    if open_incidents >= int(policy.get("incident_attention_threshold", 1)):
        decisions.append({"type":"attention","severity":"high","reason":f"{open_incidents} recovery incident(s) need attention."})
    if sla_breaches:
        decisions.append({"type":"escalation","severity":"high","reason":f"{sla_breaches} SLA breach(es) are open."})
    if pending_approvals >= int(policy.get("approval_attention_threshold", 3)):
        decisions.append({"type":"approval_queue","severity":"medium","reason":f"{pending_approvals} approvals are waiting."})
    if not decisions:
        decisions.append({"type":"continue","severity":"low","reason":"No blocking condition detected."})
    run = DecisionLoopRun(
        organization_id=loop.organization_id, loop_id=loop.id, status="completed",
        snapshot_json=json.dumps(snapshot, ensure_ascii=False), decisions_json=json.dumps(decisions, ensure_ascii=False),
    )
    loop.last_tick_at = now; loop.next_tick_at = now + timedelta(seconds=max(10, loop.interval_seconds))
    db.add_all([run, loop]); db.commit(); db.refresh(run); db.refresh(loop)
    emit_event(
        db, organization_id=loop.organization_id, company_id=loop.company_id,
        event_type="nina.decision_loop.ticked", source="nina_loop", aggregate_type="decision_loop",
        aggregate_id=str(loop.id), payload={"run_id": run.id, "snapshot": snapshot, "decisions": decisions},
    )
    return run


def tick_due_loops(db: Session) -> list[DecisionLoopRun]:
    now = datetime.utcnow()
    rows = db.query(DecisionLoop).filter(
        DecisionLoop.enabled == True,  # noqa: E712
        (DecisionLoop.next_tick_at == None) | (DecisionLoop.next_tick_at <= now),  # noqa: E711
    ).order_by(DecisionLoop.id).limit(100).all()
    return [tick_decision_loop(db, row) for row in rows]
