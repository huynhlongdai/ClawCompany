"""v30 tests: exact revision counters, paged audit, batch board restore.

Stand-ins again, for the same reason as v28 and v29: the sandbox has no
network, so SQLAlchemy is not installed and none of this has been run. What
these pin is decision logic -- token shape, guard mode, cursor advancement,
batch skip rules -- not the SQL. The conditional UPDATE against a counter
column still needs a real database, ideally with two concurrent writers.
"""
from datetime import datetime

import pytest
from fastapi import HTTPException

from app.services import cascade_restore as cr
from app.services import row_guard as rg
from app.services import row_revision as rev
from app.services import write_audit as wa


STAMP = datetime(2026, 9, 14, 12, 0, 0)


class FakeProject:
    __entity_kind__ = "project"

    def __init__(self, id=1, status="cancelled", name="P", counter=3):
        self.id = id
        self.status = status
        self.name = name
        self.description = ""
        self.progress = 0
        self.owner_member_id = None
        self.company_id = 7
        self.updated_at = STAMP
        self.row_revision = counter


class FakeCompany:
    __entity_kind__ = "company"

    def __init__(self, id=7, status="archived", name="Nova", counter=2):
        self.id = id
        self.name = name
        self.industry = "tech"
        self.status = status
        self.updated_at = STAMP
        self.row_revision = counter


class Legacy:
    """A row from before migration 0013: column present, value NULL."""

    __entity_kind__ = "project"

    def __init__(self, id=9):
        self.id = id
        self.name = "Old"
        self.status = "active"
        self.description = ""
        self.progress = 0
        self.owner_member_id = None
        self.updated_at = STAMP
        self.row_revision = None


class Uncounted:
    """An entity kind that never gets a counter at all."""

    __entity_kind__ = "agent"

    def __init__(self, id=3):
        self.id = id
        self.updated_at = STAMP


class FakeResult:
    def __init__(self, rowcount=1, rows=None):
        self.rowcount = rowcount
        self._rows = rows or []

    def scalars(self):
        return self

    def all(self):
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else None


class FakeDb:
    def __init__(self, rowcount=1, rows=None, get_map=None):
        self.rowcount = rowcount
        self.rows = rows or []
        self.get_map = get_map or {}
        self.committed = 0
        self.rolled_back = 0
        self.statements = []

    def execute(self, stmt):
        self.statements.append(stmt)
        if "Update" in type(stmt).__name__:
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


@pytest.fixture(autouse=True)
def no_events(monkeypatch):
    monkeypatch.setattr(rg, "emit_event", lambda *a, **k: None)
    monkeypatch.setattr(cr, "emit_event", lambda *a, **k: None)


# -- revision tokens --------------------------------------------------------


def test_counted_row_prefers_the_counter_token():
    assert rev.token(FakeProject(counter=3)) == "project:1:r3"


def test_uncounted_row_falls_back_to_the_timestamp_token():
    assert rev.token(Legacy()) == f"project:9:{STAMP.isoformat()}"


def test_missing_counter_is_not_zero():
    # A row that was never counted cannot be guarded exactly; reporting 0
    # would let the first guarded write claim a guarantee it lacks.
    assert rev.counter(Legacy()) is None
    assert rev.counter(FakeProject(counter=0)) == 0


def test_entity_without_the_column_never_claims_counter_support():
    assert rev.supports_counter(Uncounted()) is False
    assert rev.describe(Uncounted())["mode"] == rev.TIMESTAMP_MODE


def test_describe_marks_exactness_and_says_why_not():
    legacy = rev.describe(Legacy())
    assert legacy["exact"] is False
    assert "clock tick" in legacy["note"]
    counted = rev.describe(FakeProject())
    assert counted["exact"] is True


def test_parse_separates_counter_from_timestamp_mode():
    assert rev.parse("project:1:r7")[2:] == (rev.COUNTER_MODE, 7)
    kind, row_id, mode, value = rev.parse(f"project:1:{STAMP.isoformat()}")
    assert (kind, row_id, mode, value) == ("project", 1, rev.TIMESTAMP_MODE, STAMP)


