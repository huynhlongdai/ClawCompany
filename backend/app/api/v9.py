import json
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.authz import Principal, enforce_org, require_human, require_role
from app.core.tenancy import active_org, ensure_company, ensure_department, ensure_project, ensure_agent
from app.db.session import get_db
from app.models import (
    Agent, Approval, AutonomyPolicy, BudgetEnvelope, BudgetLedgerEntry, DelegationAssignment, ExecutiveGoal,
    Member, OperatingCycle, OrganizationMemory, RecoveryIncident, RecurringOperation, RuntimeEvent, UsageEvent,
)
from app.schemas.v9 import (
    AutonomyPolicyUpsert, BudgetEntryCreate, BudgetEnvelopeCreate, ExecutiveGoalCreate, GoalPlanRequest,
    GoalRunRequest, IncidentRetryRequest, MemoryCreate, RecurringOperationCreate,
)
from app.services.autonomy import get_policy
from app.services.budget import remaining, reserve, settle_reserved, release_reserved
from app.services.orchestration import create_goal, plan_goal, create_cycle, tick_cycle, retry_incident, summarize_cycle
from app.services.org_memory import remember, search_memories
from app.services.recurring_ops import create_recurring_operation, execute_operation

router = APIRouter(prefix="/v9", tags=["v9-autonomous-ops"])


def _goal(db: Session, goal_id: int, principal: Principal) -> ExecutiveGoal:
    item = db.get(ExecutiveGoal, goal_id)
    if not item:
        raise HTTPException(404, "Goal not found")
    enforce_org(item.organization_id, principal)
    return item


def _cycle(db: Session, cycle_id: int, principal: Principal) -> OperatingCycle:
    item = db.get(OperatingCycle, cycle_id)
    if not item:
        raise HTTPException(404, "Operating cycle not found")
    enforce_org(item.organization_id, principal)
    return item


def _budget(db: Session, budget_id: int, principal: Principal) -> BudgetEnvelope:
    item = db.get(BudgetEnvelope, budget_id)
    if not item:
        raise HTTPException(404, "Budget not found")
    enforce_org(item.organization_id, principal)
    return item


@router.get("/autonomy-policy")
def read_autonomy_policy(company_id: int | None = None, principal: Principal = Depends(require_human()), db: Session = Depends(get_db)):
    org_id = active_org(principal)
    if company_id is not None:
        ensure_company(db, company_id, principal)
    return get_policy(db, org_id, company_id)


@router.put("/autonomy-policy")
def upsert_autonomy_policy(payload: AutonomyPolicyUpsert, principal: Principal = Depends(require_role("admin")), db: Session = Depends(get_db)):
    enforce_org(payload.organization_id, principal)
    if payload.company_id is not None:
        ensure_company(db, payload.company_id, principal)
    obj = db.query(AutonomyPolicy).filter(
        AutonomyPolicy.organization_id == payload.organization_id,
        AutonomyPolicy.company_id == payload.company_id if payload.company_id is not None else AutonomyPolicy.company_id.is_(None),
    ).order_by(AutonomyPolicy.id.desc()).first()
    if not obj:
        obj = AutonomyPolicy(organization_id=payload.organization_id, company_id=payload.company_id)
    for key, value in payload.model_dump().items():
        setattr(obj, key, value)
    db.add(obj); db.commit(); db.refresh(obj)
    return obj


