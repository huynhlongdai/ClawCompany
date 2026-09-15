import json
from datetime import datetime, timedelta
from sqlalchemy.orm import Session

from app.models import (
    Agent, Approval, AutonomyPolicy, BudgetEnvelope, BudgetLedgerEntry, DelegationAssignment, ExecutiveGoal, Member,
    NinaPlanStep, OperatingCycle, OrganizationMemory, RecoveryIncident, RuntimeEvent, Task,
)
from app.runtime.factory import get_runtime
from app.services.audit import log_event
from app.services.autonomy import get_policy, risk_allowed
from app.services.budget import can_reserve, reserve, settle_reserved, release_reserved
from app.services.nina_planner import create_plan
from app.services.org_memory import remember, search_memories
from app.services.runtime_events import persist_runtime_event
from app.services.artifacts import register_artifact
from app.services.tasks import dispatch_task

TERMINAL_COMPLETE = {"run.completed", "completed", "run.complete"}
TERMINAL_FAILED = {"run.failed", "run.error", "failed", "error"}


def _json(value: str | None, fallback):
    try:
        return json.loads(value or "")
    except Exception:
        return fallback


def _snapshot(cycle: OperatingCycle) -> dict:
    return _json(cycle.snapshot_json, {})


def _set_snapshot(cycle: OperatingCycle, data: dict):
    cycle.snapshot_json = json.dumps(data, ensure_ascii=False, default=str)


def create_goal(db: Session, *, organization_id: int, user_id: int | None, company_id: int | None,
                title: str, objective: str, expected_outcome: str = "", priority: str = "high", risk: str = "medium",
                autonomy_mode: str = "inherit", deadline: str = "", budget_limit: float | None = None,
                currency: str = "USD") -> ExecutiveGoal:
    goal = ExecutiveGoal(
        organization_id=organization_id, company_id=company_id, created_by_user_id=user_id, title=title,
        objective=objective, expected_outcome=expected_outcome, priority=priority, risk=risk,
        autonomy_mode=autonomy_mode, status="draft", progress=0, deadline=deadline,
    )
    db.add(goal); db.commit(); db.refresh(goal)
    if budget_limit is not None:
        budget = BudgetEnvelope(
            organization_id=organization_id, company_id=company_id, goal_id=goal.id,
            name=f"Goal #{goal.id} · {title[:80]}", currency=currency, amount_limit=budget_limit, status="active",
        )
        db.add(budget); db.commit()
    log_event(db, organization_id, "goal.create", "executive_goals", goal.id, actor_name="Founder", payload={"title": title, "risk": risk})
    return goal


def plan_goal(db: Session, goal: ExecutiveGoal, *, user_id: int | None, max_steps: int = 5,
              project_id: int | None = None, auto_create_tasks: bool = True):
    relevant_memory = search_memories(db, goal.organization_id, goal.objective, limit=5, company_id=goal.company_id)
    plan, steps = create_plan(
        db, organization_id=goal.organization_id, user_id=user_id, objective=goal.objective,
        company_id=goal.company_id, project_id=project_id, auto_create_tasks=auto_create_tasks, max_steps=max_steps,
    )
    strategy = _json(plan.strategy_json, {})
    strategy["memory_context"] = [
        {"id": m.id, "type": m.memory_type, "content": m.content[:1200], "importance": m.importance, "confidence": m.confidence}
        for m in relevant_memory
    ]
    plan.strategy_json = json.dumps(strategy, ensure_ascii=False)
    if relevant_memory:
        plan.summary = f"{plan.summary} Grounded with {len(relevant_memory)} organizational memory item(s)."
    db.add(plan); db.commit(); db.refresh(plan)
    goal.execution_plan_id = plan.id
    goal.status = "planned"
    db.add(goal); db.commit(); db.refresh(goal)
    remember(
        db, organization_id=goal.organization_id, company_id=goal.company_id, memory_type="goal",
        content=f"Executive goal '{goal.title}': {goal.objective}", source_type="executive_goal", source_id=str(goal.id),
        importance=5, confidence=1.0, tags=["goal", goal.priority, goal.risk],
    )
    return plan, steps


