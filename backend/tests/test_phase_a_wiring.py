"""Giai đoạn A — cho agent sống thật: B1, B2, B4, B7, provision (B3), nối dây
gateway (B5 MCP, B9 embedding, tầng model) và định tuyến model.

Database thật (SQLite in-memory). Gateway là fake ghi lại lời gọi, trả payload
đúng hình dạng đã đo trên OpenClaw 2026.9.8 (xem docs/research/agent-audit.md).
"""
import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
import app.models  # noqa: F401
from app.models.auth import APIKey
from app.models.entities import Agent, Company, Department, Member, Organization
from app.runtime import openclaw_protocol as ocp
from app.services import agent_hr, model_routing, seat_profile, seat_provision

PRINCIPAL = SimpleNamespace(user_id=None)


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)()
    yield session
    session.close()


@pytest.fixture()
def org(db):
    o = Organization(name="Gốm", slug="gom-a"); db.add(o); db.commit()
    c = Company(organization_id=o.id, name="Tiệm Gốm Mộc", status="active"); db.add(c); db.commit()
    d = Department(company_id=c.id, name="Bán hàng", status="active"); db.add(d); db.commit()
    return o, c, d


def seat(db, org, rid, name, role, model="GPT-4.1", lifecycle="active"):
    o, c, d = org
    m = Member(organization_id=o.id, company_id=c.id, department_id=d.id, name=name,
               member_type="agent", role=role, status="active")
    db.add(m); db.commit()
    a = Agent(member_id=m.id, runtime_provider="openclaw", runtime_agent_id=rid,
              lifecycle=lifecycle, model=model)
    db.add(a); db.commit()
    return a, m


ENGLISH_SOUL = "# SOUL.md - The Soul of C-3PO\nI am Clawd's Third Protocol Observer.\n"


class FakeGateway:
    def __init__(self, roster=("nina", "cskh"), files=None, config=None):
        self.roster = list(roster)
        self.files = files if files is not None else {}
        self.calls: list[tuple[str, dict]] = []
        self.config = config if config is not None else {
            "models": {"providers": {"custom": {
                "baseUrl": "https://api.cometapi.com/v1",
                "apiKey": {"source": "file", "provider": "providerkey", "id": "__OPENCLAW_REDACTED__"},
                "models": [{"id": "gpt-4.1-mini", "name": "gpt-4.1-mini"}]}}},
            "agents": {"entries": {"nina": {"tools": {"deny": ["browser"]}}}},
        }

    async def list_agents(self):
        return [{"id": r} for r in self.roster]

    async def create_agent(self, rid, config):
        self.calls.append(("create_agent", {"rid": rid, **config}))
        if rid not in self.roster:
            self.roster.append(rid)
            return {"id": rid, "status": "created", "bound": True}
        return {"id": rid, "status": "bound", "bound": True}

    async def rpc(self, method, params=None):
        params = params or {}
        self.calls.append((method, params))
        if method == ocp.M_AGENTS_FILES_GET:
            key = (params["agentId"], params["name"])
            if key not in self.files:
                return {"file": {"missing": True}}
            content = self.files[key]
            return {"file": {"content": content, "hash": agent_hr.sha(content)}}
        if method == ocp.M_AGENTS_FILES_SET:
            self.files[(params["agentId"], params["name"])] = params["content"]
            return {"file": {"hash": agent_hr.sha(params["content"])}}
        if method == ocp.M_CONFIG_GET:
            return {"config": self.config, "hash": "h1"}
        if method == ocp.M_CONFIG_SCHEMA_LOOKUP:
            return {"path": params["path"], "reloadKind": "hot"}
        if method == ocp.M_CONFIG_PATCH:
            return {"changedPaths": ["x"]}
        return {"ok": True}

    def sent(self, method):
        return [p for m, p in self.calls if m == method]


# ------------------------------------------------------------------ B1

def test_display_labels_are_not_model_refs():
    assert not agent_hr.is_runtime_model_ref("GPT-4.1")
    assert not agent_hr.is_runtime_model_ref("Gemini 1.5")
    assert agent_hr.is_runtime_model_ref("custom/gpt-5-mini")
    assert agent_hr.is_runtime_model_ref("custom/claude-haiku-4-5-20251001")


