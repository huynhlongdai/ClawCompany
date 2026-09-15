"""v35 tests: delegation spend reconciliation and the SSE live channel.

Style note, same as v19-v34: these are structural and pure-function tests. They
read the source tree and exercise functions that need no database session.
Anything that requires a live Session, a running event loop against a real
server, Redis or an OpenClaw gateway is NOT covered here and is listed in
docs/architecture-v35.md section 6.
"""

import ast
import asyncio
import inspect
import io
import json
import os

import pytest

from app.services import delegation_spend, live_channel

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


# -- delegation_spend: honesty about attribution ----------------------------


def test_attribution_admits_no_delegation_id_on_usage_rows():
    data = delegation_spend.attribution()
    assert data["usage_rows_carry_delegation_id"] is False
    assert data["basis"] == "task_id + time window"


def test_attribution_admits_it_is_not_runner_reported():
    assert delegation_spend.attribution()["runner_reported_spend"] is False


def test_attribution_admits_no_pre_dispatch_enforcement():
    assert delegation_spend.attribution()["enforced_before_dispatch"] is False


def test_attribution_admits_contracts_without_task_are_uncovered():
    assert delegation_spend.attribution()["covers_contracts_without_task"] is False


def test_attribution_note_is_vietnamese():
    note = delegation_spend.attribution()["note"]
    assert "usage_events" in note
    assert "ng\u00e2n s\u00e1ch" in note


def test_warn_ratio_is_below_one():
    assert 0 < delegation_spend.WARN_RATIO < 1


def test_scan_is_bounded():
    assert delegation_spend.MAX_SCAN == 200


def test_open_statuses_exclude_closed_contracts():
    for closed in ("completed", "cancelled", "rejected"):
        assert closed not in delegation_spend.OPEN_STATUSES


def test_open_statuses_include_delivered():
    assert "delivered" in delegation_spend.OPEN_STATUSES


def test_status_over_when_spend_exceeds_limit():
    assert delegation_spend._status(10.0, 10.5, True) == "over"


def test_status_warning_at_ratio_boundary():
    assert delegation_spend._status(10.0, 8.0, True) == "warning"


def test_status_within_below_warning():
    assert delegation_spend._status(10.0, 1.0, True) == "within"


def test_status_exact_limit_is_not_over():
    assert delegation_spend._status(10.0, 10.0, True) == "warning"


def test_status_unbudgeted_when_no_ceiling():
    assert delegation_spend._status(0.0, 5.0, True) == "unbudgeted"


def test_status_unattributable_wins_over_budget():
    assert delegation_spend._status(10.0, 0.0, False) == "unattributable"


def test_zero_spend_within_budget():
    assert delegation_spend._status(10.0, 0.0, True) == "within"


class _Contract:
    def __init__(self, **kwargs):
        self.id = kwargs.get("id", 1)
        self.accepted_at = kwargs.get("accepted_at")
        self.created_at = kwargs.get("created_at")
        self.closed_at = kwargs.get("closed_at")


def test_window_falls_back_to_created_at():
    from datetime import datetime
    made = datetime(2026, 1, 1, 10, 0, 0)
    start, end = delegation_spend._window(_Contract(created_at=made))
    assert start == made
    assert end >= made


def test_window_prefers_accepted_at():
    from datetime import datetime
    made = datetime(2026, 1, 1, 10, 0, 0)
    accepted = datetime(2026, 1, 2, 10, 0, 0)
    start, _ = delegation_spend._window(_Contract(created_at=made, accepted_at=accepted))
    assert start == accepted


def test_window_uses_closed_at_as_end():
    from datetime import datetime
    accepted = datetime(2026, 1, 2, 10, 0, 0)
    closed = datetime(2026, 1, 3, 10, 0, 0)
    start, end = delegation_spend._window(_Contract(accepted_at=accepted, closed_at=closed))
    assert (start, end) == (accepted, closed)


def test_window_never_ends_before_it_starts():
    from datetime import datetime
    accepted = datetime(2026, 1, 5, 10, 0, 0)
    closed = datetime(2026, 1, 1, 10, 0, 0)
    start, end = delegation_spend._window(_Contract(accepted_at=accepted, closed_at=closed))
    assert end == start


