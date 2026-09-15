"""v27 tests: derived progress, revision guards, archive cascade.

These use light stand-ins for the ORM rows so the rules can be pinned
without a database. What they check is the *decision* logic; the SQL itself
still needs a real run (see the handover's testing section).
"""
from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException

from app.services import board_truth as bt


class FakeProject:
    __name__ = "Project"

    def __init__(self, pid=1, progress=0, status="active", company_id=7,
                 updated_at=None):
        self.id = pid
        self.progress = progress
        self.status = status
        self.company_id = company_id
        self.updated_at = updated_at or datetime(2026, 9, 14, 12, 0, 0)


class FakeTask:
    def __init__(self, tid, status, session_key=None, title="t"):
        self.id = tid
        self.status = status
        self.runtime_session_key = session_key
        self.title = title
        self.project_id = 1
        self.updated_at = datetime(2026, 9, 14, 12, 0, 0)


def _eval_where(tasks, stmt):
    """Apply the WHERE clause of a SQLAlchemy select() to an in-memory task list.

    This makes the double honest: if production's query drops a filter (e.g.
    removes ``runtime_session_key IS NOT NULL``), the unfiltered statement
    arrives here and unfiltered tasks reach archive_project — causing the test
    to fail, exactly as intended.  Unsupported clause types are treated as
    True (permissive), so only clauses the double understands gate results.
    """
    from sqlalchemy.sql import operators as ops

    def _eval(clause, task):
        # BooleanClauseList (AND / OR)
        if hasattr(clause, "clauses"):
            op = getattr(clause, "operator", None)
            results = [_eval(c, task) for c in clause.clauses]
            # SQLAlchemy uses operator.and_ for AND, operator.or_ for OR
            import operator as pyops
            if op is pyops.or_:
                return any(results)
            return all(results)  # default to AND

        # BinaryExpression: column OP value
        if hasattr(clause, "left") and hasattr(clause, "right"):
            col_key = getattr(clause.left, "key", None)
            if col_key and hasattr(task, col_key):
                task_val = getattr(task, col_key)
                right_val = getattr(clause.right, "value", None)
                op = clause.operator
                if op is ops.eq:
                    return task_val == right_val
                if op is ops.ne:
                    return task_val != right_val
                if op is ops.is_:
                    return task_val is right_val
                if op is ops.is_not:
                    return task_val is not right_val
        return True  # unknown predicate: let it through (safe default)

    try:
        wc = stmt.whereclause
    except AttributeError:
        return list(tasks)
    if wc is None:
        return list(tasks)
    return [t for t in tasks if _eval(wc, t)]


class FakeDb:
    """Answers only the two shapes board_truth asks for.

    execute().all()             → status-count tuples (for task_counts)
    execute().scalars().all()   → filtered task rows (for live_attachments
                                  and archive_project's task iteration)

    The WHERE-clause evaluator in _eval_where makes the double honest: a
    test that passes only because the double ignores a filter would also
    pass if production removed that filter.  With _eval_where, removing a
    filter from the production query removes it from the double too, so the
    wrong tasks reach the caller and the assertion fails.
    """

    def __init__(self, tasks):
        self.tasks = list(tasks)
        self.committed = 0
        self.events = []

    # board_truth calls db.execute(...).all() for counts and
    # db.execute(...).scalars().all() for task rows.
    def execute(self, stmt):
        db = self

        class Result:
            def all(self):
                counts = {}
                for t in db.tasks:
                    counts[t.status] = counts.get(t.status, 0) + 1
                return list(counts.items())

            def scalars(self):
                filtered = _eval_where(db.tasks, stmt)

                class S:
                    def all(self_inner):
                        return filtered
                return S()

        return Result()

    def add(self, _obj):
        pass

    def commit(self):
        self.committed += 1

    def refresh(self, _obj):
        pass


@pytest.fixture(autouse=True)
def no_events(monkeypatch):
    calls = []
    monkeypatch.setattr(bt, "emit_event",
                        lambda db, **kw: calls.append(kw) or object())
    return calls


# -- derived progress -------------------------------------------------------


def test_progress_is_done_over_countable():
    db = FakeDb([FakeTask(1, "done"), FakeTask(2, "done"),
                 FakeTask(3, "todo"), FakeTask(4, "review")])
    out = bt.derive(db, FakeProject())
    assert out["derived_progress"] == 50


def test_cancelled_tasks_leave_the_denominator():
    """Dropping scope must not pin a project at half done forever."""
    db = FakeDb([FakeTask(1, "done"), FakeTask(2, "cancelled")])
    out = bt.derive(db, FakeProject())
    assert out["countable"] == 1 and out["derived_progress"] == 100


def test_review_is_not_partial_credit():
    db = FakeDb([FakeTask(1, "review"), FakeTask(2, "todo")])
    assert bt.derive(db, FakeProject())["derived_progress"] == 0


def test_no_tasks_is_not_zero_percent():
    """"Nothing to measure" must not read as "measured zero"."""
    out = bt.derive(FakeDb([]), FakeProject(progress=40))
    assert out["derivable"] is False
    assert out["derived_progress"] is None
    assert out["drift"] is None


