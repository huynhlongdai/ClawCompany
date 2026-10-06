"""D1.5 — máy chủ MCP ``POST /api/mcp`` và các tool ``company_*``.

Chạy qua HTTP thật (TestClient + app FastAPI thật), DB là SQLite in-memory với
ORM thật, xác thực bằng API key thật (băm, so prefix) — không giả ``Principal``.

Phép thử của kế hoạch: hỏi Nina "công ty đang có mấy dự án đang chạy" thì con số
phải khớp DB và có log tool call. Ở đây "Nina" là một client MCP dùng key của
seat Nina; model thật không chạy trong CI, nhưng đường đi từ key → seat → tool
→ DB → kết quả → log là đường thật.
"""
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
import app.models  # noqa: F401
from app.core.security import pwd_context
from app.db.session import get_db
from app.main import app
from app.models import APIKey, CompanyEvent, TaskRun
from app.models.entities import Agent, Company, Department, Member, Organization, Project, Task


@pytest.fixture()
def env():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
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
    org = Organization(name="Nova", slug="nova-mcp"); db.add(org); db.commit()
    co = Company(organization_id=org.id, name="Nova Fashion", status="active"); db.add(co); db.commit()
    mkt = Department(company_id=co.id, name="Marketing"); ops = Department(company_id=co.id, name="Vận hành")
    db.add_all([mkt, ops]); db.commit()

    def seat(name, agent_id, dept=None):
        m = Member(organization_id=org.id, company_id=co.id, department_id=dept, name=name,
                   member_type="agent", role=name, status="active")
        db.add(m); db.commit()
        a = Agent(member_id=m.id, runtime_provider="openclaw", runtime_agent_id=agent_id,
                  lifecycle="active")
        db.add(a); db.commit()
        return m

    nina, mia, ops_bot = seat("Nina", "nina"), seat("Mia", "mia", mkt.id), seat("Ops", "ops", ops.id)
    projects = [Project(company_id=co.id, name=f"P{i}", status=s)
                for i, s in enumerate(["active", "active", "running", "planning", "done"])]
    db.add_all(projects); db.commit()
    t_mia = Task(project_id=projects[0].id, title="Viết bài", status="todo",
                 assignee_member_id=mia.id, priority="high")
    t_ops = Task(project_id=projects[0].id, title="Kiểm kho", status="todo",
                 assignee_member_id=ops_bot.id, priority="medium")
    db.add_all([t_mia, t_ops]); db.commit()

    keys = {}

    def key(member, scopes=("*",), name="k"):
        raw = f"cc_test_{member.id}_{len(keys)}_" + "x" * 20
        db.add(APIKey(organization_id=org.id, member_id=member.id, name=name, key_prefix=raw[:12],
                      key_hash=pwd_context.hash(raw), scopes=json.dumps(list(scopes))))
        db.commit()
        keys[raw] = member
        return raw

    client = TestClient(app)

    def rpc(k, method, params=None, id_=1, headers=None):
        r = client.post("/api/mcp", headers={"X-API-Key": k, **(headers or {})},
                        json={"jsonrpc": "2.0", "id": id_, "method": method, "params": params or {}})
        return r

    def call(k, name, args=None, headers=None):
        r = rpc(k, "tools/call", {"name": name, "arguments": args or {}}, headers=headers)
        assert r.status_code == 200, r.text
        res = r.json()["result"]
        return res["isError"], res["structuredContent"]

    yield {"db": db, "org": org, "nina": nina, "mia": mia, "ops": ops_bot, "t_mia": t_mia,
           "t_ops": t_ops, "projects": projects, "key": key, "rpc": rpc, "call": call,
           "client": client}
    app.dependency_overrides.pop(get_db, None)
    db.close()