@pytest.mark.asyncio
async def test_agents_update_refuses_to_push_a_display_label(db, org):
    agent, _ = seat(db, org, "nina", "Nina", "Chief of Staff")
    gw = FakeGateway()
    with pytest.raises(ValueError, match="nhãn hiển thị"):
        await agent_hr._agents_update(db, gw, agent, {"agentId": "nina", "model": "GPT-4.1"}, None)
    assert gw.sent(ocp.M_AGENTS_UPDATE) == []


# ------------------------------------------------------------------ B4

def test_seat_config_tabs_only_hold_per_agent_keys_valid_in_9_8():
    invalid = {"timeoutSeconds", "compaction.enabled", "compaction.notifyUser", "maxConcurrent",
               "subagents.maxConcurrent", "subagents.maxChildrenPerAgent"}
    every = {k for keys in seat_profile.CONFIG_TABS.values() for k in keys}
    assert not (every & invalid)
    assert {"utilityModel", "heartbeat.model"} <= every


# ------------------------------------------------------------------ B2

@pytest.mark.asyncio
async def test_ask_nina_prefers_nina_and_reports_model_errors(db, org, monkeypatch):
    from app.runtime.openclaw_native import NativeOpenClawRuntime
    from app.services import v36_insights
    seat(db, org, "cskh", "Lan", "CSKH")
    seat(db, org, "nina", "Nina", "Chief of Staff")
    rt = NativeOpenClawRuntime.__new__(NativeOpenClawRuntime)

    async def list_agents():
        return [{"id": "cskh"}, {"id": "nina"}]

    async def chat_stream(agent_id, message, *, session_key=None, timeout_seconds=120):
        rt.who = agent_id
        yield {"kind": "error", "message": "LLM request failed (authentication failed, HTTP 401)"}

    rt.list_agents, rt.chat_stream = list_agents, chat_stream
    monkeypatch.setattr("app.runtime.factory.get_runtime", lambda: rt)
    out = await v36_insights.ask_nina(db, org[0].id, message="chào")
    assert rt.who == "nina"
    assert out["answered"] is False and "401" in out["reason"]


# ------------------------------------------------------------------ B3 + B7

@pytest.mark.asyncio
async def test_provision_creates_missing_agent_and_replaces_english_samples(db, org):
    agent, _ = seat(db, org, "cskh", "Lan", "Nhân viên CSKH", lifecycle="runtime_missing")
    gw = FakeGateway(roster=("nina",), files={
        ("cskh", "SOUL.md"): ENGLISH_SOUL,
        ("cskh", "MEMORY.md"): "- 2026-10-01: khách A thích giao buổi sáng\n",
    })
    out = await seat_provision.provision_seat(db, PRINCIPAL, org[0].id, gw, agent.id)
    assert ("create_agent", {"rid": "cskh", "model": ""}) in gw.calls
    db.refresh(agent)
    assert agent.lifecycle == "active"
    assert "C-3PO" not in gw.files[("cskh", "SOUL.md")]
    assert "Lan" in gw.files[("cskh", "SOUL.md")]
    assert out["files"]["SOUL.md"]["replaced_untracked"] is True
    # Ký ức agent tự ghi không bị đè.
    assert gw.files[("cskh", "MEMORY.md")].startswith("- 2026-10-01")
    assert out["files"]["MEMORY.md"]["reason"] == "agent_memory_kept"
    # Nhãn hiển thị không được đẩy làm model.
    assert all("model" not in p for p in gw.sent(ocp.M_AGENTS_UPDATE))


@pytest.mark.asyncio
async def test_untracked_english_sample_counts_as_drift(db, org):
    agent, _ = seat(db, org, "cskh", "Lan", "CSKH")
    gw = FakeGateway(files={("cskh", "SOUL.md"): ENGLISH_SOUL})
    out = await agent_hr.drift(db, org[0].id, gw, agent.id)
    soul = next(f for f in out["files"] if f["name"] == "SOUL.md")
    assert soul["status"] == "untracked" and soul["counts_as_drift"] is True
    assert out["in_sync"] is False


# ------------------------------------------------------------------ B5 + B9 + tầng

