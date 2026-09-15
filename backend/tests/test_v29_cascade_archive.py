"""v29 tests: cascade archive for the org tree, and the write audit feed.

Same approach as the v28 tests: light stand-ins for ORM rows, so the
decision logic (cascade shape, live-session blocking, prior-state recording,
audit categorisation) is pinned without a database. Nothing here has been
executed -- the sandbox has no network, so SQLAlchemy and pytest cannot be
installed. Treat these as specifications to run on a networked machine.
"""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from app.services import entity_archive as ea
from app.services import write_audit as wa

STAMP = datetime(2026, 9, 14, 12, 0, 0)


class FakeCompany:
    __entity_kind__ = "company"

    def __init__(self, id=1, status="active", name="Nova Holding"):
        self.id = id; self.status = status; self.name = name
        self.industry = "holding"; self.updated_at = STAMP


class FakeDepartment:
    __entity_kind__ = "department"

    def __init__(self, id=10, access_level="restricted", name="Marketing"):
        self.id = id; self.access_level = access_level; self.name = name
        self.company_id = 1; self.head_member_id = None; self.updated_at = STAMP
        # v31 added a real departments.status column; entity_archive.py sets
        # dept.status = DEPARTMENT_ARCHIVED on archive and reads dept.status
        # on restore.  The fake must carry this field so archive_entity works.
        self.status = "active"


class FakeMember:
    __entity_kind__ = "member"

    def __init__(self, id=100, status="active", name="Nina", member_type="agent"):
        self.id = id; self.status = status; self.name = name
        self.member_type = member_type; self.company_id = 1
        self.department_id = 10; self.updated_at = STAMP


class FakeAgent:
    def __init__(self, id=500, member_id=100):
        self.id = id; self.member_id = member_id
        self.runtime_agent_id = f"oc-{id}"; self.lifecycle = "active"


class FakeProject:
    def __init__(self, id=900, status="active", name="Launch"):
        self.id = id; self.status = status; self.name = name
        self.company_id = 1; self.progress = 0; self.updated_at = STAMP


class FakeDb:
    def __init__(self):
        self.committed = 0; self.added = []

    def execute(self, _stmt):  # pragma: no cover - subtree helpers are patched
        raise AssertionError("subtree helpers should be patched in these tests")

    def add(self, entity):
        self.added.append(entity)

    def commit(self):
        self.committed += 1

    def refresh(self, _entity):
        return None


def plant(monkeypatch, *, departments=(), members=(), agents=(), projects=(), live=()):
    monkeypatch.setattr(ea, "_departments_of", lambda db, kind, e: list(departments) if kind in ("company", "department") else [])
    monkeypatch.setattr(ea, "_members_of", lambda db, kind, e: [e] if kind == "member" else list(members))
    monkeypatch.setattr(ea, "_agents_of", lambda db, ms: list(agents))
    monkeypatch.setattr(ea, "_projects_of", lambda db, kind, e: list(projects) if kind == "company" else [])
    monkeypatch.setattr(ea, "_live_sessions", lambda db, kind, e, ms, ps: list(live))


@pytest.fixture(autouse=True)
def no_events(monkeypatch):
    monkeypatch.setattr(ea, "emit_event", lambda *a, **k: None)


# -- kind detection ---------------------------------------------------------


def test_kind_of_reads_the_declared_kind():
    assert ea.kind_of(FakeCompany()) == "company"
    assert ea.kind_of(FakeDepartment()) == "department"
    assert ea.kind_of(FakeMember()) == "member"


def test_unknown_entity_is_refused_not_guessed():
    with pytest.raises(ea.CascadeError):
        ea.kind_of(FakeProject())


# -- preview ----------------------------------------------------------------


def test_company_preview_reports_the_whole_subtree(monkeypatch):
    db = FakeDb()
    plant(monkeypatch, departments=[FakeDepartment()], members=[FakeMember()],
          agents=[FakeAgent()], projects=[FakeProject()])
    out = ea.cascade_preview(db, FakeCompany(), 1)
    assert out["counts"] == {"departments": 1, "members": 1, "agents": 1, "projects": 1}
    assert out["blocked"] is False
    assert out["destructive"] is False


def test_preview_skips_projects_already_archived(monkeypatch):
    db = FakeDb()
    plant(monkeypatch, projects=[FakeProject(status="cancelled")])
    out = ea.cascade_preview(db, FakeCompany(), 1)
    assert out["counts"]["projects"] == 0


