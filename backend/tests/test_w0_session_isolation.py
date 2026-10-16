"""W0 — cách ly phiên giữa agent trên gateway dùng chung (bên cho thuê / bên thuê / hai tổ chức).

Đo trên gateway thật 2026.9.8 (17/10/2026, config.schema.lookup + config.get, xem docs/work-module-review.md §W0):
  * ``tools.sessions.visibility`` mặc định ``all`` (mọi phiên trên gateway), chỉ có ở gốc ``tools``;
  * ``tools.agentToAgent.enabled`` mặc định ``true``, ``allow`` rỗng = mọi cặp;
  * ``agents.entries.*.subagents.allowAgents`` mặc định chỉ chính agent đó.
Probe sống trước khi sửa: phiên của CSKH đọc được transcript của Trưởng kho qua ``sessions_history``.

Test hành vi: gateway giả GHI patch vào config như gateway thật (merge + replacePaths), rồi một bộ đánh giá
quyền với tới phiên theo đúng ngữ nghĩa docs 9.8 (``_can_reach``) trả lời "A có liệt kê/đọc được phiên B không".
Bằng chứng thật là probe ``/tools/invoke`` trên VM (work/w0/vm_w0_probe.py).
"""
import copy
import json
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.db.base import Base
from app.models.entities import Agent, Company, Department, Member, Organization
from app.runtime import openclaw_protocol as ocp
from app.services import seat_provision

PRINCIPAL = SimpleNamespace(user_id=None)


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    s = sessionmaker(bind=engine, autoflush=False, autocommit=False)()
    yield s
    s.close()


def _org(db, slug):
    o = Organization(name=slug, slug=slug); db.add(o); db.commit()
    c = Company(organization_id=o.id, name=f"Cty {slug}", status="active"); db.add(c); db.commit()
    d = Department(company_id=c.id, name="CSKH", status="active"); db.add(d); db.commit()
    return o, c, d


def _seat(db, org, rid, role="Nhân viên CSKH"):
    o, c, d = org
    m = Member(organization_id=o.id, company_id=c.id, department_id=d.id, name=rid, member_type="agent",
               role=role, status="active")
    db.add(m); db.commit()
    a = Agent(member_id=m.id, runtime_provider="openclaw", runtime_agent_id=rid, lifecycle="active", model="x")
    db.add(a); db.commit()
    return a, m


def _merge(dst: dict, src: dict, prefix: str, replace: set[str]):
    for k, v in src.items():
        path = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict) and isinstance(dst.get(k), dict) and path not in replace:
            _merge(dst[k], v, path, replace)
        else:
            dst[k] = copy.deepcopy(v)


class Gateway:
    """Gateway giả có trạng thái: config.patch merge vào config (như 9.8), hash đổi sau mỗi lần ghi."""

    def __init__(self, roster, config=None):
        self.roster = list(roster)
        self.config = config if config is not None else {"agents": {"entries": {}}}
        self.version = 1
        self.patches: list[dict] = []

    async def list_agents(self):
        return [{"id": r} for r in self.roster]

    async def rpc(self, method, params=None):
        params = params or {}
        if method == ocp.M_CONFIG_GET:
            return {"config": copy.deepcopy(self.config), "hash": f"h{self.version}"}
        if method == ocp.M_CONFIG_SCHEMA_LOOKUP:
            return {"path": params["path"], "reloadKind": "hot"}
        if method == ocp.M_CONFIG_PATCH:
            assert params.get("baseHash") in (None, f"h{self.version}"), "baseHash cũ"
            tree = json.loads(params["raw"])
            self.patches.append(tree)
            _merge(self.config, tree, "", set(params.get("replacePaths") or []))
            self.version += 1
            return {"changedPaths": ["x"]}
        return {"ok": True}


