"""v18 tests: guarded writes from the cockpit.

These cover the rules the UI must not be allowed to bypass: duplicate company
names, agent seats without a runtime binding, reporting cycles, illegal task
transitions, and assignment to inactive people.
"""
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
import app.models  # noqa: F401
from app.models import Agent, Company, CompanyEvent, Department, Member, Organization, Project, Task
from app.services import workspace_ops as ops


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def world(db):
    org = Organization(name="Nova Holding", slug="nova-holding")
    db.add(org); db.commit(); db.refresh(org)
    labs = Company(organization_id=org.id, name="Nova Labs", industry="AI Products", status="active")
    db.add(labs); db.commit(); db.refresh(labs)
    eng = Department(company_id=labs.id, name="Engineering", access_level="restricted")
    db.add(eng); db.commit(); db.refresh(eng)
    long_ = Member(organization_id=org.id, company_id=labs.id, name="Long", member_type="human",
                   role="Founder", status="active")
    db.add(long_); db.commit(); db.refresh(long_)
    return {"org": org, "labs": labs, "eng": eng, "long": long_}


def test_create_company_emits_event(db, world):
    company = ops.create_company(db, world["org"].id, name="Nova Media", industry="Content")
    assert company.id and company.status == "active"
    events = db.query(CompanyEvent).filter(CompanyEvent.event_type == "company.created").all()
    assert len(events) == 1 and events[0].source == "workspace_ops"


def test_duplicate_company_name_is_rejected(db, world):
    with pytest.raises(HTTPException) as err:
        ops.create_company(db, world["org"].id, name="  nova labs ")
    assert err.value.status_code == 409


def test_agent_seat_requires_runtime_id(db, world):
    with pytest.raises(HTTPException) as err:
        ops.create_member(db, world["org"].id, name="Dex", member_type="agent",
                          company_id=world["labs"].id)
    assert err.value.status_code == 400
    assert db.query(Member).filter(Member.name == "Dex").count() == 0


def test_agent_seat_creates_runtime_record(db, world):
    member, agent = ops.create_member(db, world["org"].id, name="Nina", member_type="agent",
                                      company_id=world["labs"].id, department_id=world["eng"].id,
                                      runtime_agent_id="oc-nina", model="openclaw-core")
    assert agent is not None
    assert agent.member_id == member.id and agent.runtime_agent_id == "oc-nina"
    assert agent.runtime_provider == "openclaw" and agent.lifecycle == "active"


def test_duplicate_runtime_id_is_rejected_and_rolls_back_seat(db, world):
    ops.create_member(db, world["org"].id, name="Nina", member_type="agent",
                      company_id=world["labs"].id, runtime_agent_id="oc-nina")
    with pytest.raises(HTTPException) as err:
        ops.create_member(db, world["org"].id, name="Nina clone", member_type="agent",
                          company_id=world["labs"].id, runtime_agent_id="oc-nina")
    assert err.value.status_code == 409
    # the orphan seat must not survive the failed runtime binding
    assert db.query(Member).filter(Member.name == "Nina clone").count() == 0
    assert db.query(Agent).count() == 1


def test_department_must_match_company(db, world):
    other = ops.create_company(db, world["org"].id, name="Nova Media")
    with pytest.raises(HTTPException) as err:
        ops.create_member(db, world["org"].id, name="Mia", member_type="human",
                          company_id=other.id, department_id=world["eng"].id)
    assert err.value.status_code == 400


def test_manager_cycle_is_rejected(db, world):
    boss = world["long"]
    mid, _ = ops.create_member(db, world["org"].id, name="Mid", member_type="human",
                               company_id=world["labs"].id, manager_id=boss.id)
    leaf, _ = ops.create_member(db, world["org"].id, name="Leaf", member_type="human",
                                company_id=world["labs"].id, manager_id=mid.id)
    with pytest.raises(HTTPException) as err:
        ops.move_member(db, boss, manager_id=leaf.id)
    assert err.value.status_code == 400
    assert "cycle" in err.value.detail.lower()


