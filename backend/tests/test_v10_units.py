from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
import app.models  # noqa: F401
from app.models import Organization, Company, Member, EventTrigger, SimulationScenario
from app.services.artifacts import register_artifact, handoff_artifact, accept_handoff
from app.services.company_event_bus import emit_event
from app.services.quality import evaluate_artifact
from app.services.trigger_engine import process_event
from app.services.simulation import run_simulation


def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def seed(db):
    org = Organization(name="Nova", slug="nova-v10")
    db.add(org); db.commit(); db.refresh(org)
    company = Company(organization_id=org.id, name="Nova Labs", industry="AI")
    db.add(company); db.commit(); db.refresh(company)
    producer = Member(organization_id=org.id, company_id=company.id, name="Coder", member_type="agent", role="Engineer")
    reviewer = Member(organization_id=org.id, company_id=company.id, name="Reviewer", member_type="agent", role="Reviewer")
    db.add_all([producer, reviewer]); db.commit(); db.refresh(producer); db.refresh(reviewer)
    return org, company, producer, reviewer


def test_artifact_registry_versions_and_handoff():
    db = session(); org, company, producer, reviewer = seed(db)
    first = register_artifact(
        db, organization_id=org.id, company_id=company.id, created_by_member_id=producer.id,
        name="app.py", bundle_key="feature-42", logical_path="src/app.py", content_text="print('v1')",
        artifact_type="source_code", mime_type="text/x-python",
    )
    second = register_artifact(
        db, organization_id=org.id, company_id=company.id, created_by_member_id=producer.id,
        name="app.py", bundle_key="feature-42", logical_path="src/app.py", content_text="print('v2')",
        artifact_type="source_code", mime_type="text/x-python",
    )
    assert first.version == 1
    assert second.version == 2
    assert second.parent_artifact_id == first.id
    assert first.content_sha256 != second.content_sha256
    handoff = handoff_artifact(db, second, to_member_id=reviewer.id, from_member_id=producer.id, purpose="code_review")
    assert handoff.status == "pending"
    accept_handoff(db, handoff, member_id=reviewer.id)
    assert handoff.status == "accepted"


def test_event_trigger_sends_agent_message():
    db = session(); org, company, producer, reviewer = seed(db)
    trigger = EventTrigger(
        organization_id=org.id, company_id=company.id, name="QA notify", event_pattern="artifact.evaluation.changes_requested",
        condition_json="{}", action_type="message",
        action_json='{"recipient_member_id": %d, "subject": "QA failed", "content": "Please fix artifact."}' % producer.id,
        enabled=True,
    )
    db.add(trigger); db.commit()
    event = emit_event(
        db, organization_id=org.id, company_id=company.id, event_type="artifact.evaluation.changes_requested",
        payload={"score": 50}, aggregate_type="artifact", aggregate_id="1",
    )
    result = process_event(db, event)
    assert result["event"].status == "processed"
    assert len(result["executions"]) == 1
    assert result["executions"][0].result_type == "agent_message"


def test_quality_gate_updates_artifact_status():
    db = session(); org, company, producer, reviewer = seed(db)
    artifact = register_artifact(
        db, organization_id=org.id, company_id=company.id, created_by_member_id=producer.id,
        name="README.md", bundle_key="release", logical_path="README.md", content_text="tiny",
    )
    evaluation = evaluate_artifact(db, artifact, evaluator_member_id=reviewer.id, rubric={"min_chars": 40, "pass_score": 80})
    assert evaluation.verdict == "changes_requested"
    assert artifact.status == "changes_requested"


def test_digital_twin_simulation_runs_without_agents():
    db = session(); org, company, producer, reviewer = seed(db)
    scenario = SimulationScenario(
        organization_id=org.id, company_id=company.id, name="Scale team",
        assumptions_json='{"add_agents": 3, "tasks_per_agent_day": 4, "failure_rate": 0.05, "horizon_days": 30}',
    )
    db.add(scenario); db.commit(); db.refresh(scenario)
    run = run_simulation(db, scenario)
    assert run.status == "completed"
    assert run.score >= 0


def test_nina_decision_loop_creates_snapshot():
    from app.models import DecisionLoop
    from app.services.decision_loop import tick_decision_loop
    db = session(); org, company, producer, reviewer = seed(db)
    loop = DecisionLoop(organization_id=org.id, company_id=company.id, name="Nina loop", interval_seconds=60, policy_json='{"approval_attention_threshold":1}')
    db.add(loop); db.commit(); db.refresh(loop)
    run = tick_decision_loop(db, loop)
    assert run.status == "completed"
    assert loop.last_tick_at is not None
    assert loop.next_tick_at is not None


def test_sla_monitor_creates_and_escalates_incident():
    from datetime import datetime, timedelta
    from app.models import Project, Task, SLAProfile, SLAIncident
    from app.services.sla import monitor_sla
    db = session(); org, company, producer, reviewer = seed(db)
    project = Project(company_id=company.id, name="Late project", status="active")
    db.add(project); db.commit(); db.refresh(project)
    task = Task(project_id=project.id, title="Late task", status="in_progress", priority="high", created_at=datetime.utcnow()-timedelta(hours=2))
    db.add(task); db.commit(); db.refresh(task)
    profile = SLAProfile(organization_id=org.id, company_id=company.id, name="Fast SLA", priority="high", completion_minutes=30, escalation_target_member_id=reviewer.id)
    db.add(profile); db.commit()
    rows = monitor_sla(db, org.id)
    assert len(rows) == 1
    assert rows[0].status == "escalated"
    assert db.query(SLAIncident).count() == 1
