"""Regression tests for the three v31 defects found in review.

Each test fails on the shipped v31 code and passes after the fix. They are
written against the smallest unit that can show the bug, because two of the
three were invisible at the HTTP layer:

1. ``row_guard.compare_and_set`` bound its loop variable to ``value``, the
   same name holding the parsed expected revision. The conditional UPDATE
   then compared the row against the value being written, so a guarded
   write either never matched (409 on a row nobody had touched) or matched
   by coincidence. This is the exact guarantee v28 exists to provide, and
   no v31 test caught it because the tests only asserted on the returned
   payload, never on the SQL predicate.
2. ``workspace_ops.create_project`` referenced ``clear_owner``, a parameter
   that only exists on ``update_project`` -- a NameError, i.e. a 500, on
   every project created with an owner.
3. ``write_audit`` reported ``has_values: True`` for an empty ``changes``
   dict, so a write that moved nothing looked like a fully reconstructable
   history.
"""

import inspect

import pytest

from app.services import field_diff as fd
from app.services import row_guard, workspace_ops, write_audit


# --------------------------------------------------------------------- bug 1

def test_guard_does_not_shadow_the_expected_revision():
    """The name holding the parsed revision must not be reassigned.

    Asserted on the source because reproducing it needs a live session and
    two writers; the shadowing itself is the defect and it is static.
    """
    source = inspect.getsource(row_guard.compare_and_set)
    assert "mode, expected_value = rev.parse" in source
    assert "for field, value in values.items()" not in source
    # And the predicate must use the parsed value, not a loop variable.
    assert "model.row_revision == expected_value" in source
    assert "model.updated_at == expected_value" in source


def test_guard_condition_names_are_bound_once():
    """No assignment to ``expected_value`` between parse and predicate."""
    lines = inspect.getsource(row_guard.compare_and_set).splitlines()
    parse_line = next(i for i, l in enumerate(lines) if "rev.parse(" in l)
    use_line = next(i for i, l in enumerate(lines) if "== expected_value" in l)
    between = lines[parse_line + 1:use_line]
    assert not [l for l in between if l.strip().startswith("expected_value")]
    assert not [l for l in between if " expected_value =" in l]


# --------------------------------------------------------------------- bug 2

def test_create_project_signature_has_no_clear_owner():
    """``clear_owner`` is an update concept; creation has nothing to clear."""
    import ast

    params = inspect.signature(workspace_ops.create_project).parameters
    assert "clear_owner" not in params
    # Bản gốc cắt source sau docstring rồi grep chuỗi, nên chính chú thích
    # "clear_owner thuộc update_project" làm test đỏ. Điều cần bảo vệ là
    # thân hàm không *đọc* hay *gán* tên đó -- kiểm bằng AST, không bằng grep.
    tree = ast.parse(inspect.getsource(workspace_ops.create_project).lstrip())
    referenced = {
        node.id for node in ast.walk(tree)
        if isinstance(node, ast.Name)
    } | {
        node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
    } | {
        kw.arg for node in ast.walk(tree) if isinstance(node, ast.Call)
        for kw in node.keywords if kw.arg
    }
    assert "clear_owner" not in referenced


def test_create_project_body_references_only_its_own_names():
    """Compile the function body against its own parameter names.

    This is what would have caught the NameError without a database: the
    body may only read names it declares, imports, or that exist at module
    scope.
    """
    import ast

    tree = ast.parse(inspect.getsource(workspace_ops.create_project).lstrip())
    fn = tree.body[0]
    declared = {a.arg for a in fn.args.args + fn.args.kwonlyargs}
    for node in ast.walk(fn):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            declared.add(node.id)
    # ``__builtins__`` là dict trong module không phải __main__, nên
    # dir(__builtins__) trả về phương thức của dict và builtin thật như
    # ``str`` bị coi là undefined. Dùng module builtins cho đúng.
    import builtins

    module_scope = set(vars(workspace_ops)) | set(dir(builtins))
    for node in ast.walk(fn):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            assert node.id in declared or node.id in module_scope, (
                f"create_project reads undefined name {node.id!r}"
            )


def test_update_project_still_accepts_clear_owner():
    params = inspect.signature(workspace_ops.update_project).parameters
    assert params["clear_owner"].default is False


def test_clear_owner_wins_over_a_simultaneous_assignment():
    """A body saying both "unassign" and "assign to N" must unassign.

    The destructive intent is the explicit one; the assignment may simply be
    a field the client never removed from its form state.
    """
    source = inspect.getsource(workspace_ops.update_project)
    assert "if owner_member_id is not None and not clear_owner:" in source