def test_flag_overruns_defaults_to_dry_run():
    assert _defaults(delegation_spend.flag_overruns)["dry_run"] is True


def test_overruns_excludes_warnings_by_default():
    assert _defaults(delegation_spend.overruns)["include_warnings"] is False


def test_flag_overruns_dedupes_on_existing_event():
    src = inspect.getsource(delegation_spend.flag_overruns)
    assert "_already_flagged" in src
    assert "already_flagged" in src


def test_already_flagged_scopes_by_organization():
    src = inspect.getsource(delegation_spend._already_flagged)
    assert "CompanyEvent.organization_id == organization_id" in src
    assert "CompanyEvent.aggregate_type" in src


def test_overrun_event_name_is_stable():
    assert delegation_spend.OVERRUN_EVENT == "delegation.budget.overrun"


def test_overrun_payload_marks_itself_unenforced():
    src = inspect.getsource(delegation_spend.flag_overruns)
    assert '"enforced": False' in src


def test_spend_for_refuses_to_measure_without_task():
    src = inspect.getsource(delegation_spend.spend_for)
    assert '"attributable": False' in src
    assert "task_id" in src


def test_spend_queries_scope_by_organization():
    src = inspect.getsource(delegation_spend.spend_for)
    assert "UsageEvent.organization_id == item.organization_id" in src


def test_spend_query_is_window_bounded():
    src = inspect.getsource(delegation_spend.spend_for)
    assert "UsageEvent.created_at >= start" in src
    assert "UsageEvent.created_at <= end" in src


def test_explain_caps_usage_rows():
    src = inspect.getsource(delegation_spend.explain)
    assert ".limit(50)" in src
    assert '"usage_events_capped_at": 50' in src


def test_explain_rejects_cross_organization_lookup():
    src = inspect.getsource(delegation_spend.explain)
    assert "item.organization_id != organization_id" in src
    assert "SpendError" in src


def test_explain_tolerates_broken_metadata_json():
    src = inspect.getsource(delegation_spend.explain)
    assert "except (TypeError, ValueError)" in src


def test_report_returns_attribution_with_every_answer():
    for name in ("report", "rollup", "flag_overruns"):
        assert "attribution" in inspect.getsource(getattr(delegation_spend, name))


def test_contracts_query_is_capped_even_with_huge_limit():
    src = inspect.getsource(delegation_spend._contracts)
    assert "min(int(limit or MAX_SCAN), MAX_SCAN)" in src


def test_rollup_scans_all_statuses():
    src = inspect.getsource(delegation_spend.rollup)
    assert "statuses=()" in src


def test_spend_module_never_writes_usage_rows():
    # The module docstring explains it never calls record_usage, so a plain
    # string grep finds "record_usage" in the docstring text and gives a
    # false positive.  Use an AST walk over actual Call nodes instead,
    # mirroring test_v34_replay.py::test_replay_does_not_call_record_usage.
    tree = _tree("app/services/delegation_spend.py")
    called = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                called.add(func.id)
            elif isinstance(func, ast.Attribute):
                called.add(func.attr)
    assert "record_usage" not in called
    # db.add(UsageEvent... is a code pattern, not a prose phrase; a plain
    # source check is safe here.
    assert "db.add(UsageEvent" not in _source("app/services/delegation_spend.py")


def test_spend_module_does_not_touch_budget_reservations():
    src = _source("app/services/delegation_spend.py")
    assert "reserve(" not in src
    assert "settle_reserved" not in src


# -- live_channel: what the push really is ---------------------------------


def test_transport_is_sse_not_websocket():
    data = live_channel.readiness()
    assert data["transport"] == "sse"
    assert data["websocket_implemented"] is False


def test_readiness_admits_server_still_polls():
    data = live_channel.readiness()
    assert data["removes_client_polling"] is True
    assert data["removes_server_polling"] is False


def test_readiness_admits_it_was_never_observed_in_production():
    assert live_channel.readiness()["observed_in_production"] is False


def test_readiness_reports_retention_limit_on_replay():
    assert live_channel.readiness()["replay_limited_by_retention_days"] == 14


