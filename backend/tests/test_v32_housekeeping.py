"""v32 tests: write trails, retention tiers, revision adoption, backoff.

Deliberately dependency-free where possible so they run in a sandbox with no
network. They pin the decisions -- which fields are tracked, which events are
evidence, what a backoff schedule looks like, which era an archive record
came from. The parts that need a real database (the UPDATE in
revision_backfill, the DELETE in event_retention, migration 0015's batch
rebuild) are pinned structurally here and must still be run against Postgres
before release. That gap is written down in docs/architecture-v32.md rather
than papered over.
"""
import ast
import inspect
import pathlib
import sys
from datetime import datetime, timedelta

BACKEND = pathlib.Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

SERVICES = BACKEND / "app" / "services"


def _source(name: str) -> str:
    return (SERVICES / name).read_text()


def _tree(name: str) -> ast.Module:
    return ast.parse(_source(name))


def _func(module: ast.Module, name: str) -> ast.FunctionDef:
    for node in ast.walk(module):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"function not found: {name}")


class _Row:
    def __init__(self, **values):
        for key, value in values.items():
            setattr(self, key, value)


# --------------------------------------------------------------- write trail

def test_every_counted_entity_kind_has_tracked_fields():
    from app.services import row_revision, write_trail

    for kind in row_revision.COUNTED_KINDS:
        assert write_trail.tracked_fields(kind), f"{kind} records no before-values"


def test_tracked_fields_never_include_tenancy_or_secret_columns():
    from app.services import write_trail

    forbidden = {"organization_id", "runtime_session_key", "password",
                 "password_hash", "row_revision", "id"}
    for kind, fields in write_trail.TRACKED.items():
        assert not (set(fields) & forbidden), f"{kind} tracks a column it should not"


def test_tracked_fields_cover_every_guarded_writable_field():
    """A field editable through the guard must be readable in history too."""
    from app.services import row_guard, write_trail

    for kind, writable in row_guard.WRITABLE.items():
        missing = set(writable) - set(write_trail.tracked_fields(kind))
        assert not missing, f"{kind} guarded fields with no before-values: {sorted(missing)}"


def test_trail_reports_only_fields_that_moved():
    from app.services import write_trail

    row = _Row(name="Nova Labs", industry="ai", status="active")
    trail = write_trail.start("company", row)
    row.status = "paused"
    fragment = trail.finish(row)
    assert fragment["changes"] == {"status": {"from": "active", "to": "paused"}}
    assert fragment["values_source"] == "write_trail"
    assert "values_error" not in fragment


def test_trail_on_an_unknown_kind_says_so_instead_of_claiming_no_change():
    from app.services import write_trail

    trail = write_trail.start("invoice", _Row(name="x"))
    fragment = trail.finish(_Row(name="y"))
    # v31.1's lesson: empty is not the same as unavailable, and the payload
    # has to carry which one it is.
    assert fragment["changes"] == {}
    assert fragment["values_error"]


def test_trail_redacts_secret_columns_if_one_is_ever_tracked():
    from app.services import field_diff

    before = field_diff.snapshot(_Row(token="live-secret"), ("token",))
    assert before["token"] == field_diff.REDACTED_PLACEHOLDER


def test_every_cockpit_write_path_starts_a_trail_and_merges_it():
    module = _tree("workspace_ops.py")
    for name in ("update_company", "update_department", "move_member",
                 "update_project", "move_task", "assign_task"):
        body = ast.dump(_func(module, name))
        assert "write_trail" in body, f"{name} takes no before-snapshot"
        assert "finish" in body, f"{name} never merges its trail into the payload"


def test_create_paths_do_not_pretend_to_have_before_values():
    module = _tree("workspace_ops.py")
    for name in ("create_company", "create_department", "create_project", "create_task"):
        body = ast.dump(_func(module, name))
        assert "write_trail" not in body, f"{name} has no prior value to record"


def test_coverage_names_the_paths_it_does_not_cover():
    from app.services import write_trail

    coverage = write_trail.coverage()
    assert coverage["not_covered"], "an honest coverage report lists the gaps"
    assert coverage["paths"]["cockpit"]
    assert coverage["redacted_fields"]


# ----------------------------------------------------------------- retention

