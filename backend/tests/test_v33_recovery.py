"""v33 tests: member runtime repair, progress autosync, ranked retrieval,
lease index hygiene.

Most of these read the source instead of running a server, for the same
reason as v30-v32: the properties worth protecting here are *policies*
("a write defaults to a dry run", "permissions are never bypassed"), and a
policy is easier to break by editing code than by hitting an endpoint.
The pure functions that can be exercised directly -- the ranker and the
backoff-free helpers -- are exercised directly.
"""

from __future__ import annotations

import ast
import io
import json
import re
import os

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(BACKEND)


def _source(rel: str) -> str:
    return io.open(os.path.join(BACKEND, rel), encoding="utf-8").read()


def _tree(rel: str) -> ast.Module:
    return ast.parse(_source(rel))


def _func(rel: str, name: str) -> ast.FunctionDef:
    for node in ast.walk(_tree(rel)):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError("no function %s in %s" % (name, rel))


def _defaults(node: ast.FunctionDef) -> dict:
    out = {}
    for name, value in zip(node.args.kwonlyargs, node.args.kw_defaults):
        if value is not None:
            try:
                out[name.arg] = ast.literal_eval(value)
            except Exception:
                out[name.arg] = "<expr>"
    return out


# -- member runtime repair --------------------------------------------------


def test_park_defaults_to_a_dry_run():
    assert _defaults(_func("app/services/member_reactivate.py", "park"))["dry_run"] is True


def test_park_refuses_while_the_member_is_still_archived():
    src = _source("app/services/member_reactivate.py")
    body = src.split("def park(", 1)[1]
    assert "ARCHIVED_STATUS" in body.split("plan = preview", 1)[0]
    assert "ReactivateError" in body.split("plan = preview", 1)[0]


def test_archived_status_comes_from_the_archive_module_not_a_copy():
    from app.services import entity_archive, member_reactivate

    assert member_reactivate.ARCHIVED_STATUS == entity_archive.MEMBER_ARCHIVED


def test_parking_never_touches_a_task_whose_lease_is_still_held():
    src = _source("app/services/member_reactivate.py")
    body = src.split("def park(", 1)[1]
    assert 'not x["lease_held"]' in body


def test_park_lands_in_the_board_vocabulary():
    from app.services import member_reactivate, workspace_ops

    assert member_reactivate.PARK_STATUS in workspace_ops.TASK_STATUSES


def test_park_does_not_demote_work_all_the_way_to_backlog():
    from app.services import member_reactivate

    assert member_reactivate.PARK_STATUS != "backlog"


def test_parking_clears_the_session_key_it_reports_dropping():
    body = _source("app/services/member_reactivate.py").split("def park(", 1)[1]
    assert "task.runtime_session_key = None" in body
    assert "dropped_session_key" in body


def test_only_running_statuses_count_as_orphans():
    from app.services import member_reactivate

    assert "in_progress" in member_reactivate.RUNNING_STATUSES
    assert "done" not in member_reactivate.RUNNING_STATUSES
    assert "cancelled" not in member_reactivate.RUNNING_STATUSES


def test_resume_plan_is_data_and_says_it_did_not_run():
    from app.services import member_reactivate

    body = _source("app/services/member_reactivate.py").split("def resume_plan(", 1)[1]
    assert "executed" in body and "why_not_executed" in body
    # A plan must not dispatch, commit, or emit.
    plan_only = body.split("def park(", 1)[0]
    assert "db.commit" not in plan_only
    assert "dispatch(" not in plan_only
    assert member_reactivate.RESUME_TOOL.startswith("company.")


def test_lease_lookup_failure_is_not_read_as_lease_free():
    src = _source("app/services/member_reactivate.py")
    body = src.split("def _lease_holder(", 1)[1].split("def _member_of(", 1)[0]
    # On failure it returns None, and the caller reports lease_held from that,
    # so the only risk is claiming a live lease is free. That risk is stated
    # in the docstring rather than hidden.
    assert "best effort" in body
    assert "return None" in body


