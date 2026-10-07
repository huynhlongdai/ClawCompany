"""M3 — Nhân sự AI: wizard tuyển, sửa hồ sơ 2 chiều, lệch + đồng bộ lại, vòng đời,
quyền tool theo seat. ORM thật (SQLite) + HTTP thật; gateway giả nhưng giữ đúng
hợp đồng đo trên 2026.9.8: hash = SHA-256 hex, expectedHash lệch → agent_file_conflict,
không xoá được phiên main, agents.delete dọn cả phiên."""
import hashlib
import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.security import create_access_token, hash_password
from app.db.base import Base
import app.models  # noqa: F401
from app.db.session import get_db
from app.main import app
from app.models import (Agent, APIKey, BudgetEnvelope, Company, Department, Member, Organization, Project, Task,
                        ToolPermission, User, UserOrganizationAccess)
from app.models.agent_hr import AgentFileSnapshot
from app.services import agent_dispatch, agent_hr, openclaw_alignment


def h(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


class GwError(RuntimeError):
    def __init__(self, msg, detail_type="", details=None):
        super().__init__(msg); self.detail_type = detail_type; self.details = details or {}


class FakeGateway:
    """Gateway giả: roster, 5 file có hash, phiên, models."""
    def __init__(self):
        self.agents: dict[str, dict] = {"main": {"id": "main", "name": "main", "model": "comet/gpt-4.1-mini"}}
        self.files: dict[tuple[str, str], str] = {}
        self.sessions: list[dict] = []
        self.calls: list[tuple[str, dict]] = []
        self.refuse_create = False
        self.refuse_update = False

    async def create_agent(self, rid, config):
        if self.refuse_create:
            return {"id": rid, "status": "missing", "bound": False, "hint": "bật OPENCLAW_REQUEST_ADMIN_SCOPE"}
        self.agents[rid] = {"id": rid, "name": rid, "model": config.get("model") or "comet/gpt-4.1-mini"}
        for f in ("AGENTS.md", "SOUL.md", "USER.md"):
            self.files[(rid, f)] = f"starter {f}"
        return {"id": rid, "status": "created", "bound": True}

    async def list_agents(self):
        out = []
        for a in self.agents.values():
            ss = [s for s in self.sessions if s["agentId"] == a["id"]]
            out.append({**a, "sessions": len(ss), "active": any(s.get("hasActiveRun") for s in ss)})
        return out

    async def cancel_run(self, handle):
        return {"ok": True}

    async def rpc(self, method, params=None):
        p = params or {}
        self.calls.append((method, p))
        rid = p.get("agentId")
        if method == "models.list":
            return {"models": [{"id": "gpt-4.1-mini", "provider": "comet", "name": "GPT-4.1 mini", "tags": ["default"]}]}
        if method == "agents.update":
            if self.refuse_update:
                raise GwError("model không tồn tại")
            a = self.agents[rid]
            for k in ("name", "model", "emoji"):
                if k in p:
                    a[k] = p[k]
            # như 2026.9.8: đổi name/emoji thì gateway tự viết lại IDENTITY.md
            ident = self.files.get((rid, "IDENTITY.md"))
            if ident is not None and ("name" in p or "emoji" in p):
                if "name" in p:
                    ident = re.sub(r"\*\*Name:\*\* .+", f"**Name:** {p['name']}", ident)
                if "emoji" in p:
                    ident = re.sub(r"\*\*Emoji:\*\* .+", f"**Emoji:** {p['emoji']}", ident)
                self.files[(rid, "IDENTITY.md")] = ident + "\n<!-- gateway -->"
            return {"ok": True, "agentId": rid}
        if method == "agents.delete":
            self.agents.pop(rid)
            self.sessions = [s for s in self.sessions if s["agentId"] != rid]
            for k in [k for k in self.files if k[0] == rid]:
                self.files.pop(k)
            return {"ok": True, "agentId": rid}
        if method == "agent.identity.get":
            m = re.search(r"\*\*Name:\*\* (.+)", self.files.get((rid, "IDENTITY.md"), ""))
            return {"agentId": rid, "name": m.group(1).strip() if m else self.agents[rid]["name"]}
        if method == "agents.files.get":
            c = self.files.get((rid, p["name"]))
            if c is None:
                return {"agentId": rid, "file": {"name": p["name"], "missing": True}}
            return {"agentId": rid, "file": {"name": p["name"], "missing": False, "content": c, "hash": h(c), "size": len(c)}}
        if method == "agents.files.set":
            cur = self.files.get((rid, p["name"]))
            if "expectedHash" in p and (cur is None or h(cur) != p["expectedHash"]):
                raise GwError("conflict", "agent_file_conflict", {"currentHash": h(cur) if cur else ""})
            self.files[(rid, p["name"])] = p["content"]
            return {"ok": True, "file": {"name": p["name"], "hash": h(p["content"]), "size": len(p["content"])}}
        if method == "sessions.list":
            return {"sessions": [dict(s) for s in self.sessions]}
        if method == "sessions.abort":
            for s in self.sessions:
                if s["key"] == p["key"]:
                    s["hasActiveRun"] = False
            return {"ok": True}
        if method == "sessions.delete":
            if p["key"].endswith(":main"):
                raise GwError(f"Cannot delete the main session ({p['key']}).")
            self.sessions = [s for s in self.sessions if s["key"] != p["key"]]
            return {"ok": True}
        if method == "sessions.reset":
            return {"ok": True, "key": p["key"]}
        raise GwError(f"unknown method {method}")


@pytest.fixture()
def env(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    Maker = sessionmaker(bind=engine, autoflush=False)
    db = Maker()

    def override():
        s = Maker()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = override
    gw = FakeGateway()
    for target in ("app.services.provisioning.get_runtime", "app.api.agents.get_runtime",
                   "app.services.agent_dispatch.get_runtime"):
        monkeypatch.setattr(target, lambda: gw)
    org = Organization(name="Nova M3", slug="nova-m3"); other = Organization(name="Khác", slug="khac-m3")
    db.add_all([org, other]); db.commit()
    co = Company(organization_id=org.id, name="Nova Shop", status="active"); db.add(co); db.commit()
    co_other = Company(organization_id=other.id, name="Khác", status="active"); db.add(co_other); db.commit()
    sales = Department(company_id=co.id, name="Bán hàng", access_level="restricted")
    mkt = Department(company_id=co.id, name="Marketing", access_level="restricted")
    db.add_all([sales, mkt]); db.commit()
    boss = Member(organization_id=org.id, company_id=co.id, name="Chị Lan", member_type="human", role="CEO")
    db.add(boss); db.commit()
    lead_s = Member(organization_id=org.id, company_id=co.id, department_id=sales.id, name="Anh Minh",
                    member_type="human", role="Trưởng phòng bán hàng", manager_id=boss.id)
    lead_m = Member(organization_id=org.id, company_id=co.id, department_id=mkt.id, name="Chị Hoa",
                    member_type="human", role="Trưởng phòng marketing", manager_id=boss.id)
    db.add_all([lead_s, lead_m]); db.commit()
    sales.head_member_id = lead_s.id; mkt.head_member_id = lead_m.id; db.commit()
    users = {}
    for role in ("owner", "manager", "member"):
        u = User(email=f"{role}@m3.test", password_hash=hash_password("Matkhau123"), display_name=role.title())
        db.add(u); db.commit()
        db.add(UserOrganizationAccess(user_id=u.id, organization_id=org.id, role=role, is_default=True, status="active"))
        db.commit(); users[role] = u
    uo = User(email="o@khac.test", password_hash=hash_password("Matkhau123")); db.add(uo); db.commit()
    db.add(UserOrganizationAccess(user_id=uo.id, organization_id=other.id, role="owner", is_default=True, status="active"))
    db.commit(); users["other"] = uo

    def tok(name):
        u = users[name]
        org_id = other.id if name == "other" else org.id
        return {"Authorization": "Bearer " + create_access_token(u.id, org_id, "owner" if name == "other" else name)}

    client = TestClient(app)
    yield type("E", (), dict(db=db, org=org, co=co, sales=sales, mkt=mkt, boss=boss, lead_s=lead_s,
                             lead_m=lead_m, tok=staticmethod(tok), c=client, gw=gw))
    app.dependency_overrides.pop(get_db, None)


def hire(env, **kw):
    body = {"name": "Thu Trang", "role": "Nhân viên chăm sóc khách", "company_id": env.co.id,
            "department_id": env.sales.id, "personality": "than-thien", "monthly_budget": 25,
            "job_description": "Trả lời khách trên kênh chat\nTổng hợp phản hồi hằng tuần",
            "manager_notes": "- Báo cáo mỗi sáng thứ Hai"}
    body.update(kw)
    r = env.c.post("/api/agents/hire", json=body, headers=env.tok("manager"))
    assert r.status_code == 200, r.text
    return r.json()


def drift(env, aid):
    r = env.c.get(f"/api/agents/{aid}/drift", headers=env.tok("member"))
    assert r.status_code == 200, r.text
    return r.json()


# ------------------------------------------------------------------ tuyển

def test_hire_creates_agent_with_five_files_and_snapshots(env):
    out = hire(env, tools={"company_budget_check": "ask"})
    rid = out["runtime_agent_id"]
    assert out["status"] == "active" and rid.startswith("thu-trang-")
    assert rid in env.gw.agents
    assert env.gw.agents[rid]["name"] == "Thu Trang" and env.gw.agents[rid]["emoji"] == "🤝"
    for f in agent_hr.SEAT_FILES:
        assert (rid, f) in env.gw.files, f
    assert "**Name:** Thu Trang" in env.gw.files[(rid, "IDENTITY.md")]
    assert "Thân thiện" in env.gw.files[(rid, "SOUL.md")]
    assert "- Trả lời khách trên kênh chat" in env.gw.files[(rid, "AGENTS.md")]
    assert "25 USD/tháng" in env.gw.files[(rid, "AGENTS.md")]
    assert "Báo cáo cho: Anh Minh" in env.gw.files[(rid, "AGENTS.md")]   # mặc định = trưởng phòng
    snaps = env.db.query(AgentFileSnapshot).filter_by(agent_id=out["agent_id"]).all()
    assert {s.name for s in snaps} == set(agent_hr.SEAT_FILES)
    assert all(s.hash == h(env.gw.files[(rid, s.name)]) for s in snaps)
    m = env.db.get(Member, out["member_id"])
    assert m.manager_id == env.lead_s.id and m.department_id == env.sales.id
    env_b = env.db.get(BudgetEnvelope, out["budget_envelope_id"])
    assert env_b.scope_type == "member" and env_b.scope_id == m.id and env_b.period == "monthly" and env_b.amount_limit == 25
    tp = env.db.query(ToolPermission).filter_by(member_id=m.id, tool="company_budget_check").one()
    assert tp.level == "ask"
    assert env.db.get(Agent, out["agent_id"]).model == "comet/gpt-4.1-mini"   # model mặc định thật của gateway
    d = drift(env, out["agent_id"])
    assert d["in_sync"] is True and d["roster_match"] is True
    assert {f["status"] for f in d["files"]} == {"in_sync"}


def test_hire_when_gateway_refuses_is_honest(env):
    env.gw.refuse_create = True
    out = hire(env)
    assert out["status"] == "needs_runtime" and out["warnings"]
    assert all(f["written"] is False for f in out["files"])
    assert not [k for k in env.gw.files if k[0] == out["runtime_agent_id"]]
    a = env.db.get(Agent, out["agent_id"])
    assert a.lifecycle == "runtime_missing"
    assert env.db.query(AgentFileSnapshot).filter_by(agent_id=a.id).count() == 5   # để đẩy lên sau
    p = Project(company_id=env.co.id, name="P"); env.db.add(p); env.db.commit()
    t = Task(project_id=p.id, title="Việc", assignee_member_id=a.member_id, status="todo"); env.db.add(t); env.db.commit()
    with pytest.raises(agent_dispatch.DispatchError, match="chưa có agent trên gateway"):
        agent_dispatch.resolve_seat(env.db, t)


def test_hire_validation_and_roles(env):
    base = {"name": "X", "company_id": env.co.id}
    assert env.c.post("/api/agents/hire", json=base, headers=env.tok("member")).status_code == 403
    r = env.c.post("/api/agents/hire", json={**base, "personality": "nong-nay"}, headers=env.tok("manager"))
    assert r.status_code == 422 and "Tính cách" in r.text
    r = env.c.post("/api/agents/hire", json={**base, "tools": {"company_budget_check": "maybe"}}, headers=env.tok("manager"))
    assert r.status_code == 422
    r = env.c.post("/api/agents/hire", json={"name": "X", "department_id": env.sales.id, "company_id": 9999},
                   headers=env.tok("manager"))
    assert r.status_code == 404
    with pytest.raises(Exception, match="USER.md"):
        agent_hr.render_files(name="A", role="B", company="C", department="", manager="", manager_notes="x" * 4100)
    assert env.db.query(Agent).count() == 0     # không để lại seat dở


def test_hire_options_lists_models_and_personalities(env):
    r = env.c.get("/api/agents/hire/options", headers=env.tok("manager"))
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["models"][0]["id"] == "comet/gpt-4.1-mini" and j["models"][0]["default"]
    assert {p["key"] for p in j["personalities"]} == set(agent_hr.PERSONALITIES)
    assert {d["name"] for d in j["departments"]} == {"Bán hàng", "Marketing"}
    assert env.c.get("/api/agents/hire/options", headers=env.tok("member")).status_code == 403


# ------------------------------------------------------------------ sửa 2 chiều & lệch

def test_edit_soul_on_ui_writes_gateway_and_snapshot(env):
    out = hire(env); aid, rid = out["agent_id"], out["runtime_agent_id"]
    prof = env.c.get(f"/api/agents/{aid}/profile", headers=env.tok("manager")).json()
    soul = next(f for f in prof["files"] if f["name"] == "SOUL.md")
    r = env.c.put(f"/api/agents/{aid}/files/SOUL.md", json={"content": "# SOUL mới\nNghiêm túc.", "expected_hash": soul["hash"]},
                  headers=env.tok("manager"))
    assert r.status_code == 200, r.text
    assert env.gw.files[(rid, "SOUL.md")] == "# SOUL mới\nNghiêm túc."
    snap = env.db.query(AgentFileSnapshot).filter_by(agent_id=aid, name="SOUL.md").one()
    env.db.refresh(snap)
    assert snap.content == "# SOUL mới\nNghiêm túc." and snap.hash == h(snap.content)
    assert drift(env, aid)["in_sync"] is True


def test_manual_gateway_edit_is_reported_then_resynced(env):
    out = hire(env); aid, rid = out["agent_id"], out["runtime_agent_id"]
    original = env.gw.files[(rid, "SOUL.md")]
    env.gw.files[(rid, "SOUL.md")] = "sửa tay trên máy gateway"
    env.gw.files[(rid, "MEMORY.md")] += "\n- agent tự ghi nhớ"
    d = drift(env, aid)
    st = {f["name"]: f for f in d["files"]}
    assert d["in_sync"] is False and d["drift_count"] == 1
    assert st["SOUL.md"]["status"] == "edited_on_gateway" and st["SOUL.md"]["counts_as_drift"]
    assert st["SOUL.md"]["gateway_content"] == "sửa tay trên máy gateway"
    assert st["MEMORY.md"]["status"] == "edited_on_gateway" and not st["MEMORY.md"]["counts_as_drift"]
    # đẩy bản ClawCompany lên
    r = env.c.post(f"/api/agents/{aid}/resync", json={"direction": "push", "files": ["SOUL.md"]}, headers=env.tok("manager"))
    assert r.status_code == 200, r.text
    assert env.gw.files[(rid, "SOUL.md")] == original and r.json()["drift"]["in_sync"] is True
    # sửa tay lần nữa rồi nhận bản gateway
    env.gw.files[(rid, "SOUL.md")] = "bản gateway được chấp nhận"
    r = env.c.post(f"/api/agents/{aid}/resync", json={"direction": "pull"}, headers=env.tok("manager"))
    assert r.status_code == 200 and r.json()["drift"]["in_sync"] is True
    snap = env.db.query(AgentFileSnapshot).filter_by(agent_id=aid, name="SOUL.md").one(); env.db.refresh(snap)
    assert snap.content == "bản gateway được chấp nhận" and snap.source == "gateway_accepted"
    assert env.c.post(f"/api/agents/{aid}/resync", json={"direction": "pull"}, headers=env.tok("member")).status_code == 403


def test_resync_push_detects_race(env):
    out = hire(env); aid, rid = out["agent_id"], out["runtime_agent_id"]
    env.gw.files[(rid, "AGENTS.md")] = "sửa tay"
    orig_rpc = env.gw.rpc

    async def racing(method, params=None):      # có người sửa tiếp đúng lúc đồng bộ
        if method == "agents.files.set" and params.get("name") == "AGENTS.md":
            env.gw.files[(rid, "AGENTS.md")] = "sửa tay lần 2"
        return await orig_rpc(method, params)
    env.gw.rpc = racing
    r = env.c.post(f"/api/agents/{aid}/resync", json={"direction": "push"}, headers=env.tok("manager"))
    assert r.status_code == 200
    done = r.json()["done"][0]
    assert done["ok"] is False and env.gw.files[(rid, "AGENTS.md")] == "sửa tay lần 2"   # không ghi đè mù


def test_update_hr_writes_db_and_gateway(env):
    out = hire(env); aid, rid = out["agent_id"], out["runtime_agent_id"]
    r = env.c.patch(f"/api/agents/{aid}/hr", json={"name": "Thu Trang Lê", "model": "comet/gpt-4.1",
                                                   "personality": "ngan-gon"}, headers=env.tok("manager"))
    assert r.status_code == 200, r.text
    j = r.json()
    assert set(j["changed"]) >= {"name", "model", "personality"} and not j["warnings"]
    assert env.gw.agents[rid]["name"] == "Thu Trang Lê" and env.gw.agents[rid]["model"] == "comet/gpt-4.1"
    a = env.db.get(Agent, aid); env.db.refresh(a); m = env.db.get(Member, a.member_id); env.db.refresh(m)
    assert m.name == "Thu Trang Lê" and a.model == "comet/gpt-4.1"
    assert "**Name:** Thu Trang Lê" in env.gw.files[(rid, "IDENTITY.md")]
    assert "Ngắn gọn" in env.gw.files[(rid, "SOUL.md")]
    assert j["files"]["IDENTITY.md"]["written"] and j["files"]["SOUL.md"]["written"]
    assert drift(env, aid)["in_sync"] is True


def test_update_hr_does_not_overwrite_manual_edit(env):
    out = hire(env); aid, rid = out["agent_id"], out["runtime_agent_id"]
    env.gw.files[(rid, "IDENTITY.md")] = "- **Name:** Tên sửa tay\n"
    r = env.c.patch(f"/api/agents/{aid}/hr", json={"role": "Trưởng nhóm CSKH"}, headers=env.tok("manager"))
    assert r.status_code == 200
    j = r.json()
    assert j["files"]["IDENTITY.md"]["reason"] == "edited_on_gateway" and j["warnings"]
    assert env.gw.files[(rid, "IDENTITY.md")] == "- **Name:** Tên sửa tay\n"
    d = drift(env, aid)
    assert not d["in_sync"]
    name_f = next(f for f in d["fields"] if f["field"] == "name")
    assert name_f["gateway"] == "Tên sửa tay" and not name_f["match"]


def test_update_hr_gateway_refusal_keeps_db_model(env):
    out = hire(env); aid = out["agent_id"]
    env.gw.refuse_update = True
    r = env.c.patch(f"/api/agents/{aid}/hr", json={"model": "comet/khong-co"}, headers=env.tok("manager"))
    assert r.status_code == 200 and "từ chối" in r.json()["warnings"][0]
    a = env.db.get(Agent, aid); env.db.refresh(a)
    assert a.model != "comet/khong-co"


def test_department_move_defaults_manager_to_new_head(env):
    out = hire(env); aid = out["agent_id"]; rid = out["runtime_agent_id"]
    r = env.c.patch(f"/api/agents/{aid}/hr", json={"department_id": env.mkt.id}, headers=env.tok("manager"))
    assert r.status_code == 200, r.text
    m = env.db.get(Member, out["member_id"]); env.db.refresh(m)
    assert m.department_id == env.mkt.id and m.manager_id == env.lead_m.id
    assert "Báo cáo cho: Chị Hoa" in env.gw.files[(rid, "AGENTS.md")]
    other_co = Department(company_id=env.db.query(Company).filter(Company.name == "Khác").one().id, name="Y")
    env.db.add(other_co); env.db.commit()
    assert env.c.patch(f"/api/agents/{aid}/hr", json={"department_id": other_co.id},
                       headers=env.tok("manager")).status_code == 422


# ------------------------------------------------------------------ vòng đời

def _task(env, member_id, status="todo", **kw):
    p = env.db.query(Project).first()
    if p is None:
        p = Project(company_id=env.co.id, name="Dự án"); env.db.add(p); env.db.commit()
    t = Task(project_id=p.id, title=f"Việc {status}", assignee_member_id=member_id, status=status, **kw)
    env.db.add(t); env.db.commit()
    return t


def test_pause_blocks_dispatch_and_resume(env):
    out = hire(env); aid = out["agent_id"]
    t = _task(env, out["member_id"])
    r = env.c.post(f"/api/agents/{aid}/lifecycle", json={"action": "pause"}, headers=env.tok("manager"))
    assert r.status_code == 200 and r.json()["lifecycle"] == "paused"
    env.db.expire_all()
    with pytest.raises(agent_dispatch.DispatchError, match="tạm dừng"):
        agent_dispatch.resolve_seat(env.db, t)
    # đối chiếu roster không được âm thầm bỏ trạng thái tạm dừng
    a = env.db.get(Agent, aid)
    openclaw_alignment.reconcile(env.db, env.org.id, [])
    env.db.refresh(a); assert a.lifecycle == "paused"
    r = env.c.post(f"/api/agents/{aid}/lifecycle", json={"action": "resume"}, headers=env.tok("manager"))
    assert r.status_code == 200 and r.json()["lifecycle"] == "active"
    env.db.expire_all()
    assert agent_dispatch.resolve_seat(env.db, t)[1].id == aid
    assert env.c.post(f"/api/agents/{aid}/lifecycle", json={"action": "resume"},
                      headers=env.tok("manager")).status_code == 409
    assert env.c.post(f"/api/agents/{aid}/lifecycle", json={"action": "pause"},
                      headers=env.tok("member")).status_code == 403


def test_retire_cleans_sessions_and_hands_over(env):
    out = hire(env); aid, rid, mid = out["agent_id"], out["runtime_agent_id"], out["member_id"]
    sales = env.db.get(Department, env.sales.id); sales.head_member_id = mid; env.db.commit()
    junior = Member(organization_id=env.org.id, company_id=env.co.id, department_id=env.sales.id, name="Bé Na",
                    member_type="human", manager_id=mid)
    env.db.add(junior); env.db.commit()
    env.db.add(APIKey(organization_id=env.org.id, member_id=mid, name="k", key_prefix="cc_x", key_hash="x", is_active=True))
    env.db.commit()
    t_run = _task(env, mid, "in_progress", runtime_session_key=f"agent:{rid}:task-1")
    t_todo = _task(env, mid, "todo")
    t_done = _task(env, mid, "done")
    env.gw.sessions = [{"key": f"agent:{rid}:main", "agentId": rid, "isMain": True},
                       {"key": f"agent:{rid}:task-1", "agentId": rid, "hasActiveRun": True},
                       {"key": f"agent:{rid}:task-2", "agentId": rid},
                       {"key": "agent:main:main", "agentId": "main", "isMain": True}]
    env.gw.files[(rid, "MEMORY.md")] += "\n- điều đã học"
    r = env.c.post(f"/api/agents/{aid}/lifecycle", json={"action": "retire", "reason": "thôi việc"},
                   headers=env.tok("manager"))
    assert r.status_code == 200, r.text
    j = r.json()
    g = j["gateway"]
    assert j["lifecycle"] == "retired" and not j["warnings"], j
    assert g["sessions_before"] == 3 and g["sessions_after"] == 0 and g["agent_removed"] and not g["still_on_roster"]
    assert rid not in env.gw.agents and [s["agentId"] for s in env.gw.sessions] == ["main"]
    assert ("sessions.abort", {"key": f"agent:{rid}:task-1", "agentId": rid}) in env.gw.calls
    env.db.expire_all()
    assert env.db.get(Task, t_run.id).status == "todo"
    for t in (t_run, t_todo):
        tt = env.db.get(Task, t.id)
        assert tt.assignee_member_id is None and tt.assignee_department_id == env.sales.id
    assert env.db.get(Task, t_done.id).assignee_member_id == mid      # lịch sử giữ nguyên
    assert env.db.get(Department, env.sales.id).head_member_id is None
    assert env.db.get(Member, junior.id).manager_id == env.lead_s.id
    assert env.db.query(APIKey).filter_by(member_id=mid).one().is_active is False
    assert env.db.query(BudgetEnvelope).filter_by(scope_id=mid, scope_type="member").one().status == "closed"
    mem = env.db.query(AgentFileSnapshot).filter_by(agent_id=aid, name="MEMORY.md").one()
    assert "điều đã học" in mem.content and mem.source == "archived_on_retire"
    assert env.db.get(Member, mid).status == "retired"
    # sau khi nghỉ: không sửa, không đồng bộ, không nhận việc
    assert env.c.patch(f"/api/agents/{aid}/hr", json={"role": "x"}, headers=env.tok("manager")).status_code == 409
    assert env.c.post(f"/api/agents/{aid}/resync", json={"direction": "push"}, headers=env.tok("manager")).status_code == 409
    with pytest.raises(agent_dispatch.DispatchError, match="nghỉ việc"):
        agent_dispatch.resolve_seat(env.db, env.db.get(Task, t_done.id))
    d = drift(env, aid)
    assert d["roster_match"] is False and d["in_sync"] is True
    r2 = env.c.post(f"/api/agents/{aid}/lifecycle", json={"action": "retire"}, headers=env.tok("manager"))
    assert r2.json().get("noop") is True


def test_retire_keep_on_gateway_and_reassign(env):
    a1 = hire(env); a2 = hire(env, name="Quốc Bảo")
    rid = a1["runtime_agent_id"]
    t = _task(env, a1["member_id"], "todo")
    env.gw.sessions = [{"key": f"agent:{rid}:main", "agentId": rid, "isMain": True},
                       {"key": f"agent:{rid}:task-9", "agentId": rid}]
    r = env.c.post(f"/api/agents/{a1['agent_id']}/lifecycle",
                   json={"action": "retire", "remove_from_gateway": False, "reassign_to_member_id": a2["member_id"]},
                   headers=env.tok("manager"))
    assert r.status_code == 200, r.text
    g = r.json()["gateway"]
    assert g["sessions_deleted"] == 1 and g["main_reset"] == 1 and g["sessions_after"] == 0 and not g["agent_removed"]
    assert rid in env.gw.agents
    env.db.expire_all()
    assert env.db.get(Task, t.id).assignee_member_id == a2["member_id"]
    bad = env.c.post(f"/api/agents/{a2['agent_id']}/lifecycle",
                     json={"action": "retire", "reassign_to_member_id": a1["member_id"]}, headers=env.tok("manager"))
    assert bad.status_code == 422      # không giao việc cho người đã nghỉ


# ------------------------------------------------------------------ roster, quyền tool, tenancy

def test_roster_and_tools_and_tenancy(env):
    out = hire(env)
    env.gw.agents["la-lung"] = {"id": "la-lung", "name": "la-lung"}
    r = env.c.get("/api/agents/roster", headers=env.tok("member"))
    assert r.status_code == 200, r.text
    j = r.json()
    it = next(i for i in j["items"] if i["agent_id"] == out["agent_id"])
    assert it["on_gateway"] is True and it["department"] == "Bán hàng" and it["manager"] == "Anh Minh"
    assert j["unbound_on_gateway"] == 1 and j["counts"] == {"active": 1}
    tl = env.c.get(f"/api/agents/{out['agent_id']}/tools", headers=env.tok("member")).json()
    assert tl["tier"] == "executor"
    lv = {t["name"]: t for t in tl["tools"]}
    assert lv["company_budget_check"]["level"] == "off" and lv["company_budget_check"]["source"].startswith("default")
    r = env.c.put("/api/mcp/permissions", json={"tool": "company_budget_check", "level": "ask", "member_id": out["member_id"]},
                  headers=env.tok("owner"))
    assert r.status_code == 200, r.text
    tl = env.c.get(f"/api/agents/{out['agent_id']}/tools", headers=env.tok("member")).json()
    lv = {t["name"]: t for t in tl["tools"]}
    assert lv["company_budget_check"] == {**lv["company_budget_check"], "level": "ask", "source": "member"}
    # tổ chức khác không thấy
    for path in (f"/api/agents/{out['agent_id']}/drift", f"/api/agents/{out['agent_id']}/tools"):
        assert env.c.get(path, headers=env.tok("other")).status_code == 404
    assert env.c.post(f"/api/agents/{out['agent_id']}/lifecycle", json={"action": "pause"},
                      headers=env.tok("other")).status_code == 404
    assert env.c.get("/api/agents/roster", headers=env.tok("other")).json()["items"] == []


def test_regen_keeps_ui_customized_file_unless_asked(env):
    out = hire(env); aid, rid = out["agent_id"], out["runtime_agent_id"]
    prof = env.c.get(f"/api/agents/{aid}/profile", headers=env.tok("manager")).json()
    soul = next(f for f in prof["files"] if f["name"] == "SOUL.md")
    custom = soul["content"] + "\n- Luôn chào khách bằng tên.\n"
    assert env.c.put(f"/api/agents/{aid}/files/SOUL.md", json={"content": custom, "expected_hash": soul["hash"]},
                     headers=env.tok("manager")).status_code == 200
    r = env.c.patch(f"/api/agents/{aid}/hr", json={"personality": "phan-bien"}, headers=env.tok("manager")).json()
    assert r["files"]["SOUL.md"]["reason"] == "customized" and r["warnings"]
    assert env.gw.files[(rid, "SOUL.md")] == custom
    assert r["files"]["IDENTITY.md"]["written"]          # file chưa chỉnh tay vẫn sinh lại
    r = env.c.patch(f"/api/agents/{aid}/hr", json={"regenerate_files": ["SOUL.md"]}, headers=env.tok("manager")).json()
    assert r["files"]["SOUL.md"]["written"] and "Phản biện" in env.gw.files[(rid, "SOUL.md")]
    assert env.c.patch(f"/api/agents/{aid}/hr", json={"regenerate_files": ["MEMORY.md"]},
                       headers=env.tok("manager")).status_code == 422
    assert drift(env, aid)["in_sync"] is True


def test_model_inherited_from_defaults_is_not_false_drift():
    # agent vừa agents.create thừa hưởng agents.defaults.model = {primary, fallbacks}
    from app.services.seat_profile import model_str
    assert model_str({"primary": "comet/gpt-4.1-mini", "fallbacks": []}) == "comet/gpt-4.1-mini"
    assert model_str("comet/gpt-4.1") == "comet/gpt-4.1" and model_str(None) == ""