def _goal_budget(db: Session, goal_id: int) -> BudgetEnvelope | None:
    return db.query(BudgetEnvelope).filter(BudgetEnvelope.goal_id == goal_id, BudgetEnvelope.status == "active").order_by(BudgetEnvelope.id.desc()).first()


def _ensure_approval(db: Session, goal: ExecutiveGoal, cycle: OperatingCycle, reason: str) -> Approval:
    snap = _snapshot(cycle)
    approval_id = snap.get("approval_id")
    approval = db.get(Approval, approval_id) if approval_id else None
    if approval:
        return approval
    approval = Approval(
        organization_id=goal.organization_id, company_id=goal.company_id, action=f"goal.execute:{goal.id}",
        risk=goal.risk, policy_key="autonomy.goal.execute", status="pending",
        evidence=json.dumps({"goal_id": goal.id, "cycle_id": cycle.id, "reason": reason}, ensure_ascii=False),
    )
    db.add(approval); db.commit(); db.refresh(approval)
    snap["approval_id"] = approval.id
    snap["approval_reason"] = reason
    _set_snapshot(cycle, snap); cycle.status = "waiting_approval"; db.add(cycle); db.commit(); db.refresh(cycle)
    return approval


def create_cycle(db: Session, goal: ExecutiveGoal, *, estimated_cost_per_assignment: float = 0.25) -> OperatingCycle:
    if not goal.execution_plan_id:
        raise ValueError("Goal must be planned before execution")
    policy = get_policy(db, goal.organization_id, goal.company_id)
    mode = goal.autonomy_mode if goal.autonomy_mode and goal.autonomy_mode != "inherit" else policy.mode
    cycle = OperatingCycle(
        organization_id=goal.organization_id, goal_id=goal.id, status="queued", mode=mode,
        started_at=datetime.utcnow(), snapshot_json=json.dumps({
            "policy_id": policy.id, "policy_mode": policy.mode, "max_auto_risk": policy.max_auto_risk,
            "estimated_cost_per_assignment": estimated_cost_per_assignment,
        }),
    )
    db.add(cycle); db.commit(); db.refresh(cycle)
    steps = db.query(NinaPlanStep).filter(NinaPlanStep.plan_id == goal.execution_plan_id).order_by(NinaPlanStep.step_index).all()
    for step in steps:
        parent_member_id = None
        if step.owner_member_id:
            owner = db.get(Member, step.owner_member_id)
            parent_member_id = owner.manager_id if owner else None
        assignment = DelegationAssignment(
            organization_id=goal.organization_id, cycle_id=cycle.id, goal_id=goal.id, plan_step_id=step.id,
            parent_member_id=parent_member_id, assignee_member_id=step.owner_member_id, task_id=step.task_id,
            depth=0 if parent_member_id is None else 1, instruction=f"{step.title}\n\n{step.description}",
            status="queued", max_attempts=max(1, policy.retry_limit + 1), estimated_cost=estimated_cost_per_assignment,
        )
        db.add(assignment)
    db.commit()
    if mode == "manual":
        _ensure_approval(db, goal, cycle, "Organization autonomy mode is manual")
    elif not risk_allowed(goal.risk, policy.max_auto_risk):
        _ensure_approval(db, goal, cycle, f"Goal risk '{goal.risk}' exceeds auto-execution threshold '{policy.max_auto_risk}'")
    else:
        cycle.status = "running"; goal.status = "running"; db.add_all([cycle, goal]); db.commit()
    log_event(db, goal.organization_id, "operating_cycle.create", "operating_cycles", cycle.id, actor_name="Nina", payload={"goal_id": goal.id, "mode": mode})
    return cycle


