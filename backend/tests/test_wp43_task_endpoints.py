"""WP-4.3 UI — ba endpoint mà màn hình chi tiết công việc dùng.

Service phía dưới đã có test hành vi riêng (`test_wp43_handoff_dispatch.py`,
`test_wp37_work_memory_rooms.py`). Ở đây kiểm **phần chỉ tồn tại ở tầng
endpoint**, và phần đó không mỏng như nó trông:

* `POST /tasks/{id}/handoff` tự tạo **phiếu bàn giao** khi task chưa có artifact
  nào — vì bàn giao trong hệ thống này luôn gắn với một artifact, mà bắt người
  dùng tạo artifact trước khi bàn giao là bắt họ làm việc của hệ thống.
* `GET /tasks/{id}/context-pack` phải gọi **đúng hàm** mà dispatch gọi. Một màn
  hình xem trước hiện khác cái agent nhận thì tệ hơn là không có.
* Cả ba phải chặn theo tenant.
"""
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
import app.models  # noqa: F401
from app.models.entities import Agent, Company, Member, Organization, Project, Task
from app.models.v10 import Artifact
from app.models.v37 import TaskJournalEntry


@pytest.fixture()
def db():
    """SQLite in-memory, model ORM thật.

    Các endpoint nhận `db` làm tham số nên truyền session nào cũng được, và một
    database riêng cho từng test thì không phụ thuộc thứ tự chạy — bản đầu dùng
    `SessionLocal` (database file dùng chung) và hỏng ngay khi test thứ hai tạo
    cùng một tên tổ chức.
    """
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)()
    try:
        yield session
    finally:
        session.close()


def _world(db: Session, slug: str):
    # Tên riêng theo từng test: `organizations.name` là UNIQUE. Nay mỗi test có
    # database in-memory riêng nên chuyện này không còn bắt buộc, nhưng giữ để
    # test không phụ thuộc vào việc fixture cô lập tới mức nào.
    org = Organization(name=f"Nova {slug}", slug=slug)
    db.add(org); db.commit(); db.refresh(org)
    company = Company(organization_id=org.id, name="Nova Fashion", status="active")
    db.add(company); db.commit(); db.refresh(company)
    boss = Member(organization_id=org.id, company_id=company.id, name="Long",
                  member_type="human", role="Founder", status="active")
    db.add(boss); db.commit(); db.refresh(boss)
    mia = Member(organization_id=org.id, company_id=company.id, name="Mia",
                 member_type="agent", role="Content Lead", status="active")
    db.add(mia); db.commit(); db.refresh(mia)
    db.add(Agent(member_id=mia.id, runtime_provider="openclaw",
                 runtime_agent_id="", lifecycle="active"))
    project = Project(company_id=company.id, name="Summer", status="active", progress=10)
    db.add(project); db.commit(); db.refresh(project)
    task = Task(project_id=project.id, title="Việc thử", description="mô tả",
                assignee_member_id=boss.id, status="backlog", priority="medium")
    db.add(task); db.commit(); db.refresh(task)
    return {"org": org, "company": company, "boss": boss, "mia": mia,
            "project": project, "task": task}