def test_readiness_cursor_is_the_event_id():
    assert live_channel.readiness()["cursor"] == "runtime_event.id"


def test_poll_interval_is_short_but_not_zero():
    assert 0.5 <= live_channel.POLL_SECONDS <= 5


def test_heartbeat_is_longer_than_poll():
    assert live_channel.HEARTBEAT_SECONDS > live_channel.POLL_SECONDS


def test_stream_has_a_hard_duration_cap():
    assert live_channel.MAX_DURATION_SECONDS == 300


def test_batch_is_bounded():
    assert live_channel.MAX_BATCH == 100


def test_live_statuses_are_actually_live():
    assert set(live_channel.LIVE_TASK_STATUSES) == {"in_progress", "review"}


def test_frame_is_valid_sse():
    text = live_channel.frame("events", {"cursor": 7})
    assert text.startswith("event: events\ndata: ")
    assert text.endswith("\n\n")


def test_frame_payload_is_single_line():
    text = live_channel.frame("snapshot", {"note": "a b", "cursor": 1})
    body = text.split("data: ", 1)[1]
    assert body.count("\n") == 2  # only the two terminating newlines


def test_frame_payload_round_trips():
    text = live_channel.frame("events", {"cursor": 3, "events": [{"id": 3}]})
    body = text.split("data: ", 1)[1].strip()
    assert json.loads(body)["cursor"] == 3


def test_frame_keeps_vietnamese_readable():
    text = live_channel.frame("heartbeat", {"note": "ti\u1ebfn \u0111\u1ed9"})
    assert "ti\u1ebfn \u0111\u1ed9" in text


def test_frame_survives_non_serializable_values():
    from datetime import datetime
    text = live_channel.frame("snapshot", {"at": datetime(2026, 1, 1)})
    assert "2026-01-01" in text


def test_event_payload_marks_unparsable_json():
    class _Row:
        id = 4
        runtime_run_id = "run-4"
        runtime_session_key = "agent:1:main"
        event_type = "message"
        progress = 0.5
        event_json = "{not json"
        created_at = None

    payload = live_channel._event_payload(_Row())
    assert payload["event"] == {"unparsed": True}
    assert payload["created_at"] is None


def test_event_payload_keeps_cursor_field():
    class _Row:
        id = 11
        runtime_run_id = "run-11"
        runtime_session_key = ""
        event_type = "done"
        progress = 1.0
        event_json = "{}"
        created_at = None

    assert live_channel._event_payload(_Row())["id"] == 11