@pytest.mark.asyncio
async def test_wire_gateway_one_patch_with_seat_isolated_mcp_models_and_memory(db, org):
    nina, nina_m = seat(db, org, "nina", "Nina", "Chief of Staff")
    org[2].head_member_id = nina_m.id; db.add(org[2]); db.commit()   # Nina là trưởng phòng → lead
    cskh, _ = seat(db, org, "cskh", "Lan", "Nhân viên CSKH")
    seat(db, org, "ghost", "Ma", "CSKH")                   # không có trên gateway
    gw = FakeGateway()
    out = await seat_provision.wire_gateway(db, PRINCIPAL, org[0].id, gw)
    patches = gw.sent(ocp.M_CONFIG_PATCH)
    assert len(patches) == 1 and patches[0]["baseHash"] == "h1"
    tree = json.loads(patches[0]["raw"])
    servers = tree["mcp"]["servers"]
    assert set(servers) == {"cc-nina", "cc-cskh"}
    assert servers["cc-nina"]["headers"]["X-ClawCompany-Seat"] == "nina"
    assert servers["cc-nina"]["toolFilter"] == {"include": ["company_*"]}
    # Mỗi ghế chỉ thấy máy chủ MCP của chính mình; deny cũ được giữ.
    assert tree["agents"]["entries"]["nina"]["tools"]["deny"] == ["browser", "cc-cskh__*"]
    # Ghế thừa hành: tool công ty mặc định "Tắt" thành deny ở gateway, và không có shell.
    assert tree["agents"]["entries"]["cskh"]["tools"]["deny"] == [
        "cc-nina__*", "cc-cskh__company_budget_check", "cc-cskh__company_plan_submit",
        "cc-cskh__company_task_assign", "exec", "process"]
    assert tree["agents"]["entries"]["cskh"]["tools"]["elevated"] == {"enabled": False}
    assert "agents.entries.nina.tools.deny" in patches[0]["replacePaths"]
    # Key riêng từng ghế, đã băm trong DB, không trả ra ngoài.
    key = servers["cc-nina"]["headers"]["X-API-Key"]
    row = db.query(APIKey).filter(APIKey.member_id == nina_m.id, APIKey.is_active == True).one()  # noqa: E712
    assert row.key_prefix == key[:12] and key not in json.dumps(out)
    # Tầng model: quản lý T3, thừa hành T2, việc vặt + heartbeat T1, có fallback.
    assert tree["agents"]["entries"]["nina"]["model"]["primary"] == "custom/gemini-3.8-flash"
    assert tree["agents"]["entries"]["cskh"]["model"]["primary"] == "custom/gpt-5-mini"
    assert tree["agents"]["entries"]["cskh"]["utilityModel"] == "custom/gpt-5-nano"
    assert tree["agents"]["entries"]["cskh"]["heartbeat"]["model"] == "custom/gpt-5-nano"
    ids = {m["id"] for m in tree["models"]["providers"]["custom"]["models"]}
    assert {"gpt-4.1-mini", "gpt-5-nano", "gpt-5-mini", "gemini-3.8-flash", "claude-sonnet-5"} <= ids
    # B9: embedding đi qua cùng endpoint + SecretRef, không bao giờ là key thô.
    remote = tree["memory"]["search"]["remote"]
    assert remote["baseUrl"] == "https://api.cometapi.com/v1"
    assert remote["apiKey"] == {"source": "file", "provider": "providerkey", "id": "value"}
    assert out["skipped_not_on_gateway"] == ["ghost"]
    db.refresh(nina)
    assert nina.model == "custom/gemini-3.8-flash"


@pytest.mark.asyncio
async def test_rewiring_rotates_the_seat_key(db, org):
    _, m = seat(db, org, "nina", "Nina", "Chief of Staff")
    gw = FakeGateway(roster=("nina",))
    await seat_provision.wire_gateway(db, PRINCIPAL, org[0].id, gw)
    await seat_provision.wire_gateway(db, PRINCIPAL, org[0].id, gw)
    rows = db.query(APIKey).filter(APIKey.member_id == m.id).all()
    assert len(rows) == 2 and sum(r.is_active for r in rows) == 1


@pytest.mark.asyncio
async def test_dry_run_writes_nothing(db, org):
    agent, _ = seat(db, org, "nina", "Nina", "Chief of Staff")
    gw = FakeGateway(roster=("nina",))
    out = await seat_provision.wire_gateway(db, PRINCIPAL, org[0].id, gw, dry_run=True)
    assert out["dry_run"] is True and gw.sent(ocp.M_CONFIG_PATCH) == []
    assert db.query(APIKey).count() == 0
    db.refresh(agent)
    assert agent.model == "GPT-4.1"


