import json
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.authz import Principal, enforce_org, require_human, require_role, require_scope
from app.core.tenancy import active_org, ensure_company, ensure_member, ensure_task
from app.db.session import get_db
from app.models import (
    Agent, AgentMessage, Approval, Artifact, ArtifactEvaluation, ArtifactHandoff, CompanyEvent, DecisionLoop,
    DecisionLoopRun, EventTrigger, ExecutiveGoal, Member, RecoveryIncident, RuntimeEvent, SLAIncident, SLAProfile,
    SimulationRun, SimulationScenario, TriggerExecution,
)
from app.schemas.v10 import (
    AgentMessageCreate, ArtifactCreate, ArtifactEvaluationCreate, ArtifactHandoffCreate, CompanyEventCreate,
    DecisionLoopCreate, EventTriggerCreate, SLAProfileCreate, SimulationScenarioCreate,
)
from app.services.agent_messaging import mark_read, send_message
from app.services.artifacts import accept_handoff, handoff_artifact, materialize_artifact, register_artifact
from app.services.company_event_bus import emit_event, payload_of
from app.services.decision_loop import tick_decision_loop
from app.services.quality import evaluate_artifact
from app.services.simulation import run_simulation
from app.services.sla import monitor_sla
from app.services.trigger_engine import process_event

router = APIRouter(prefix="/v10", tags=["v10-event-driven-company"])


def _artifact(db: Session, artifact_id: int, principal: Principal) -> Artifact:
    item = db.get(Artifact, artifact_id)
    if not item: raise HTTPException(404, "Artifact not found")
    enforce_org(item.organization_id, principal)
    return item


def _event(db: Session, event_id: int, principal: Principal) -> CompanyEvent:
    item = db.get(CompanyEvent, event_id)
    if not item: raise HTTPException(404, "Company event not found")
    enforce_org(item.organization_id, principal)
    return item


@router.post("/events")
def create_event(payload: CompanyEventCreate, principal: Principal = Depends(require_scope("company.events:write")), db: Session = Depends(get_db)):
    enforce_org(payload.organization_id, principal)
    if payload.company_id is not None: ensure_company(db, payload.company_id, principal)
    return emit_event(
        db, organization_id=payload.organization_id, company_id=payload.company_id, event_type=payload.event_type,
        source=payload.source, aggregate_type=payload.aggregate_type, aggregate_id=payload.aggregate_id,
        correlation_id=payload.correlation_id, causation_id=payload.causation_id, payload=payload.payload,
    )


@router.get("/events")
def list_events(status: str | None = None, event_type: str | None = None, limit: int = Query(default=100, ge=1, le=500),
                principal: Principal = Depends(require_scope("company.events:read")), db: Session = Depends(get_db)):
    org_id = active_org(principal)
    q = db.query(CompanyEvent).filter(CompanyEvent.organization_id == org_id)
    if status: q = q.filter(CompanyEvent.status == status)
    if event_type: q = q.filter(CompanyEvent.event_type == event_type)
    return q.order_by(CompanyEvent.id.desc()).limit(limit).all()


