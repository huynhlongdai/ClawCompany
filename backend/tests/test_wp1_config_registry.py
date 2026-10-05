"""WP-1.1 + WP-1.2 — kiểm hành vi của Config Registry.

Cách viết test ở đây: một **fake transport** ghi lại mọi lời gọi RPC rồi trả về
payload đúng hình dạng upstream. Đây không phải loại double mà `_reports/
test-triage.md` đã phê phán: cái bị phê là double *bỏ qua điều kiện lọc* rồi
khiến test tưởng SQL đúng. Ở đây thứ cần kiểm chính là **frame gửi đi** — params
nào, path nào, hash nào — nên fake transport là đúng công cụ, và phần chạm
gateway thật được kiểm riêng bằng `tools/probe_config.py`.

Mỗi test dưới đây phải đỏ được nếu bỏ chốt tương ứng trong service. Chỗ nào chỉ
kiểm hình dạng chứ không kiểm hành vi thì nói rõ trong docstring.
"""
import json

import pytest

from app.runtime import openclaw_protocol as ocp
from app.services import openclaw_config as cfg


class FakeGateway:
    """Ghi lại lời gọi và trả payload theo hình dạng upstream."""

    def __init__(self, config: dict | None = None, *, hash_: str = "h1",
                 applied_hash: str | None = None, changed_paths=None):
        self.config = config if config is not None else {}
        self.hash = hash_
        self.applied_hash = applied_hash
        self.changed_paths = changed_paths if changed_paths is not None else ["x"]
        self.calls: list[tuple[str, dict]] = []
        # path -> reloadKind, để test quyết định path nào cần restart
        self.reload_kinds: dict[str, str] = {}

    async def rpc(self, method: str, params: dict | None = None) -> dict:
        params = params or {}
        self.calls.append((method, params))
        if method == ocp.M_CONFIG_GET:
            payload = {"config": self.config, "hash": self.hash,
                       "configRevisionHash": "rev1"}
            if self.applied_hash is not None:
                payload["appliedConfigHash"] = self.applied_hash
            return payload
        if method == ocp.M_CONFIG_SCHEMA_LOOKUP:
            path = params.get("path", "")
            return {"path": path,
                    "reloadKind": self.reload_kinds.get(path, ocp.RELOAD_HOT),
                    "schema": {"type": "string"}, "children": []}
        if method == ocp.M_CONFIG_PATCH:
            return {"changedPaths": self.changed_paths}
        return {}

    def patches(self) -> list[dict]:
        return [p for m, p in self.calls if m == ocp.M_CONFIG_PATCH]


def registry(gateway: FakeGateway, **kw) -> cfg.ConfigRegistry:
    return cfg.ConfigRegistry(gateway, **kw)


# ----------------------------------------------------------- WP-1.1: hằng số

def test_agents_namespace_constants_exist():
    """Những method mà lượt trước tưởng không có.

    Chỉ kiểm chuỗi, nên test này *không* chứng minh gateway có method đó —
    bằng chứng đó nằm ở `_reports/native-probe-agents.log`. Nó chỉ chặn việc
    ai đó lỡ tay đổi tên hằng số.
    """
    assert ocp.M_AGENTS_CREATE == "agents.create"
    assert ocp.M_AGENTS_FILES_SET == "agents.files.set"
    assert ocp.M_AGENTS_WORKSPACE_GET == "agents.workspace.get"
    assert ocp.M_CONFIG_SCHEMA_LOOKUP == "config.schema.lookup"
    assert ocp.M_USAGE_COST == "usage.cost"


def test_admin_scope_is_opt_in_and_separate_from_approvals():
    """Quyền ghi cấu hình không được đi kèm miễn phí với quyền duyệt."""
    assert ocp.SCOPE_ADMIN not in ocp.COMPANY_SCOPES
    assert ocp.SCOPE_ADMIN in ocp.CONFIG_SCOPES
    assert ocp.SCOPE_APPROVALS not in ocp.CONFIG_SCOPES