# ------------------------------------------------------------------ định tuyến

@pytest.mark.parametrize("title,expected", [
    ("Tóm tắt phản hồi khách tuần này", "T1"),          # đọc nội bộ
    ("Tóm tắt tình trạng đơn hàng gửi lại khách hàng", "T3"),  # ra ngoài
    ("Tóm tắt câu hỏi của khách hàng", "T2"),          # khách sẽ đọc → không T1
    ("Phân loại email đến", "T1"),
    ("Soạn bài giới thiệu men lam", "T2"),
    ("Lập kế hoạch khuyến mãi tháng 11", "T3"),
    ("Đề xuất chính sách giá bán sỉ", "T4"),
    ("Gửi email báo giá cho khách", "T3"),               # hành động ra ngoài
])
def test_rules_pick_the_cheapest_sufficient_tier(title, expected):
    assert model_routing.decide(title=title).tier == expected


def test_rework_escalates_at_most_one_tier_and_budget_caps_t4():
    d = model_routing.decide(title="Soạn bài", rework_count=5)
    assert (d.base_tier, d.tier, d.escalated) == ("T2", "T3", True)
    capped = model_routing.decide(title="Đề xuất chính sách giá", budget_state="warned")
    assert capped.tier == "T3"
    assert model_routing.decide(title="Phân loại", priority="critical").tier == "T3"
    assert model_routing.decide(title="Phân loại", pinned_tier="T4").tier == "T4"


@pytest.mark.asyncio
async def test_native_run_agent_patches_the_session_model_before_sending(monkeypatch):
    from app.runtime.openclaw_native import NativeOpenClawRuntime
    rt = NativeOpenClawRuntime.__new__(NativeOpenClawRuntime)
    calls = []

    async def _rpc(method, params=None):
        calls.append((method, params))
        return {"runId": "r1"} if method == ocp.M_CHAT_SEND else {}

    rt._rpc = _rpc
    await rt.run_agent("cskh", "việc", metadata={"company_task_id": 7, "model": "custom/gpt-5-mini"},
                       session_key="agent:cskh:company-task-7")
    methods = [m for m, _ in calls]
    assert methods == [ocp.M_SESSIONS_CREATE, ocp.M_SESSIONS_PATCH, ocp.M_CHAT_SEND]
    assert calls[1][1] == {"key": "agent:cskh:company-task-7", "model": "custom/gpt-5-mini"}
    assert "model" not in calls[2][1]


def test_api_key_cache_skips_bcrypt_but_respects_revocation(db, org, monkeypatch):
    from app.core import authz
    from app.core.security import pwd_context
    raw = "cc_" + "x" * 40
    row = APIKey(organization_id=org[0].id, name="k", key_prefix=raw[:12],
                 key_hash=pwd_context.hash(raw), scopes="[]")
    db.add(row); db.commit()
    authz._KEY_CACHE.clear()
    authz.get_principal(None, raw, db)
    calls = []
    monkeypatch.setattr(authz.pwd_context, "verify", lambda *a: calls.append(1) or False)
    assert authz.get_principal(None, raw, db).organization_id == org[0].id
    assert calls == []
    row.is_active = False; db.add(row); db.commit()
    with pytest.raises(HTTPException):
        authz.get_principal(None, raw, db)


@pytest.mark.asyncio
async def test_turning_a_tool_off_reaches_the_gateway_and_back(db, org):
    from app.services import tool_permissions
    _, m = seat(db, org, "nina", "Nina", "Chief of Staff")
    org[2].head_member_id = m.id; db.add(org[2]); db.commit()
    gw = FakeGateway(roster=("nina",))
    gw.config["mcp"] = {"servers": {"cc-nina": {}}}
    gw.config["agents"]["entries"]["nina"]["tools"]["deny"] = ["browser"]
    assert (await seat_provision.sync_tool_policy(db, org[0].id, gw)) == {"changed": []}
    tool_permissions.set_level(db, org[0].id, "company_message_send", "off", member_id=m.id)
    out = await seat_provision.sync_tool_policy(db, org[0].id, gw)
    tree = json.loads(gw.sent(ocp.M_CONFIG_PATCH)[-1]["raw"])
    assert tree["agents"]["entries"]["nina"]["tools"]["deny"] == ["browser", "cc-nina__company_message_send"]
    assert out["changed"] == ["nina"]
    gw.config["agents"]["entries"]["nina"]["tools"]["deny"] = tree["agents"]["entries"]["nina"]["tools"]["deny"]
    tool_permissions.set_level(db, org[0].id, "company_message_send", "allowed", member_id=m.id)
    await seat_provision.sync_tool_policy(db, org[0].id, gw)
    tree = json.loads(gw.sent(ocp.M_CONFIG_PATCH)[-1]["raw"])
    assert tree["agents"]["entries"]["nina"]["tools"]["deny"] == ["browser"]