@router.post("/events/{event_id}/dispatch")
def dispatch_event(event_id: int, principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    return process_event(db, _event(db, event_id, principal))


@router.post("/triggers")
def create_trigger(payload: EventTriggerCreate, principal: Principal = Depends(require_role("admin")), db: Session = Depends(get_db)):
    enforce_org(payload.organization_id, principal)
    if payload.company_id is not None: ensure_company(db, payload.company_id, principal)
    if payload.action_type not in {"message", "goal", "approval", "workflow"}:
        raise HTTPException(400, "action_type must be message, goal, approval or workflow")
    item = EventTrigger(
        organization_id=payload.organization_id, company_id=payload.company_id, name=payload.name,
        event_pattern=payload.event_pattern, condition_json=json.dumps(payload.condition, ensure_ascii=False),
        action_type=payload.action_type, action_json=json.dumps(payload.action, ensure_ascii=False),
        cooldown_seconds=payload.cooldown_seconds, enabled=payload.enabled,
    )
    db.add(item); db.commit(); db.refresh(item)
    return item


@router.get("/triggers")
def list_triggers(principal: Principal = Depends(require_human()), db: Session = Depends(get_db)):
    return db.query(EventTrigger).filter(EventTrigger.organization_id == active_org(principal)).order_by(EventTrigger.id.desc()).all()


@router.get("/trigger-executions")
def list_trigger_executions(limit: int = Query(default=100, ge=1, le=500), principal: Principal = Depends(require_human()), db: Session = Depends(get_db)):
    return db.query(TriggerExecution).filter(TriggerExecution.organization_id == active_org(principal)).order_by(TriggerExecution.id.desc()).limit(limit).all()


@router.post("/messages")
def create_message(payload: AgentMessageCreate, principal: Principal = Depends(require_scope("company.messages:write")), db: Session = Depends(get_db)):
    enforce_org(payload.organization_id, principal)
    if payload.company_id is not None: ensure_company(db, payload.company_id, principal)
    try:
        return send_message(db, **payload.model_dump())
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.get("/messages")
def list_messages(member_id: int | None = None, thread_key: str | None = None, unread_only: bool = False,
                  limit: int = Query(default=100, ge=1, le=500), principal: Principal = Depends(require_scope("company.messages:read")), db: Session = Depends(get_db)):
    org_id = active_org(principal)
    if member_id is not None: ensure_member(db, member_id, principal)
    q = db.query(AgentMessage).filter(AgentMessage.organization_id == org_id)
    if member_id is not None:
        q = q.filter((AgentMessage.sender_member_id == member_id) | (AgentMessage.recipient_member_id == member_id))
    if thread_key: q = q.filter(AgentMessage.thread_key == thread_key)
    if unread_only: q = q.filter(AgentMessage.status != "read")
    return q.order_by(AgentMessage.id.desc()).limit(limit).all()


@router.post("/messages/{message_id}/read")
def read_message(message_id: int, principal: Principal = Depends(require_scope("company.messages:write")), db: Session = Depends(get_db)):
    item = db.get(AgentMessage, message_id)
    if not item: raise HTTPException(404, "Message not found")
    enforce_org(item.organization_id, principal)
    return mark_read(db, item)


@router.post("/artifacts")
def create_artifact(payload: ArtifactCreate, principal: Principal = Depends(require_scope("company.artifacts:write")), db: Session = Depends(get_db)):
    enforce_org(payload.organization_id, principal)
    if payload.company_id is not None: ensure_company(db, payload.company_id, principal)
    if payload.task_id is not None: ensure_task(db, payload.task_id, principal)
    try:
        return register_artifact(db, **payload.model_dump())
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.get("/artifacts")
def list_artifacts(bundle_key: str | None = None, task_id: int | None = None, status: str | None = None,
                   limit: int = Query(default=100, ge=1, le=500), principal: Principal = Depends(require_scope("company.artifacts:read")), db: Session = Depends(get_db)):
    org_id = active_org(principal)
    q = db.query(Artifact).filter(Artifact.organization_id == org_id)
    if bundle_key: q = q.filter(Artifact.bundle_key == bundle_key)
    if task_id is not None:
        ensure_task(db, task_id, principal); q = q.filter(Artifact.task_id == task_id)
    if status: q = q.filter(Artifact.status == status)
    return q.order_by(Artifact.id.desc()).limit(limit).all()


@router.get("/artifacts/{artifact_id}")
def artifact_detail(artifact_id: int, principal: Principal = Depends(require_scope("company.artifacts:read")), db: Session = Depends(get_db)):
    artifact = _artifact(db, artifact_id, principal)
    handoffs = db.query(ArtifactHandoff).filter(ArtifactHandoff.artifact_id == artifact.id).order_by(ArtifactHandoff.id.desc()).all()
    evaluations = db.query(ArtifactEvaluation).filter(ArtifactEvaluation.artifact_id == artifact.id).order_by(ArtifactEvaluation.id.desc()).all()
    return {"artifact": artifact, "handoffs": handoffs, "evaluations": evaluations}


@router.post("/artifacts/{artifact_id}/handoff")
def artifact_handoff(artifact_id: int, payload: ArtifactHandoffCreate, principal: Principal = Depends(require_scope("company.artifacts:write")), db: Session = Depends(get_db)):
    artifact = _artifact(db, artifact_id, principal)
    ensure_member(db, payload.to_member_id, principal)
    if payload.from_member_id is not None: ensure_member(db, payload.from_member_id, principal)
    try:
        return handoff_artifact(db, artifact, **payload.model_dump())
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.get("/handoffs")
def list_handoffs(member_id: int | None = None, status: str | None = None,
                  principal: Principal = Depends(require_scope("company.artifacts:read")), db: Session = Depends(get_db)):
    org_id = active_org(principal)
    q = db.query(ArtifactHandoff).filter(ArtifactHandoff.organization_id == org_id)
    if member_id is not None:
        ensure_member(db, member_id, principal); q = q.filter(ArtifactHandoff.to_member_id == member_id)
    if status: q = q.filter(ArtifactHandoff.status == status)
    return q.order_by(ArtifactHandoff.id.desc()).limit(250).all()


@router.post("/handoffs/{handoff_id}/accept")
def handoff_accept(handoff_id: int, member_id: int, principal: Principal = Depends(require_scope("company.artifacts:write")), db: Session = Depends(get_db)):
    item = db.get(ArtifactHandoff, handoff_id)
    if not item: raise HTTPException(404, "Handoff not found")
    enforce_org(item.organization_id, principal); ensure_member(db, member_id, principal)
    try: return accept_handoff(db, item, member_id=member_id)
    except ValueError as exc: raise HTTPException(400, str(exc))


@router.post("/artifacts/{artifact_id}/materialize")
def materialize(artifact_id: int, principal: Principal = Depends(require_scope("company.artifacts:write")), db: Session = Depends(get_db)):
    artifact = _artifact(db, artifact_id, principal)
    try:
        path = materialize_artifact(artifact)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"artifact_id": artifact.id, "path": path, "sha256": artifact.content_sha256}