def test_moving_company_clears_stale_department(db, world):
    member, _ = ops.create_member(db, world["org"].id, name="Mover", member_type="human",
                                  company_id=world["labs"].id, department_id=world["eng"].id)
    media = ops.create_company(db, world["org"].id, name="Nova Media")
    ops.move_member(db, member, company_id=media.id)
    assert member.company_id == media.id
    assert member.department_id is None


def test_task_transition_rules(db, world):
    project = ops.create_project(db, world["labs"], name="Launch v18", owner_member_id=world["long"].id)
    task = ops.create_task(db, project, world["org"].id, title="Ship cockpit writes",
                           assignee_member_id=world["long"].id)
    assert task.status == "backlog"
    with pytest.raises(HTTPException) as err:
        ops.move_task(db, task, project, world["org"].id, status="done")
    assert err.value.status_code == 409
    ops.move_task(db, task, project, world["org"].id, status="todo")
    ops.move_task(db, task, project, world["org"].id, status="in_progress")
    ops.move_task(db, task, project, world["org"].id, status="review")
    ops.move_task(db, task, project, world["org"].id, status="done")
    assert task.status == "done"


def test_unassigned_task_cannot_start(db, world):
    project = ops.create_project(db, world["labs"], name="Launch v18")
    task = ops.create_task(db, project, world["org"].id, title="Orphan work")
    ops.move_task(db, task, project, world["org"].id, status="todo")
    with pytest.raises(HTTPException) as err:
        ops.move_task(db, task, project, world["org"].id, status="in_progress")
    assert err.value.status_code == 400


def test_cannot_assign_to_offboarded_member(db, world):
    gone, _ = ops.create_member(db, world["org"].id, name="Gone", member_type="human",
                                company_id=world["labs"].id, status="offboarded")
    project = ops.create_project(db, world["labs"], name="Launch v18")
    with pytest.raises(HTTPException) as err:
        ops.create_task(db, project, world["org"].id, title="Nope", assignee_member_id=gone.id)
    assert err.value.status_code == 400


def test_cannot_unassign_work_in_progress(db, world):
    project = ops.create_project(db, world["labs"], name="Launch v18")
    task = ops.create_task(db, project, world["org"].id, title="Busy",
                           assignee_member_id=world["long"].id)
    ops.move_task(db, task, project, world["org"].id, status="todo")
    ops.move_task(db, task, project, world["org"].id, status="in_progress")
    with pytest.raises(HTTPException) as err:
        ops.assign_task(db, task, project, world["org"].id, assignee_member_id=None)
    assert err.value.status_code == 400


def test_project_progress_bounds(db, world):
    project = ops.create_project(db, world["labs"], name="Launch v18")
    with pytest.raises(HTTPException) as err:
        ops.update_project(db, project, world["org"].id, progress=140)
    assert err.value.status_code == 400
    ops.update_project(db, project, world["org"].id, progress=55, status="active")
    assert project.progress == 55 and project.status == "active"


def test_invalid_status_vocabulary(db, world):
    with pytest.raises(HTTPException):
        ops.create_company(db, world["org"].id, name="Weird", status="sleeping")
    with pytest.raises(HTTPException):
        ops.create_project(db, world["labs"], name="Weird", status="vibing")


def test_events_recorded_for_task_lifecycle(db, world):
    project = ops.create_project(db, world["labs"], name="Launch v18")
    task = ops.create_task(db, project, world["org"].id, title="Traceable",
                           assignee_member_id=world["long"].id)
    ops.move_task(db, task, project, world["org"].id, status="todo")
    types = [e.event_type for e in db.query(CompanyEvent).all()]
    assert "task.created" in types and "task.todo" in types
    assert all(e.company_id == world["labs"].id
               for e in db.query(CompanyEvent).filter(CompanyEvent.aggregate_type == "task").all())


def test_knowledge_document_created_unindexed(db, world):
    doc = ops.create_knowledge_document(db, world["org"].id, title="Runbook", content="steps",
                                        company_id=world["labs"].id, access_level="org_public")
    assert doc.indexed is False and doc.access_level == "org_public"
    assert db.query(CompanyEvent).filter(
        CompanyEvent.event_type == "knowledge.document.created").count() == 1