def _dependencies_complete(db: Session, assignment: DelegationAssignment, cycle: OperatingCycle) -> bool:
    if not assignment.plan_step_id:
        return True
    step = db.get(NinaPlanStep, assignment.plan_step_id)
    if not step:
        return True
    dep_indexes = _json(step.dependency_step_ids_json, [])
    if not dep_indexes:
        return True
    all_steps = db.query(NinaPlanStep).filter(NinaPlanStep.plan_id == step.plan_id).all()
    by_index = {s.step_index: s for s in all_steps}
    dep_step_ids = [by_index[i].id for i in dep_indexes if i in by_index]
    if not dep_step_ids:
        return True
    deps = db.query(DelegationAssignment).filter(
        DelegationAssignment.cycle_id == cycle.id,
        DelegationAssignment.plan_step_id.in_(dep_step_ids),
    ).all()
    return len(deps) == len(dep_step_ids) and all(d.status == "completed" for d in deps)


def _incident(db: Session, *, goal: ExecutiveGoal, cycle: OperatingCycle, assignment: DelegationAssignment, error: str,
              severity: str = "medium", incident_type: str = "runtime_failure") -> RecoveryIncident:
    existing = db.query(RecoveryIncident).filter(
        RecoveryIncident.assignment_id == assignment.id,
        RecoveryIncident.status.in_(["open", "retrying"]),
    ).order_by(RecoveryIncident.id.desc()).first()
    if existing:
        return existing
    agent_id = None
    if assignment.assignee_member_id:
        agent = db.query(Agent).filter(Agent.member_id == assignment.assignee_member_id).first()
        agent_id = agent.id if agent else None
    item = RecoveryIncident(
        organization_id=goal.organization_id, goal_id=goal.id, cycle_id=cycle.id, assignment_id=assignment.id,
        task_id=assignment.task_id, agent_id=agent_id, runtime_run_id=assignment.runtime_run_id,
        incident_type=incident_type, severity=severity, status="open", error=error,
        retry_count=max(0, assignment.attempt_count - 1), max_retries=max(0, assignment.max_attempts - 1),
    )
    db.add(item); db.commit(); db.refresh(item)
    log_event(db, goal.organization_id, "recovery.incident.open", "recovery_incidents", item.id, actor_name="runtime", result="failed", risk=severity, payload={"assignment_id": assignment.id, "error": error})
    return item


def _terminal_event(db: Session, assignment: DelegationAssignment) -> RuntimeEvent | None:
    if not assignment.runtime_run_id:
        return None
    return db.query(RuntimeEvent).filter(RuntimeEvent.runtime_run_id == assignment.runtime_run_id).order_by(RuntimeEvent.id.desc()).first()


def _extract_output(event: RuntimeEvent | None) -> str:
    if not event:
        return ""
    payload = _json(event.event_json, {})
    result = payload.get("result")
    if isinstance(result, dict):
        return str(result.get("output") or result.get("content") or result.get("text") or "")
    if isinstance(result, str):
        return result
    return str(payload.get("content") or payload.get("message") or "")


async def _capture_run(db: Session, goal: ExecutiveGoal, assignment: DelegationAssignment):
    if not assignment.runtime_run_id:
        return
    agent = db.query(Agent).join(Member, Agent.member_id == Member.id).filter(Member.id == assignment.assignee_member_id).first() if assignment.assignee_member_id else None
    async for event in get_runtime().stream_run(assignment.runtime_run_id):
        persist_runtime_event(
            db, organization_id=goal.organization_id, run_id=assignment.runtime_run_id, event=event,
            agent_id=agent.id if agent else None, task_id=assignment.task_id,
        )


def _source_reserved_outstanding(db: Session, budget_id: int, source_id: str) -> float:
    rows = db.query(BudgetLedgerEntry).filter(
        BudgetLedgerEntry.budget_id == budget_id,
        BudgetLedgerEntry.source_type == "delegation",
        BudgetLedgerEntry.source_id == source_id,
    ).all()
    reserved = sum(float(x.amount or 0) for x in rows if x.entry_type == "reserve")
    consumed = sum(float(x.amount or 0) for x in rows if x.entry_type in {"spend", "release"})
    return max(0.0, reserved - consumed)


