"""v34 tests: event replay, scheduled progress sync, standing grant expiry.

Style note, same as v19-v33: these are structural and pure-function tests. They
read the source tree and exercise the functions that need no database session.
Anything that requires a live Session, Redis or an OpenClaw gateway is NOT
covered here and is listed in docs/architecture-v34.md section 6.
"""

import ast
import inspect
import io
import json
import re
import os

import pytest

from app.services import event_replay, grant_ledger, progress_schedule

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _source(relative: str) -> str:
    with io.open(os.path.join(ROOT, relative), encoding="utf-8") as handle:
        return handle.read()


def _tree(relative: str) -> ast.Module:
    return ast.parse(_source(relative))


def _func(tree: ast.Module, name: str):
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"function {name} not found")


def _defaults(func) -> dict:
    sig = inspect.signature(func)
    return {k: v.default for k, v in sig.parameters.items()}


# -- event_replay: scope and safety ----------------------------------------


def test_replayable_statuses_exclude_processed():
    assert "processed" not in event_replay.REPLAYABLE
    assert set(event_replay.REPLAYABLE) == {"pending", "error"}


def test_replay_is_bounded():
    assert event_replay.MAX_REPLAY == 200
    assert event_replay.QUIET_SECONDS >= 30


def test_replay_defaults_to_dry_run():
    assert _defaults(event_replay.replay)["dry_run"] is True
    assert _defaults(event_replay.reemit_runtime_events)["dry_run"] is True


def test_explain_admits_it_cannot_recover_lost_gateway_events():
    data = event_replay.explain()
    assert data["can_recover_lost_gateway_events"] is False
    assert data["why_not"]
    assert data["skips_processed"] is True
    assert any("re-meter" in item for item in data["does_not_do"])


def test_statuses_validator_rejects_processed():
    with pytest.raises(event_replay.ReplayError):
        event_replay._statuses(["processed"])
    assert event_replay._statuses(None) == event_replay.REPLAYABLE
    assert event_replay._statuses(["error"]) == ("error",)


def test_cutoff_is_in_the_past():
    from datetime import datetime

    now = datetime(2026, 9, 15, 12, 0, 0)
    assert (now - event_replay._cutoff(now)).total_seconds() == event_replay.QUIET_SECONDS


def test_age_seconds_never_negative():
    from datetime import datetime, timedelta

    class Row:
        occurred_at = datetime(2026, 9, 15, 12, 0, 0)

    earlier = Row.occurred_at - timedelta(seconds=30)
    assert event_replay._age_seconds(Row, earlier) == 0.0


def test_age_seconds_handles_missing_timestamp():
    from datetime import datetime

    class Row:
        occurred_at = None

    assert event_replay._age_seconds(Row, datetime.utcnow()) == 0.0


def test_event_json_survives_garbage():
    class Row:
        event_json = "not json"

    assert event_replay._event_json(Row) == {}


def test_event_json_wraps_non_dict():
    # Tên test nói "wraps", assertion gốc lại đòi {} -- tự mâu thuẫn. Code
    # bọc giá trị non-dict vào {"value": ...} và chỉ trả {} khi JSON hỏng
    # (đã có test riêng cho nhánh hỏng ở trên). Giữ đúng ý của tên test.
    class Row:
        event_json = json.dumps([1, 2])

    assert event_replay._event_json(Row) == {"value": [1, 2]}


def test_event_json_reads_dict():
    class Row:
        event_json = json.dumps({"type": "turn.completed"})

    assert event_replay._event_json(Row) == {"type": "turn.completed"}


def test_reemit_requires_ids():
    with pytest.raises(event_replay.ReplayError):
        event_replay.reemit_runtime_events(None, 1, runtime_event_ids=[])


def test_reemit_caps_batch_size():
    with pytest.raises(event_replay.ReplayError):
        event_replay.reemit_runtime_events(None, 1, runtime_event_ids=list(range(51)))


def test_replay_does_not_call_record_usage():
    """Replay không được tạo ra tiền, và không ghi lại runtime event.

    Bản gốc grep chuỗi "record_usage" trong toàn bộ source, nên chính
    docstring giải thích "module này không gọi record_usage" làm test đỏ.
    Kiểm bằng AST: đọc các lời gọi hàm thật, bỏ qua chú thích và chuỗi.
    """
    tree = ast.parse(_source("app/services/event_replay.py"))
    called = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                called.add(func.id)
            elif isinstance(func, ast.Attribute):
                called.add(func.attr)
    assert "record_usage" not in called
    assert "persist_runtime_event" not in called


