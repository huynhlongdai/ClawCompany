"""v31 tests: field-level diffs, clear sentinel, department status/uniqueness.

Same honesty as v28-v30: the sandbox has no network, so SQLAlchemy is not
installed and none of this has been executed. These pin decision logic --
what counts as a change, what may be cleared, how a history is rebuilt --
not the SQL. The unique index and the migration's duplicate guard still need
a real database.
"""
from datetime import datetime

import pytest

from app.services import field_diff as fd

STAMP = datetime(2026, 9, 15, 6, 0, 0)


class Row:
    def __init__(self, **kw):
        self.id = kw.pop("id", 1)
        self.name = kw.pop("name", "Alpha")
        self.status = kw.pop("status", "active")
        self.owner_member_id = kw.pop("owner_member_id", 4)
        self.description = kw.pop("description", "")
        self.updated_at = kw.pop("updated_at", STAMP)
        for k, v in kw.items():
            setattr(self, k, v)


# ------------------------------------------------------------------ normalize

def test_normalize_passes_scalars_through():
    assert fd.normalize(None) is None
    assert fd.normalize(7) == 7
    assert fd.normalize(1.5) == 1.5
    assert fd.normalize(True) is True


def test_normalize_renders_datetimes_as_iso():
    assert fd.normalize(STAMP) == STAMP.isoformat()


def test_normalize_truncates_long_text_with_a_marker():
    out = fd.normalize("x" * (fd.MAX_VALUE_CHARS + 50))
    assert out.endswith(fd.TRUNCATION_MARKER)
    assert len(out) == fd.MAX_VALUE_CHARS + len(fd.TRUNCATION_MARKER)


def test_normalize_leaves_short_text_intact():
    assert fd.normalize("planning") == "planning"


# -------------------------------------------------------------------- snapshot

def test_snapshot_reads_the_requested_fields():
    assert fd.snapshot(Row(), ["name", "status"]) == {"name": "Alpha", "status": "active"}


def test_snapshot_uses_none_for_missing_attributes():
    assert fd.snapshot(Row(), ["nope"]) == {"nope": None}


def test_snapshot_redacts_secret_looking_fields():
    row = Row()
    row.token = "super-secret"
    assert fd.snapshot(row, ["token"]) == {"token": fd.REDACTED_PLACEHOLDER}


def test_redaction_is_case_insensitive():
    row = Row()
    setattr(row, "API_KEY", "abc")
    assert fd.snapshot(row, ["API_KEY"])["API_KEY"] == fd.REDACTED_PLACEHOLDER


# ------------------------------------------------------------------------ diff

def test_diff_reports_only_fields_that_moved():
    before = {"name": "Alpha", "status": "active"}
    after = {"name": "Beta", "status": "active"}
    assert fd.diff(before, after) == {"name": {"from": "Alpha", "to": "Beta"}}


def test_diff_treats_a_rewrite_of_the_same_value_as_no_change():
    assert fd.diff({"status": "active"}, {"status": "active"}) == {}


def test_diff_records_a_clear_as_a_move_to_none():
    out = fd.diff({"owner_member_id": 4}, {"owner_member_id": None})
    assert out == {"owner_member_id": {"from": 4, "to": None}}


def test_diff_distinguishes_empty_string_from_none():
    assert fd.diff({"description": None}, {"description": ""}) != {}


def test_unchanged_lists_the_no_op_fields():
    before = {"name": "Alpha", "status": "active"}
    after = {"name": "Alpha", "status": "paused"}
    assert fd.unchanged(before, after) == ["name"]


# --------------------------------------------------------------------- sentinel

def test_clear_sentinel_is_recognised():
    assert fd.is_clear(fd.CLEAR)


def test_none_is_not_a_clear_request():
    # The whole point: null keeps meaning "leave alone" for v28 clients.
    assert not fd.is_clear(None)


def test_ordinary_strings_are_not_clear_requests():
    assert not fd.is_clear("__clear")
    assert not fd.is_clear("")


