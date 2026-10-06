"""v27 tests: derived progress, revision guards, archive cascade.

D0.2: chạy trên ORM thật (SQLite in-memory), không còn ``FakeDb``. Double cũ
trả *mọi* task cho mọi truy vấn đếm — bỏ ``WHERE project_id`` ở production
thì test vẫn xanh. Ở đây mỗi phép thử có thêm một dự án "nhiễu" cùng DB
(task done + task đang chạy có session), nên bỏ bất kỳ điều kiện WHERE nào
của ``board_truth`` đều làm test đỏ.
"""
from datetime import timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
import app.models  # noqa: F401
from app.models import CompanyEvent
from app.models.entities import Company, Organization, Project, Task
from app.services import board_truth as bt


@pytest.fixture()
def orm():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine, autoflush=False)()
    org = Organization(name="Nova", slug="nova-v27"); db.add(org); db.commit()
    co = Company(organization_id=org.id, name="Nova Labs", status="active"); db.add(co); db.commit()
    noise = Project(company_id=co.id, name="Nhiễu", status="active", progress=0); db.add(noise); db.commit()
    # Dự án khác cùng công ty: 3 việc xong + 1 việc đang chạy có session.
    for i, st in enumerate(["done", "done", "done", "in_progress"]):
        db.add(Task(project_id=noise.id, title=f"n{i}", status=st,
                    runtime_session_key="agent:nina:company-task-noise" if st == "in_progress" else None))
    db.commit()
    yield {"db": db, "org": org, "company": co, "noise": noise}
    db.close()


def _project(orm, progress=0, status="active"):
    p = Project(company_id=orm["company"].id, name="P", status=status, progress=progress)
    orm["db"].add(p); orm["db"].commit(); orm["db"].refresh(p)
    return p


def _tasks(orm, project, *specs):
    out = []
    for spec in specs:
        status, session = (spec, None) if isinstance(spec, str) else spec
        t = Task(project_id=project.id, title=status, status=status, runtime_session_key=session)
        orm["db"].add(t); out.append(t)
    orm["db"].commit()
    return out


def _events(orm, event_type):
    return orm["db"].query(CompanyEvent).filter(CompanyEvent.event_type == event_type).count()


# -- derived progress -------------------------------------------------------


def test_progress_is_done_over_countable(orm):
    p = _project(orm)
    _tasks(orm, p, "done", "done", "todo", "review")
    out = bt.derive(orm["db"], p)
    assert out["derived_progress"] == 50
    assert out["total_tasks"] == 4, "việc của dự án khác không được đếm"


def test_cancelled_tasks_leave_the_denominator(orm):
    """Dropping scope must not pin a project at half done forever."""
    p = _project(orm)
    _tasks(orm, p, "done", "cancelled")
    out = bt.derive(orm["db"], p)
    assert out["countable"] == 1 and out["derived_progress"] == 100


def test_review_is_not_partial_credit(orm):
    p = _project(orm)
    _tasks(orm, p, "review", "todo")
    assert bt.derive(orm["db"], p)["derived_progress"] == 0


def test_no_tasks_is_not_zero_percent(orm):
    """"Nothing to measure" must not read as "measured zero"."""
    p = _project(orm, progress=40)
    out = bt.derive(orm["db"], p)
    assert out["derivable"] is False
    assert out["derived_progress"] is None
    assert out["drift"] is None


def test_drift_is_signed_against_the_stored_column(orm):
    p = _project(orm, progress=90)
    _tasks(orm, p, "done", "todo")
    assert bt.derive(orm["db"], p)["drift"] == -40


def test_sync_refuses_to_overwrite_when_nothing_is_measurable(orm):
    p = _project(orm, progress=40)
    out = bt.sync_progress(orm["db"], p, orm["org"].id)
    orm["db"].refresh(p)
    assert out["applied"] is False and p.progress == 40


def test_sync_applies_and_reports_the_previous_value(orm):
    p = _project(orm, progress=0)
    _tasks(orm, p, "done", "todo")
    out = bt.sync_progress(orm["db"], p, orm["org"].id)
    orm["db"].expire_all()
    assert out["applied"] is True
    assert out["previous_progress"] == 0 and orm["db"].get(Project, p.id).progress == 50
    assert _events(orm, bt.PROGRESS_EVENT) == 1


def test_sync_in_sync_is_a_no_op_not_a_write(orm):
    p = _project(orm, progress=50)
    _tasks(orm, p, "done", "todo")
    rev = bt.revision(p)
    out = bt.sync_progress(orm["db"], p, orm["org"].id)
    orm["db"].expire_all()
    assert out["applied"] is False
    assert bt.revision(orm["db"].get(Project, p.id)) == rev and _events(orm, bt.PROGRESS_EVENT) == 0


# -- revisions --------------------------------------------------------------


def test_revision_changes_when_the_row_is_touched(orm):
    p = _project(orm)
    first = bt.revision(p)
    p.updated_at = p.updated_at + timedelta(seconds=1)
    assert bt.revision(p) != first


def test_missing_revision_opts_out_rather_than_failing(orm):
    """Pre-v27 clients must keep working."""
    bt.check_revision(orm["db"], _project(orm), None)