def test_frame_limit_is_above_the_measured_schema_size():
    """`config.schema` đo được 2.213.650 byte trên gateway 2026.9.4 thật.

    Mặc định `max_size` của thư viện websockets là 1 MiB, nên lời gọi này từng
    chết với `1009 message too big` — và không ai biết, vì chưa ai gọi nó. Test
    canh giữ để không ai hạ hạn mức xuống dưới mức đã đo.
    Bằng chứng: `_reports/native-probe-agents.log`.
    """
    from app.core.config import settings
    measured_schema_bytes = 2_213_650
    assert settings.openclaw_max_frame_bytes > measured_schema_bytes


def test_bootstrap_budgets_match_upstream_defaults():
    assert ocp.BOOTSTRAP_MAX_CHARS == 20_000
    assert ocp.BOOTSTRAP_TOTAL_MAX_CHARS == 60_000
    # USER.md nhỏ hơn các file khác — chỗ này rất dễ bị bỏ sót khi làm UI.
    assert ocp.USER_MD_MAX_CHARS == 4_000
    assert "SOUL.md" in ocp.AGENT_BOOTSTRAP_FILES


# ------------------------------------------------------------- đường dẫn

def test_dotted_and_tuple_paths_produce_the_same_tree():
    assert cfg._nest({"a.b.c": 1}) == {"a": {"b": {"c": 1}}}
    assert cfg._nest({("a", "b", "c"): 1}) == {"a": {"b": {"c": 1}}}


def test_sibling_paths_merge_instead_of_overwriting():
    """Hai path cùng nhánh phải trộn — nếu không, patch thứ hai xoá patch thứ nhất."""
    tree = cfg._nest({"agents.entries.dev.model": "m1",
                      "agents.entries.dev.thinkingDefault": "high"})
    assert tree == {"agents": {"entries": {"dev": {
        "model": "m1", "thinkingDefault": "high"}}}}


def test_path_collision_is_refused():
    with pytest.raises(cfg.ConfigError) as exc:
        cfg._nest({"a.b": 1, "a.b.c": 2})
    assert exc.value.reason == "path_collision"


def test_none_is_preserved_because_null_means_delete():
    """JSON merge patch: ``null`` là xoá khoá. Không được lọc bỏ nó."""
    assert cfg._nest({"a.b": None}) == {"a": {"b": None}}


# --------------------------------------------------- replacePaths: chốt chính

@pytest.mark.asyncio
async def test_patch_that_drops_array_entries_is_refused():
    gw = FakeGateway({"agents": {"entries": {"dev": {"skills": ["a", "b", "c"]}}}})
    with pytest.raises(cfg.ConfigError) as exc:
        await registry(gw).patch({"agents.entries.dev.skills": ["a"]})

    assert exc.value.reason == "replace_path_required"
    assert exc.value.details["arrays"][0]["removed"] == 2
    # Quan trọng: bị chặn TRƯỚC khi gửi, nên gateway không hề nhận patch nào.
    assert gw.patches() == []


@pytest.mark.asyncio
async def test_same_patch_passes_when_the_path_is_authorized():
    gw = FakeGateway({"agents": {"entries": {"dev": {"skills": ["a", "b", "c"]}}}})
    out = await registry(gw).patch(
        {"agents.entries.dev.skills": ["a"]},
        replace_paths=["agents.entries.dev.skills"],
    )
    assert out["applied"] is True
    sent = gw.patches()[0]
    assert sent["replacePaths"] == ["agents.entries.dev.skills"]


@pytest.mark.asyncio
async def test_appending_to_an_array_needs_no_authorization():
    """Chỉ *mất* phần tử mới cần khai. Thêm vào cuối thì không."""
    gw = FakeGateway({"agents": {"entries": {"dev": {"skills": ["a"]}}}})
    out = await registry(gw).patch({"agents.entries.dev.skills": ["a", "b"]})
    assert out["applied"] is True
    assert "replacePaths" not in gw.patches()[0]