def test_parse_still_splits_timestamps_that_contain_colons():
    assert rev.parse(f"task:12:{STAMP.isoformat()}")[3] == STAMP


def test_never_written_row_parses_as_no_timestamp():
    assert rev.parse("project:4:0")[3] is None


def test_malformed_tokens_raise_a_typed_error():
    for bad in ("", "project", "project:x:r1", "project:1:not-a-time"):
        with pytest.raises(rev.RevisionError):
            rev.parse(bad)


def test_next_counter_adopts_an_uncounted_row_at_one():
    assert rev.next_counter(Legacy()) == 1
    assert rev.next_counter(FakeProject(counter=4)) == 5


# -- guarded writes ---------------------------------------------------------


def test_counter_token_guards_on_the_counter_column():
    db = FakeDb(rowcount=1)
    project = FakeProject(counter=3)
    out = rg.compare_and_set(db, project, {"name": "New"},
                             expected_revision="project:1:r3")
    assert out["applied"] is True
    assert out["guard_mode"] == rev.COUNTER_MODE
    assert out["exact"] is True


def test_a_guarded_write_bumps_the_counter():
    db = FakeDb(rowcount=1)
    project = FakeProject(counter=3)
    rg.compare_and_set(db, project, {"name": "New"}, expected_revision="project:1:r3")
    values = db.statements[0].compile().params
    assert values["row_revision"] == 4


def test_a_timestamp_guarded_write_still_adopts_the_counter():
    # This is how a pre-0013 row stops being uncounted without a backfill
    # pass: the first guarded write writes 1.
    db = FakeDb(rowcount=1)
    legacy = Legacy()
    out = rg.compare_and_set(db, legacy, {"name": "New"},
                             expected_revision=f"project:9:{STAMP.isoformat()}")
    assert out["guard_mode"] == rev.TIMESTAMP_MODE
    assert out["exact"] is False
    assert db.statements[0].compile().params["row_revision"] == 1


def test_timestamp_guard_reports_itself_as_inexact():
    db = FakeDb(rowcount=1)
    out = rg.compare_and_set(db, Legacy(), {"name": "N"},
                             expected_revision=f"project:9:{STAMP.isoformat()}")
    assert out["exact"] is False


def test_counter_token_on_an_entity_without_a_counter_is_refused():
    with pytest.raises(rg.GuardError):
        rg.compare_and_set(FakeDb(), Uncounted(), {"name": "N"},
                           expected_revision="agent:3:r1")


def test_lost_race_on_the_counter_rolls_back_and_raises_409():
    db = FakeDb(rowcount=0)
    with pytest.raises(HTTPException) as exc:
        rg.compare_and_set(db, FakeProject(counter=3), {"name": "N"},
                           expected_revision="project:1:r3")
    assert exc.value.status_code == 409
    assert db.rolled_back == 1
    assert db.committed == 0


def test_conflict_reports_the_preferred_token_not_the_legacy_one():
    db = FakeDb(rowcount=0)
    with pytest.raises(HTTPException) as exc:
        rg.compare_and_set(db, FakeProject(counter=9), {"name": "N"},
                           expected_revision="project:1:r3")
    assert exc.value.detail["current_revision"] == "project:1:r9"


def test_token_for_another_row_is_still_refused():
    with pytest.raises(rg.GuardError):
        rg.compare_and_set(FakeDb(), FakeProject(), {"name": "N"},
                           expected_revision="project:2:r3")


def test_tenancy_columns_are_still_not_writable():
    for fields in rg.WRITABLE.values():
        assert "organization_id" not in fields
        assert "row_revision" not in fields


# -- audit pagination -------------------------------------------------------