def test_restore_records_are_evidence_tier():
    from app.services import event_retention

    for event_type in ("company.archived", "department.archived", "member.archived",
                       "project.archived", "project.restored", "board.write.guarded",
                       "board.write.conflict"):
        assert event_retention.tier_of(event_type) == "evidence", event_type


def test_runtime_chatter_expires_soonest():
    from app.services import event_retention

    assert event_retention.tier_of("openclaw.stream.gap") == "runtime"
    assert event_retention.tier_of("department.updated") == "default"
    assert (event_retention.RUNTIME_DAYS
            < event_retention.DEFAULT_DAYS
            < event_retention.EVIDENCE_DAYS)


def test_every_archive_event_type_is_listed_as_evidence():
    """If entity_archive learns a new kind, retention must learn it too."""
    from app.services import entity_archive, event_retention

    declared = set(entity_archive.ARCHIVE_EVENTS.values()) | set(
        entity_archive.RESTORE_EVENTS.values())
    missing = declared - set(event_retention.EVIDENCE_TYPES)
    assert not missing, f"undo records that would expire early: {sorted(missing)}"


def test_prune_defaults_to_a_dry_run():
    from app.services import event_retention

    signature = inspect.signature(event_retention.prune)
    assert signature.parameters["dry_run"].default is True
    assert event_retention.policy()["dry_run_default"] is True


def test_prune_is_bounded_per_call():
    from app.services import event_retention

    assert 0 < event_retention.MAX_DELETE <= 50000
    assert event_retention.policy()["max_delete_per_call"] == event_retention.MAX_DELETE


def test_protected_aggregates_fails_closed():
    """An unreadable protection query must refuse, not authorise deletion."""
    module = _tree("event_retention.py")
    body = ast.dump(_func(module, "protected_aggregates"))
    assert "RetentionError" in body
    assert "Raise" in body


def test_cutoffs_are_per_tier_and_ordered():
    from app.services import event_retention

    cutoffs = event_retention._cutoffs(datetime(2026, 9, 15, 8, 0, 0))
    assert cutoffs["evidence"] < cutoffs["default"] < cutoffs["runtime"]


def test_prune_never_returns_the_full_deleted_id_list():
    source = _source("event_retention.py")
    block = source.split("def prune")[1]
    assert 'plan.pop("event_ids", None)' in block
    assert 'sample_event_ids' in block


# ----------------------------------------------------------- revision adoption

def test_backfill_defaults_to_a_dry_run_and_starts_at_one():
    from app.services import revision_backfill

    signature = inspect.signature(revision_backfill.backfill)
    assert signature.parameters["dry_run"].default is True
    assert revision_backfill.START_AT == 1
    assert revision_backfill.QUIET_SECONDS >= 30


def test_backfill_covers_exactly_the_counted_kinds():
    from app.services import revision_backfill, row_revision

    assert set(revision_backfill.MODELS) == set(row_revision.COUNTED_KINDS)


def test_backfill_only_touches_null_counters_inside_the_quiet_period():
    source = _source("revision_backfill.py")
    block = source.split("def backfill")[1]
    assert "row_revision.is_(None)" in block, "it must not renumber an existing counter"
    assert "updated_at < cutoff" in block, "the quiet period must be in the predicate"


def test_backfill_never_bumps_updated_at():
    block = _source("revision_backfill.py").split("def backfill")[1]
    assert "values(row_revision=START_AT)" in block
    assert "updated_at=" not in block


def test_org_scoping_exists_for_every_kind():
    from app.services import revision_backfill

    for kind, model in revision_backfill.MODELS.items():
        assert revision_backfill._org_filter(kind, model, 1) is not None, kind


def test_quiet_period_excludes_rows_written_moments_ago():
    from app.services import revision_backfill

    now = datetime(2026, 9, 15, 8, 0, 0)
    cutoff = now - timedelta(seconds=revision_backfill.QUIET_SECONDS)
    fresh = now - timedelta(seconds=1)
    assert not fresh < cutoff, "a row written a second ago must not adopt a counter"


# ------------------------------------------------------- department archiving

