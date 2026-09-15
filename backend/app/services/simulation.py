import json
from sqlalchemy import func
from sqlalchemy.orm import Session
from app.models import Agent, Company, Member, SimulationRun, SimulationScenario, Task, Project, UsageEvent


def run_simulation(db: Session, scenario: SimulationScenario) -> SimulationRun:
    assumptions = json.loads(scenario.assumptions_json or "{}")
    org_id = scenario.organization_id
    company_id = scenario.company_id
    agents_q = db.query(Agent).join(Member, Agent.member_id == Member.id).filter(Member.organization_id == org_id)
    tasks_q = db.query(Task).join(Project, Task.project_id == Project.id).join(Company, Project.company_id == Company.id).filter(Company.organization_id == org_id)
    if company_id is not None:
        agents_q = agents_q.filter(Member.company_id == company_id)
        tasks_q = tasks_q.filter(Company.id == company_id)
    agents = agents_q.count()
    open_tasks = tasks_q.filter(Task.status.notin_(["done", "completed", "cancelled"])).count()
    added_agents = int(assumptions.get("add_agents", 0))
    tasks_per_agent_day = float(assumptions.get("tasks_per_agent_day", 4.0))
    failure_rate = max(0.0, min(1.0, float(assumptions.get("failure_rate", 0.08))))
    avg_cost_per_task = max(0.0, float(assumptions.get("avg_cost_per_task", 0.35)))
    days = max(1, int(assumptions.get("horizon_days", 30)))
    effective_agents = max(0, agents + added_agents)
    gross_capacity = effective_agents * tasks_per_agent_day * days
    expected_capacity = gross_capacity * (1.0 - failure_rate)
    expected_cost = min(open_tasks, expected_capacity) * avg_cost_per_task
    backlog_after = max(0.0, open_tasks - expected_capacity)
    utilization = min(1.0, (open_tasks / expected_capacity)) if expected_capacity > 0 else 1.0
    score = max(0.0, min(100.0, 100.0 - (backlog_after * 2.0) - (failure_rate * 30.0) - (max(0, utilization - 0.9) * 50.0)))
    snapshot = {"agents": agents, "open_tasks": open_tasks, "company_id": company_id}
    result = {
        "effective_agents": effective_agents, "gross_capacity_tasks": round(gross_capacity, 2),
        "expected_capacity_tasks": round(expected_capacity, 2), "expected_cost": round(expected_cost, 2),
        "backlog_after_horizon": round(backlog_after, 2), "utilization": round(utilization, 4),
        "failure_rate": failure_rate, "horizon_days": days,
    }
    item = SimulationRun(
        organization_id=org_id, scenario_id=scenario.id, status="completed",
        input_snapshot_json=json.dumps(snapshot, ensure_ascii=False), result_json=json.dumps(result, ensure_ascii=False), score=score,
    )
    scenario.status = "simulated"; db.add_all([item, scenario]); db.commit(); db.refresh(item); db.refresh(scenario)
    return item