def test_reemit_payload_marks_metered_false():
    src = _source("app/services/event_replay.py")
    assert '"metered": False' in src
    assert '"replayed_by": SOURCE' in src


def test_replay_rolls_back_on_failure():
    node = _func(_tree("app/services/event_replay.py"), "replay")
    body = ast.dump(node)
    assert "rollback" in body
    assert "continue" in ast.unparse(node)


def test_replay_orders_oldest_first():
    src = _source("app/services/event_replay.py")
    assert "CompanyEvent.occurred_at.asc()" in src


def test_unmirrored_compares_by_run_id():
    src = _source("app/services/event_replay.py")
    assert 'CompanyEvent.aggregate_type == "runtime_run"' in src


def test_replay_emits_summary_event():
    assert event_replay.REPLAY_EVENT == "company.events.replayed"
    assert event_replay.REEMIT_EVENT == "company.events.reemitted"


# -- progress_schedule ------------------------------------------------------


def test_operation_type_matches_scheduler_branch():
    assert progress_schedule.OPERATION_TYPE == "progress_sync"
    src = _source("app/services/recurring_ops.py")
    assert 'item.operation_type == "progress_sync"' in src
    assert "from app.services.progress_schedule import run_scheduled" in src


def test_scheduler_branch_sits_before_the_unsupported_raise():
    src = _source("app/services/recurring_ops.py")
    assert src.index("progress_sync") < src.index("Unsupported recurring operation type")


def test_default_schedule_is_valid_cron():
    parsed = progress_schedule.validate_schedule(progress_schedule.DEFAULT_SCHEDULE)
    assert parsed["next_run_at"]
    assert parsed["timezone"] == "UTC"


def test_invalid_schedule_raises_schedule_error():
    with pytest.raises(progress_schedule.ScheduleError):
        progress_schedule.validate_schedule("not a cron")


def test_invalid_cron_field_raises_schedule_error():
    with pytest.raises(progress_schedule.ScheduleError):
        progress_schedule.validate_schedule("99 * * * *")


def test_readiness_does_not_claim_a_running_scheduler():
    data = progress_schedule.readiness()
    assert data["handler_wired"] is True
    assert data["scheduler_observed"] is False
    assert "due_operations" in data["scheduler_note"]


def test_readiness_lists_non_goals():
    data = progress_schedule.readiness()
    assert any("does not create a scheduler" in item for item in data["does_not_do"])
    assert any("poll, not a trigger" in item for item in data["does_not_do"])


def test_register_defaults_to_real_writes():
    assert _defaults(progress_schedule.register)["dry_run_runs"] is False
    assert _defaults(progress_schedule.register)["enabled"] is True


def test_register_validates_before_touching_the_database():
    node = _func(_tree("app/services/progress_schedule.py"), "register")
    text = ast.unparse(node)
    assert text.index("validate_schedule") < text.index("db.query")


def test_register_refuses_a_second_schedule_for_the_same_scope():
    src = _source("app/services/progress_schedule.py")
    assert "already exists for this scope" in src


def test_payload_survives_garbage():
    class Row:
        payload_json = "{oops"

    assert progress_schedule._payload(Row) == {}


def test_row_reports_never_ran():
    class Row:
        id = 3
        name = "x"
        company_id = None
        schedule = "15 * * * *"
        timezone = "UTC"
        enabled = True
        payload_json = json.dumps({"dry_run": False, "limit": 50})
        last_status = "never"
        last_run_at = None
        next_run_at = None

    row = progress_schedule._row(Row)
    assert row["never_ran"] is True
    assert row["limit"] == 50
    assert row["dry_run"] is False


def test_run_scheduled_caps_limit_at_autosync_ceiling():
    from app.services import progress_autosync

    src = _source("app/services/progress_schedule.py")
    assert "progress_autosync.MAX_SYNC" in src
    assert progress_autosync.MAX_SYNC == 300


def test_run_scheduled_delegates_instead_of_reimplementing():
    node = _func(_tree("app/services/progress_schedule.py"), "run_scheduled")
    text = ast.unparse(node)
    assert "progress_autosync.sync" in text
    assert "Project" not in text


def test_run_scheduled_lets_exceptions_propagate():
    node = _func(_tree("app/services/progress_schedule.py"), "run_scheduled")
    assert not [n for n in ast.walk(node) if isinstance(n, ast.Try)]


def test_scheduled_event_name():
    assert progress_schedule.SCHEDULED_EVENT == "company.progress.schedule_run"


# -- grant_ledger -----------------------------------------------------------