@router.post("/artifacts/{artifact_id}/evaluate")
def evaluate(artifact_id: int, payload: ArtifactEvaluationCreate, principal: Principal = Depends(require_scope("company.artifacts:write")), db: Session = Depends(get_db)):
    artifact = _artifact(db, artifact_id, principal)
    if payload.evaluator_member_id is not None: ensure_member(db, payload.evaluator_member_id, principal)
    try: return evaluate_artifact(db, artifact, **payload.model_dump())
    except ValueError as exc: raise HTTPException(400, str(exc))


@router.get("/evaluations")
def list_evaluations(verdict: str | None = None, principal: Principal = Depends(require_scope("company.artifacts:read")), db: Session = Depends(get_db)):
    org_id = active_org(principal)
    q = db.query(ArtifactEvaluation).filter(ArtifactEvaluation.organization_id == org_id)
    if verdict: q = q.filter(ArtifactEvaluation.verdict == verdict)
    return q.order_by(ArtifactEvaluation.id.desc()).limit(250).all()


@router.post("/sla-profiles")
def create_sla(payload: SLAProfileCreate, principal: Principal = Depends(require_role("admin")), db: Session = Depends(get_db)):
    enforce_org(payload.organization_id, principal)
    if payload.company_id is not None: ensure_company(db, payload.company_id, principal)
    if payload.escalation_target_member_id is not None: ensure_member(db, payload.escalation_target_member_id, principal)
    item = SLAProfile(**payload.model_dump())
    db.add(item); db.commit(); db.refresh(item); return item


@router.get("/sla-profiles")
def list_sla(principal: Principal = Depends(require_human()), db: Session = Depends(get_db)):
    return db.query(SLAProfile).filter(SLAProfile.organization_id == active_org(principal)).order_by(SLAProfile.id.desc()).all()