class AuditEvent:
    def __init__(self, id, event_type="board.write.guarded", payload=None):
        self.id = id
        self.event_type = event_type
        self.source = "row_guard"
        self.aggregate_type = "project"
        self.aggregate_id = "1"
        self.company_id = 7
        self.actor_member_id = 4
        self.correlation_id = ""
        self.occurred_at = STAMP
        self.payload = payload or {"fields": ["name"], "revision": "project:1:r4"}


class AuditDb:
    def __init__(self, events):
        self.events = events
        self.last_limit = None

    def execute(self, stmt):
        # The fake honours only the limit; filtering is asserted through the
        # rows the test feeds in, not by re-implementing SQL here.
        self.last_limit = getattr(stmt, "_limit", None)
        return FakeResult(rows=list(self.events))


@pytest.fixture(autouse=True)
def audit_payload(monkeypatch):
    monkeypatch.setattr(wa, "payload_of", lambda event: getattr(event, "payload", {}))


def test_first_page_without_a_cursor_reports_no_previous_bookmark():
    db = AuditDb([AuditEvent(5), AuditEvent(4)])
    out = wa.feed(db, 1, limit=10)
    assert out["cursor"] is None
    assert out["returned"] == 2


def test_a_full_page_hands_back_a_cursor():
    db = AuditDb([AuditEvent(i) for i in range(20, 10, -1)])
    out = wa.feed(db, 1, limit=10)
    assert out["has_more"] is True
    assert out["next_cursor"] == 11


def test_a_short_page_ends_the_walk():
    db = AuditDb([AuditEvent(5)])
    out = wa.feed(db, 1, limit=10)
    assert out["next_cursor"] is None
    assert out["has_more"] is False


def test_cursor_advances_past_filtered_out_events():
    # Category filtering happens in Python. Paging on the last *returned*
    # row would re-serve every event the filter dropped at the tail.
    events = [AuditEvent(30, "board.write.conflict")]
    events += [AuditEvent(i) for i in range(29, 19, -1)]
    db = AuditDb(events)
    out = wa.feed(db, 1, limit=1, categories=("conflict",))
    assert out["returned"] == 1
    assert out["next_cursor"] == 30


def test_a_broken_cursor_returns_the_first_page_instead_of_an_error():
    db = AuditDb([AuditEvent(5)])
    out = wa.feed(db, 1, cursor="not-a-number")
    assert out["cursor"] is None
    assert out["returned"] == 1


def test_limit_is_still_clamped_not_trusted():
    db = AuditDb([AuditEvent(i) for i in range(500, 0, -1)])
    assert wa.feed(db, 1, limit=9999)["limit"] == wa.MAX_LIMIT


def test_entity_history_passes_the_cursor_through():
    db = AuditDb([AuditEvent(3)])
    out = wa.entity_history(db, 1, "project", "1", cursor=99)
    assert out["cursor"] == 99


# -- batch project restore --------------------------------------------------


class ArchiveEvent:
    def __init__(self, payload, id=88):
        self.id = id
        self.payload = payload
        self.occurred_at = STAMP


def plant(monkeypatch, *, event, projects, previews=None, restores=None):
    monkeypatch.setattr(cr, "last_archive_event", lambda *a, **k: event)
    monkeypatch.setattr(cr, "payload_of", lambda e: getattr(e, "payload", {}))
    monkeypatch.setattr(cr.board_restore, "restore_preview",
                        lambda db, project, org: (previews or {}).get(
                            project.id, {"previous_status": "active",
                                         "previous_status_known": True,
                                         "will_restore_tasks": [],
                                         "will_skip_tasks": []}))

    def _restore(db, project, org, actor_member_id=None):
        handler = (restores or {}).get(project.id)
        if handler is not None:
            return handler()
        project.status = "active"
        return {"project_id": project.id, "status": "active",
                "previous_status_known": True, "restored_tasks": [1],
                "skipped_tasks": []}

    monkeypatch.setattr(cr.board_restore, "restore_project", _restore)
    return FakeDb(rows=projects, get_map={p.id: p for p in projects})