def test_stale_revision_is_409_and_carries_the_current_one(orm):
    p = _project(orm)
    with pytest.raises(HTTPException) as err:
        bt.check_revision(orm["db"], p, "project:1:1999-01-01T00:00:00")
    assert err.value.status_code == 409
    assert err.value.detail["current_revision"] == bt.revision(p)


def test_matching_revision_passes(orm):
    p = _project(orm)
    bt.check_revision(orm["db"], p, bt.revision(p))


def test_conflict_event_failure_does_not_mask_the_409(orm, monkeypatch):
    def boom(db, **kw):
        raise RuntimeError("bus down")

    monkeypatch.setattr(bt, "emit_event", boom)
    with pytest.raises(HTTPException) as err:
        bt.check_revision(orm["db"], _project(orm), "stale", organization_id=orm["org"].id)
    assert err.value.status_code == 409


def test_sync_honours_the_revision_guard(orm):
    p = _project(orm, progress=0)
    _tasks(orm, p, "done")
    with pytest.raises(HTTPException):
        bt.sync_progress(orm["db"], p, orm["org"].id, expected_revision="stale")
    orm["db"].expire_all()
    assert orm["db"].get(Project, p.id).progress == 0


# -- archive ----------------------------------------------------------------


def test_preview_counts_what_would_be_cancelled_without_writing(orm):
    p = _project(orm)
    _tasks(orm, p, "todo", "done", "blocked")
    out = bt.archive_preview(orm["db"], p)
    assert out["will_cancel_tasks"] == 2
    assert out["will_keep_done_tasks"] == 1
    assert out["blocked"] is False, "phiên đang chạy của dự án khác không chặn dự án này"
    orm["db"].expire_all()
    assert sorted(t.status for t in orm["db"].query(Task).filter(Task.project_id == p.id)) == ["blocked", "done", "todo"]


def test_live_session_blocks_the_archive(orm, monkeypatch):
    monkeypatch.setattr(bt.lease_store, "holder", lambda key: "worker-a")
    p = _project(orm)
    _tasks(orm, p, ("in_progress", "agent:nina:company-task-1"))
    with pytest.raises(HTTPException) as err:
        bt.archive_project(orm["db"], p, orm["org"].id)
    assert err.value.status_code == 409
    live = err.value.detail["live_runtime_sessions"]
    assert [x["session_key"] for x in live] == ["agent:nina:company-task-1"]
    assert live[0]["followed_by"] == "worker-a"


def test_in_progress_without_a_session_does_not_block(orm, monkeypatch):
    monkeypatch.setattr(bt.lease_store, "holder", lambda key: "")
    p = _project(orm)
    (t,) = _tasks(orm, p, "in_progress")
    out = bt.archive_project(orm["db"], p, orm["org"].id)
    assert out["cancelled_task_ids"] == [t.id]


def test_force_archives_but_admits_what_it_left_running(orm, monkeypatch):
    monkeypatch.setattr(bt.lease_store, "holder", lambda key: "worker-a")
    p = _project(orm)
    _tasks(orm, p, ("in_progress", "s1"))
    out = bt.archive_project(orm["db"], p, orm["org"].id, force=True)
    assert out["forced"] is True
    assert [x["session_key"] for x in out["left_running"]] == ["s1"]


def test_archive_never_deletes_and_keeps_done_work(orm):
    p = _project(orm)
    todo, done = _tasks(orm, p, "todo", "done")
    out = bt.archive_project(orm["db"], p, orm["org"].id)
    orm["db"].expire_all()
    db = orm["db"]
    assert out["deleted"] is False and out["cancelled_task_ids"] == [todo.id]
    assert db.get(Project, p.id).status == bt.ARCHIVE_STATUS
    assert db.get(Task, todo.id).status == "cancelled" and db.get(Task, done.id).status == "done"
    # Dự án nhiễu không bị đụng tới.
    assert db.get(Project, orm["noise"].id).status == "active"
    assert sorted(t.status for t in db.query(Task).filter(Task.project_id == orm["noise"].id)) == \
        ["done", "done", "done", "in_progress"]


def test_archive_uses_existing_vocabulary_only():
    """No new status words: v18's board must still understand the result."""
    from app.services.workspace_ops import PROJECT_STATUSES, TASK_STATUSES

    assert bt.ARCHIVE_STATUS in PROJECT_STATUSES
    assert "cancelled" in TASK_STATUSES
    assert all(s in TASK_STATUSES for s in bt.OPEN_STATUSES)


def test_archive_honours_the_revision_guard(orm):
    p = _project(orm)
    with pytest.raises(HTTPException) as err:
        bt.archive_project(orm["db"], p, orm["org"].id, expected_revision="stale")
    assert err.value.status_code == 409
    orm["db"].expire_all()
    assert orm["db"].get(Project, p.id).status == "active"


def test_finished_run_keeps_its_session_key_but_does_not_block(orm, monkeypatch):
    """Sau khi chạy xong, task ở review/blocked vẫn giữ session key — không còn agent nào chạy."""
    monkeypatch.setattr(bt.lease_store, "holder", lambda key: "")
    p = _project(orm)
    _tasks(orm, p, ("review", "agent:nina:company-task-7"), ("blocked", "agent:nina:company-task-8"))
    assert bt.archive_preview(orm["db"], p)["live_runtime_sessions"] == []