def test_department_archive_uses_status_not_permission():
    from app.services import entity_archive, workspace_ops

    assert entity_archive.DEPARTMENT_ARCHIVED in workspace_ops.DEPARTMENT_STATUSES
    assert entity_archive.DEPARTMENT_DEFAULT_RESTORE in workspace_ops.DEPARTMENT_STATUSES
    # The v29 word survives only so old records can still be read back.
    assert entity_archive.DEPARTMENT_LOCKED in workspace_ops.ACCESS_LEVELS


def test_the_two_vocabularies_do_not_overlap():
    """Era detection relies on the words being disjoint."""
    from app.services import entity_archive

    assert not (set(entity_archive.DEPARTMENT_STATUS_WORDS)
                & set(entity_archive.LEGACY_ACCESS_WORDS))


def test_a_v32_record_restores_status_only():
    from app.services import entity_archive

    plan = entity_archive._dept_restore("paused")
    assert plan == {"status": "paused", "access_level": None, "era": "v32", "known": True}


def test_a_v29_record_restores_the_access_level_it_recorded():
    from app.services import entity_archive

    plan = entity_archive._dept_restore("restricted")
    assert plan["access_level"] == "restricted"
    assert plan["status"] == entity_archive.DEPARTMENT_DEFAULT_RESTORE
    assert plan["era"] == "v29"


def test_an_unknown_record_is_flagged_rather_than_guessed_silently():
    from app.services import entity_archive

    plan = entity_archive._dept_restore(None)
    assert plan["known"] is False
    assert plan["access_level"] is None


def test_both_eras_count_as_archived():
    from app.services import entity_archive

    v32_row = _Row(status="archived", access_level="restricted")
    v29_row = _Row(status="active", access_level="confidential")
    live_row = _Row(status="active", access_level="restricted")
    assert entity_archive._already_archived("department", v32_row)
    assert entity_archive._already_archived("department", v29_row)
    assert not entity_archive._already_archived("department", live_row)


def test_archiving_a_department_no_longer_writes_access_level():
    block = _source("entity_archive.py").split("def _apply_archive")[1].split("\ndef ")[0]
    assert "dept.status = DEPARTMENT_ARCHIVED" in block
    assert "dept.access_level =" not in block, "archiving must not change permission"


# ------------------------------------------------------------------- backoff

def test_backoff_starts_at_the_v26_delay():
    from app.services.redis_pool import RETRY_SECONDS, backoff_delay

    assert backoff_delay(1, jitter=False) == RETRY_SECONDS


def test_backoff_grows_and_then_stops_growing():
    from app.services.redis_pool import MAX_RETRY_SECONDS, backoff_delay

    schedule = [backoff_delay(n, jitter=False) for n in range(1, 12)]
    assert schedule == sorted(schedule)
    assert schedule[-1] == MAX_RETRY_SECONDS


def test_jitter_stays_inside_the_declared_ratio():
    from app.services.redis_pool import JITTER_RATIO, backoff_delay

    base = backoff_delay(3, jitter=False)
    for _ in range(200):
        value = backoff_delay(3)
        assert base * (1 - JITTER_RATIO) - 0.01 <= value <= base * (1 + JITTER_RATIO) + 0.01


def test_a_success_clears_the_backoff():
    block = _source("redis_pool.py").split('self._error = ""')[1]
    assert "self._consecutive = 0" in block


def test_pool_status_reports_the_backoff_state():
    from app.services.redis_pool import pool

    status = pool.status()
    for key in ("consecutive_failures", "retry_delay", "max_retry_seconds", "backend"):
        assert key in status


# ------------------------------------------------------------------ migration

def test_migration_backfills_before_it_constrains():
    path = BACKEND / "alembic/versions/0015_v32_department_status_not_null.py"
    upgrade = path.read_text().split("def upgrade")[1].split("def downgrade")[0]
    assert upgrade.index("UPDATE departments") < upgrade.index("batch_alter_table")
    assert "RuntimeError" in upgrade, "it must refuse rather than fail mid-rebuild"


def test_migration_chain_is_linear():
    path = BACKEND / "alembic/versions/0015_v32_department_status_not_null.py"
    assert 'down_revision = "0014_v31_department_status_and_unique_name"' in path.read_text()


def test_migration_leaves_access_level_alone():
    path = BACKEND / "alembic/versions/0015_v32_department_status_not_null.py"
    upgrade = path.read_text().split("def upgrade")[1].split("def downgrade")[0]
    assert "access_level" not in upgrade