def _can_reach(config: dict, requester: str, target: str, *, requester_session: str, target_session: str) -> bool:
    """Ngữ nghĩa docs 9.8 (gateway/config-tools/sessions-and-subagents): phiên của ``requester`` có nhắm được
    phiên ``target_session`` bằng sessions_list/history/send không (không xét con sub-agent)."""
    vis = ((config.get("tools") or {}).get("sessions") or {}).get("visibility") or "all"
    a2a = (config.get("tools") or {}).get("agentToAgent") or {}
    if requester_session == target_session:
        return True
    if vis == "self":
        return False
    if requester != target:
        if vis in ("agent", "tree"):
            return False
        if a2a.get("enabled", True) is False:
            return False
        allow = [x for x in (a2a.get("allow") or [])]
        if allow and not (requester in allow and target in allow):
            return False
        return True
    return vis in ("agent", "all") or vis == "tree" and requester_session.endswith(":main")


def _spawn_allowed(config: dict, requester: str, target: str) -> bool:
    entry = ((config.get("agents") or {}).get("entries") or {}).get(requester) or {}
    allow = (entry.get("subagents") or {}).get("allowAgents")
    if allow is None:
        allow = (((config.get("agents") or {}).get("defaults") or {}).get("subagents") or {}).get("allowAgents")
    if allow is None:
        return target == requester           # mặc định 9.8: chỉ chính mình
    return "*" in allow or target in allow


@pytest.mark.asyncio
async def test_default_gateway_leaks_and_isolation_closes_it_for_provider_and_renter(db):
    provider, renter = _org(db, "ben-cho-thue"), _org(db, "ben-thue")
    _seat(db, provider, "gom-cskh")
    _seat(db, renter, "thue-cskh")
    gw = Gateway(["gom-cskh", "thue-cskh", "main"],
                 config={"agents": {"defaults": {"subagents": {"allowAgents": ["*"]}}, "entries": {}}})
    a, b = "agent:gom-cskh:company-task-1", "agent:thue-cskh:company-task-9"
    # Trước: mặc định OpenClaw — bên thuê đọc được phiên bên cho thuê và spawn được agent của họ.
    assert _can_reach(gw.config, "thue-cskh", "gom-cskh", requester_session=b, target_session=a)
    assert _spawn_allowed(gw.config, "thue-cskh", "gom-cskh")
    rep = seat_provision.session_isolation_report(gw.config, ["gom-cskh", "thue-cskh"])
    assert rep["ok"] is False and rep["visibility"] is None and rep["agent_to_agent_enabled"] is None

    out = await seat_provision.ensure_session_isolation(db, gw)
    assert sorted(out["changed"]) == sorted([
        "tools.sessions.visibility", "tools.agentToAgent.enabled",
        "agents.entries.gom-cskh.subagents.allowAgents", "agents.entries.thue-cskh.subagents.allowAgents"])
    assert gw.config["tools"]["sessions"]["visibility"] == "self"
    assert gw.config["tools"]["agentToAgent"]["enabled"] is False
    for req, tgt, rs, ts in (("thue-cskh", "gom-cskh", b, a), ("gom-cskh", "thue-cskh", a, b)):
        assert not _can_reach(gw.config, req, tgt, requester_session=rs, target_session=ts)
        assert not _spawn_allowed(gw.config, req, tgt)
        assert _spawn_allowed(gw.config, req, req)              # sub-agent của chính mình vẫn được
    # Cùng một ghế, phiên việc khác (vd. A2A của khách khác) cũng không với tới: visibility=self.
    assert not _can_reach(gw.config, "gom-cskh", "gom-cskh", requester_session=a,
                          target_session="agent:gom-cskh:a2a-khach-khac")
    assert _can_reach(gw.config, "gom-cskh", "gom-cskh", requester_session=a, target_session=a)
    # Agent không phải của ClawCompany ("main") không bị đụng entry, chỉ chịu khoá gốc.
    assert "main" not in gw.config["agents"]["entries"]
    assert seat_provision.session_isolation_report(gw.config, ["gom-cskh", "thue-cskh"])["ok"] is True


