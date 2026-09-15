"""v17 tests: aggregate reads that back the business UI screens."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
import app.models  # noqa: F401
from app.models import (Organization, Company, Department, Member, Agent, Project, Task,
                        KnowledgeDocument)
from app.services import workspace_cockpit as cockpit


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
    other = Organization(name="Rival Group", slug="rival-group")
    db.add_all([org, other]); db.commit(); db.refresh(org); db.refresh(other)

    labs = Company(organization_id=org.id, name="Nova Labs", industry="AI Products")
    media = Company(organization_id=org.id, name="Nova Media", industry="Content")
    rival = Company(organization_id=other.id, name="Rival Co", industry="Other")
    db.add_all([labs, media, rival]); db.commit()
    for c in (labs, media, rival):
        db.refresh(c)

    engineering = Department(company_id=labs.id, name="Engineering", access_level="restricted")
    db.add(engineering); db.commit(); db.refresh(engineering)

    nina = Member(organization_id=org.id, company_id=labs.id, department_id=engineering.id,
                  name="Nina", member_type="agent", role="AI Chief of Staff")
    dex = Member(organization_id=org.id, company_id=labs.id, department_id=engineering.id,
                 name="Dex", member_type="agent", role="Backend agent")
    long_ = Member(organization_id=org.id, company_id=labs.id, name="Long", member_type="human", role="Founder")
    mia = Member(organization_id=org.id, company_id=media.id, name="Mia", member_type="agent", role="Editor agent")
    outsider = Member(organization_id=other.id, company_id=rival.id, name="Outsider", member_type="human")
    db.add_all([nina, dex, long_, mia, outsider]); db.commit()
    for m in (nina, dex, long_, mia, outsider):
        db.refresh(m)

    db.add(Agent(member_id=nina.id, runtime_agent_id="oc-nina", model="openclaw-core",
                 success_rate=0.97, cost_30d=42.5, risk="low"))
    db.commit()

    launch = Project(company_id=labs.id, name="Launch v16", status="active", progress=60,
                     owner_member_id=nina.id)
    brand = Project(company_id=media.id, name="Brand refresh", status="planning", progress=10)
    rival_project = Project(company_id=rival.id, name="Rival project", status="active")
    db.add_all([launch, brand, rival_project]); db.commit()
    for p in (launch, brand, rival_project):
        db.refresh(p)

    db.add_all([
        Task(project_id=launch.id, title="Design API", status="done", assignee_member_id=dex.id),
        Task(project_id=launch.id, title="Write tests", status="in_progress", assignee_member_id=dex.id),
        Task(project_id=launch.id, title="Ship", status="backlog"),
        Task(project_id=rival_project.id, title="Not ours", status="backlog"),
    ])
    db.add(KnowledgeDocument(organization_id=org.id, company_id=labs.id, title="Launch runbook", indexed=True))
    db.commit()
    return {"org": org, "other": other, "labs": labs, "media": media, "nina": nina, "dex": dex,
            "long": long_, "mia": mia, "launch": launch}


def test_overview_counts_are_tenant_scoped(db, world):
    data = cockpit.org_overview(db, world["org"].id)
    assert data["organization"]["name"] == "Nova Holding"
    assert data["kpis"]["companies"] == 2
    assert data["kpis"]["members"] == 4
    assert data["kpis"]["humans"] == 1
    assert data["kpis"]["agents"] == 3
    assert data["kpis"]["projects_total"] == 2
    assert data["kpis"]["projects_active"] == 1
    assert data["kpis"]["knowledge_documents"] == 1


def test_overview_company_cards_carry_headcount(db, world):
    cards = {c["name"]: c for c in cockpit.org_overview(db, world["org"].id)["companies"]}
    assert cards["Nova Labs"]["members"] == 3 and cards["Nova Labs"]["agents"] == 2
    assert cards["Nova Media"]["members"] == 1 and cards["Nova Media"]["projects"] == 1


def test_company_detail_lists_departments_and_projects(db, world):
    detail = cockpit.company_detail(db, world["labs"])
    assert detail["headcount"] == {"humans": 1, "agents": 2, "total": 3}
    assert detail["departments"][0]["name"] == "Engineering"
    assert detail["departments"][0]["members"] == 2
    assert [p["name"] for p in detail["projects"]] == ["Launch v16"]


def test_people_directory_filters_and_enriches_agents(db, world):
    agents = cockpit.people_directory(db, world["org"].id, member_type="agent")
    assert {a["name"] for a in agents} == {"Nina", "Dex", "Mia"}
    nina = next(a for a in agents if a["name"] == "Nina")
    assert nina["agent"]["runtime_agent_id"] == "oc-nina" and nina["agent"]["success_rate"] == 0.97
    assert nina["company_name"] == "Nova Labs" and nina["department_name"] == "Engineering"
    assert next(a for a in agents if a["name"] == "Mia")["agent"] is None
    humans = cockpit.people_directory(db, world["org"].id, member_type="human")
    assert [h["name"] for h in humans] == ["Long"]


def test_project_board_rolls_up_tasks(db, world):
    board = {p["name"]: p for p in cockpit.project_board(db, world["org"].id)}
    launch = board["Launch v16"]
    assert launch["tasks_total"] == 3 and launch["tasks_done"] == 1 and launch["tasks_open"] == 2
    assert launch["company_name"] == "Nova Labs"
    assert board["Brand refresh"]["tasks_total"] == 0
    assert "Rival project" not in board


def test_task_queue_joins_names_and_filters(db, world):
    queue = cockpit.task_queue(db, world["org"].id)
    assert len(queue) == 3 and all(t["company_name"] == "Nova Labs" for t in queue)
    assigned = cockpit.task_queue(db, world["org"].id, assignee_member_id=world["dex"].id)
    assert {t["title"] for t in assigned} == {"Design API", "Write tests"}
    assert all(t["assignee_type"] == "agent" for t in assigned)
    assert [t["title"] for t in cockpit.task_queue(db, world["org"].id, status="done")] == ["Design API"]


def test_knowledge_library_scoped_by_company(db, world):
    docs = cockpit.knowledge_library(db, world["org"].id)
    assert [d["title"] for d in docs] == ["Launch runbook"]
    assert docs[0]["company_name"] == "Nova Labs" and docs[0]["indexed"] is True
    assert cockpit.knowledge_library(db, world["org"].id, company_id=world["media"].id) == []


def test_org_chart_nests_companies_departments_members(db, world):
    chart = cockpit.org_chart(db, world["org"].id)
    labs = next(c for c in chart["companies"] if c["name"] == "Nova Labs")
    engineering = labs["departments"][0]
    assert {m["name"] for m in engineering["members"]} == {"Nina", "Dex"}
    assert [m["name"] for m in labs["unassigned_members"]] == ["Long"]
    assert "Rival Co" not in {c["name"] for c in chart["companies"]}


def test_empty_organization_is_safe(db, world):
    empty = Organization(name="Empty Org", slug="empty-org")
    db.add(empty); db.commit(); db.refresh(empty)
    assert cockpit.project_board(db, empty.id) == []
    assert cockpit.task_queue(db, empty.id) == []
    assert cockpit.org_overview(db, empty.id)["kpis"]["projects_total"] == 0