@router.post("/goals")
def create_executive_goal(payload: ExecutiveGoalCreate, principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    enforce_org(payload.organization_id, principal)
    if payload.company_id is not None:
        ensure_company(db, payload.company_id, principal)
    return create_goal(db, organization_id=payload.organization_id, user_id=principal.user_id, **payload.model_dump(exclude={"organization_id"}))


@router.get("/goals")
def list_goals(status: str | None = None, principal: Principal = Depends(require_human()), db: Session = Depends(get_db)):
    org_id = active_org(principal)
    q = db.query(ExecutiveGoal).filter(ExecutiveGoal.organization_id == org_id)
    if status:
        q = q.filter(ExecutiveGoal.status == status)
    return q.order_by(ExecutiveGoal.id.desc()).all()


@router.get("/goals/{goal_id}")
def goal_detail(goal_id: int, principal: Principal = Depends(require_human()), db: Session = Depends(get_db)):
    goal = _goal(db, goal_id, principal)
    budget = db.query(BudgetEnvelope).filter(BudgetEnvelope.goal_id == goal.id).order_by(BudgetEnvelope.id.desc()).first()
    cycles = db.query(OperatingCycle).filter(OperatingCycle.goal_id == goal.id).order_by(OperatingCycle.id.desc()).all()
    return {"goal": goal, "budget": budget, "cycles": cycles}


@router.post("/goals/{goal_id}/plan")
def generate_goal_plan(goal_id: int, payload: GoalPlanRequest, principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    goal = _goal(db, goal_id, principal)
    if payload.project_id is not None:
        ensure_project(db, payload.project_id, principal)
    try:
        plan, steps = plan_goal(db, goal, user_id=principal.user_id, **payload.model_dump())
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"goal": goal, "plan": plan, "steps": steps}


@router.post("/goals/{goal_id}/run")
async def run_goal(goal_id: int, payload: GoalRunRequest, principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    goal = _goal(db, goal_id, principal)
    try:
        cycle = create_cycle(db, goal, estimated_cost_per_assignment=payload.estimated_cost_per_assignment)
        # First tick dispatches dependency-free assignments when policy allows it.
        return await tick_cycle(db, cycle, capture_runtime=False)
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.get("/cycles")
def list_cycles(status: str | None = None, principal: Principal = Depends(require_human()), db: Session = Depends(get_db)):
    org_id = active_org(principal)
    q = db.query(OperatingCycle).filter(OperatingCycle.organization_id == org_id)
    if status:
        q = q.filter(OperatingCycle.status == status)
    return q.order_by(OperatingCycle.id.desc()).limit(100).all()


@router.get("/cycles/{cycle_id}")
def cycle_detail(cycle_id: int, principal: Principal = Depends(require_human()), db: Session = Depends(get_db)):
    cycle = _cycle(db, cycle_id, principal)
    return summarize_cycle(db, cycle)


@router.post("/cycles/{cycle_id}/tick")
async def cycle_tick(cycle_id: int, capture_runtime: bool = True, principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    cycle = _cycle(db, cycle_id, principal)
    try:
        return await tick_cycle(db, cycle, capture_runtime=capture_runtime)
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.get("/delegations")
def list_delegations(cycle_id: int | None = None, principal: Principal = Depends(require_human()), db: Session = Depends(get_db)):
    org_id = active_org(principal)
    q = db.query(DelegationAssignment).filter(DelegationAssignment.organization_id == org_id)
    if cycle_id is not None:
        cycle = _cycle(db, cycle_id, principal)
        q = q.filter(DelegationAssignment.cycle_id == cycle.id)
    return q.order_by(DelegationAssignment.id.desc()).limit(250).all()


@router.post("/budgets")
def create_budget(payload: BudgetEnvelopeCreate, principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    enforce_org(payload.organization_id, principal)
    if payload.company_id is not None:
        ensure_company(db, payload.company_id, principal)
    if payload.goal_id is not None:
        _goal(db, payload.goal_id, principal)
    item = BudgetEnvelope(**payload.model_dump(), amount_reserved=0, amount_spent=0, status="active")
    db.add(item); db.commit(); db.refresh(item)
    return item


@router.get("/budgets")
def list_budgets(principal: Principal = Depends(require_human()), db: Session = Depends(get_db)):
    org_id = active_org(principal)
    rows = db.query(BudgetEnvelope).filter(BudgetEnvelope.organization_id == org_id).order_by(BudgetEnvelope.id.desc()).all()
    return [{"budget": x, "remaining": remaining(x)} for x in rows]


@router.get("/budgets/{budget_id}")
def budget_detail(budget_id: int, principal: Principal = Depends(require_human()), db: Session = Depends(get_db)):
    budget = _budget(db, budget_id, principal)
    ledger = db.query(BudgetLedgerEntry).filter(BudgetLedgerEntry.budget_id == budget.id).order_by(BudgetLedgerEntry.id.desc()).all()
    return {"budget": budget, "remaining": remaining(budget), "ledger": ledger}


@router.post("/budgets/{budget_id}/entries")
def budget_entry(budget_id: int, payload: BudgetEntryCreate, principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    budget = _budget(db, budget_id, principal)
    try:
        if payload.entry_type == "reserve":
            entry = reserve(db, budget, payload.amount, source_type=payload.source_type, source_id=payload.source_id, memo=payload.memo)
        elif payload.entry_type == "spend":
            entry = settle_reserved(db, budget, payload.amount, source_type=payload.source_type, source_id=payload.source_id, memo=payload.memo)
        elif payload.entry_type == "release":
            entry = release_reserved(db, budget, payload.amount, source_type=payload.source_type, source_id=payload.source_id, memo=payload.memo)
        else:
            raise ValueError("entry_type must be reserve, spend or release")
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"entry": entry, "budget": budget, "remaining": remaining(budget)}


@router.post("/memory")
def create_memory(payload: MemoryCreate, principal: Principal = Depends(require_role("member")), db: Session = Depends(get_db)):
    enforce_org(payload.organization_id, principal)
    if payload.company_id is not None: ensure_company(db, payload.company_id, principal)
    if payload.department_id is not None: ensure_department(db, payload.department_id, principal)
    if payload.project_id is not None: ensure_project(db, payload.project_id, principal)
    if payload.agent_id is not None: ensure_agent(db, payload.agent_id, principal)
    return remember(db, organization_id=payload.organization_id, **payload.model_dump(exclude={"organization_id"}))


@router.get("/memory/search")
def memory_search(q: str = "", company_id: int | None = None, limit: int = Query(default=20, ge=1, le=100), principal: Principal = Depends(require_human()), db: Session = Depends(get_db)):
    org_id = active_org(principal)
    if company_id is not None: ensure_company(db, company_id, principal)
    return search_memories(db, org_id, q, limit, company_id)


@router.post("/recurring-operations")
def create_recurring(payload: RecurringOperationCreate, principal: Principal = Depends(require_role("admin")), db: Session = Depends(get_db)):
    enforce_org(payload.organization_id, principal)
    if payload.company_id is not None: ensure_company(db, payload.company_id, principal)
    try:
        return create_recurring_operation(
            db, organization_id=payload.organization_id, company_id=payload.company_id, name=payload.name,
            schedule=payload.schedule, timezone_name=payload.timezone, operation_type=payload.operation_type,
            payload=payload.payload, enabled=payload.enabled,
        )
    except Exception as exc:
        raise HTTPException(400, f"Invalid recurring operation: {exc}")


@router.get("/recurring-operations")
def list_recurring(principal: Principal = Depends(require_human()), db: Session = Depends(get_db)):
    org_id = active_org(principal)
    return db.query(RecurringOperation).filter(RecurringOperation.organization_id == org_id).order_by(RecurringOperation.id.desc()).all()


@router.post("/recurring-operations/{operation_id}/run-now")
def run_recurring_now(operation_id: int, principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    item = db.get(RecurringOperation, operation_id)
    if not item: raise HTTPException(404, "Recurring operation not found")
    enforce_org(item.organization_id, principal)
    return execute_operation(db, item, user_id=principal.user_id)


@router.get("/incidents")
def list_incidents(status: str | None = None, principal: Principal = Depends(require_human()), db: Session = Depends(get_db)):
    org_id = active_org(principal)
    q = db.query(RecoveryIncident).filter(RecoveryIncident.organization_id == org_id)
    if status: q = q.filter(RecoveryIncident.status == status)
    return q.order_by(RecoveryIncident.id.desc()).limit(200).all()


@router.post("/incidents/{incident_id}/retry")
def retry_recovery_incident(incident_id: int, payload: IncidentRetryRequest, principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    item = db.get(RecoveryIncident, incident_id)
    if not item: raise HTTPException(404, "Incident not found")
    enforce_org(item.organization_id, principal)
    try:
        incident, assignment = retry_incident(db, item, force=payload.force)
        return {"incident": incident, "assignment": assignment}
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.get("/org/delegation-tree")
def delegation_tree(company_id: int | None = None, principal: Principal = Depends(require_human()), db: Session = Depends(get_db)):
    org_id = active_org(principal)
    q = db.query(Member).filter(Member.organization_id == org_id, Member.status.in_(["active", "provisioning_failed"]))
    if company_id is not None:
        ensure_company(db, company_id, principal); q = q.filter(Member.company_id == company_id)
    rows = q.order_by(Member.id).all()
    by_manager: dict[int | None, list[Member]] = {}
    for row in rows: by_manager.setdefault(row.manager_id, []).append(row)
    def node(member: Member, seen: set[int]):
        if member.id in seen: return {"id":member.id,"name":member.name,"role":member.role,"member_type":member.member_type,"cycle":True,"children":[]}
        next_seen = seen | {member.id}
        return {"id":member.id,"name":member.name,"role":member.role,"member_type":member.member_type,"status":member.status,"children":[node(x,next_seen) for x in by_manager.get(member.id,[])]}
    roots = [m for m in rows if m.manager_id is None or not any(x.id == m.manager_id for x in rows)]
    return [node(m,set()) for m in roots]


@router.get("/control-center")
def control_center(principal: Principal = Depends(require_human()), db: Session = Depends(get_db)):
    org_id = active_org(principal)
    goals = db.query(ExecutiveGoal).filter(ExecutiveGoal.organization_id == org_id).order_by(ExecutiveGoal.id.desc()).limit(8).all()
    cycles = db.query(OperatingCycle).filter(OperatingCycle.organization_id == org_id).order_by(OperatingCycle.id.desc()).limit(8).all()
    incidents = db.query(RecoveryIncident).filter(RecoveryIncident.organization_id == org_id, RecoveryIncident.status.in_(["open", "retrying"])).order_by(RecoveryIncident.id.desc()).limit(8).all()
    budgets = db.query(BudgetEnvelope).filter(BudgetEnvelope.organization_id == org_id, BudgetEnvelope.status == "active").all()
    policy = get_policy(db, org_id, None)
    since = datetime.utcnow() - timedelta(days=1)
    usage_amount = db.query(func.coalesce(func.sum(UsageEvent.amount), 0.0)).filter(UsageEvent.organization_id == org_id, UsageEvent.created_at >= since).scalar() or 0.0
    running_assignments = db.query(DelegationAssignment).filter(DelegationAssignment.organization_id == org_id, DelegationAssignment.status == "running").count()
    pending_approvals = db.query(Approval).filter(Approval.organization_id == org_id, Approval.status == "pending").count()
    memories = db.query(OrganizationMemory).filter(OrganizationMemory.organization_id == org_id, OrganizationMemory.status == "active").count()
    return {
        "autonomy": {"mode": policy.mode, "max_auto_risk": policy.max_auto_risk, "max_concurrent_runs": policy.max_concurrent_runs},
        "metrics": {
            "active_goals": sum(1 for g in goals if g.status not in {"completed", "cancelled"}),
            "running_assignments": running_assignments,
            "open_incidents": len(incidents),
            "pending_approvals": pending_approvals,
            "memory_items": memories,
            "usage_cost_24h": float(usage_amount),
            "budget_limit": sum(float(x.amount_limit or 0) for x in budgets),
            "budget_spent": sum(float(x.amount_spent or 0) for x in budgets),
        },
        "goals": goals,
        "cycles": cycles,
        "incidents": incidents,
        "budgets": [{"id":x.id,"name":x.name,"currency":x.currency,"limit":x.amount_limit,"reserved":x.amount_reserved,"spent":x.amount_spent,"remaining":remaining(x)} for x in budgets],
    }