def test_preview_skips_members_already_offboarded(monkeypatch):
    db = FakeDb()
    plant(monkeypatch, members=[FakeMember(status="offboarded"), FakeMember(id=101)])
    out = ea.cascade_preview(db, FakeCompany(), 1)
    assert out["counts"]["members"] == 1


def test_live_session_blocks_the_preview(monkeypatch):
    db = FakeDb()
    plant(monkeypatch, members=[FakeMember()],
          live=[{"task_id": 5, "session_key": "agent:7:company-task-5"}])
    out = ea.cascade_preview(db, FakeMember(), 1)
    assert out["blocked"] is True and out["blocked_reason"]


def test_agents_are_reported_as_left_registered(monkeypatch):
    db = FakeDb()
    plant(monkeypatch, members=[FakeMember()], agents=[FakeAgent()])
    out = ea.cascade_preview(db, FakeMember(), 1)
    assert out["agents_left_registered"][0]["runtime_agent_id"] == "oc-500"


def test_department_preview_does_not_claim_projects(monkeypatch):
    db = FakeDb()
    plant(monkeypatch, departments=[FakeDepartment()], members=[FakeMember()],
          projects=[FakeProject()])
    out = ea.cascade_preview(db, FakeDepartment(), 1)
    assert out["counts"]["projects"] == 0
    # Only a company archive lists departments as cascade targets.
    assert out["will_archive"]["departments"] == []


# -- archive ----------------------------------------------------------------


def test_archive_blocks_on_live_sessions_without_force(monkeypatch):
    db = FakeDb()
    plant(monkeypatch, members=[FakeMember()], live=[{"task_id": 5, "session_key": "k"}])
    with pytest.raises(HTTPException) as err:
        ea.archive_entity(db, FakeMember(), 1)
    assert err.value.status_code == 409
    assert "live_runtime_sessions" in err.value.detail


def test_forced_archive_says_what_it_left_running(monkeypatch):
    db = FakeDb()
    member = FakeMember()
    plant(monkeypatch, members=[member], live=[{"task_id": 5, "session_key": "k"}])
    out = ea.archive_entity(db, member, 1, force=True)
    assert out["forced"] is True
    assert out["left_running"] == [{"task_id": 5, "session_key": "k"}]
    assert out["deleted"] is False


def test_already_archived_company_is_refused(monkeypatch):
    db = FakeDb()
    plant(monkeypatch)
    with pytest.raises(HTTPException) as err:
        ea.archive_entity(db, FakeCompany(status="archived"), 1)
    assert err.value.status_code == 409


def test_member_archive_uses_the_existing_offboarded_word(monkeypatch):
    db = FakeDb()
    member = FakeMember(status="active")
    plant(monkeypatch, members=[member])
    out = ea.archive_entity(db, member, 1)
    assert member.status == "offboarded"
    assert out["previous"]["self"] == "active"


def test_department_archive_locks_access_level(monkeypatch):
    # v31 added departments.status; v32 archives on status, not access_level.
    # The column that "locks" a department is now status="archived", not
    # access_level="confidential" (which was the v29 behaviour).
    db = FakeDb()
    dept = FakeDepartment(access_level="org_public")
    plant(monkeypatch, members=[FakeMember()])
    out = ea.archive_entity(db, dept, 1)
    assert dept.status == ea.DEPARTMENT_ARCHIVED          # status is the lock
    assert dept.access_level == "org_public"              # access_level is untouched by v32
    assert out["previous"]["self"] == "active"            # prior status recorded, not access_level


def test_company_archive_cascades_to_departments_members_and_projects(monkeypatch):
    db = FakeDb()
    company, dept = FakeCompany(), FakeDepartment()
    member, project = FakeMember(), FakeProject()
    plant(monkeypatch, departments=[dept], members=[member], projects=[project])
    calls = []

    def fake_archive_project(db_, p, org, **kw):
        calls.append((p.id, kw.get("force")))
        return {"previous_status": p.status, "cancelled_task_ids": [1, 2]}

    monkeypatch.setattr(ea, "archive_project", fake_archive_project)
    out = ea.archive_entity(db, company, 1)
    assert company.status == "archived"
    # v32 archives departments via status="archived", not access_level (v29 legacy).
    assert dept.status == ea.DEPARTMENT_ARCHIVED
    assert dept.access_level == "restricted"          # access_level untouched by v32
    assert member.status == "offboarded"
    assert calls == [(900, True)]
    assert out["archived_projects"][0]["cancelled_task_ids"] == [1, 2]
    assert out["archived_members"] == [100]