def test_weekly_report_counts_cost_per_accepted_output(db, org):
    from app.models import Project, Task
    from app.models.work_graph import TaskRun
    from app.models.v37 import TaskJournalEntry
    from app.services.company_event_bus import emit_event
    _, m = seat(db, org, "cskh", "Lan", "CSKH")
    p = Project(company_id=org[1].id, name="P", status="active"); db.add(p); db.commit()
    for i, (status, cost, rework) in enumerate([("done", 0.002, False), ("done", 0.004, True), ("todo", 0.001, False)]):
        t = Task(project_id=p.id, title=f"Việc {i}", status=status); db.add(t); db.commit()
        r = TaskRun(organization_id=org[0].id, task_id=t.id, member_id=m.id, cost_usd=cost); db.add(r); db.commit()
        if rework:
            db.add(TaskJournalEntry(organization_id=org[0].id, task_id=t.id, seq=1, kind="review",
                                    summary="trả về", outcome="rejected")); db.commit()
        emit_event(db, organization_id=org[0].id, event_type="model.routed", aggregate_type="task",
                   aggregate_id=str(t.id), payload={"tier": "T2", "task_run_id": r.id})
    out = model_routing.report(db, org[0].id)
    t2 = next(r for r in out["tiers"] if r["tier"] == "T2")
    assert (t2["runs"], t2["accepted"]) == (3, 1)
    assert t2["cost_usd"] == pytest.approx(0.007) and t2["cost_per_accepted_usd"] == pytest.approx(0.007)


@pytest.mark.asyncio
async def test_seat_chat_stream_talks_to_that_seat_only_inside_the_org(db, org, monkeypatch):
    from app.runtime.openclaw_native import NativeOpenClawRuntime
    from app.services import v36_insights
    agent, _ = seat(db, org, "cskh", "Lan", "CSKH")
    rt = NativeOpenClawRuntime.__new__(NativeOpenClawRuntime)

    async def list_agents():
        return [{"id": "cskh"}]

    async def chat_stream(agent_id, message, *, session_key=None, timeout_seconds=120):
        rt.who = (agent_id, session_key)
        yield {"kind": "final", "text": "Dạ chào anh"}

    rt.list_agents, rt.chat_stream = list_agents, chat_stream
    monkeypatch.setattr("app.runtime.factory.get_runtime", lambda: rt)
    frames = [f async for f in v36_insights.ask_nina_stream(sessionmaker_ctx(db), org[0].id, message="chào",
                                                            seat_agent_id=agent.id)]
    assert rt.who == ("cskh", "agent:cskh:main") and "Dạ chào anh" in frames[-1]
    other = [f async for f in v36_insights.ask_nina_stream(sessionmaker_ctx(db), org[0].id + 99,
                                                           message="chào", seat_agent_id=agent.id)]
    assert "Không thấy" in other[-1]


def sessionmaker_ctx(db):
    from contextlib import contextmanager

    @contextmanager
    def _f():
        yield db
    return _f


@pytest.mark.asyncio
async def test_rewiring_does_not_touch_memory_search_when_already_right(db, org):
    seat(db, org, "nina", "Nina", "Chief of Staff")
    gw = FakeGateway(roster=("nina",))
    await seat_provision.wire_gateway(db, PRINCIPAL, org[0].id, gw, allow_restart=True)
    tree = json.loads(gw.sent(ocp.M_CONFIG_PATCH)[-1]["raw"])
    gw.config["memory"] = tree["memory"]
    out = await seat_provision.wire_gateway(db, PRINCIPAL, org[0].id, gw, allow_restart=False)
    assert out["memory"] == "đã đúng, không đổi"
    assert "memory" not in json.loads(gw.sent(ocp.M_CONFIG_PATCH)[-1]["raw"])