@pytest.mark.asyncio
async def test_deleting_an_array_counts_as_removal():
    gw = FakeGateway({"tools": {"allow": ["exec"]}})
    with pytest.raises(cfg.ConfigError) as exc:
        await registry(gw).patch({"tools.allow": None})
    assert exc.value.details["arrays"][0]["kind"] == "deleted"


@pytest.mark.asyncio
async def test_deleting_a_parent_object_requires_its_contained_arrays():
    """Upstream: "Deleting a containing object requires its contained array paths"."""
    gw = FakeGateway({"agents": {"entries": {"dev": {"skills": ["a"], "model": "m"}}}})
    with pytest.raises(cfg.ConfigError) as exc:
        await registry(gw).patch({"agents.entries.dev": None})
    paths = [r["path"] for r in exc.value.details["arrays"]]
    assert "agents.entries.dev.skills" in paths


def test_wildcard_replace_path_is_refused():
    """Hai file docs của upstream nói khác nhau; ta theo bản nghiêm hơn.

    ``rpc-talk-config-and-agents.md`` nêu ví dụ ``agents.entries.*.skills``,
    còn ``config-rpc.md`` nói thẳng "Parent paths and * wildcards do not
    authorize descendant arrays". Nhận wildcard nghĩa là UI hứa một lần ghi mà
    gateway sẽ từ chối.
    """
    with pytest.raises(cfg.ConfigError) as exc:
        cfg.validate_replace_paths(["agents.entries.*.skills"])
    assert exc.value.reason == "wildcard_replace_path"
    # Cú pháp [] cho mảng lồng theo id thì hợp lệ, đó là của upstream.
    assert cfg.validate_replace_paths(
        ["models.providers.custom.models[].input"]
    ) == ["models.providers.custom.models[].input"]


def test_doc_conflict_is_recorded_in_the_protocol_module():
    """Chỗ docs tự mâu thuẫn phải đọc được từ code, không nằm trong đầu ai đó."""
    topics = [c["topic"] for c in ocp.DOC_CONFLICTS]
    assert "replacePaths wildcards" in topics


# ------------------------------------------------------------------ baseHash

@pytest.mark.asyncio
async def test_base_hash_is_fetched_when_the_caller_omits_it():
    gw = FakeGateway({"agents": {}}, hash_="abc123")
    out = await registry(gw).patch({"agents.defaults.model": "m"})
    assert gw.patches()[0]["baseHash"] == "abc123"
    assert out["base_hash_source"] == "config.get"


@pytest.mark.asyncio
async def test_caller_supplied_base_hash_wins():
    gw = FakeGateway({"agents": {}}, hash_="fresh")
    await registry(gw).patch({"agents.defaults.model": "m"}, base_hash="stale")
    # Gửi đúng hash caller đưa: nếu nó cũ, gateway sẽ từ chối — đó là mục đích.
    assert gw.patches()[0]["baseHash"] == "stale"


@pytest.mark.asyncio
async def test_first_write_with_no_existing_config_skips_the_hash_check():
    """Upstream: "a first write with no existing config skips the check"."""
    gw = FakeGateway({}, hash_="")
    out = await registry(gw).patch({"agents.defaults.model": "m"})
    assert out["applied"] is True
    assert "baseHash" not in gw.patches()[0]


@pytest.mark.asyncio
async def test_existing_config_without_hash_is_refused():
    gw = FakeGateway({"agents": {"defaults": {}}}, hash_="")
    with pytest.raises(cfg.ConfigError) as exc:
        await registry(gw).patch({"agents.defaults.model": "m"})
    assert exc.value.reason == "missing_base_hash"


# -------------------------------------------------------------- raw là chuỗi