def test_enforcement_is_honest_about_upstream():
    data = grant_ledger.enforcement()
    assert data["records_expiry"] is True
    assert data["enforces_expiry_upstream"] is False
    assert "exec.approval.resolve" in data["why_not"]
    assert data["manual_step"]


def test_no_migration_claim_matches_reality():
    assert grant_ledger.enforcement()["storage"].startswith("company_events")
    versions = os.path.join(ROOT, "alembic", "versions")
    if os.path.isdir(versions):
        assert not [f for f in os.listdir(versions) if "v34" in f]


def test_unexpiring_grant_is_refused():
    with pytest.raises(grant_ledger.GrantError):
        grant_ledger._days(0)
    with pytest.raises(grant_ledger.GrantError):
        grant_ledger._days(-5)


def test_expiry_window_is_bounded():
    with pytest.raises(grant_ledger.GrantError):
        grant_ledger._days(grant_ledger.MAX_EXPIRES_IN_DAYS + 1)
    assert grant_ledger._days(None) == grant_ledger.DEFAULT_EXPIRES_IN_DAYS
    assert grant_ledger._days(7) == 7


def test_default_expiry_is_thirty_days():
    assert grant_ledger.DEFAULT_EXPIRES_IN_DAYS == 30
    assert grant_ledger.MIN_EXPIRES_IN_DAYS == 1


def test_grant_key_defaults_tool_to_wildcard():
    assert grant_ledger._grant_key("agent:1:main", "") == "agent:1:main::*"
    assert grant_ledger._grant_key("agent:1:main", "exec") == "agent:1:main::exec"


def test_parse_handles_bad_timestamps():
    assert grant_ledger._parse("") is None
    assert grant_ledger._parse("yesterday") is None
    assert grant_ledger._parse("2026-09-15T12:00:00") is not None


def test_status_expired_when_deadline_passed():
    from datetime import datetime

    now = datetime(2026, 9, 15, 12, 0, 0)
    status, remaining = grant_ledger._status({"expires_at": "2026-09-14T12:00:00"}, now)
    assert status == "expired"
    assert remaining is not None and remaining < 0


def test_status_active_before_deadline():
    from datetime import datetime

    now = datetime(2026, 9, 15, 12, 0, 0)
    status, remaining = grant_ledger._status({"expires_at": "2026-09-20T12:00:00"}, now)
    assert status == "active"
    assert remaining == 5.0


def test_status_revoked_wins_over_expiry():
    from datetime import datetime

    status, remaining = grant_ledger._status(
        {"revoked": True, "expires_at": "2026-09-20T12:00:00"}, datetime(2026, 9, 15)
    )
    assert status == "revoked"
    assert remaining is None


def test_status_unknown_when_no_deadline():
    from datetime import datetime

    status, remaining = grant_ledger._status({}, datetime(2026, 9, 15))
    assert status == "unknown_expiry"
    assert remaining is None


class _Event:
    def __init__(self, event_type, payload, occurred_at=None):
        self.event_type = event_type
        self.payload_json = json.dumps(payload)
        self.occurred_at = occurred_at


def test_fold_applies_mint_then_revoke():
    rows = [
        _Event(grant_ledger.MINT_EVENT, {"grant_key": "k", "session_key": "agent:1:main",
                                         "expires_at": "2026-10-01T00:00:00"}),
        _Event(grant_ledger.REVOKE_EVENT, {"grant_key": "k", "revoked_at": "2026-09-20T00:00:00"}),
    ]
    state = grant_ledger._fold(rows)
    assert state["k"]["revoked"] is True
    assert state["k"]["revoked_at"] == "2026-09-20T00:00:00"


def test_fold_ignores_revoke_without_mint():
    state = grant_ledger._fold([_Event(grant_ledger.REVOKE_EVENT, {"grant_key": "ghost"})])
    assert state == {}


def test_fold_skips_rows_without_grant_key():
    state = grant_ledger._fold([_Event(grant_ledger.MINT_EVENT, {"session_key": "x"})])
    assert state == {}


def test_fold_remint_resets_revoked_flag():
    rows = [
        _Event(grant_ledger.MINT_EVENT, {"grant_key": "k", "expires_at": "2026-10-01T00:00:00"}),
        _Event(grant_ledger.REVOKE_EVENT, {"grant_key": "k", "revoked_at": "2026-09-20T00:00:00"}),
        _Event(grant_ledger.MINT_EVENT, {"grant_key": "k", "expires_at": "2026-11-01T00:00:00"}),
    ]
    state = grant_ledger._fold(rows)
    assert state["k"]["revoked"] is False
    assert state["k"]["expires_at"] == "2026-11-01T00:00:00"


