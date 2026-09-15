"""WP-2.1 + WP-2.2 — hồ sơ nhân sự AI: đọc gộp ba nguồn, ghi có điều kiện.

Test ở đây dùng **database thật** (SQLite in-memory, model ORM thật) cho phần
tenancy, và một fake gateway cho phần RPC. Ranh giới đó có lý: cái cần kiểm ở
phía database là câu `WHERE` có chặn đúng tenant hay không — nên phải là SQL
thật; cái cần kiểm ở phía gateway là **params gửi đi** và **cách xử lý lỗi trả
về** — nên fake ghi lại lời gọi là đúng công cụ.

Phần chạm gateway thật (ghi SOUL.md rồi hỏi lại agent xem giọng có đổi) nằm ở
`tools/probe_seat.py`, không nằm trong suite này.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
import app.models  # noqa: F401
from app.models.entities import Agent, Company, Department, Member, Organization
from app.runtime import openclaw_protocol as ocp
from app.runtime.openclaw_native import OpenClawProtocolError
from app.services import seat_profile as sp

GOOD_HASH = "a" * 64
OTHER_HASH = "b" * 64


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def org(db):
    organization = Organization(name="Nova", slug="nova-wp2")
    db.add(organization); db.commit(); db.refresh(organization)
    company = Company(organization_id=organization.id, name="Nova Fashion", status="active")
    db.add(company); db.commit(); db.refresh(company)
    department = Department(company_id=company.id, name="Điều hành", status="active")
    db.add(department); db.commit(); db.refresh(department)
    return organization, company, department


def make_seat(db, org, *, runtime_id="dev", name="Nina"):
    organization, company, department = org
    boss = Member(organization_id=organization.id, company_id=company.id,
                  name="Long", member_type="human", role="Founder", status="active")
    db.add(boss); db.commit(); db.refresh(boss)
    member = Member(organization_id=organization.id, company_id=company.id,
                    department_id=department.id, manager_id=boss.id, name=name,
                    member_type="agent", role="AI Chief of Staff", status="active")
    db.add(member); db.commit(); db.refresh(member)
    agent = Agent(member_id=member.id, runtime_provider="openclaw",
                  runtime_agent_id=runtime_id, lifecycle="active",
                  model="cometapi/gpt-4o-mini", success_rate=98.0, cost_30d=4.26)
    db.add(agent); db.commit(); db.refresh(agent)
    return agent, member


class FakeGateway:
    """Fake gateway: ghi lại lời gọi, trả payload đúng hình dạng đã đo được."""

    def __init__(self, *, roster=("dev",), files=None, conflict_on=(),
                 config=None):
        self.roster = list(roster)
        self.files = files if files is not None else {
            "IDENTITY.md": {"content": "# Nina\n", "hash": GOOD_HASH, "missing": False},
            "SOUL.md": {"content": "# SOUL.md - The Soul of C-3PO\n", "hash": GOOD_HASH,
                        "missing": False},
            "AGENTS.md": {"content": "Quy tắc làm việc\n", "hash": GOOD_HASH, "missing": False},
            "USER.md": {"content": "- Thích báo cáo ngắn\n", "hash": GOOD_HASH, "missing": False},
            "MEMORY.md": {"content": "", "hash": "", "missing": True, "expectedAbsent": True},
        }
        self.conflict_on = set(conflict_on)
        self.config = config if config is not None else {
            "agents": {"defaults": {"model": "cheap", "maxConcurrent": 4},
                       "entries": {"dev": {"model": "cometapi/gpt-4o-mini",
                                           "identity": {"name": "Nina"},
                                           "skills": ["a", "b"]}}}}
        self.calls: list[tuple[str, dict]] = []

    async def list_agents(self):
        return [{"id": a} for a in self.roster]

    async def rpc(self, method, params=None):
        params = params or {}
        self.calls.append((method, params))
        if method == ocp.M_AGENT_IDENTITY_GET:
            return {"agentId": params.get("agentId"), "name": "Nina", "emoji": "✦"}
        if method == ocp.M_CONFIG_GET:
            return {"config": self.config, "hash": "h1", "configRevisionHash": "r1"}
        if method == ocp.M_CONFIG_SCHEMA_LOOKUP:
            return {"path": params.get("path", ""), "reloadKind": ocp.RELOAD_HOT,
                    "schema": {}, "children": []}
        if method == ocp.M_CONFIG_PATCH:
            return {"changedPaths": ["x"]}
        if method == ocp.M_AGENTS_FILES_GET:
            name = params["name"]
            if name not in self.files:
                raise OpenClawProtocolError(f'unsupported file "{name}"',
                                            {"code": "INVALID_REQUEST"})
            record = dict(self.files[name])
            record["name"] = name
            record["size"] = len(record.get("content", ""))
            return {"agentId": params["agentId"], "workspace": "/ws", "file": record}
        if method == ocp.M_AGENTS_FILES_SET:
            name = params["name"]
            if name in self.conflict_on:
                # Đúng hình dạng lỗi của upstream.
                raise OpenClawProtocolError(
                    "config conflict",
                    {"code": "INVALID_REQUEST",
                     "details": {"type": ocp.ERR_AGENT_FILE_CONFLICT,
                                 "currentHash": OTHER_HASH}})
            self.files[name] = {"content": params["content"], "hash": GOOD_HASH,
                                "missing": False}
            return {"ok": True, "agentId": params["agentId"], "workspace": "/ws",
                    "file": {"name": name, "hash": GOOD_HASH,
                             "size": len(params["content"])}}
        return {}

    def sent(self, method):
        return [p for m, p in self.calls if m == method]


def service(db, gateway):
    return sp.SeatProfileService(db, gateway)


# ------------------------------------------------------------- WP-2.1: đọc

@pytest.mark.asyncio
async def test_profile_merges_three_sources_and_labels_each_one(db, org):
    agent, member = make_seat(db, org)
    gw = FakeGateway()
    out = await service(db, gw).read(agent.id, org[0].id)

    # database
    assert out["seat"]["name"] == "Nina"
    assert out["seat"]["department"] == "Điều hành"
    assert out["seat"]["manager"] == "Long"
    # gateway
    assert out["identity"]["name"] == "Nina"
    assert out["config"]["effective"]["model"] == "cometapi/gpt-4o-mini"
    assert len(out["files"]) == 5
    # và mỗi nhóm nói rõ nguồn của nó
    assert out["sources"]["seat"] == "db"
    assert out["sources"]["files"] == "gateway"
    assert out["sources"]["config"] == "gateway"


@pytest.mark.asyncio
async def test_files_carry_the_hash_needed_to_write_back(db, org):
    """WP-2.2 không ghi được nếu WP-2.1 không trả hash ra ngoài."""
    agent, _ = make_seat(db, org)
    out = await service(db, FakeGateway()).read(agent.id, org[0].id)
    soul = next(f for f in out["files"] if f["name"] == "SOUL.md")
    assert len(soul["hash"]) == ocp.AGENT_FILE_HASH_LENGTH


@pytest.mark.asyncio
async def test_missing_memory_file_is_reported_as_expected_absent(db, org):
    """MEMORY.md chưa có nghĩa là chưa học được gì — không phải lỗi tải."""
    agent, _ = make_seat(db, org)
    out = await service(db, FakeGateway()).read(agent.id, org[0].id)
    memory = next(f for f in out["files"] if f["name"] == "MEMORY.md")
    assert memory["missing"] is True and memory["expected_absent"] is True
    assert not any("MEMORY.md" in w for w in out["warnings"])


@pytest.mark.asyncio
async def test_seat_missing_from_the_gateway_roster_is_flagged_loudly(db, org):
    """Lỗi đã gặp thật ở ask_nina: tin database mà không hỏi gateway."""
    agent, _ = make_seat(db, org, runtime_id="ghost")
    out = await service(db, FakeGateway(roster=("dev",))).read(agent.id, org[0].id)
    assert out["roster_match"] is False
    assert any("gateway không có agent nào tên vậy" in w for w in out["warnings"])


@pytest.mark.asyncio
async def test_gateway_outage_still_returns_the_database_half(db, org):
    """Màn hình nhân sự không được trắng xoá vì gateway đang khởi động lại."""
    agent, _ = make_seat(db, org)

    class Dead(FakeGateway):
        async def list_agents(self):
            raise RuntimeError("connection refused")

        async def rpc(self, method, params=None):
            raise RuntimeError("connection refused")

    out = await service(db, Dead()).read(agent.id, org[0].id)
    assert out["seat"]["name"] == "Nina"
    assert out["roster_match"] is None
    assert len(out["warnings"]) >= 2


@pytest.mark.asyncio
async def test_seat_without_runtime_id_says_so_instead_of_calling_the_gateway(db, org):
    agent, _ = make_seat(db, org, runtime_id="")
    gw = FakeGateway()
    out = await service(db, gw).read(agent.id, org[0].id)
    assert out["roster_match"] is False
    assert gw.calls == [], "không có runtime_agent_id thì đừng hỏi gateway"


@pytest.mark.asyncio
async def test_over_budget_file_warns_about_silent_truncation(db, org):
    agent, _ = make_seat(db, org)
    gw = FakeGateway()
    gw.files["SOUL.md"] = {"content": "x" * 25_000, "hash": GOOD_HASH, "missing": False}
    out = await service(db, gw).read(agent.id, org[0].id)

    soul = next(f for f in out["files"] if f["name"] == "SOUL.md")
    assert soul["over_budget"] is True and soul["max_chars"] == 20_000
    assert any("cắt bớt khi dựng prompt" in w for w in out["warnings"])


@pytest.mark.asyncio
async def test_user_md_has_a_smaller_budget_than_the_others(db, org):
    """4 000 chứ không phải 20 000 — chỗ rất dễ bỏ sót khi làm UI."""
    agent, _ = make_seat(db, org)
    gw = FakeGateway()
    gw.files["USER.md"] = {"content": "y" * 5_000, "hash": GOOD_HASH, "missing": False}
    out = await service(db, gw).read(agent.id, org[0].id)

    user = next(f for f in out["files"] if f["name"] == "USER.md")
    assert user["max_chars"] == 4_000 and user["over_budget"] is True
    soul = next(f for f in out["files"] if f["name"] == "SOUL.md")
    assert soul["max_chars"] == 20_000


@pytest.mark.asyncio
async def test_total_budget_is_checked_even_when_each_file_fits(db, org):
    agent, _ = make_seat(db, org)
    gw = FakeGateway()
    # Ba file đúng bằng hạn mức mỗi file (20 000), cộng USER.md đúng hạn mức
    # riêng của nó (4 000): từng file đều hợp lệ, tổng 64 000 thì không.
    for name in ("IDENTITY.md", "SOUL.md", "AGENTS.md"):
        gw.files[name] = {"content": "z" * 20_000, "hash": GOOD_HASH, "missing": False}
    gw.files["USER.md"] = {"content": "y" * 4_000, "hash": GOOD_HASH, "missing": False}
    out = await service(db, gw).read(agent.id, org[0].id)

    assert all(not f["over_budget"] for f in out["files"]), "từng file đều trong hạn mức"
    assert out["budget"]["total_chars"] == 64_000
    assert out["budget"]["over_budget"] is True
    assert any("hạn mức chung" in w for w in out["warnings"])


@pytest.mark.asyncio
async def test_shipped_sample_soul_is_detected(db, org):
    """Phát hiện thật: seat tên Nina nhưng SOUL.md vẫn là bản mẫu C-3PO."""
    agent, _ = make_seat(db, org)
    out = await service(db, FakeGateway()).read(agent.id, org[0].id)
    soul = next(f for f in out["files"] if f["name"] == "SOUL.md")
    assert soul["looks_like_shipped_sample"] is True
    identity = next(f for f in out["files"] if f["name"] == "IDENTITY.md")
    assert identity["looks_like_shipped_sample"] is False


@pytest.mark.asyncio
async def test_profile_does_not_leak_across_organizations(db, org):
    agent, _ = make_seat(db, org)
    other = Organization(name="Rival", slug="rival-wp2")
    db.add(other); db.commit(); db.refresh(other)
    with pytest.raises(sp.SeatError) as exc:
        await service(db, FakeGateway()).read(agent.id, other.id)
    assert exc.value.reason == "not_found"


@pytest.mark.asyncio
async def test_config_separates_seat_values_from_inherited_defaults(db, org):
    agent, _ = make_seat(db, org)
    out = await service(db, FakeGateway()).read(agent.id, org[0].id)
    assert "maxConcurrent" in out["config"]["inherited_keys"]
    assert "model" not in out["config"]["inherited_keys"]


# ------------------------------------------------- WP-2.2: ghi file (tab 1-3)

@pytest.mark.asyncio
async def test_writing_a_file_sends_expected_hash(db, org):
    agent, _ = make_seat(db, org)
    gw = FakeGateway()
    out = await service(db, gw).write_file(
        agent.id, org[0].id, name="SOUL.md", content="# Nina\nNói ngắn, thẳng.\n",
        expected_hash=GOOD_HASH)

    assert out["ok"] is True and out["conditional"] is True
    sent = gw.sent(ocp.M_AGENTS_FILES_SET)[0]
    assert sent["expectedHash"] == GOOD_HASH
    assert sent["name"] == "SOUL.md" and sent["agentId"] == "dev"


@pytest.mark.asyncio
async def test_stale_hash_becomes_a_conflict_carrying_the_current_hash(db, org):
    """Chốt chính của WP-2.2: hai người sửa cùng lúc, người sau bị chặn.

    Upstream trả `INVALID_REQUEST` với `details.type = agent_file_conflict` và
    `details.currentHash`. Service phải dịch thành lỗi có `current_hash` để UI
    nói được "ai đó vừa sửa, tải lại" — chứ không phải ném một chuỗi lỗi thô.
    """
    agent, _ = make_seat(db, org)
    gw = FakeGateway(conflict_on=("SOUL.md",))

    with pytest.raises(sp.SeatFileConflict) as exc:
        await service(db, gw).write_file(agent.id, org[0].id, name="SOUL.md",
                                         content="bản mới", expected_hash=GOOD_HASH)

    assert exc.value.reason == "file_conflict"
    assert exc.value.details["current_hash"] == OTHER_HASH
    assert "Tải lại" in str(exc.value)


@pytest.mark.asyncio
async def test_missing_hash_is_refused_unless_force(db, org):
    agent, _ = make_seat(db, org)
    gw = FakeGateway()
    with pytest.raises(sp.SeatError) as exc:
        await service(db, gw).write_file(agent.id, org[0].id, name="SOUL.md",
                                        content="x", expected_hash=None)
    assert exc.value.reason == "hash_required"
    assert gw.sent(ocp.M_AGENTS_FILES_SET) == []

    out = await service(db, gw).write_file(agent.id, org[0].id, name="SOUL.md",
                                          content="x", expected_hash=None, force=True)
    assert out["conditional"] is False
    assert "expectedHash" not in gw.sent(ocp.M_AGENTS_FILES_SET)[0]


@pytest.mark.asyncio
async def test_over_budget_write_is_refused_not_truncated(db, org):
    """Từ chối, chứ không cắt hộ: cắt hộ là lặp lại đúng hành vi âm thầm."""
    agent, _ = make_seat(db, org)
    gw = FakeGateway()
    with pytest.raises(sp.SeatError) as exc:
        await service(db, gw).write_file(agent.id, org[0].id, name="SOUL.md",
                                        content="x" * 20_001, expected_hash=GOOD_HASH)
    assert exc.value.reason == "over_budget"
    assert exc.value.details["max_chars"] == 20_000
    assert gw.sent(ocp.M_AGENTS_FILES_SET) == []


@pytest.mark.asyncio
async def test_user_md_write_uses_its_own_smaller_budget(db, org):
    agent, _ = make_seat(db, org)
    gw = FakeGateway()
    with pytest.raises(sp.SeatError) as exc:
        await service(db, gw).write_file(agent.id, org[0].id, name="USER.md",
                                        content="y" * 4_001, expected_hash=GOOD_HASH)
    assert exc.value.details["max_chars"] == 4_000


@pytest.mark.asyncio
async def test_files_outside_the_bootstrap_set_are_refused(db, org):
    """DREAMS.md thuộc agents.workspace.get, không thuộc namespace này."""
    agent, _ = make_seat(db, org)
    gw = FakeGateway()
    for name in ("DREAMS.md", "../../etc/passwd", "openclaw.json"):
        with pytest.raises(sp.SeatError) as exc:
            await service(db, gw).write_file(agent.id, org[0].id, name=name,
                                            content="x", expected_hash=GOOD_HASH)
        assert exc.value.reason == "unsupported_file"
    assert gw.sent(ocp.M_AGENTS_FILES_SET) == []


@pytest.mark.asyncio
async def test_write_is_tenant_scoped(db, org):
    agent, _ = make_seat(db, org)
    other = Organization(name="Rival", slug="rival-write")
    db.add(other); db.commit(); db.refresh(other)
    gw = FakeGateway()
    with pytest.raises(sp.SeatError) as exc:
        await service(db, gw).write_file(agent.id, other.id, name="SOUL.md",
                                        content="x", expected_hash=GOOD_HASH)
    assert exc.value.reason == "not_found"
    assert gw.calls == []


# ----------------------------------------------- WP-2.2: ghi config (tab 4-6)

@pytest.mark.asyncio
async def test_config_write_targets_only_this_seat(db, org):
    agent, _ = make_seat(db, org)
    gw = FakeGateway()
    out = await service(db, gw).write_config(
        agent.id, org[0].id, tab="capability",
        values={"thinkingDefault": "high"}, dry_run=True)

    import json
    raw = json.loads(out["params"]["raw"])
    assert raw == {"agents": {"entries": {"dev": {"thinkingDefault": "high"}}}}
    # Không được chạm agents.defaults: sửa defaults là sửa cho cả công ty.
    assert "defaults" not in raw["agents"]


@pytest.mark.asyncio
async def test_a_tab_cannot_write_keys_that_belong_to_another_tab(db, org):
    """Chặn ở server. Frontend không đáng tin, đó là lý do có danh sách đóng."""
    agent, _ = make_seat(db, org)
    gw = FakeGateway()
    with pytest.raises(sp.SeatError) as exc:
        await service(db, gw).write_config(
            agent.id, org[0].id, tab="capability",
            values={"thinkingDefault": "high", "tools.allow": ["exec"]})

    assert exc.value.reason == "key_not_in_tab"
    assert exc.value.details["rejected"] == ["tools.allow"]
    assert gw.sent(ocp.M_CONFIG_PATCH) == []


@pytest.mark.asyncio
async def test_array_config_keys_are_authorized_as_replace_paths(db, org):
    """`skills` là mảng: ghi lại là thay, nên phải khai replacePaths."""
    agent, _ = make_seat(db, org)
    gw = FakeGateway()
    out = await service(db, gw).write_config(
        agent.id, org[0].id, tab="permission", values={"skills": ["a"]})

    assert out["applied"] is True
    assert gw.sent(ocp.M_CONFIG_PATCH)[0]["replacePaths"] == ["agents.entries.dev.skills"]


@pytest.mark.asyncio
async def test_dotted_keys_become_nested_config(db, org):
    agent, _ = make_seat(db, org)
    gw = FakeGateway()
    out = await service(db, gw).write_config(
        agent.id, org[0].id, tab="permission",
        values={"sandbox.mode": "all", "sandbox.workspaceAccess": "rw"}, dry_run=True)

    import json
    seat = json.loads(out["params"]["raw"])["agents"]["entries"]["dev"]
    assert seat["sandbox"] == {"mode": "all", "workspaceAccess": "rw"}


@pytest.mark.asyncio
async def test_unknown_tab_is_refused(db, org):
    agent, _ = make_seat(db, org)
    with pytest.raises(sp.SeatError) as exc:
        await service(db, FakeGateway()).write_config(
            agent.id, org[0].id, tab="personality", values={"x": 1})
    # Tab Tính cách ghi FILE, không ghi config — nói rõ thay vì "unknown key".
    assert exc.value.reason == "unknown_tab"
    assert "capability" in exc.value.details["writable_tabs"]


@pytest.mark.asyncio
async def test_config_error_from_the_registry_is_surfaced_not_swallowed(db, org):
    """Chốt của WP-1.2 phải còn hiệu lực khi gọi qua tầng seat."""
    agent, _ = make_seat(db, org)
    gw = FakeGateway()
    with pytest.raises(sp.SeatError) as exc:
        # skills hiện có ["a","b"]; ghi ["a"] là mất phần tử -> cần replacePaths,
        # và service seat khai nó tự động, nên ta thử một mảng KHÁC không nằm
        # trong ARRAY_CONFIG_KEYS để chốt của registry lộ ra.
        await service(db, gw).write_config(
            agent.id, org[0].id, tab="budget",
            values={"heartbeat.activeHours.start": "09:00"}, allow_restart=False,
            base_hash="")
    # baseHash rỗng + config đã tồn tại -> registry từ chối, và lý do đi nguyên
    # vẹn ra ngoài thay vì thành "400 bad request" vô nghĩa.
    assert exc.value.reason == "missing_base_hash"


@pytest.mark.asyncio
async def test_tab_map_tells_the_ui_which_tabs_write_files_vs_config(db, org):
    agent, _ = make_seat(db, org)
    out = await service(db, FakeGateway()).read(agent.id, org[0].id)
    tabs = out["tabs"]
    assert tabs["personality"]["files"] == ["SOUL.md"]
    assert tabs["personality"]["config_keys"] == []
    assert "thinkingDefault" in tabs["capability"]["config_keys"]
    assert tabs["capability"]["files"] == []


@pytest.mark.asyncio
async def test_model_drift_between_db_and_gateway_is_surfaced(db, org):
    """Đo được lúc nghiệm thu: DB ghi "GPT-4.1", gateway chạy gpt-4o-mini.

    Cột `agents.model` do seed script đặt và không ai cập nhật lại, nên mọi báo
    cáo dựa vào nó đang nói về một model không chạy. Hồ sơ phải nói ra chỗ lệch
    chứ không âm thầm chọn một bên.
    """
    agent, _ = make_seat(db, org)
    agent.model = "GPT-4.1"
    db.add(agent); db.commit()

    out = await service(db, FakeGateway()).read(agent.id, org[0].id)
    assert out["model_drift"] == {"db": "GPT-4.1",
                                  "gateway": "cometapi/gpt-4o-mini", "match": False}
    assert any("gateway đang chạy" in w for w in out["warnings"])


@pytest.mark.asyncio
async def test_no_drift_warning_when_the_two_models_agree(db, org):
    agent, _ = make_seat(db, org)
    agent.model = "cometapi/gpt-4o-mini"
    db.add(agent); db.commit()

    out = await service(db, FakeGateway()).read(agent.id, org[0].id)
    assert out["model_drift"]["match"] is True
    assert not any("gateway đang chạy" in w for w in out["warnings"])