def test_preview_lists_only_projects_this_archive_cancelled(monkeypatch):
    projects = [FakeProject(id=1), FakeProject(id=2)]
    event = ArchiveEvent({"archived_projects": [{"project_id": 1}]})
    db = plant(monkeypatch, event=event, projects=projects)
    out = cr.preview(db, FakeCompany(), 1)
    assert [item["project_id"] for item in out["will_restore"]] == [1]


def test_preview_skips_a_project_somebody_already_reopened(monkeypatch):
    projects = [FakeProject(id=1, status="active")]
    event = ArchiveEvent({"archived_projects": [{"project_id": 1}]})
    db = plant(monkeypatch, event=event, projects=projects)
    out = cr.preview(db, FakeCompany(), 1)
    assert out["will_restore"] == []
    assert "already reopened" in out["will_skip"][0]["reason"]


def test_preview_reports_a_project_that_no_longer_exists(monkeypatch):
    event = ArchiveEvent({"archived_projects": [{"project_id": 42}]})
    db = plant(monkeypatch, event=event, projects=[])
    out = cr.preview(db, FakeCompany(), 1)
    assert out["will_skip"][0]["reason"] == "project no longer exists"


def test_garbage_entries_in_the_payload_are_dropped(monkeypatch):
    event = ArchiveEvent({"archived_projects": ["nope", {"project_id": "x"}, {}]})
    db = plant(monkeypatch, event=event, projects=[])
    assert cr.preview(db, FakeCompany(), 1)["recorded_projects"] == 0


def test_no_archive_record_refuses_instead_of_reopening_everything(monkeypatch):
    db = plant(monkeypatch, event=None, projects=[FakeProject(id=1)])
    with pytest.raises(HTTPException) as exc:
        cr.restore_projects(db, FakeCompany(), 1)
    assert exc.value.status_code == 409


def test_batch_restores_each_project_through_the_v28_path(monkeypatch):
    projects = [FakeProject(id=1), FakeProject(id=2)]
    event = ArchiveEvent({"archived_projects": [{"project_id": 1}, {"project_id": 2}]})
    db = plant(monkeypatch, event=event, projects=projects)
    out = cr.restore_projects(db, FakeCompany(), 1)
    assert out["restored_count"] == 2
    assert out["complete"] is True


def test_one_failure_does_not_abort_the_batch(monkeypatch):
    projects = [FakeProject(id=1), FakeProject(id=2)]
    event = ArchiveEvent({"archived_projects": [{"project_id": 1}, {"project_id": 2}]})

    def boom():
        raise HTTPException(409, detail={"error": "Project is not archived"})

    db = plant(monkeypatch, event=event, projects=projects, restores={1: boom})
    out = cr.restore_projects(db, FakeCompany(), 1)
    assert out["restored_count"] == 1
    assert out["failed"][0]["project_id"] == 1
    assert out["complete"] is False


def test_a_partial_batch_is_reported_not_rolled_back(monkeypatch):
    projects = [FakeProject(id=1), FakeProject(id=2)]
    event = ArchiveEvent({"archived_projects": [{"project_id": 1}, {"project_id": 2}]})

    def boom():
        raise HTTPException(500, detail="kaboom")

    db = plant(monkeypatch, event=event, projects=projects, restores={2: boom})
    out = cr.restore_projects(db, FakeCompany(), 1)
    assert [item["project_id"] for item in out["restored"]] == [1]
    assert out["failed"][0]["reason"] == "kaboom"


def test_restoring_a_board_does_not_claim_the_company_came_back(monkeypatch):
    projects = [FakeProject(id=1)]
    event = ArchiveEvent({"archived_projects": [{"project_id": 1}]})
    db = plant(monkeypatch, event=event, projects=projects)
    out = cr.restore_projects(db, FakeCompany(status="archived"), 1)
    assert out["company_still_archived"] is True


def test_batch_restore_is_company_scoped(monkeypatch):
    db = plant(monkeypatch, event=None, projects=[])
    with pytest.raises(HTTPException) as exc:
        cr.preview(db, FakeProject(), 1)
    assert exc.value.status_code == 400