# --------------------------------------------------------------------- bug 3

class _Event:
    """Minimal stand-in for a CompanyEvent row."""

    def __init__(self, payload, event_type="board.write.guarded"):
        import json

        self.id = 1
        self.event_type = event_type
        self.source = "row_guard"
        # write_audit.row_of() đọc company_id (cột có thật trên
        # company_events). Double thiếu trường này nên test đỏ dù code đúng.
        self.organization_id = 1
        self.company_id = None
        self.aggregate_type = "project"
        self.aggregate_id = "7"
        self.actor_member_id = None
        self.correlation_id = ""
        self.payload_json = json.dumps(payload)
        self.occurred_at = None
        self.status = "done"
        self.error = ""


def _row(payload):
    return write_audit.row_of(_Event(payload))


def test_empty_changes_is_not_reported_as_having_values():
    row = _row({"fields": ["status"], "changes": {}})
    assert row["has_values"] is False


def test_real_changes_are_reported_as_having_values():
    row = _row({"fields": ["status"],
                "changes": {"status": {"from": "planning", "to": "active"}}})
    assert row["has_values"] is True
    assert row["changes"]["status"]["from"] == "planning"


def test_missing_changes_stays_absent_not_empty():
    """Pre-v31 events must read as "unknown", never as "nothing changed"."""
    row = _row({"fields": ["status"]})
    assert row["changes"] is None
    assert row["has_values"] is False


def test_reconstruct_counts_the_empty_changes_row():
    """An empty diff is still a write with no recoverable before-values."""
    out = fd.reconstruct([{"id": 1, "category": "write", "changes": {}},
                          {"id": 2, "category": "write"}])
    assert out["writes_without_values"] == 2
    assert out["field_names"] == []
    assert out["note"]


# ------------------------------------------------------------------ migration

def test_migration_refuses_before_touching_the_schema():
    """The duplicate check must precede the first DDL statement.

    Raising after ``add_column`` leaves the schema half-migrated on SQLite
    and MySQL, where DDL is not rolled back with the transaction.
    """
    import pathlib

    path = pathlib.Path(__file__).resolve().parents[1] / "alembic" / "versions" / \
        "0014_v31_department_status_and_unique_name.py"
    source = path.read_text()
    upgrade = source.split("def upgrade():", 1)[1].split("def downgrade")[0]
    assert upgrade.index("DUPLICATE_QUERY") < upgrade.index("add_column")
    assert upgrade.index("RuntimeError") < upgrade.index("add_column")


def test_migration_is_rerunnable_after_a_refusal():
    """Nothing before the raise mutates data, so a retry is safe."""
    import pathlib

    path = pathlib.Path(__file__).resolve().parents[1] / "alembic" / "versions" / \
        "0014_v31_department_status_and_unique_name.py"
    upgrade = path.read_text().split("def upgrade():", 1)[1].split("def downgrade")[0]
    before_raise = upgrade.split("raise RuntimeError")[0]
    for mutation in ("op.add_column", "op.execute", "op.create_index", "op.alter_column"):
        assert mutation not in before_raise


# ------------------------------------------------------------ clear semantics

def test_clearable_is_a_strict_subset_of_writable():
    """A field that cannot be written must not be clearable either."""
    for entity, fields in row_guard.CLEARABLE.items():
        writable = set(row_guard.WRITABLE.get(entity, ()))
        assert set(fields) <= writable, f"{entity}: {set(fields) - writable}"


def test_no_required_column_is_clearable():
    """Names and statuses are never nullable; clearing them would 500."""
    for entity, fields in row_guard.CLEARABLE.items():
        assert "name" not in fields
        assert "title" not in fields
        assert "status" not in fields


def test_clear_sentinel_is_not_a_plausible_real_value():
    assert fd.CLEAR.startswith("__") and fd.CLEAR.endswith("__")
    assert not fd.is_clear("")
    assert not fd.is_clear(None)
    assert not fd.is_clear(0)
    assert fd.is_clear(fd.CLEAR)


@pytest.mark.parametrize("entity", sorted(row_guard.CLEARABLE))
def test_clearable_fields_lookup_matches_the_table(entity):
    class Row:
        pass

    Row.__name__ = entity.capitalize()
    assert row_guard.clearable_fields(Row()) == row_guard.CLEARABLE[entity]


def test_unknown_entity_has_nothing_clearable():
    class Widget:
        pass

    assert row_guard.clearable_fields(Widget()) == ()