def _settle_assignment_budget(db: Session, goal: ExecutiveGoal, assignment: DelegationAssignment, completed: bool):
    budget = _goal_budget(db, goal.id)
    if not budget or assignment.estimated_cost <= 0:
        return
    source_id = str(assignment.id)
    outstanding = _source_reserved_outstanding(db, budget.id, source_id)
    if outstanding <= 0:
        return
    amount = min(float(assignment.estimated_cost), outstanding)
    if completed:
        settle_reserved(db, budget, amount, source_type="delegation", source_id=source_id, memo="AI assignment completed")
    else:
        release_reserved(db, budget, amount, source_type="delegation", source_id=source_id, memo="AI assignment reservation released")


def _daily_budget_commitment(db: Session, organization_id: int) -> float:
    start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    rows = db.query(BudgetLedgerEntry).filter(
        BudgetLedgerEntry.organization_id == organization_id,
        BudgetLedgerEntry.created_at >= start,
    ).all()
    by_source: dict[tuple[int, str, str], dict[str, float]] = {}
    for row in rows:
        key = (row.budget_id, row.source_type or "", row.source_id or "")
        slot = by_source.setdefault(key, {"reserve": 0.0, "release": 0.0, "spend": 0.0})
        if row.entry_type in slot:
            slot[row.entry_type] += float(row.amount or 0)
    total = 0.0
    for values in by_source.values():
        outstanding = max(0.0, values["reserve"] - values["release"] - values["spend"])
        total += values["spend"] + outstanding
    return total


async def _dispatch_ready(db: Session, goal: ExecutiveGoal, cycle: OperatingCycle, policy: AutonomyPolicy):
    active = db.query(DelegationAssignment).filter(
        DelegationAssignment.cycle_id == cycle.id,
        DelegationAssignment.status.in_(["running", "delegated"]),
    ).count()
    capacity = max(0, policy.max_concurrent_runs - active)
    if capacity <= 0:
        return 0
    budget = _goal_budget(db, goal.id)
    dispatched = 0
    rows = db.query(DelegationAssignment).filter(
        DelegationAssignment.cycle_id == cycle.id,
        DelegationAssignment.status == "queued",
    ).order_by(DelegationAssignment.id).all()
    for assignment in rows:
        if dispatched >= capacity:
            break
        if not _dependencies_complete(db, assignment, cycle):
            continue
        if not assignment.task_id or not assignment.assignee_member_id:
            assignment.status = "blocked"; db.add(assignment); db.commit(); continue
        daily_committed = _daily_budget_commitment(db, goal.organization_id)
        if policy.daily_budget_limit > 0 and daily_committed + assignment.estimated_cost > policy.daily_budget_limit:
            assignment.status = "budget_blocked"; db.add(assignment); db.commit()
            _incident(
                db, goal=goal, cycle=cycle, assignment=assignment,
                error=f"Daily AI budget limit exceeded: committed {daily_committed:.2f}, action {assignment.estimated_cost:.2f}, limit {policy.daily_budget_limit:.2f}",
                severity="high", incident_type="daily_budget_limit",
            )
            continue
        if policy.per_action_limit > 0 and assignment.estimated_cost > policy.per_action_limit:
            assignment.status = "budget_blocked"; db.add(assignment); db.commit()
            _incident(db, goal=goal, cycle=cycle, assignment=assignment, error="Per-action budget limit exceeded", severity="high", incident_type="budget_limit")
            continue
        if budget and assignment.estimated_cost > 0:
            outstanding = _source_reserved_outstanding(db, budget.id, str(assignment.id))
            if outstanding <= 0:
                ok, reason = can_reserve(budget, assignment.estimated_cost)
                if not ok:
                    assignment.status = "budget_blocked"; db.add(assignment); db.commit()
                    _incident(db, goal=goal, cycle=cycle, assignment=assignment, error=reason, severity="high", incident_type="budget_limit")
                    continue
                reserve(db, budget, assignment.estimated_cost, source_type="delegation", source_id=str(assignment.id), memo="AI assignment reservation")
        task = db.get(Task, assignment.task_id)
        if not task:
            assignment.status = "failed"; db.add(assignment); db.commit()
            _incident(db, goal=goal, cycle=cycle, assignment=assignment, error="Task not found")
            continue
        try:
            assignment.attempt_count += 1
            assignment.started_at = datetime.utcnow()
            await dispatch_task(db, task)
            assignment.runtime_run_id = task.runtime_run_id or ""
            assignment.status = "running"
            db.add(assignment); db.commit(); db.refresh(assignment)
            dispatched += 1
        except Exception as exc:
            assignment.status = "failed"; db.add(assignment); db.commit()
            _settle_assignment_budget(db, goal, assignment, False)
            _incident(db, goal=goal, cycle=cycle, assignment=assignment, error=str(exc))
    return dispatched