def test_coverage_lists_what_the_repair_refuses_to_do():
    from app.services import member_reactivate

    cover = member_reactivate.coverage()
    assert cover["does_not_do"]
    assert any("dispatch" in x for x in cover["does_not_do"])


def test_park_is_bounded_per_call():
    from app.services import member_reactivate

    assert 0 < member_reactivate.MAX_PARK <= 1000
    body = _source("app/services/member_reactivate.py").split("def park(", 1)[1]
    assert "MAX_PARK" in body


# -- progress autosync ------------------------------------------------------


def test_progress_sync_defaults_to_a_dry_run():
    assert _defaults(_func("app/services/progress_autosync.py", "sync"))["dry_run"] is True


def test_a_project_with_no_tasks_is_never_written_down_to_zero():
    from app.services import progress_autosync

    body = _source("app/services/progress_autosync.py").split("def _row(", 1)[1]
    assert "no tasks to measure" in body
    assert progress_autosync.policy()["unknown_is_skipped"] is True


def test_finished_projects_keep_their_historical_number():
    from app.services import progress_autosync, workspace_ops

    for status in progress_autosync.FROZEN_STATUSES:
        assert status in workspace_ops.PROJECT_STATUSES
    assert "done" in progress_autosync.FROZEN_STATUSES
    assert "cancelled" in progress_autosync.FROZEN_STATUSES


def test_tiny_drift_is_not_worth_an_audit_row():
    from app.services import progress_autosync

    assert progress_autosync.MIN_DRIFT >= 2
    body = _source("app/services/progress_autosync.py").split("def _row(", 1)[1]
    assert "within noise threshold" in body


def test_progress_is_written_only_through_the_single_writer():
    body = _source("app/services/progress_autosync.py").split("def sync(", 1)[1]
    assert "board_truth.sync_progress" in body
    # This pass must never assign the column itself.
    assert "project.progress =" not in body


def test_the_truth_number_comes_from_board_truth():
    from app.services import progress_autosync

    assert progress_autosync.policy()["source_of_truth"] == "board_truth.derive"


def test_drift_report_puts_the_worst_offenders_first():
    body = _source("app/services/progress_autosync.py").split("def drift_report(", 1)[1]
    assert "reverse=True" in body


def test_a_failed_project_does_not_abort_the_whole_pass():
    body = _source("app/services/progress_autosync.py").split("def sync(", 1)[1]
    assert "failed.append" in body


def test_sync_is_bounded_and_org_scoped():
    from app.services import progress_autosync

    assert 0 < progress_autosync.MAX_SYNC <= 1000
    body = _source("app/services/progress_autosync.py").split("def _projects(", 1)[1]
    assert "Project.organization_id == organization_id" in body


# -- ranked retrieval -------------------------------------------------------


def test_retrieval_never_queries_entries_itself():
    src = _source("app/services/mesh_retrieval.py")
    # The only read path is knowledge_mesh.search, which owns permissions.
    assert "SharedKnowledgeEntry" not in src
    assert "knowledge_mesh.search" in src


def test_permission_filtering_happens_before_ranking():
    body = _source("app/services/mesh_retrieval.py").split("def search(", 1)[1]
    assert body.index("knowledge_mesh.search") < body.index("score_rows")


def test_semantic_mode_still_goes_through_the_permission_call():
    body = _source("app/services/mesh_retrieval.py").split("def search(", 1)[1]
    before_mode_split = body.split("if mode == KEYWORD", 1)[0]
    assert "knowledge_mesh.search" in before_mode_split


def test_the_ranker_admits_what_it_cannot_do():
    from app.services import mesh_retrieval

    explain = mesh_retrieval.explain()
    assert explain["trained_model"] is False
    assert explain["understands_synonyms"] is False
    assert "synonyms" in explain["bad_at"]