def test_drift_is_signed_against_the_stored_column():
    db = FakeDb([FakeTask(1, "done"), FakeTask(2, "todo")])
    assert bt.derive(db, FakeProject(progress=90))["drift"] == -40


def test_sync_refuses_to_overwrite_when_nothing_is_measurable():
    project = FakeProject(progress=40)
    out = bt.sync_progress(FakeDb([]), project, 1)
    assert out["applied"] is False and project.progress == 40


def test_sync_applies_and_reports_the_previous_value():
    project = FakeProject(progress=0)
    db = FakeDb([FakeTask(1, "done"), FakeTask(2, "todo")])
    out = bt.sync_progress(db, project, 1)
    assert out["applied"] is True
    assert out["previous_progress"] == 0 and project.progress == 50


def test_sync_in_sync_is_a_no_op_not_a_write():
    project = FakeProject(progress=50)
    db = FakeDb([FakeTask(1, "done"), FakeTask(2, "todo")])
    out = bt.sync_progress(db, project, 1)
    assert out["applied"] is False and db.committed == 0


# -- revisions --------------------------------------------------------------


def test_revision_changes_when_the_row_is_touched():
    p = FakeProject()
    first = bt.revision(p)
    p.updated_at = p.updated_at + timedelta(seconds=1)
    assert bt.revision(p) != first


def test_missing_revision_opts_out_rather_than_failing():
    """Pre-v27 clients must keep working."""
    bt.check_revision(FakeDb([]), FakeProject(), None)


def test_stale_revision_is_409_and_carries_the_current_one():
    p = FakeProject()
    with pytest.raises(HTTPException) as err:
        bt.check_revision(FakeDb([]), p, "project:1:1999-01-01T00:00:00")
    assert err.value.status_code == 409
    assert err.value.detail["current_revision"] == bt.revision(p)


def test_matching_revision_passes():
    p = FakeProject()
    bt.check_revision(FakeDb([]), p, bt.revision(p))


def test_conflict_event_failure_does_not_mask_the_409(monkeypatch):
    def boom(db, **kw):
        raise RuntimeError("bus down")

    monkeypatch.setattr(bt, "emit_event", boom)
    with pytest.raises(HTTPException) as err:
        bt.check_revision(FakeDb([]), FakeProject(), "stale", organization_id=1)
    assert err.value.status_code == 409


def test_sync_honours_the_revision_guard():
    project = FakeProject(progress=0)
    db = FakeDb([FakeTask(1, "done")])
    with pytest.raises(HTTPException):
        bt.sync_progress(db, project, 1, expected_revision="stale")
    assert project.progress == 0


# -- archive ----------------------------------------------------------------


def test_preview_counts_what_would_be_cancelled_without_writing():
    db = FakeDb([FakeTask(1, "todo"), FakeTask(2, "done"), FakeTask(3, "blocked")])
    out = bt.archive_preview(db, FakeProject())
    assert out["will_cancel_tasks"] == 2
    assert out["will_keep_done_tasks"] == 1
    assert db.committed == 0


def test_live_session_blocks_the_archive(monkeypatch):
    monkeypatch.setattr(bt.lease_store, "holder", lambda key: "worker-a")
    db = FakeDb([FakeTask(1, "in_progress", session_key="agent:nina:company-task-1")])
    with pytest.raises(HTTPException) as err:
        bt.archive_project(db, FakeProject(), 1)
    assert err.value.status_code == 409
    assert err.value.detail["live_runtime_sessions"][0]["followed_by"] == "worker-a"


def test_in_progress_without_a_session_does_not_block(monkeypatch):
    monkeypatch.setattr(bt.lease_store, "holder", lambda key: "")
    db = FakeDb([FakeTask(1, "in_progress")])
    out = bt.archive_project(db, FakeProject(), 1)
    assert out["cancelled_task_ids"] == [1]


def test_force_archives_but_admits_what_it_left_running(monkeypatch):
    monkeypatch.setattr(bt.lease_store, "holder", lambda key: "worker-a")
    db = FakeDb([FakeTask(1, "in_progress", session_key="s1")])
    out = bt.archive_project(db, FakeProject(), 1, force=True)
    assert out["forced"] is True
    assert out["left_running"][0]["session_key"] == "s1"


def test_archive_never_deletes_and_keeps_done_work():
    tasks = [FakeTask(1, "todo"), FakeTask(2, "done")]
    db = FakeDb(tasks)
    project = FakeProject()
    out = bt.archive_project(db, project, 1)
    assert out["deleted"] is False
    assert project.status == bt.ARCHIVE_STATUS
    assert tasks[0].status == "cancelled" and tasks[1].status == "done"


def test_archive_uses_existing_vocabulary_only():
    """No new status words: v18's board must still understand the result."""
    from app.services.workspace_ops import PROJECT_STATUSES, TASK_STATUSES

    assert bt.ARCHIVE_STATUS in PROJECT_STATUSES
    assert "cancelled" in TASK_STATUSES
    assert all(s in TASK_STATUSES for s in bt.OPEN_STATUSES)


def test_archive_honours_the_revision_guard():
    project = FakeProject()
    with pytest.raises(HTTPException) as err:
        bt.archive_project(FakeDb([]), project, 1, expected_revision="stale")
    assert err.value.status_code == 409
    assert project.status == "active"