def test_archive_records_prior_member_statuses_for_restore(monkeypatch):
    db = FakeDb()
    a, b = FakeMember(id=100, status="active"), FakeMember(id=101, status="paused")
    plant(monkeypatch, members=[a, b])
    monkeypatch.setattr(ea, "archive_project", lambda *a_, **k: {})
    out = ea.archive_entity(db, FakeCompany(), 1)
    assert out["previous"]["members"] == {"100": "active", "101": "paused"}


# -- restore ----------------------------------------------------------------


class FakeEvent:
    def __init__(self, payload, occurred_at=None):
        self.payload = payload
        self.occurred_at = occurred_at or STAMP


def plant_event(monkeypatch, payload):
    monkeypatch.setattr(ea, "last_archive_event", lambda db, e, org: FakeEvent(payload) if payload is not None else None)
    monkeypatch.setattr(ea, "payload_of", lambda event: event.payload)


def test_restore_preview_uses_recorded_statuses(monkeypatch):
    db = FakeDb()
    member = FakeMember(status="offboarded")
    plant(monkeypatch, members=[member])
    plant_event(monkeypatch, {"previous": {"self": "paused", "members": {"100": "paused"}}})
    out = ea.restore_preview(db, FakeCompany(status="archived"), 1)
    assert out["restore_to"] == "paused" and out["prior_state_known"] is True
    assert out["will_restore_members"][0]["restore_to"] == "paused"
    assert out["will_restore_members"][0]["prior_status_known"] is True


def test_restore_preview_is_honest_when_there_is_no_record(monkeypatch):
    db = FakeDb()
    plant(monkeypatch, members=[FakeMember(status="offboarded")])
    plant_event(monkeypatch, None)
    out = ea.restore_preview(db, FakeCompany(status="archived"), 1)
    assert out["has_archive_record"] is False
    assert out["prior_state_known"] is False
    assert out["restore_to"] == "active"
    assert out["will_restore_members"][0]["prior_status_known"] is False


def test_recorded_ignores_junk_keys_and_values():
    payload = {"previous": {"members": {"100": "active", "x": "active", "101": 7}}}
    assert ea._recorded(payload, "members") == {100: "active"}


def test_restore_refuses_a_row_that_is_not_archived(monkeypatch):
    db = FakeDb()
    plant(monkeypatch)
    with pytest.raises(HTTPException) as err:
        ea.restore_entity(db, FakeCompany(status="active"), 1)
    assert err.value.status_code == 409


def test_restore_returns_each_row_to_its_own_prior_state(monkeypatch):
    db = FakeDb()
    company = FakeCompany(status="archived")
    dept = FakeDepartment(access_level="confidential")
    a = FakeMember(id=100, status="offboarded")
    b = FakeMember(id=101, status="offboarded")
    plant(monkeypatch, departments=[dept], members=[a, b])
    plant_event(monkeypatch, {"previous": {"self": "paused",
                                            "members": {"100": "active", "101": "paused"},
                                            "departments": {"10": "org_public"}},
                              "archived_projects": [{"project_id": 900}]})
    out = ea.restore_entity(db, company, 1)
    assert company.status == "paused"
    assert dept.access_level == "org_public"
    assert (a.status, b.status) == ("active", "paused")
    assert out["projects_restored_separately"] == [900]


def test_restore_leaves_members_somebody_already_reinstated(monkeypatch):
    db = FakeDb()
    kept = FakeMember(id=100, status="active")
    plant(monkeypatch, members=[kept])
    plant_event(monkeypatch, {"previous": {"self": "active", "members": {"100": "paused"}}})
    out = ea.restore_entity(db, FakeCompany(status="archived"), 1)
    assert kept.status == "active"
    assert out["restored_members"] == []


# -- write audit ------------------------------------------------------------


