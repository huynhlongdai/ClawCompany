"""v28 tests: binding guards and reversible archive.

These use light stand-ins for ORM rows, so they pin the decision logic
(token parsing, field allowlists, conflict shape, restore selection) and not
the SQL. The conditional UPDATE itself needs a real database to be called
verified, and nothing here has been run -- the sandbox has no network, so
SQLAlchemy cannot be installed.
"""
from datetime import datetime, timedelta

import pytest

from sqlalchemy import create_engine, Integer, String, DateTime, Text
from sqlalchemy.orm import DeclarativeBase, Session, mapped_column, Mapped
from sqlalchemy.pool import StaticPool

from app.services import board_restore as br
from app.services import row_guard as rg
from fastapi import HTTPException


class FakeProject:
    def __init__(self, id=1, status="active", name="P", stamp=None):
        self.id = id; self.status = status; self.name = name
        self.progress = 0; self.company_id = 7
        self.updated_at = stamp or datetime(2026, 9, 14, 12, 0, 0)


class FakeTask:
    def __init__(self, id, status="cancelled", title="T"):
        self.id = id; self.status = status; self.title = title
        self.project_id = 1; self.updated_at = datetime(2026, 9, 14, 12, 0, 0)


class FakeResult:
    def __init__(self, rowcount=1, rows=None):
        self.rowcount = rowcount; self._rows = rows or []

    def scalars(self):
        return self

    def all(self):
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else None


class FakeDb:
    def __init__(self, rowcount=1, rows=None, get_map=None):
        self.rowcount = rowcount; self.rows = rows or []
        self.get_map = get_map or {}
        self.committed = 0; self.rolled_back = 0; self.statements = []

    def execute(self, stmt):
        self.statements.append(stmt)
        if getattr(stmt, "is_update", False) or "Update" in type(stmt).__name__:
            return FakeResult(rowcount=self.rowcount)
        return FakeResult(rows=self.rows)

    def commit(self):
        self.committed += 1

    def rollback(self):
        self.rolled_back += 1

    def refresh(self, _entity):
        return None

    def add(self, _entity):
        return None

    def get(self, _model, key):
        return self.get_map.get(key)


# ---------------------------------------------------------------------------
# Real-ORM harness for tests that must exercise the actual conditional UPDATE
# ---------------------------------------------------------------------------

_FIXED_STAMP = datetime(2026, 1, 1, 0, 0, 0)  # far in the past → always != utcnow()


class _GuardBase(DeclarativeBase):
    pass


class _GuardProject(_GuardBase):
    """Throwaway project model on in-memory SQLite.

    Mirrors every column compare_and_set touches.  __entity_kind__ = "project"
    makes row_revision.kind_of() return "project", matching WRITABLE and
    COUNTED_KINDS.  Production code is not touched.
    """
    __tablename__ = "guard_projects"
    __entity_kind__ = "project"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), default="P")
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="active")
    progress: Mapped[int] = mapped_column(Integer, default=0)
    owner_member_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    company_id: Mapped[int] = mapped_column(Integer, default=7)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    row_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)