def test_identical_text_outranks_unrelated_text():
    from app.services import mesh_retrieval

    rows = [
        {"entry_id": 1, "title": "khac han", "content": "noi dung khong lien quan gi"},
        {"entry_id": 2, "title": "chinh sach hoan tien", "content": "chinh sach hoan tien cho khach"},
    ]
    scored = mesh_retrieval.score_rows("chinh sach hoan tien", rows)
    by_id = {r["entry_id"]: r["score"] for r in scored}
    assert by_id[2] > by_id[1]


def test_an_empty_query_is_not_scored_at_all():
    from app.services import mesh_retrieval

    scored = mesh_retrieval.score_rows("   ", [{"entry_id": 1, "title": "a", "content": "b"}])
    assert scored[0]["scored"] is False
    assert scored[0]["score"] is None


def test_an_empty_entry_scores_zero_instead_of_raising():
    from app.services import mesh_retrieval

    scored = mesh_retrieval.score_rows("bat ky", [{"entry_id": 1, "title": "", "content": ""}])
    assert scored[0]["score"] == 0.0


def test_scoring_is_a_pure_function():
    node = _func("app/services/mesh_retrieval.py", "score_rows")
    names = {a.arg for a in node.args.args}
    assert "db" not in names
    body = ast.unparse(node)
    assert "commit" not in body and "_log" not in body


def test_hybrid_keeps_the_keyword_signal_without_letting_it_win():
    from app.services import mesh_retrieval

    assert mesh_retrieval.SEMANTIC_WEIGHT > mesh_retrieval.KEYWORD_WEIGHT
    assert abs(mesh_retrieval.SEMANTIC_WEIGHT + mesh_retrieval.KEYWORD_WEIGHT - 1.0) < 1e-9


def test_the_candidate_pool_is_wider_than_the_page_but_bounded():
    from app.services import mesh_retrieval

    assert mesh_retrieval.CANDIDATE_FACTOR > 1
    assert mesh_retrieval.MAX_CANDIDATES <= 100


def test_long_entries_are_truncated_before_embedding():
    from app.services import mesh_retrieval

    assert 0 < mesh_retrieval.EMBED_CHARS <= 4000
    body = _source("app/services/mesh_retrieval.py").split("def _text_of(", 1)[1]
    assert "EMBED_CHARS" in body


def test_an_unknown_mode_falls_back_instead_of_raising():
    body = _source("app/services/mesh_retrieval.py").split("def search(", 1)[1]
    assert "mode = HYBRID" in body


def test_the_embedding_is_the_one_v26_already_shipped():
    from app.services import mesh_retrieval, vector_search

    assert mesh_retrieval.hash384_embedding is vector_search.hash384_embedding
    assert mesh_retrieval.cosine is vector_search.cosine


# -- lease index hygiene ----------------------------------------------------


def test_index_prune_defaults_to_a_dry_run():
    node = _func("app/services/runtime_leases.py", "prune_index")
    assert _defaults(node)["dry_run"] is True


def test_index_prune_is_bounded():
    from app.services import runtime_leases

    assert runtime_leases.MAX_INDEX_PRUNE <= 5000
    body = _source("app/services/runtime_leases.py").split("def prune_index(", 1)[1]
    assert "MAX_INDEX_PRUNE" in body


def test_a_live_lease_is_never_pruned_from_the_index():
    body = _source("app/services/runtime_leases.py").split("def prune_index(", 1)[1]
    assert "if owner:" in body
    assert "live += 1" in body


def test_index_size_is_reported_so_a_leak_is_visible():
    body = _source("app/services/runtime_leases.py").split("def status(", 1)[1]
    assert "index_size" in body.split("def index_size", 1)[0]


def test_index_size_is_unknown_rather_than_zero_without_redis():
    body = _source("app/services/runtime_leases.py").split("def index_size(", 1)[1]
    head = body.split("def prune_index(", 1)[0]
    assert "return None" in head


def test_the_memory_backend_says_there_is_nothing_to_leak():
    body = _source("app/services/runtime_leases.py").split("def prune_index(", 1)[1]
    assert "no shared index set to leak" in body