def _auto_retry(db: Session, goal: ExecutiveGoal, cycle: OperatingCycle, policy: AutonomyPolicy):
    if cycle.mode != "autonomous":
        return 0
    retried = 0
    incidents = db.query(RecoveryIncident).filter(
        RecoveryIncident.cycle_id == cycle.id,
        RecoveryIncident.status == "open",
    ).all()
    for incident in incidents:
        assignment = db.get(DelegationAssignment, incident.assignment_id) if incident.assignment_id else None
        if not assignment:
            continue
        if assignment.attempt_count >= assignment.max_attempts:
            continue
        if incident.severity in {"high", "critical"} and policy.pause_on_high_incident:
            continue
        incident.status = "retrying"; incident.retry_count += 1
        assignment.status = "queued"; assignment.runtime_run_id = ""
        if assignment.task_id:
            task = db.get(Task, assignment.task_id)
            if task:
                task.status = "backlog"; task.runtime_run_id = None; db.add(task)
        db.add_all([incident, assignment]); db.commit(); retried += 1
    return retried


async def tick_cycle(db: Session, cycle: OperatingCycle, *, capture_runtime: bool = True):
    goal = db.get(ExecutiveGoal, cycle.goal_id)
    if not goal:
        raise ValueError("Goal not found")
    policy = get_policy(db, goal.organization_id, goal.company_id)
    snap = _snapshot(cycle)
    approval = db.get(Approval, snap.get("approval_id")) if snap.get("approval_id") else None
    if cycle.status == "waiting_approval":
        if not approval or approval.status == "pending":
            return summarize_cycle(db, cycle)
        if approval.status not in {"approved", "approve"}:
            cycle.status = "cancelled"; goal.status = "blocked"; cycle.completed_at = datetime.utcnow()
            db.add_all([cycle, goal]); db.commit()
            return summarize_cycle(db, cycle)
        cycle.status = "running"; goal.status = "running"; db.add_all([cycle, goal]); db.commit()

    running = db.query(DelegationAssignment).filter(
        DelegationAssignment.cycle_id == cycle.id,
        DelegationAssignment.status == "running",
    ).all()
    for assignment in running:
        latest = _terminal_event(db, assignment)
        typ = latest.event_type if latest else ""
        if capture_runtime and typ not in TERMINAL_COMPLETE | TERMINAL_FAILED:
            try:
                await _capture_run(db, goal, assignment)
                latest = _terminal_event(db, assignment); typ = latest.event_type if latest else ""
            except Exception as exc:
                typ = "run.failed"
                _incident(db, goal=goal, cycle=cycle, assignment=assignment, error=str(exc))
        if typ in TERMINAL_COMPLETE:
            assignment.status = "completed"; assignment.completed_at = datetime.utcnow()
            if assignment.task_id:
                task = db.get(Task, assignment.task_id)
                if task: task.status = "done"; db.add(task)
            if assignment.plan_step_id:
                step = db.get(NinaPlanStep, assignment.plan_step_id)
                if step: step.status = "completed"; db.add(step)
            db.add(assignment); db.commit(); _settle_assignment_budget(db, goal, assignment, True)
            output = _extract_output(latest)
            if output:
                remember(
                    db, organization_id=goal.organization_id, company_id=goal.company_id, memory_type="execution_result",
                    content=f"Goal '{goal.title}' execution result: {output[:8000]}", source_type="delegation",
                    source_id=str(assignment.id), importance=4, confidence=0.9, tags=["execution", "result"],
                )
                producer_agent = db.query(Agent).filter(Agent.member_id == assignment.assignee_member_id).first() if assignment.assignee_member_id else None
                register_artifact(
                    db, organization_id=goal.organization_id, company_id=goal.company_id, task_id=assignment.task_id,
                    created_by_member_id=assignment.assignee_member_id, created_by_agent_id=producer_agent.id if producer_agent else None,
                    runtime_run_id=assignment.runtime_run_id, bundle_key=f"goal-{goal.id}",
                    logical_path=f"tasks/{assignment.task_id or assignment.id}/result.md",
                    name=f"Execution result · {assignment.id}", artifact_type="runtime_output", mime_type="text/markdown",
                    content_text=output, metadata={"goal_id": goal.id, "cycle_id": cycle.id, "assignment_id": assignment.id},
                )
        elif typ in TERMINAL_FAILED:
            assignment.status = "failed"; assignment.completed_at = datetime.utcnow(); db.add(assignment); db.commit()
            _settle_assignment_budget(db, goal, assignment, False)
            _incident(db, goal=goal, cycle=cycle, assignment=assignment, error=_extract_output(latest) or typ)

    _auto_retry(db, goal, cycle, policy)
    if cycle.status == "running":
        await _dispatch_ready(db, goal, cycle, policy)

    rows = db.query(DelegationAssignment).filter(DelegationAssignment.cycle_id == cycle.id).all()
    total = len(rows); completed = sum(1 for x in rows if x.status == "completed")
    failed = sum(1 for x in rows if x.status in {"failed", "budget_blocked"})
    goal.progress = int((completed / total) * 100) if total else 0
    if total and completed == total:
        cycle.status = "completed"; cycle.completed_at = datetime.utcnow(); goal.status = "completed"; goal.progress = 100
        remember(
            db, organization_id=goal.organization_id, company_id=goal.company_id, memory_type="outcome",
            content=f"Executive goal '{goal.title}' completed successfully.", source_type="executive_goal", source_id=str(goal.id),
            importance=5, confidence=1.0, tags=["goal", "completed"],
        )
    elif failed and not any(x.status in {"queued", "running"} for x in rows):
        cycle.status = "needs_attention"; goal.status = "needs_attention"
    db.add_all([goal, cycle]); db.commit(); db.refresh(cycle); db.refresh(goal)
    return summarize_cycle(db, cycle)