@pytest.mark.asyncio
async def test_isolation_is_idempotent_and_repairs_drift(db):
    org = _org(db, "gom")
    _seat(db, org, "cskh")
    gw = Gateway(["cskh"])
    await seat_provision.ensure_session_isolation(db, gw)
    n = len(gw.patches)
    again = await seat_provision.ensure_session_isolation(db, gw)
    assert again["changed"] == [] and len(gw.patches) == n          # đã đúng → không ghi config
    # Có người nới tay trên gateway → lần sau kéo về, kể cả mảng allowAgents bị mở rộng.
    gw.config["tools"]["sessions"]["visibility"] = "all"
    gw.config["agents"]["entries"]["cskh"]["subagents"]["allowAgents"] = ["cskh", "nina"]
    fixed = await seat_provision.ensure_session_isolation(db, gw)
    assert sorted(fixed["changed"]) == ["agents.entries.cskh.subagents.allowAgents", "tools.sessions.visibility"]
    assert gw.config["tools"]["sessions"]["visibility"] == "self"
    assert gw.config["agents"]["entries"]["cskh"]["subagents"]["allowAgents"] == ["cskh"]


@pytest.mark.asyncio
async def test_wire_gateway_compiles_isolation_in_the_same_patch(db):
    org = _org(db, "gom")
    _seat(db, org, "nina", role="Chief of Staff")
    _seat(db, org, "cskh")
    gw = Gateway(["nina", "cskh"])
    out = await seat_provision.wire_gateway(db, PRINCIPAL, org[0].id, gw, models=False, memory=False)
    assert len(gw.patches) == 1
    tree = gw.patches[0]
    assert tree["tools"] == {"sessions": {"visibility": "self"}, "agentToAgent": {"enabled": False}}
    assert tree["agents"]["entries"]["nina"]["subagents"] == {"allowAgents": ["nina"]}
    assert tree["agents"]["entries"]["cskh"]["subagents"] == {"allowAgents": ["cskh"]}
    assert "tools.sessions.visibility" in out["session_isolation"]
    # Nối lại lần hai: khoá cách ly đã đúng → không gửi lại.
    await seat_provision.wire_gateway(db, PRINCIPAL, org[0].id, gw, models=False, memory=False)
    assert "tools" not in gw.patches[-1]
    assert "subagents" not in gw.patches[-1]["agents"]["entries"]["nina"]


@pytest.mark.asyncio
async def test_retired_seats_are_not_written_and_non_gateway_runtime_is_skipped(db):
    org = _org(db, "gom")
    a, _ = _seat(db, org, "cu")
    a.lifecycle = "retired"; db.add(a); db.commit()
    _seat(db, org, "moi")
    gw = Gateway(["cu", "moi"])
    out = await seat_provision.ensure_session_isolation(db, gw)
    assert "agents.entries.cu.subagents.allowAgents" not in out["changed"]
    assert "agents.entries.moi.subagents.allowAgents" in out["changed"]

    class Mock:
        pass
    assert (await seat_provision.ensure_session_isolation(db, Mock()))["skipped"]


@pytest.mark.asyncio
async def test_losing_a_concurrent_write_rereads_instead_of_failing(db):
    """Hai tiến trình API cùng khởi động: tiến trình thua baseHash đọc lại thấy đã đúng → không lỗi, không ghi lần 2."""
    org = _org(db, "gom")
    _seat(db, org, "cskh")
    gw = Gateway(["cskh"])

    class Racing(Gateway):
        def __init__(self, inner):
            self.inner, self.raced = inner, False

        async def list_agents(self):
            return await self.inner.list_agents()

        async def rpc(self, method, params=None):
            if method == ocp.M_CONFIG_PATCH and not self.raced:
                self.raced = True
                await seat_provision.ensure_session_isolation(db, self.inner)   # tiến trình kia ghi trước
                raise RuntimeError("baseHash mismatch")
            return await self.inner.rpc(method, params)

    out = await seat_provision.ensure_session_isolation(db, Racing(gw))
    assert out["changed"] == [] and out["ok"] is True
    assert len(gw.patches) == 1