def test_handoff_creates_a_note_artifact_when_the_task_has_none(db):
    """Task chưa có sản phẩm nào vẫn bàn giao được.

    Không sinh ra đường bàn giao thứ hai: vẫn là `artifact_handoffs`, chỉ khác ở
    chỗ hệ thống tự tạo một artifact loại `handoff_note` mang chính hướng dẫn.
    """
    import asyncio

    from app.api.tasks import TaskHandoffIn, task_handoff
    from app.core.authz import Principal

    world = _world(db, "nova-ep1")
    assert db.execute(select(Artifact).where(
        Artifact.task_id == world["task"].id)).scalars().first() is None

    principal = Principal(user_id=1, organization_id=world["org"].id, role="owner",
                          auth_type="jwt", scopes=[], member_id=world["boss"].id)
    out = asyncio.run(task_handoff(
        world["task"].id,
        TaskHandoffIn(to_member_id=world["mia"].id,
                      instructions="Soát lại tông thương hiệu", dispatch=False),
        principal=principal, db=db))

    assert out["created_handoff_note"] is True
    artifact = db.execute(select(Artifact).where(
        Artifact.task_id == world["task"].id)).scalars().first()
    assert artifact is not None
    assert artifact.artifact_type == "handoff_note"
    # Phiếu mang chính nội dung hướng dẫn, nên mở artifact ra là đọc được.
    assert "tông thương hiệu" in (artifact.content_text or "")
    # Và sổ ghi có mục handoff dù không dispatch.
    entry = db.execute(select(TaskJournalEntry).where(
        TaskJournalEntry.task_id == world["task"].id,
        TaskJournalEntry.kind == "handoff")).scalars().first()
    assert entry is not None and "Long bàn giao cho Mia" in entry.summary


def test_handoff_reuses_the_latest_existing_artifact(db):
    """Có sản phẩm rồi thì bàn giao chính nó, đừng tạo phiếu rác."""
    import asyncio

    from app.api.tasks import TaskHandoffIn, task_handoff
    from app.core.authz import Principal

    world = _world(db, "nova-ep2")
    existing = Artifact(organization_id=world["org"].id, company_id=world["company"].id,
                        task_id=world["task"].id, name="hooks.md",
                        logical_path="content/hooks.md", version=1,
                        artifact_type="deliverable", bundle_key="hooks-ep2")
    db.add(existing); db.commit(); db.refresh(existing)

    principal = Principal(user_id=1, organization_id=world["org"].id, role="owner",
                          auth_type="jwt", scopes=[], member_id=world["boss"].id)
    out = asyncio.run(task_handoff(
        world["task"].id,
        TaskHandoffIn(to_member_id=world["mia"].id, instructions="", dispatch=False),
        principal=principal, db=db))

    assert out["created_handoff_note"] is False
    assert out["artifact_id"] == existing.id
    assert db.execute(select(Artifact).where(
        Artifact.task_id == world["task"].id)).scalars().all().__len__() == 1


def test_context_pack_endpoint_returns_the_same_pack_dispatch_would_send(db):
    """Xem trước phải là thật, không phải mô phỏng."""
    from app.api.tasks import task_context_pack
    from app.core.authz import Principal
    from app.services import work_context

    world = _world(db, "nova-ep3")
    principal = Principal(user_id=1, organization_id=world["org"].id, role="owner",
                          auth_type="jwt", scopes=[], member_id=world["boss"].id)

    from_endpoint = task_context_pack(world["task"].id, principal=principal, db=db)
    from_service = work_context.build_pack(db, world["task"],
                                           organization_id=world["org"].id)
    assert from_endpoint["text"] == from_service["text"]
    assert len(from_endpoint["blocks"]) == 7
    assert from_endpoint["never_trimmed"] == [2, 6, 7]


def test_journal_endpoint_resolves_actor_names(db):
    """UI cần tên người, không phải id — nếu không màn hình đọc như log máy."""
    from app.api.tasks import task_journal_read
    from app.core.authz import Principal
    from app.services import task_journal

    world = _world(db, "nova-ep4")
    task_journal.append(db, world["task"], kind="note",
                        actor_member_id=world["boss"].id, summary="ghi thử")
    task_journal.append(db, world["task"], kind="note", summary="hệ thống ghi")

    principal = Principal(user_id=1, organization_id=world["org"].id, role="owner",
                          auth_type="jwt", scopes=[], member_id=world["boss"].id)
    out = task_journal_read(world["task"].id, principal=principal, db=db)

    assert [e["actor_name"] for e in out["entries"]] == ["Long", "hệ thống"]
    assert out["digest"]["success_rate"] is None
    assert "handoff" in out["kinds"]