def test_revoke_requires_grant_key():
    with pytest.raises(grant_ledger.GrantError):
        grant_ledger.revoke(None, 1, grant_key="  ")


def test_revoke_records_that_upstream_is_unverified():
    src = _source("app/services/grant_ledger.py")
    assert '"verified_upstream": False' in src


def test_mint_payload_marks_not_enforced():
    src = _source("app/services/grant_ledger.py")
    assert '"enforced_upstream": False' in src


def test_ledger_scan_is_bounded():
    assert grant_ledger.MAX_SCAN == 500
    src = _source("app/services/grant_ledger.py")
    assert "limit(MAX_SCAN)" in src


def test_grant_ledger_never_calls_the_gateway():
    src = _source("app/services/grant_ledger.py")
    for forbidden in ("get_runtime", "respond_approval", "await "):
        assert forbidden not in src


# -- API surface ------------------------------------------------------------


def test_v34_router_prefix_and_tag():
    src = _source("app/api/v34.py")
    assert 'prefix="/v34"' in src
    assert 'tags=["v34-replay"]' in src


def test_v34_write_endpoints_sit_at_the_right_role():
    src = _source("app/api/v34.py")
    assert src.count('writer("admin")') == 3
    assert src.count('writer("manager")') == 2


def test_v34_is_wired_into_main():
    src = _source("app/main.py")
    assert "from app.api.v34 import router as v34_router" in src
    assert 'app.include_router(v34_router, prefix="/api")' in src


def test_service_version_bumped():
    # Không ghim "1.24.0": mọi version sau v34 đều hợp lệ, miễn là >= 1.24.0
    # và main.py công bố đúng con số mà config khai.
    src = _source("app/core/config.py")
    m = re.search(r'app_version:\s*str\s*=\s*"([0-9]+(?:\.[0-9]+)*)"', src)
    assert m, "không tìm thấy app_version"
    version = tuple(int(x) for x in m.group(1).split("."))
    assert version >= (1, 24, 0), f"v34 cần service >= 1.24.0, đang là {version}"
    assert '"%s"' % m.group(1) in _source("app/main.py")


def test_bridge_contracts_cover_every_v34_endpoint():
    path = os.path.join(os.path.dirname(ROOT), "openclaw-company-bridge", "tool-contracts.json")
    data = json.load(io.open(path, encoding="utf-8"))
    tools = data["tools"] if isinstance(data, dict) and "tools" in data else data
    names = {t["name"] for t in tools}
    for expected in (
        "company.events.backlog", "company.events.detail", "company.events.replay",
        "company.events.runtime_unmirrored", "company.events.runtime_reemit",
        "company.progress.schedules", "company.progress.schedule_create",
        "company.progress.schedule_toggle", "company.grants.ledger",
        "company.grants.due", "company.grants.revoke", "company.replay.coverage",
    ):
        assert expected in names


def test_bridge_contract_count_does_not_shrink_below_v34():
    """v34 khai 181 tool contract. Sau này chỉ được thêm, không được mất.

    Ghim đúng 181 khiến v35 (192 tool) làm đỏ test, nên assertion gốc chưa
    từng chạy. Điều cần bảo vệ là không có tool nào bị xoá âm thầm, và mọi
    tool đều có name/method/path.
    """
    path = os.path.join(os.path.dirname(ROOT), "openclaw-company-bridge", "tool-contracts.json")
    data = json.load(io.open(path, encoding="utf-8"))
    tools = data["tools"] if isinstance(data, dict) and "tools" in data else data
    assert len(tools) >= 181, f"bridge chỉ còn {len(tools)} tool, v34 đã có 181"
    names = [t["name"] for t in tools]
    assert len(names) == len(set(names)), "có tool contract trùng tên"
    for tool in tools:
        assert tool.get("method") and tool.get("path"), f"{tool.get('name')} thiếu method/path"


def test_write_contracts_are_not_marked_read_only():
    path = os.path.join(os.path.dirname(ROOT), "openclaw-company-bridge", "tool-contracts.json")
    data = json.load(io.open(path, encoding="utf-8"))
    tools = data["tools"] if isinstance(data, dict) and "tools" in data else data
    by_name = {t["name"]: t for t in tools}
    for name in ("company.events.replay", "company.grants.revoke",
                 "company.progress.schedule_create"):
        assert by_name[name].get("read_only") is False


def test_coverage_endpoint_reports_all_three_ceilings():
    node = _func(_tree("app/api/v34.py"), "coverage")
    text = ast.unparse(node)
    assert "event_replay.explain()" in text
    assert "progress_schedule.readiness()" in text
    assert "grant_ledger.enforcement()" in text