@router.post("/sla/check")
def sla_check(principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    items = monitor_sla(db, active_org(principal)); return {"created": len(items), "incidents": items}


@router.get("/sla-incidents")
def list_sla_incidents(status: str | None = None, principal: Principal = Depends(require_human()), db: Session = Depends(get_db)):
    q = db.query(SLAIncident).filter(SLAIncident.organization_id == active_org(principal))
    if status: q = q.filter(SLAIncident.status == status)
    return q.order_by(SLAIncident.id.desc()).limit(250).all()


@router.post("/decision-loops")
def create_loop(payload: DecisionLoopCreate, principal: Principal = Depends(require_role("admin")), db: Session = Depends(get_db)):
    enforce_org(payload.organization_id, principal)
    if payload.company_id is not None: ensure_company(db, payload.company_id, principal)
    item = DecisionLoop(
        organization_id=payload.organization_id, company_id=payload.company_id, name=payload.name, mode=payload.mode,
        interval_seconds=payload.interval_seconds, policy_json=json.dumps(payload.policy, ensure_ascii=False), enabled=payload.enabled,
    )
    db.add(item); db.commit(); db.refresh(item); return item


@router.get("/decision-loops")
def list_loops(principal: Principal = Depends(require_human()), db: Session = Depends(get_db)):
    return db.query(DecisionLoop).filter(DecisionLoop.organization_id == active_org(principal)).order_by(DecisionLoop.id.desc()).all()


@router.post("/decision-loops/{loop_id}/tick")
def tick_loop(loop_id: int, principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    item = db.get(DecisionLoop, loop_id)
    if not item: raise HTTPException(404, "Decision loop not found")
    enforce_org(item.organization_id, principal); return tick_decision_loop(db, item)


@router.get("/decision-loop-runs")
def list_loop_runs(principal: Principal = Depends(require_human()), db: Session = Depends(get_db)):
    return db.query(DecisionLoopRun).filter(DecisionLoopRun.organization_id == active_org(principal)).order_by(DecisionLoopRun.id.desc()).limit(250).all()


@router.post("/simulations")
def create_simulation(payload: SimulationScenarioCreate, principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    enforce_org(payload.organization_id, principal)
    if payload.company_id is not None: ensure_company(db, payload.company_id, principal)
    item = SimulationScenario(
        organization_id=payload.organization_id, company_id=payload.company_id, name=payload.name,
        description=payload.description, assumptions_json=json.dumps(payload.assumptions, ensure_ascii=False), status="draft",
    )
    db.add(item); db.commit(); db.refresh(item); return item


@router.get("/simulations")
def list_simulations(principal: Principal = Depends(require_human()), db: Session = Depends(get_db)):
    return db.query(SimulationScenario).filter(SimulationScenario.organization_id == active_org(principal)).order_by(SimulationScenario.id.desc()).all()


@router.post("/simulations/{scenario_id}/run")
def execute_simulation(scenario_id: int, principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    item = db.get(SimulationScenario, scenario_id)
    if not item: raise HTTPException(404, "Simulation scenario not found")
    enforce_org(item.organization_id, principal); return run_simulation(db, item)


@router.get("/simulation-runs")
def list_simulation_runs(principal: Principal = Depends(require_human()), db: Session = Depends(get_db)):
    return db.query(SimulationRun).filter(SimulationRun.organization_id == active_org(principal)).order_by(SimulationRun.id.desc()).limit(250).all()


@router.get("/founder-cockpit")
def founder_cockpit(principal: Principal = Depends(require_human()), db: Session = Depends(get_db)):
    org_id = active_org(principal)
    events = db.query(CompanyEvent).filter(CompanyEvent.organization_id == org_id).order_by(CompanyEvent.id.desc()).limit(12).all()
    messages = db.query(AgentMessage).filter(AgentMessage.organization_id == org_id).order_by(AgentMessage.id.desc()).limit(12).all()
    artifacts = db.query(Artifact).filter(Artifact.organization_id == org_id).order_by(Artifact.id.desc()).limit(12).all()
    evaluations = db.query(ArtifactEvaluation).filter(ArtifactEvaluation.organization_id == org_id).order_by(ArtifactEvaluation.id.desc()).limit(12).all()
    sla = db.query(SLAIncident).filter(SLAIncident.organization_id == org_id, SLAIncident.status.in_(["open", "escalated"])).order_by(SLAIncident.id.desc()).limit(12).all()
    decision_runs = db.query(DecisionLoopRun).filter(DecisionLoopRun.organization_id == org_id).order_by(DecisionLoopRun.id.desc()).limit(5).all()
    since_24h = datetime.utcnow() - timedelta(days=1)
    return {
        "metrics": {
            "pending_events": db.query(CompanyEvent).filter(CompanyEvent.organization_id == org_id, CompanyEvent.status == "pending").count(),
            "messages_24h": db.query(AgentMessage).filter(AgentMessage.organization_id == org_id, AgentMessage.created_at >= since_24h).count(),
            "ready_artifacts": db.query(Artifact).filter(Artifact.organization_id == org_id, Artifact.status == "ready").count(),
            "qa_changes_requested": db.query(ArtifactEvaluation).filter(ArtifactEvaluation.organization_id == org_id, ArtifactEvaluation.verdict == "changes_requested").count(),
            "sla_breaches": len(sla),
            "open_recovery_incidents": db.query(RecoveryIncident).filter(RecoveryIncident.organization_id == org_id, RecoveryIncident.status.in_(["open", "retrying"])).count(),
            "pending_approvals": db.query(Approval).filter(Approval.organization_id == org_id, Approval.status == "pending").count(),
            "active_goals": db.query(ExecutiveGoal).filter(ExecutiveGoal.organization_id == org_id, ExecutiveGoal.status.notin_(["completed", "cancelled"])).count(),
        },
        "events": [{"id":e.id,"event_type":e.event_type,"source":e.source,"status":e.status,"occurred_at":e.occurred_at,"payload":payload_of(e)} for e in events],
        "messages": messages, "artifacts": artifacts, "evaluations": evaluations, "sla_incidents": sla,
        "decision_runs": [{"id":r.id,"loop_id":r.loop_id,"snapshot":json.loads(r.snapshot_json or "{}"),"decisions":json.loads(r.decisions_json or "[]"),"created_at":r.created_at} for r in decision_runs],
    }