def test_prune_reads_in_batches_not_one_giant_mget():
    body = _source("app/services/runtime_leases.py").split("def prune_index(", 1)[1]
    assert "range(0, len(members), 200)" in body


# -- router and bridge surface ---------------------------------------------


def test_every_v33_write_endpoint_requires_at_least_manager():
    src = _source("app/api/v33.py")
    for chunk in src.split("@router.post")[1:]:
        header = chunk.split(") -> dict", 1)[0]
        assert "writer(" in header, header[:200]
        assert 'writer("member")' not in header


def test_runtime_writes_are_admin_only():
    src = _source("app/api/v33.py")
    park = src.split("def member_runtime_park(", 1)[1].split("->", 1)[0]
    prune = src.split("def lease_index_prune(", 1)[1].split("->", 1)[0]
    assert 'writer("admin")' in park
    assert 'writer("admin")' in prune


def test_api_keys_keep_passing_on_scope_alone():
    body = _source("app/api/v33.py").split("def writer(", 1)[1]
    assert 'principal.auth_type != "api_key"' in body


def test_retrieval_refuses_an_identity_free_caller():
    body = _source("app/api/v33.py").split("def knowledge_search(", 1)[1]
    assert "principal.member_id is None" in body
    assert "raise HTTPException(400" in body


def test_a_company_scoped_call_is_tenancy_checked():
    src = _source("app/api/v33.py")
    for name in ("progress_drift", "progress_sync"):
        body = src.split("def %s(" % name, 1)[1].split("\n\n\n", 1)[0]
        assert "ensure_company" in body


def test_a_blocked_repair_is_a_conflict_not_a_server_error():
    body = _source("app/api/v33.py").split("def member_runtime_park(", 1)[1]
    assert "ReactivateError" in body
    assert "HTTPException(409" in body


def test_every_new_bridge_tool_points_at_a_real_v33_route():
    contracts = json.load(io.open(os.path.join(ROOT, "openclaw-company-bridge",
                                               "tool-contracts.json"), encoding="utf-8"))
    src = _source("app/api/v33.py")
    v33 = [t for t in contracts["tools"] if "/v33/" in t["path"]]
    assert len(v33) == 10
    for tool in v33:
        route = tool["path"].replace("/api/v33", "")
        assert '"%s"' % route in src, route


def test_bridge_tool_names_stay_unique():
    contracts = json.load(io.open(os.path.join(ROOT, "openclaw-company-bridge",
                                               "tool-contracts.json"), encoding="utf-8"))
    names = [t["name"] for t in contracts["tools"]]
    assert len(names) == len(set(names))


def test_write_tools_carry_the_write_scope():
    contracts = json.load(io.open(os.path.join(ROOT, "openclaw-company-bridge",
                                               "tool-contracts.json"), encoding="utf-8"))
    for tool in contracts["tools"]:
        if "/v33/" in tool["path"] and tool["method"] == "POST":
            assert tool["scope"] == "company.workspace:write"


def _service_version() -> tuple[int, ...]:
    """Version hiện tại của service, đọc từ config.

    Bản gốc ghim chuỗi "1.23.0". Ghim số tuyệt đối biến mọi lần bump version
    thành một test đỏ, nên assertion đó không thể từng được chạy. Điều cần
    bảo vệ là quan hệ: version của service phải >= version giới thiệu router
    này, và config với main.py phải nói cùng một con số.
    """
    src = _source("app/core/config.py")
    m = re.search(r'app_version:\s*str\s*=\s*"([0-9]+(?:\.[0-9]+)*)"', src)
    assert m, "không tìm thấy app_version trong app/core/config.py"
    return tuple(int(x) for x in m.group(1).split("."))


def test_the_service_version_moved_with_the_router():
    version = _service_version()
    assert version >= (1, 23, 0), f"v33 cần service >= 1.23.0, đang là {version}"
    main = _source("app/main.py")
    literal = '"%s"' % ".".join(str(x) for x in version)
    assert main.count(literal) >= 2, "main.py phải công bố cùng version với config"
    assert "v33_router" in main
