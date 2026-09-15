import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
import app.models  # noqa: F401
from app.models import Organization, Company, Department, Member, Agent, AutonomyPolicy, BudgetEnvelope, BudgetLedgerEntry
from app.services.autonomy import risk_allowed
from app.services.budget import remaining, reserve, settle_reserved
from app.services.orchestration import create_goal, plan_goal, create_cycle, tick_cycle
from app.services.recurring_ops import compute_next


def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_cron_next_in_timezone():
    base = datetime(2026, 9, 11, 21, 0, tzinfo=ZoneInfo("Asia/Ho_Chi_Minh"))
    nxt = compute_next("0 8 * * *", "Asia/Ho_Chi_Minh", base)
    assert nxt == datetime(2026, 9, 12, 1, 0)  # stored as naive UTC


def test_risk_threshold():
    assert risk_allowed("low", "low") is True
    assert risk_allowed("medium", "low") is False
    assert risk_allowed("high", "high") is True


def test_budget_reserve_and_settle():
    db = session()
    org = Organization(name="Acme", slug="acme")
    db.add(org); db.commit(); db.refresh(org)
    budget = BudgetEnvelope(organization_id=org.id, name="Ops", amount_limit=10, amount_reserved=0, amount_spent=0)
    db.add(budget); db.commit(); db.refresh(budget)
    reserve(db, budget, 2.5, source_type="test", source_id="1")
    assert remaining(budget) == 7.5
    settle_reserved(db, budget, 2.5, source_type="test", source_id="1")
    assert budget.amount_reserved == 0
    assert budget.amount_spent == 2.5
    assert db.query(BudgetLedgerEntry).count() == 2


def test_autonomous_operating_cycle_end_to_end_with_mock_runtime():
    db = session()
    org = Organization(name="Nova", slug="nova")
    db.add(org); db.commit(); db.refresh(org)
    company = Company(organization_id=org.id, name="Nova Fashion", industry="Fashion")
    db.add(company); db.commit(); db.refresh(company)
    dep = Department(company_id=company.id, name="Growth")
    db.add(dep); db.commit(); db.refresh(dep)
    manager = Member(organization_id=org.id, company_id=company.id, department_id=dep.id, name="Sophia", member_type="agent", role="Growth Manager")
    db.add(manager); db.commit(); db.refresh(manager)
    worker = Member(organization_id=org.id, company_id=company.id, department_id=dep.id, name="Mia", member_type="agent", role="Content Specialist", manager_id=manager.id)
    db.add(worker); db.commit(); db.refresh(worker)
    db.add(Agent(member_id=manager.id, runtime_agent_id="sophia-test", model="mock"))
    db.add(Agent(member_id=worker.id, runtime_agent_id="mia-test", model="mock"))
    db.add(AutonomyPolicy(organization_id=org.id, mode="autonomous", max_auto_risk="low", max_concurrent_runs=2, retry_limit=1, per_action_limit=5, daily_budget_limit=50))
    db.commit()

    goal = create_goal(
        db, organization_id=org.id, user_id=None, company_id=company.id, title="Launch campaign",
        objective="Research and produce a launch campaign", expected_outcome="Campaign ready", risk="low",
        autonomy_mode="inherit", budget_limit=10,
    )
    plan, steps = plan_goal(db, goal, user_id=None, max_steps=2, project_id=None, auto_create_tasks=True)
    assert len(steps) == 2
    cycle = create_cycle(db, goal, estimated_cost_per_assignment=1)

    # First tick dispatches only the root dependency.
    first = asyncio.run(tick_cycle(db, cycle, capture_runtime=False))
    assert first["counts"]["running"] == 1

    # Capture root completion and dispatch dependent step.
    second = asyncio.run(tick_cycle(db, cycle, capture_runtime=True))
    assert second["counts"]["completed"] == 1
    assert second["counts"]["running"] == 1

    # Capture second completion and close the goal/cycle.
    third = asyncio.run(tick_cycle(db, cycle, capture_runtime=True))
    assert third["cycle"].status == "completed"
    assert third["counts"]["completed"] == 2
    db.refresh(goal)
    assert goal.status == "completed"
    assert goal.progress == 100
    budget = db.query(BudgetEnvelope).filter(BudgetEnvelope.goal_id == goal.id).one()
    assert budget.amount_spent == 2
    assert budget.amount_reserved == 0