def summarize_cycle(db: Session, cycle: OperatingCycle):
    rows = db.query(DelegationAssignment).filter(DelegationAssignment.cycle_id == cycle.id).order_by(DelegationAssignment.id).all()
    incidents = db.query(RecoveryIncident).filter(RecoveryIncident.cycle_id == cycle.id).order_by(RecoveryIncident.id.desc()).all()
    return {
        "cycle": cycle,
        "assignments": rows,
        "incidents": incidents,
        "counts": {
            "total": len(rows), "completed": sum(1 for x in rows if x.status == "completed"),
            "running": sum(1 for x in rows if x.status == "running"),
            "blocked": sum(1 for x in rows if x.status in {"blocked", "budget_blocked"}),
            "failed": sum(1 for x in rows if x.status == "failed"),
        },
    }


def retry_incident(db: Session, incident: RecoveryIncident, *, force: bool = False):
    assignment = db.get(DelegationAssignment, incident.assignment_id) if incident.assignment_id else None
    if not assignment:
        raise ValueError("Incident has no delegation assignment")
    if not force and assignment.attempt_count >= assignment.max_attempts:
        raise ValueError("Retry limit reached")
    goal = db.get(ExecutiveGoal, assignment.goal_id)
    if not goal:
        raise ValueError("Goal not found")
    _settle_assignment_budget(db, goal, assignment, False)
    incident.status = "retrying"
    incident.retry_count += 1
    assignment.status = "queued"
    assignment.runtime_run_id = ""
    if assignment.task_id:
        task = db.get(Task, assignment.task_id)
        if task:
            task.status = "backlog"
            task.runtime_run_id = None
            task.runtime_task_id = None
            db.add(task)
    db.add_all([incident, assignment]); db.commit(); db.refresh(incident); db.refresh(assignment)
    return incident, assignment