@pytest.mark.asyncio
async def test_raw_is_a_json_string_not_an_object():
    """``raw`` là chuỗi cấu hình. Gửi object là sai kiểu và gateway từ chối."""
    gw = FakeGateway({"agents": {}})
    await registry(gw).patch({"agents.entries.dev.model": "cometapi/gpt-4o-mini"})
    raw = gw.patches()[0]["raw"]
    assert isinstance(raw, str)
    assert json.loads(raw) == {"agents": {"entries": {"dev": {
        "model": "cometapi/gpt-4o-mini"}}}}


@pytest.mark.asyncio
async def test_unicode_survives_the_round_trip():
    """Tính cách agent viết bằng tiếng Việt — không được escape thành \\uXXXX."""
    gw = FakeGateway({"agents": {}})
    await registry(gw).patch({"agents.entries.dev.identity.theme": "Trợ lý điều hành"})
    assert "Trợ lý điều hành" in gw.patches()[0]["raw"]


# ------------------------------------------------------------ reload / restart

@pytest.mark.asyncio
async def test_restart_paths_are_refused_unless_allowed():
    gw = FakeGateway({"agents": {}})
    gw.reload_kinds["gateway.bind"] = ocp.RELOAD_RESTART
    with pytest.raises(cfg.ConfigError) as exc:
        await registry(gw).patch({"gateway.bind": "lan"})
    assert exc.value.reason == "restart_required"
    assert gw.patches() == []

    out = await registry(gw).patch({"gateway.bind": "lan"}, allow_restart=True)
    assert out["requires_restart"] is True


@pytest.mark.asyncio
async def test_reload_plan_is_computed_before_writing():
    """Cảnh báo restart phải đến trước lúc Lưu, không phải sau."""
    gw = FakeGateway({"agents": {}})
    gw.reload_kinds["agents.entries.dev.model"] = ocp.RELOAD_HOT
    plan = await registry(gw).reload_plan(["agents.entries.dev.model"])
    assert plan["requires_restart"] is False
    assert plan["paths"]["agents.entries.dev.model"] == "hot"
    assert plan["unknown"] == []


@pytest.mark.asyncio
async def test_unknown_reload_kind_is_surfaced_not_assumed_hot():
    """OpenClaw có thể thêm giá trị mới; đoán 'hot' là đoán về phía nguy hiểm."""
    gw = FakeGateway({"agents": {}})
    gw.reload_kinds["a.b"] = "reboot-the-planet"
    node = await registry(gw).schema_node("a.b")
    assert node["reload_kind"].startswith("unknown:")
    assert (await registry(gw).reload_plan(["a.b"]))["unknown"] == ["a.b"]


@pytest.mark.asyncio
async def test_schema_lookup_is_cached_per_path():
    gw = FakeGateway({"agents": {}})
    reg = registry(gw)
    await reg.schema_node("agents.defaults.model")
    await reg.schema_node("agents.defaults.model")
    lookups = [p for m, p in gw.calls if m == ocp.M_CONFIG_SCHEMA_LOOKUP]
    assert len(lookups) == 1, "một form mở ra hỏi hàng chục path; đừng tiêu hạn mức"


# ------------------------------------------------------------------ dry run

@pytest.mark.asyncio
async def test_dry_run_sends_nothing_but_shows_the_exact_frame():
    gw = FakeGateway({"agents": {}})
    out = await registry(gw).patch({"agents.defaults.model": "m"}, dry_run=True)
    assert out["dry_run"] is True
    assert out["method"] == ocp.M_CONFIG_PATCH
    assert json.loads(out["params"]["raw"]) == {"agents": {"defaults": {"model": "m"}}}
    assert gw.patches() == []


# ---------------------------------------------------------------- hạn mức ghi

def test_write_budget_allows_up_to_the_limit_then_refuses():
    budget = cfg._WriteBudget(limit=3, window=60)
    for i in range(3):
        budget.check("config.patch", now=float(i))
    with pytest.raises(cfg.RateLimited) as exc:
        budget.check("config.patch", now=3.0)
    assert exc.value.details["retry_after"] > 0