# --------------------------------------------------------------------- describe

def test_describe_renders_each_field_transition():
    text = fd.describe({"status": {"from": "active", "to": "paused"}})
    assert "status" in text and "active" in text and "paused" in text


def test_describe_marks_empty_and_blank_distinctly():
    text = fd.describe({"owner_member_id": {"from": 4, "to": None},
                        "description": {"from": "x", "to": ""}})
    assert "(empty)" in text
    assert "(blank)" in text


def test_describe_says_so_when_nothing_changed():
    assert fd.describe({}) == "no field values changed"


def test_describe_shortens_very_long_values():
    text = fd.describe({"description": {"from": "y" * 200, "to": "z"}})
    assert "..." in text


# ------------------------------------------------------------------ reconstruct

def _write_row(id, changes, at="2026-09-15T06:00:00", actor=9):
    return {"id": id, "category": "write", "changes": changes,
            "occurred_at": at, "actor_member_id": actor}


def test_reconstruct_builds_a_per_field_timeline():
    rows = [_write_row(3, {"status": {"from": "active", "to": "paused"}}),
            _write_row(2, {"status": {"from": "planning", "to": "active"}}),
            _write_row(1, {"name": {"from": "A", "to": "B"}})]
    out = fd.reconstruct(rows)
    assert out["field_names"] == ["name", "status"]
    assert len(out["fields"]["status"]) == 2


def test_reconstruct_keeps_newest_first_order():
    rows = [_write_row(3, {"status": {"from": "active", "to": "paused"}}),
            _write_row(2, {"status": {"from": "planning", "to": "active"}})]
    out = fd.reconstruct(rows)
    assert [e["event_id"] for e in out["fields"]["status"]] == [3, 2]


def test_reconstruct_carries_actor_and_timestamp():
    out = fd.reconstruct([_write_row(5, {"name": {"from": "A", "to": "B"}}, actor=12)])
    entry = out["fields"]["name"][0]
    assert entry["actor_member_id"] == 12
    assert entry["at"] == "2026-09-15T06:00:00"


def test_reconstruct_counts_pre_v31_writes_instead_of_hiding_them():
    rows = [_write_row(2, {"name": {"from": "A", "to": "B"}}),
            {"id": 1, "category": "write", "changes": None,
             "occurred_at": "", "actor_member_id": None}]
    out = fd.reconstruct(rows)
    assert out["writes_without_values"] == 1
    assert out["note"]


def test_reconstruct_does_not_count_non_write_rows_as_missing_values():
    out = fd.reconstruct([{"id": 1, "category": "archive", "changes": None}])
    assert out["writes_without_values"] == 0
    assert out["note"] == ""


def test_reconstruct_of_an_empty_feed_is_empty_and_quiet():
    out = fd.reconstruct([])
    assert out["fields"] == {} and out["note"] == ""


# ------------------------------------------------------- guard + ops surfaces
# These import lazily: row_guard and workspace_ops pull in SQLAlchemy and
# FastAPI, which this sandbox does not have. The skip is the honest outcome,
# not a passing test that proves nothing.

def _mod(name):
    return pytest.importorskip(f"app.services.{name}")


def test_clearable_is_a_subset_of_writable():
    rg = _mod("row_guard")
    for kind, fields in rg.CLEARABLE.items():
        assert set(fields) <= set(rg.WRITABLE[kind])


def test_department_status_is_a_guarded_field():
    rg = _mod("row_guard")
    assert "status" in rg.WRITABLE["department"]


def test_department_name_is_not_clearable():
    rg = _mod("row_guard")
    assert "name" not in rg.CLEARABLE["department"]


def test_department_statuses_do_not_reuse_access_levels():
    ops = _mod("workspace_ops")
    assert "archived" in ops.DEPARTMENT_STATUSES
    assert not set(ops.DEPARTMENT_STATUSES) & set(ops.ACCESS_LEVELS)