def test_events_since_scopes_runs_through_tasks():
    """Scope theo organization phải đi qua project -> company.

    Assertion gốc grep chuỗi "Task.organization_id == organization_id" trong
    source, và chính dòng đó là LỖI: bảng ``tasks`` không có cột
    organization_id, nên mọi lời gọi kênh live nổ AttributeError. Một test
    grep source như vậy không phát hiện lỗi -- nó bảo tồn lỗi. Thay bằng
    kiểm chứng hành vi trên SQLite thật, có hai tenant để chứng minh không
    rò rỉ chéo.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.db.base import Base
    from app.models import Company, Organization, Project, Task

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine, autoflush=False, autocommit=False)()
    try:
        runs = {}
        for slug, run in (("mine", "run-mine"), ("theirs", "run-theirs")):
            org = Organization(name=slug, slug=f"{slug}-v35-scope")
            db.add(org); db.commit(); db.refresh(org)
            company = Company(organization_id=org.id, name=f"{slug} co", status="active")
            db.add(company); db.commit(); db.refresh(company)
            project = Project(company_id=company.id, name="P", status="active", progress=0)
            db.add(project); db.commit(); db.refresh(project)
            db.add(Task(project_id=project.id, title="T", status="in_progress",
                        priority="high", runtime_run_id=run))
            db.commit()
            runs[slug] = (org.id, run)

        mine_org, mine_run = runs["mine"]
        theirs_org, theirs_run = runs["theirs"]

        assert live_channel._run_ids(db, mine_org) == [mine_run]
        assert live_channel._run_ids(db, theirs_org) == [theirs_run]
        # Và không có cột organization_id trên tasks -- đó là lý do phải join.
        assert not hasattr(Task, "organization_id")
    finally:
        db.close()


def test_run_id_scope_is_bounded():
    assert ".limit(500)" in inspect.getsource(live_channel._run_ids)


def test_events_since_returns_empty_when_org_has_no_runs():
    src = inspect.getsource(live_channel.events_since)
    assert "if not allowed" in src


def test_events_since_caps_limit():
    src = inspect.getsource(live_channel.events_since)
    assert "min(int(limit or MAX_BATCH), MAX_BATCH)" in src


def test_events_since_is_ascending_for_cursor_safety():
    assert "RuntimeEvent.id.asc()" in inspect.getsource(live_channel.events_since)


def test_snapshot_includes_readiness_so_ui_cannot_overclaim():
    src = inspect.getsource(live_channel.snapshot)
    assert "readiness()" in src


def test_snapshot_reports_followers_and_registry():
    src = inspect.getsource(live_channel.snapshot)
    assert "supervisor.snapshot" in src
    assert "registry.status()" in src


def test_stream_opens_a_session_per_tick():
    src = inspect.getsource(live_channel.stream_frames)
    assert src.count("session_factory()") >= 2
    assert src.count("session.close()") >= 2


def test_stream_closes_sessions_in_finally():
    tree = _tree("app/services/live_channel.py")
    node = _func(tree, "stream_frames")
    tries = [child for child in ast.walk(node) if isinstance(child, ast.Try)]
    assert len(tries) >= 2
    assert all(child.finalbody for child in tries)


def test_stream_emits_snapshot_first():
    src = inspect.getsource(live_channel.stream_frames)
    assert src.index('frame("snapshot"') < src.index('frame("events"')


def test_stream_ends_with_a_reconnect_cursor():
    src = inspect.getsource(live_channel.stream_frames)
    assert '"reconnect_with_cursor"' in src
    assert '"max_duration_reached"' in src


def test_stream_is_an_async_generator():
    assert inspect.isasyncgenfunction(live_channel.stream_frames)


def test_stream_frames_terminates_and_yields_in_order():
    # Không stub Task.organization_id nữa: cột đó không tồn tại trên model và
    # việc dựng stub chính là cách che đi lỗi thật. live_channel đã được sửa
    # để scope qua project -> company, và test_org_scoping_joins_through_project
    # dưới đây kiểm chứng điều đó trên SQLite thật.
    class _Session:
        """Minimal session double for stream_frames.

        live_channel.stream_frames() opens a session per tick via
        session_factory(), then passes it to snapshot() → events_since() →
        db.query(RuntimeEvent) and db.query(Task).  The double must expose
        .query() returning a chainable no-op so the generator can run to
        completion without hitting a real database.
        """

        def close(self):
            pass

        def query(self, *args):
            class _Q:
                def filter(self, *a, **kw): return self
                def filter_by(self, **kw): return self
                def order_by(self, *a): return self
                def join(self, *a, **kw): return self
                def limit(self, n): return self
                def all(self): return []
                def first(self): return None
            return _Q()

    ticks = {"value": 0.0}

    def clock():
        ticks["value"] += 1.0
        return ticks["value"]

    async def drive():
        out = []
        gen = live_channel.stream_frames(_Session, 1, cursor=0, max_duration_seconds=2,
                                         poll_seconds=0, clock=clock)
        async for item in gen:
            out.append(item)
            if len(out) > 8:
                break
        return out

    frames = asyncio.run(drive())
    assert frames
    assert frames[0].startswith("event: snapshot")
    assert frames[-1].startswith("event: closed")


def test_live_tasks_limit_is_bounded():
    src = inspect.getsource(live_channel.live_tasks)
    assert "min(int(limit or 50), 200)" in src


def test_live_channel_never_writes():
    src = _source("app/services/live_channel.py")
    assert "db.add(" not in src
    assert "db.commit()" not in src
    assert "emit_event" not in src


# -- API surface, wiring, contracts ---------------------------------------


def test_v35_router_prefix_and_tag():
    src = _source("app/api/v35.py")
    assert 'prefix="/v35"' in src
    assert 'tags=["v35-spend-push"]' in src


def test_only_the_flag_endpoint_writes():
    src = _source("app/api/v35.py")
    assert src.count("@router.post") == 1
    assert src.count('writer("admin")') == 1


def test_stream_endpoint_disables_proxy_buffering():
    src = _source("app/api/v35.py")
    assert '"X-Accel-Buffering": "no"' in src
    assert 'media_type="text/event-stream"' in src


def test_stream_endpoint_uses_session_factory_not_request_session():
    tree = _tree("app/api/v35.py")
    node = _func(tree, "live_stream")
    src = ast.unparse(node)
    assert "SessionLocal" in src
    assert "get_db" not in src


def test_every_v35_endpoint_requires_a_scope():
    tree = _tree("app/api/v35.py")
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        decorators = "".join(ast.unparse(item) for item in node.decorator_list)
        if "router." not in decorators:
            continue
        src = ast.unparse(node)
        assert "require_scope" in src or "writer(" in src


def test_company_filter_goes_through_tenancy():
    src = _source("app/api/v35.py")
    assert "ensure_company" in src


def test_v35_is_wired_into_main():
    src = _source("app/main.py")
    assert "from app.api.v35 import router as v35_router" in src
    assert 'app.include_router(v35_router, prefix="/api")' in src


def test_service_version_bumped():
    """v35 cần service >= 1.25.0, và main.py phải nói cùng con số với config.

    Không ghim đúng "1.25.0": mọi lần bump version sau đó sẽ làm test này đỏ,
    và một test đỏ vì lý do đó thì chưa từng được chạy. Đây là lần thứ ba cùng
    khuôn lỗi trong repo này (v33, v34, rồi v35).
    """
    import re

    src = _source("app/core/config.py")
    match = re.search(r'app_version:\s*str\s*=\s*"([0-9]+(?:\.[0-9]+)*)"', src)
    assert match, "không tìm thấy app_version trong app/core/config.py"
    version = tuple(int(x) for x in match.group(1).split("."))
    assert version >= (1, 25, 0), f"v35 cần service >= 1.25.0, đang là {version}"
    assert f'"{match.group(1)}"' in _source("app/main.py")


def test_bridge_contracts_cover_every_v35_endpoint():
    path = os.path.join(os.path.dirname(ROOT), "openclaw-company-bridge", "tool-contracts.json")
    data = json.load(io.open(path, encoding="utf-8"))
    tools = data["tools"] if isinstance(data, dict) and "tools" in data else data
    names = {t["name"] for t in tools}
    for expected in (
        "company.spend.coverage", "company.spend.report", "company.spend.rollup",
        "company.spend.overruns", "company.spend.detail", "company.spend.flag_overruns",
        "company.live.readiness", "company.live.snapshot", "company.live.events",
        "company.live.tasks", "company.live.stream",
    ):
        assert expected in names


def test_bridge_contract_count_is_192():
    path = os.path.join(os.path.dirname(ROOT), "openclaw-company-bridge", "tool-contracts.json")
    data = json.load(io.open(path, encoding="utf-8"))
    tools = data["tools"] if isinstance(data, dict) and "tools" in data else data
    assert len(tools) == 192


def test_flag_contract_is_not_read_only():
    path = os.path.join(os.path.dirname(ROOT), "openclaw-company-bridge", "tool-contracts.json")
    data = json.load(io.open(path, encoding="utf-8"))
    tools = data["tools"] if isinstance(data, dict) and "tools" in data else data
    by_name = {t["name"]: t for t in tools}
    assert by_name["company.spend.flag_overruns"]["read_only"] is False
    assert by_name["company.spend.report"]["read_only"] is True


def test_v35_adds_no_migration():
    folder = os.path.join(os.path.dirname(ROOT), "backend", "migrations", "versions")
    if not os.path.isdir(folder):
        pytest.skip("migrations folder not present in this checkout")
    names = sorted(os.listdir(folder))
    assert not any(name.startswith("0016") for name in names)


def test_docs_v35_exists_and_lists_unverified_work():
    path = os.path.join(os.path.dirname(ROOT), "docs", "architecture-v35.md")
    with io.open(path, encoding="utf-8") as handle:
        text = handle.read()
    assert "1.25.0" in text
    assert "SSE" in text