def test_write_budget_is_per_method():
    budget = cfg._WriteBudget(limit=1, window=60)
    budget.check("config.patch", now=0.0)
    budget.check("config.apply", now=0.0)   # method khác, hạn mức riêng
    with pytest.raises(cfg.RateLimited):
        budget.check("config.patch", now=1.0)


def test_write_budget_forgets_calls_outside_the_window():
    budget = cfg._WriteBudget(limit=1, window=60)
    budget.check("config.patch", now=0.0)
    budget.check("config.patch", now=61.0)


def test_budget_default_matches_the_documented_limit():
    assert ocp.CONTROL_PLANE_RATE_LIMIT == (30, 60)
    budget = cfg._WriteBudget()
    assert (budget.limit, budget.window) == (30, 60)


@pytest.mark.asyncio
async def test_reads_are_not_counted_against_the_write_budget():
    """Đọc schema không phải ghi; đếm nó vào hạn mức sẽ khoá UI vô cớ."""
    gw = FakeGateway({"agents": {}})
    reg = registry(gw, budget=cfg._WriteBudget(limit=1, window=60))
    for i in range(5):
        await reg.schema_node(f"a.b{i}")
    await reg.snapshot()
    out = await reg.patch({"agents.defaults.model": "m"})
    assert out["applied"] is True


# ------------------------------------------------------- phản hồi & trạng thái

@pytest.mark.asyncio
async def test_empty_changed_paths_is_reported_as_a_no_op_not_a_failure():
    gw = FakeGateway({"agents": {}}, changed_paths=[])
    out = await registry(gw).patch({"agents.defaults.model": "m"})
    assert out["applied"] is True and out["no_op"] is True


@pytest.mark.asyncio
async def test_pending_apply_is_detected_from_the_two_hashes():
    """Đã lưu nhưng chưa nạp là một trạng thái thật; UI phải nói ra."""
    gw = FakeGateway({"agents": {}}, applied_hash="rev0")   # revision hiện tại là rev1
    snap = await registry(gw).snapshot()
    assert snap["pending_apply"] is True

    gw2 = FakeGateway({"agents": {}}, applied_hash="rev1")
    assert (await registry(gw2).snapshot())["pending_apply"] is False


@pytest.mark.asyncio
async def test_empty_patch_is_refused():
    gw = FakeGateway({"agents": {}})
    with pytest.raises(cfg.ConfigError) as exc:
        await registry(gw).patch({})
    assert exc.value.reason == "empty_patch"


# ------------------------------------------------------------ seat: thừa hưởng

@pytest.mark.asyncio
async def test_agent_entry_separates_own_values_from_inherited_ones():
    """Người vận hành phải thấy giá trị nào của riêng seat, nào của cả công ty."""
    gw = FakeGateway({"agents": {
        "defaults": {"model": "cheap", "thinkingDefault": "medium"},
        "entries": {"dev": {"model": "expensive"}},
    }})
    out = await registry(gw).agent_entry("dev")
    assert out["exists"] is True
    assert out["effective"]["model"] == "expensive"      # entry thắng defaults
    assert out["effective"]["thinkingDefault"] == "medium"
    assert out["inherited_keys"] == ["thinkingDefault"]


@pytest.mark.asyncio
async def test_missing_agent_entry_says_so_instead_of_inventing_one():
    gw = FakeGateway({"agents": {"defaults": {"model": "m"}, "entries": {}}})
    out = await registry(gw).agent_entry("ghost")
    assert out["exists"] is False
    assert out["entry"] == {}


def test_entry_path_is_a_tuple_so_dotted_names_survive():
    reg = cfg.ConfigRegistry(FakeGateway())
    assert reg.entry_path("dev", "identity", "name") == (
        "agents", "entries", "dev", "identity", "name")
    # Một agentId có dấu chấm không được tách đôi.
    tree = cfg._nest({reg.entry_path("a.b", "model"): "m"})
    assert tree["agents"]["entries"]["a.b"]["model"] == "m"