@pytest.fixture
def _guard_session():
    """Fresh in-memory SQLite per test.  StaticPool shares one connection so
    out-of-band UPDATEs (the race simulation) are visible within the same
    session object."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    _GuardBase.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


@pytest.fixture
def _guard_proj(_guard_session):
    """A project row at a fixed past timestamp; row_revision starts NULL."""
    p = _GuardProject(name="P", status="active", updated_at=_FIXED_STAMP, row_revision=None)
    _guard_session.add(p)
    _guard_session.commit()
    _guard_session.refresh(p)
    return p


@pytest.fixture(autouse=True)
def no_events(monkeypatch):
    monkeypatch.setattr(rg, "emit_event", lambda *a, **k: None)
    monkeypatch.setattr(br, "emit_event", lambda *a, **k: None)


# -- revision tokens --------------------------------------------------------


def test_revision_token_splits_despite_colons_in_timestamp():
    project = FakeProject()
    name, row_id, stamp = rg.parse_revision(f"fakeproject:1:{project.updated_at.isoformat()}")
    assert (name, row_id, stamp) == ("fakeproject", 1, project.updated_at)


def test_never_written_row_parses_as_no_timestamp():
    assert rg.parse_revision("project:4:0")[2] is None


def test_malformed_token_is_a_guard_error_not_a_crash():
    for bad in ("", "project", "project:abc:2026-01-01T00:00:00", "project:1:not-a-date"):
        with pytest.raises(rg.GuardError):
            rg.parse_revision(bad)


def test_token_for_another_row_is_refused():
    db = FakeDb()
    with pytest.raises(rg.GuardError):
        rg.compare_and_set(db, FakeProject(id=1), {"name": "x"},
                           expected_revision="fakeproject:2:2026-09-14T12:00:00")


# -- the guard is binding, not advisory -------------------------------------


def test_missing_revision_is_refused_rather_than_degrading_to_plain_update():
    db = FakeDb()
    with pytest.raises(rg.GuardError):
        rg.compare_and_set(db, FakeProject(), {"name": "x"}, expected_revision="")
    assert db.committed == 0


def test_lost_race_is_reported_by_the_database_not_guessed(_guard_session, _guard_proj):
    # Token reflects the row BEFORE another writer advances updated_at.
    token = f"project:{_guard_proj.id}:{_FIXED_STAMP.isoformat()}"
    # Race: a concurrent write moves the row's timestamp.
    from sqlalchemy import text
    _guard_session.execute(
        text("UPDATE guard_projects SET updated_at = :s WHERE id = :i"),
        {"s": (_FIXED_STAMP + timedelta(seconds=1)).isoformat(), "i": _guard_proj.id},
    )
    _guard_session.commit()
    # compare_and_set issues WHERE updated_at = old_stamp; the database
    # returns rowcount=0 because the row moved.  This is the binding guard.
    with pytest.raises(HTTPException) as err:
        rg.compare_and_set(_guard_session, _guard_proj, {"name": "new"},
                           expected_revision=token)
    assert err.value.status_code == 409
    assert err.value.detail["applied"] is False
    assert err.value.detail["binding"] is True
    # rowcount=0 came from the database, not a fake.  Prove the write never
    # landed: after rollback the name is unchanged.
    _guard_session.refresh(_guard_proj)
    assert _guard_proj.name != "new"


def test_winning_write_commits_and_reports_both_revisions(_guard_session, _guard_proj):
    token = f"project:{_guard_proj.id}:{_FIXED_STAMP.isoformat()}"
    out = rg.compare_and_set(_guard_session, _guard_proj, {"name": "new"},
                             expected_revision=token)
    assert out["applied"] is True
    assert out["previous_revision"] == token
    assert out["fields"] == ["name"]


def test_conflict_event_failure_does_not_mask_the_409(monkeypatch, _guard_session, _guard_proj):
    def boom(*_a, **_k):
        raise RuntimeError("event bus down")
    monkeypatch.setattr(rg, "emit_event", boom)
    token = f"project:{_guard_proj.id}:{_FIXED_STAMP.isoformat()}"
    # Advance the row so the guard sees rowcount=0.
    from sqlalchemy import text
    _guard_session.execute(
        text("UPDATE guard_projects SET updated_at = :s WHERE id = :i"),
        {"s": (_FIXED_STAMP + timedelta(seconds=1)).isoformat(), "i": _guard_proj.id},
    )
    _guard_session.commit()
    with pytest.raises(HTTPException) as err:
        rg.compare_and_set(_guard_session, _guard_proj, {"name": "x"},
                           expected_revision=token, organization_id=3)
    assert err.value.status_code == 409


# -- field allowlist --------------------------------------------------------


def test_tenancy_and_runtime_columns_are_not_writable_anywhere():
    forbidden = {"organization_id", "company_id", "runtime_session_key", "runtime_agent_id", "id"}
    for fields in rg.WRITABLE.values():
        assert forbidden.isdisjoint(fields)


def test_unknown_field_is_refused_before_touching_the_database():
    project = FakeProject()
    db = FakeDb()
    with pytest.raises(rg.GuardError):
        rg.compare_and_set(db, project, {"organization_id": 9},
                           expected_revision=f"fakeproject:1:{project.updated_at.isoformat()}")
    assert db.statements == []


def test_empty_value_set_is_refused_so_a_no_op_cannot_bump_the_revision():
    project = FakeProject()
    with pytest.raises(rg.GuardError):
        rg.compare_and_set(FakeDb(), project, {},
                           expected_revision=f"fakeproject:1:{project.updated_at.isoformat()}")


def test_entity_without_a_field_list_gets_no_generic_write_path():
    class FakeApproval:
        id = 1; updated_at = datetime(2026, 9, 14, 12, 0, 0)
    with pytest.raises(rg.GuardError):
        rg.compare_and_set(FakeDb(), FakeApproval(), {"status": "approved"},
                           expected_revision="fakeapproval:1:2026-09-14T12:00:00")


# -- restore ----------------------------------------------------------------


class FakeEvent:
    def __init__(self, payload, id=11):
        import json
        self.id = id
        self.payload_json = json.dumps(payload)
        self.occurred_at = datetime(2026, 9, 14, 11, 0, 0)


def _preview(monkeypatch, project, event, rows):
    monkeypatch.setattr(br, "last_archive_event", lambda *a, **k: event)
    db = FakeDb(rows=rows, get_map={t.id: t for t in rows})
    return db, br.restore_preview(db, project, 1)


def test_restore_reads_the_cancelled_ids_out_of_the_archive_event(monkeypatch):
    tasks = [FakeTask(5), FakeTask(6)]
    event = FakeEvent({"cancelled_task_ids": [5, 6], "previous_status": "active"})
    _db, preview = _preview(monkeypatch, FakeProject(status="cancelled"), event, tasks)
    assert [t["task_id"] for t in preview["will_restore_tasks"]] == [5, 6]
    assert preview["previous_status"] == "active"
    assert preview["previous_status_known"] is True


def test_pre_v28_archive_has_no_previous_status_and_says_so(monkeypatch):
    event = FakeEvent({"cancelled_task_ids": [5]})
    _db, preview = _preview(monkeypatch, FakeProject(status="cancelled"), event, [FakeTask(5)])
    assert preview["previous_status"] == br.RESTORE_STATUS
    assert preview["previous_status_known"] is False


def test_a_task_someone_moved_after_the_archive_is_left_alone(monkeypatch):
    tasks = [FakeTask(5), FakeTask(6, status="in_progress")]
    event = FakeEvent({"cancelled_task_ids": [5, 6]})
    db, _ = _preview(monkeypatch, FakeProject(status="cancelled"), event, tasks)
    out = br.restore_project(db, FakeProject(status="cancelled"), 1)
    assert out["restored_task_ids"] == [5]
    assert [t["task_id"] for t in out["skipped_tasks"]] == [6]


def test_restored_tasks_land_in_existing_board_vocabulary():
    from app.services.workspace_ops import PROJECT_STATUSES, TASK_STATUSES
    assert br.RESTORE_TASK_STATUS in TASK_STATUSES
    assert br.RESTORE_STATUS in PROJECT_STATUSES


def test_restoring_a_live_project_is_refused(monkeypatch):
    monkeypatch.setattr(br, "last_archive_event", lambda *a, **k: None)
    with pytest.raises(HTTPException) as err:
        br.restore_project(FakeDb(), FakeProject(status="active"), 1)
    assert err.value.status_code == 409


def test_archive_without_a_record_refuses_and_points_at_the_manual_path(monkeypatch):
    monkeypatch.setattr(br, "last_archive_event", lambda *a, **k: None)
    with pytest.raises(HTTPException) as err:
        br.restore_project(FakeDb(), FakeProject(status="cancelled"), 1)
    assert "hint" in err.value.detail


def test_ids_recorded_but_no_longer_present_are_reported_not_silently_dropped(monkeypatch):
    event = FakeEvent({"cancelled_task_ids": [5, 99]})
    _db, preview = _preview(monkeypatch, FakeProject(status="cancelled"), event, [FakeTask(5)])
    assert preview["missing_tasks"] == [99]


def test_corrupt_payload_degrades_to_nothing_to_restore(monkeypatch):
    class Broken:
        id = 3; payload_json = "{not json"; occurred_at = None
    monkeypatch.setattr(br, "last_archive_event", lambda *a, **k: Broken())
    preview = br.restore_preview(FakeDb(), FakeProject(status="cancelled"), 1)
    assert preview["recorded_cancelled_tasks"] == 0


def test_archive_now_records_what_it_is_reversing():
    import inspect
    from app.services import board_truth
    assert "previous_status" in inspect.getsource(board_truth.archive_project)


def test_restore_event_is_distinct_from_the_archive_event():
    from app.services.board_truth import ARCHIVE_EVENT
    assert br.RESTORE_EVENT != ARCHIVE_EVENT


def test_archive_lookup_is_scoped_to_one_organization():
    import inspect
    assert "organization_id" in inspect.getsource(br.last_archive_event)


def test_guard_conflict_reuses_v27_event_type():
    from app.services.board_truth import CONFLICT_EVENT
    assert rg.CONFLICT_EVENT == CONFLICT_EVENT


def test_stale_window_is_documented_as_closed_by_the_database():
    import inspect
    source = inspect.getsource(rg.compare_and_set)
    assert "rowcount" in source


def test_guarded_update_sets_updated_at_explicitly(_guard_session, _guard_proj):
    # Behavioral check: compare_and_set issues a Core UPDATE, not an ORM
    # flush, so 'onupdate' hooks do not fire.  updated_at must be set
    # explicitly in the VALUES clause; otherwise the revision never moves and
    # the next guarded write passes a WHERE it should fail.
    original_stamp = _guard_proj.updated_at
    token = f"project:{_guard_proj.id}:{original_stamp.isoformat()}"
    rg.compare_and_set(_guard_session, _guard_proj, {"name": "Renamed"}, expected_revision=token)
    # db.refresh() is called inside compare_and_set; updated_at here reflects
    # what the database actually stored after the write.
    assert _guard_proj.updated_at != original_stamp