class AuditEvent:
    def __init__(self, id, event_type, payload=None, occurred_at=None,
                 aggregate_type="project", aggregate_id="900"):
        self.id = id; self.event_type = event_type; self.payload = payload or {}
        self.occurred_at = occurred_at or STAMP
        self.aggregate_type = aggregate_type; self.aggregate_id = aggregate_id
        self.company_id = 1; self.actor_member_id = 100
        self.source = "row_guard"; self.correlation_id = "corr-1"


class AuditResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return self._rows


class AuditDb:
    def __init__(self, rows):
        self.rows = rows

    def execute(self, _stmt):
        return AuditResult(self.rows)


@pytest.fixture(autouse=True)
def audit_payload(monkeypatch):
    monkeypatch.setattr(wa, "payload_of", lambda event: event.payload)


def test_guarded_write_row_names_the_fields_that_moved():
    row = wa.row_of(AuditEvent(1, "board.write.guarded",
                               {"entity": "project", "fields": {"status": "active"},
                                "revision": "project:900:x"}))
    assert row["category"] == "write"
    assert row["fields"] == ["status"]
    assert "status" in row["summary"]
    assert row["applied"] is True


def test_conflict_row_is_not_marked_applied():
    row = wa.row_of(AuditEvent(2, "board.write.conflict",
                               {"applied": False, "expected_revision": "project:900:old"}))
    assert row["category"] == "conflict"
    assert row["applied"] is False
    assert "changed first" in row["summary"]


def test_archive_and_restore_rows_are_categorised():
    archived = wa.row_of(AuditEvent(3, "project.archived", {"cancelled_task_ids": [1, 2, 3]}))
    restored = wa.row_of(AuditEvent(4, "member.restored", {"kind": "member",
                                                           "restored_members": [{"member_id": 100}]}))
    assert archived["category"] == "archive" and "3 open task" in archived["summary"]
    assert restored["category"] == "restore"


def test_unknown_event_type_is_labelled_other_not_dropped():
    row = wa.row_of(AuditEvent(5, "something.new"))
    assert row["category"] == "other" and row["summary"] == "something.new"


def test_malformed_payload_does_not_break_a_row():
    event = AuditEvent(6, "board.write.guarded", payload=None)
    event.payload = "not-a-dict"
    row = wa.row_of(event)
    assert row["fields"] == [] and row["id"] == 6


def test_runtime_events_are_excluded_by_default():
    assert "openclaw.stream.gap" not in wa.event_types()
    assert "openclaw.stream.gap" in wa.event_types(include_runtime=True)


def test_feed_counts_conflicts_separately():
    db = AuditDb([AuditEvent(1, "board.write.conflict", {"applied": False}),
                  AuditEvent(2, "board.write.guarded", {"fields": {"name": "x"}})])
    out = wa.feed(db, 1)
    assert out["returned"] == 2
    assert out["conflicts"] == 1
    assert out["counts_by_category"]["write"] == 1


def test_feed_can_filter_to_one_category():
    db = AuditDb([AuditEvent(1, "board.write.conflict", {"applied": False}),
                  AuditEvent(2, "board.write.guarded", {"fields": {"name": "x"}})])
    out = wa.feed(db, 1, categories=("conflict",))
    assert [row["event_type"] for row in out["rows"]] == ["board.write.conflict"]


def test_feed_limit_is_clamped_not_trusted():
    db = AuditDb([])
    assert wa.feed(db, 1, limit=10_000)["limit"] == wa.MAX_LIMIT
    # limit=0 means "use the default", not "clamp to 1".
    # Production: max(1, min(int(0 or DEFAULT_LIMIT), MAX_LIMIT)) == DEFAULT_LIMIT.
    # Documented decision (see _reports/test-triage.md §1.2):
    # 0 means default, not floor — the floor is 1 but only for positive inputs.
    assert wa.feed(db, 1, limit=0)["limit"] == wa.DEFAULT_LIMIT


def test_feed_reports_truncation_instead_of_implying_completeness():
    rows = [AuditEvent(i, "board.write.guarded", {"fields": {"name": "x"}}) for i in range(3)]
    out = wa.feed(AuditDb(rows), 1, limit=3)
    assert out["truncated"] is True
    assert out["returned"] == 3


def test_entity_history_scopes_to_one_row():
    db = AuditDb([AuditEvent(1, "project.archived", {"cancelled_task_ids": []})])
    out = wa.entity_history(db, 1, "project", "900")
    assert out["rows"][0]["entity_id"] == "900"
    assert out["include_runtime"] is False