def test_initialize_and_list_all_24_tools(env):
    k = env["key"](env["nina"])
    r = env["rpc"](k, "initialize", {"protocolVersion": "2025-03-26", "capabilities": {},
                                     "clientInfo": {"name": "openclaw"}})
    assert r.status_code == 200 and r.headers.get("Mcp-Session-Id")
    assert r.json()["result"]["protocolVersion"] == "2025-03-26"
    # notification: 202, không thân
    n = env["client"].post("/api/mcp", headers={"X-API-Key": k},
                           json={"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert n.status_code == 202
    tools = env["rpc"](k, "tools/list").json()["result"]["tools"]
    names = {t["name"] for t in tools}
    assert len(tools) == 24 and all(n.startswith("company_") for n in names)
    assert "company_task_checkout" in names


def test_nina_counts_running_projects_from_the_database_and_the_call_is_logged(env):
    k = env["key"](env["nina"])
    err, out = env["call"](k, "company_project_get")
    assert not err
    db_running = sum(1 for p in env["projects"] if p.status in ("active", "running", "in_progress"))
    assert out["running_count"] == db_running == 3
    assert out["total"] == 5 and out["by_status"]["planning"] == 1
    db = env["db"]; db.expire_all()
    log = db.execute(select(CompanyEvent).where(CompanyEvent.event_type == "mcp.tool.called")).scalars().all()
    assert len(log) == 1
    payload = json.loads(log[0].payload_json)
    assert payload["tool"] == "company_project_get" and payload["ok"] is True
    assert log[0].actor_member_id == env["nina"].id


def test_scopes_limit_both_listing_and_calling(env):
    k = env["key"](env["mia"], scopes=("company.tasks:read",))
    names = {t["name"] for t in env["rpc"](k, "tools/list").json()["result"]["tools"]}
    assert names == {"company_tasks_list", "company_task_get"}
    err, out = env["call"](k, "company_project_get")
    assert err and out["error"] == "forbidden"


def test_department_seat_cannot_see_another_departments_task(env):
    mia = env["key"](env["mia"])
    err, out = env["call"](mia, "company_task_get", {"task_id": env["t_ops"].id})
    assert err and out["error"] == "not_found"
    err, out = env["call"](mia, "company_task_get", {"task_id": env["t_mia"].id})
    assert not err and out["goal_line"].endswith("Viết bài")
    # Nina không thuộc phòng nào → thấy cả công ty.
    nina = env["key"](env["nina"])
    err, out = env["call"](nina, "company_tasks_list", {"scope": "team"})
    assert {t["id"] for t in out["tasks"]} == {env["t_mia"].id, env["t_ops"].id}
    err, out = env["call"](mia, "company_tasks_list", {"scope": "team"})
    assert {t["id"] for t in out["tasks"]} == {env["t_mia"].id}


def test_status_tool_goes_through_the_lifecycle(env):
    k = env["key"](env["mia"])
    t = env["t_mia"]
    err, out = env["call"](k, "company_task_status", {"task_id": t.id, "status": "done",
                                                       "reason": "xong rồi"})
    assert err and out["error"] == "conflict"          # todo → done: nhảy cóc
    err, out = env["call"](k, "company_task_status", {"task_id": t.id, "status": "in_progress",
                                                       "reason": "bắt tay làm"})
    assert not err and out == {"task_id": t.id, "from": "todo", "to": "in_progress"}
    db = env["db"]; db.expire_all()
    ev = db.execute(select(CompanyEvent).where(CompanyEvent.event_type == "task.in_progress")).scalar_one()
    assert json.loads(ev.payload_json)["via"] == "mcp"
    # Không phải việc của mình → không đổi được.
    ops = env["key"](env["ops"])
    err, out = env["call"](ops, "company_task_status", {"task_id": t.id, "status": "review",
                                                         "reason": "x"})
    assert err and out["error"] == "not_found"


def test_checkout_uses_the_current_run_and_second_holder_loses(env):
    from app.services import task_lifecycle
    db, t, mia = env["db"], env["t_mia"], env["mia"]
    run = task_lifecycle.open_run(db, t, organization_id=env["org"].id, member_id=mia.id)
    run.status = "running"; db.add(run); db.commit()
    k = env["key"](mia)
    hdr = {"X-OpenClaw-Session-Key": f"agent:mia:company-task-{t.id}"}
    err, out = env["call"](k, "company_task_checkout", {"task_id": t.id}, headers=hdr)
    assert not err and out["run_id"] == run.id
    # Một client khác (không có session của lượt này) cố giữ → thua, không thử lại.
    err, out = env["call"](k, "company_task_checkout", {"task_id": t.id})
    assert err and out["error"] == "conflict"
    db.expire_all()
    assert db.get(Task, t.id).checkout_run_id == run.id
    assert db.query(TaskRun).filter(TaskRun.status == "skipped").count() == 1


def test_comment_lands_in_the_task_journal(env):
    k = env["key"](env["mia"])
    err, out = env["call"](k, "company_task_comment", {"task_id": env["t_mia"].id,
                                                        "body": "Đã viết 3 bài", "kind": "result"})
    assert not err and out["journal_seq"] == 1


def test_agents_cannot_spoof_system_events_or_pass_unknown_args(env):
    k = env["key"](env["mia"])
    err, out = env["call"](k, "company_event_emit", {"event_type": "task.done", "payload": {}})
    assert not err and out["event_type"] == "agent.task.done"
    err, out = env["call"](k, "company_tasks_list", {"assignee_member_id": 1})
    assert err and out["error"] == "invalid_argument"


def test_human_tokens_and_unbound_keys_are_refused(env):
    from app.core.security import create_access_token
    c = env["client"]
    r = c.post("/api/mcp", headers={"Authorization": "Bearer " + create_access_token(
        1, env["org"].id, "owner")},
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert r.status_code in (401, 403)
    r = c.post("/api/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert r.status_code == 401
    assert c.get("/api/mcp").status_code in (401, 405)


# ------------------------------------------------------------------ D1.6

def _lead_and_executor(env):
    """Mia thành trưởng phòng Marketing; thêm một seat thừa hành trong phòng."""
    from app.models.entities import Department
    db = env["db"]
    mkt = db.get(Department, env["mia"].department_id)
    mkt.head_member_id = env["mia"].id; db.add(mkt)
    junior = Member(organization_id=env["org"].id, company_id=env["mia"].company_id,
                    department_id=mkt.id, name="Junior", member_type="agent", role="Writer",
                    status="active", manager_id=env["mia"].id)
    db.add(junior); db.commit()
    db.add(Agent(member_id=junior.id, runtime_provider="openclaw", runtime_agent_id="junior",
                 lifecycle="active")); db.commit()
    return env["mia"], junior


def test_executor_seat_gets_403_on_budget_check_even_with_full_scopes(env):
    lead, junior = _lead_and_executor(env)
    k = env["key"](junior, scopes=("*",))     # gateway/scope đều cho qua
    names = {t["name"] for t in env["rpc"](k, "tools/list").json()["result"]["tools"]}
    assert "company_budget_check" not in names and len(names) == 22
    r = env["rpc"](k, "tools/call", {"name": "company_budget_check", "arguments": {}})
    assert r.status_code == 403 and r.json()["error"]["data"]["level"] == "off"
    # Trưởng phòng thì được.
    err, out = env["call"](env["key"](lead), "company_budget_check")
    assert not err and "envelopes" in out
    db = env["db"]; db.expire_all()
    denied = db.execute(select(CompanyEvent).where(CompanyEvent.event_type == "mcp.tool.denied")).scalar_one()
    assert json.loads(denied.payload_json)["reason"] == "level_off"
    # Đường REST cũ cũng chặn: lớp 2 không phụ thuộc vào việc đi qua MCP.
    from app.services import tool_permissions
    tool_permissions.set_level(db, env["org"].id, "company_tasks_list", "off", member_id=junior.id)
    r = env["client"].get("/api/company-tools/tasks", params={"runtime_agent_id": "junior"},
                          headers={"X-API-Key": k})
    assert r.status_code == 403


def test_ask_level_creates_one_approval_then_runs_after_it_is_approved(env):
    from app.models import Approval
    from app.services import tool_permissions
    db = env["db"]
    tool_permissions.set_level(db, env["org"].id, "company_report_submit", "ask", role="lead")
    k = env["key"](env["nina"])
    args = {"title": "Tuần 41", "content": "ổn"}
    err, out = env["call"](k, "company_report_submit", args)
    assert not err and out["pending_approval"]
    err, again = env["call"](k, "company_report_submit", args)
    assert again["approval_id"] == out["approval_id"]          # không sinh approval trùng
    db.expire_all()
    ap = db.get(Approval, out["approval_id"]); ap.status = "approved"; db.add(ap); db.commit()
    err, done = env["call"](k, "company_report_submit", args)
    assert not err and done.get("report_id")


def test_member_override_beats_tier_and_unknown_actions_are_denied_for_agents(env):
    from app.services import policy, tool_permissions
    lead, junior = _lead_and_executor(env)
    db = env["db"]
    tool_permissions.set_level(db, env["org"].id, "company_budget_check", "allowed",
                               member_id=junior.id)
    assert tool_permissions.resolve(db, junior, "company_budget_check") == ("allowed", "member")
    assert tool_permissions.resolve(db, junior, "company_shell_exec") == ("off", "unknown_tool")
    d = policy.authorize(db, env["org"].id, "exec.rm", actor_member_id=junior.id)
    assert d.decision == "deny" and d.policy_key == "default_deny"
    human = Member(organization_id=env["org"].id, name="Long", member_type="human",
                   role="Founder", status="active")
    db.add(human); db.commit()
    assert policy.authorize(db, env["org"].id, "exec.rm", actor_member_id=human.id).decision == "allow"
