"""M1.3: lỗi 500 có CORS + JSON tiếng Việt, /health báo schema, doctor 1 nút,
follower tự nối lại, bỏ chế độ gateway cũ."""
import asyncio
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.db.base import Base
import app.models  # noqa: F401
from app.models import Agent, Company, Member, Organization, Project, Task
from app.runtime import factory, openclaw_protocol as ocp
from app.runtime.mock import MockOpenClawRuntime
from app.runtime.openclaw_native import NativeOpenClawRuntime, OpenClawProtocolError
from app.services import openclaw_doctor, schema_status, stream_catchup
from app.services import runtime_stream as rs

ORIGIN = settings.cors_origins.split(",")[0].strip()


# --- lỗi 500: JSON + CORS -------------------------------------------------

@pytest.fixture(scope="module")
def client():
    from app.main import app

    async def boom():
        raise RuntimeError("no running event loop")

    async def gw():
        raise OpenClawProtocolError("Unknown agent id", {"code": "INVALID_REQUEST"})
    app.add_api_route("/__m13/boom", boom)
    app.add_api_route("/__m13/gw", gw)
    return TestClient(app, raise_server_exceptions=False)


def test_unhandled_500_is_json_and_keeps_cors(client):
    r = client.get("/__m13/boom", headers={"Origin": ORIGIN, "X-Request-ID": "req_test"})
    assert r.status_code == 500
    assert r.headers.get("access-control-allow-origin") == ORIGIN
    body = r.json()
    assert body["code"] == "internal_error" and body["request_id"] == "req_test"
    assert "Lỗi máy chủ" in body["detail"] and "event loop" not in body["detail"]


def test_gateway_error_is_502_with_vietnamese_reason(client):
    r = client.get("/__m13/gw", headers={"Origin": ORIGIN})
    assert r.status_code == 502 and r.json()["code"] == "openclaw_error"
    assert r.headers.get("access-control-allow-origin") == ORIGIN
    assert "Gateway OpenClaw trả lỗi" in r.json()["detail"]


def test_http_exceptions_are_untouched(client):
    assert client.get("/api/v19/openclaw/doctor").status_code in (401, 403)


# --- /health báo schema ---------------------------------------------------

def _engine_with(rev):
    eng = create_engine("sqlite://")
    if rev is not None:
        with eng.begin() as c:
            c.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(64))"))
            c.execute(text("INSERT INTO alembic_version VALUES (:r)"), {"r": rev})
    return eng


def test_code_has_exactly_one_head():
    assert len(schema_status.code_heads()) == 1


def test_schema_ok_behind_unmanaged():
    head = schema_status.code_heads()[0]
    assert schema_status.status(_engine_with(head))["schema"] == "ok"
    behind = schema_status.status(_engine_with("0023_old"))
    assert behind["schema"] == "behind" and "alembic upgrade head" in behind["fix"]
    assert schema_status.status(_engine_with(None))["schema"] == "unmanaged"


def test_health_degrades_when_schema_is_behind(client, monkeypatch):
    monkeypatch.setattr(schema_status, "status", lambda engine: {"schema": "behind", "db": ["a"], "code": ["b"]})
    body = client.get("/health").json()
    assert body["status"] == "degraded" and body["schema"]["schema"] == "behind"
    monkeypatch.setattr(schema_status, "status", lambda engine: {"schema": "ok", "db": ["b"], "code": ["b"]})
    assert client.get("/health").json()["status"] == "ok"


# --- bỏ chế độ gateway cũ -------------------------------------------------

def test_legacy_gateway_mode_means_native_not_mock(monkeypatch):
    assert factory.resolve_mode("gateway") == "native"
    assert factory.resolve_mode(" Native ") == "native"
    assert factory.resolve_mode("mock") == "mock"
    monkeypatch.setattr(settings, "openclaw_mode", "gateway")
    assert isinstance(factory.get_runtime(), NativeOpenClawRuntime)
    monkeypatch.setattr(settings, "openclaw_mode", "mock")
    assert isinstance(factory.get_runtime(), MockOpenClawRuntime)
    with pytest.raises(ImportError):
        import app.runtime.gateway  # noqa: F401


# --- doctor ---------------------------------------------------------------

@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    s = sessionmaker(bind=engine, autoflush=False, autocommit=False)()
    yield s
    s.close()


@pytest.fixture()
def world(db):
    org = Organization(name="Nova", slug="nova"); db.add(org); db.commit(); db.refresh(org)
    co = Company(organization_id=org.id, name="Labs", industry="AI", status="active"); db.add(co); db.commit()
    nina = Member(organization_id=org.id, company_id=co.id, name="Nina", member_type="agent", role="CoS", status="active")
    db.add(nina); db.commit(); db.refresh(nina)
    db.add(Agent(member_id=nina.id, runtime_provider="openclaw", runtime_agent_id="nina", lifecycle="active")); db.commit()
    project = Project(company_id=co.id, name="P", status="active", progress=0); db.add(project); db.commit()
    task = Task(project_id=project.id, title="T", assignee_member_id=nina.id, status="in_progress",
                priority="high", runtime_run_id="run-1", runtime_session_key=ocp.task_session_key("nina", 1))
    db.add(task); db.commit(); db.refresh(task)
    return {"org": org, "task": task}


class _GW:
    def __init__(self, fail=None, models=None, roster=("main", "nina"), skill=True, raw_config=None):
        self.raw_config = raw_config
        self.fail = fail or {}
        self.models = models if models is not None else [
            {"id": "gpt-4.1-mini", "provider": "comet", "available": True, "tags": ["default"]}]
        self.roster = roster
        self.skill = skill

    async def rpc(self, method, params=None):
        if method in self.fail:
            raise self.fail[method]
        if method == ocp.M_STATUS:
            return {"runtimeVersion": "2026.9.8"}
        if method == ocp.M_MODELS_LIST:
            return {"models": self.models}
        if method == "config.get":
            if self.raw_config is None:
                raise OpenClawProtocolError("missing scope", {"code": "FORBIDDEN"})
            return {"raw": self.raw_config}
        if method == "skills.status":
            return {"skills": [{"name": "clawcompany-heartbeat"}] if self.skill else []}
        return {}

    async def list_agents(self):
        return [{"id": a} for a in self.roster]


@pytest.fixture()
def native(monkeypatch):
    monkeypatch.setattr(settings, "openclaw_mode", "native")
    monkeypatch.setattr(settings, "openclaw_api_token", "t")
    monkeypatch.setattr(settings, "openclaw_request_approvals_scope", True)
    monkeypatch.setattr(schema_status, "status", lambda engine: {"schema": "ok", "db": ["h"], "code": ["h"]})
    from app.services import heartbeat_policy
    monkeypatch.setattr(heartbeat_policy, "SKILL_SLUG", "clawcompany-heartbeat")


def _doc(db, world, gw):
    return asyncio.run(openclaw_doctor.run(db, gw, world["org"].id))


def _by_id(out):
    return {c["id"]: c for c in out["checks"]}


def test_doctor_all_green(db, world, native):
    out = _doc(db, world, _GW())
    assert out["status"] == "ok", out
    c = _by_id(out)
    assert "2026.9.8" in c["connect"]["detail"] and "comet/gpt-4.1-mini" in c["model"]["detail"]


def test_doctor_pairing_failure_stops_early_with_fix(db, world, native):
    err = OpenClawProtocolError("Gateway chưa duyệt thiết bị ClawCompany.", {"code": "PAIRING_REQUIRED"})
    out = _doc(db, world, _GW(fail={ocp.M_STATUS: err}))
    c = _by_id(out)
    assert out["status"] == "fail" and c["connect"]["status"] == "fail"
    assert "openclaw devices approve" in c["connect"]["fix"]
    assert "model" not in c  # không kết nối được thì không kiểm tiếp


def test_doctor_refused_connection_points_to_container(db, world, native):
    out = _doc(db, world, _GW(fail={ocp.M_STATUS: ConnectionRefusedError(111, "refused")}))
    assert "docker compose ps openclaw" in _by_id(out)["connect"]["fix"]


def test_doctor_no_model_is_a_failure(db, world, native):
    out = _doc(db, world, _GW(models=[]))
    assert _by_id(out)["model"]["status"] == "fail" and out["status"] == "fail"


def test_doctor_orphan_seat_and_missing_skill_are_warnings(db, world, native):
    out = _doc(db, world, _GW(roster=("main",), skill=False))
    c = _by_id(out)
    assert c["agents"]["status"] == "warn" and "nina" in c["agents"]["detail"]
    assert c["heartbeat"]["status"] == "skip"  # ghế duy nhất đã lệch thì không có gì để kiểm


def test_doctor_checks_heartbeat_on_bound_seats_and_offers_install(db, world, native):
    out = _doc(db, world, _GW(skill=False))
    c = _by_id(out)["heartbeat"]
    assert c["status"] == "warn" and "nina" in c["detail"] and "main" not in c["detail"]
    assert c["action"]["path"] == "/v19/openclaw/heartbeat-skill"
    assert "action" not in _by_id(_doc(db, world, _GW()))["heartbeat"]


def test_doctor_in_mock_mode_says_agents_are_simulated(db, world, native, monkeypatch):
    monkeypatch.setattr(settings, "openclaw_mode", "mock")
    out = _doc(db, world, _GW())
    c = _by_id(out)
    assert c["mode"]["status"] == "fail" and "OPENCLAW_MODE=native" in c["mode"]["fix"]
    assert "connect" not in c


def test_doctor_reports_schema_behind(db, world, native, monkeypatch):
    monkeypatch.setattr(schema_status, "status", lambda engine: {
        "schema": "behind", "db": ["0023"], "code": ["0027"], "fix": "Chạy: alembic upgrade head"})
    c = _by_id(_doc(db, world, _GW()))
    assert c["schema"]["status"] == "fail" and "upgrade head" in c["schema"]["fix"]


# --- follower tự nối lại --------------------------------------------------

class _Flaky:
    def __init__(self, script):
        self.script = list(script)
        self.subscribes = 0

    async def stream_run(self, key):
        self.subscribes += 1
        step = self.script.pop(0)
        if isinstance(step, BaseException):
            raise step
        for event in step:
            yield event


def _run_consume(db, world, monkeypatch, runtime, max_reconnects=6):
    monkeypatch.setattr(settings, "openclaw_stream_max_reconnects", max_reconnects)
    monkeypatch.setattr(settings, "openclaw_stream_backoff_seconds", 0.0)
    monkeypatch.setattr(rs, "get_runtime", lambda: runtime)
    monkeypatch.setattr(rs, "SessionLocal", lambda: db)
    monkeypatch.setattr(db, "close", lambda: None)
    catchups = []

    async def no_catch_up(db_, rt, state, apply):
        catchups.append(state.reconnects)
        return {"terminal": False}

    async def noop(*a, **k):
        return {}
    monkeypatch.setattr(stream_catchup, "catch_up", no_catch_up)
    monkeypatch.setattr(rs.stream_reconcile, "reconcile", noop)
    monkeypatch.setattr(rs, "handle_event", lambda db_, state, event: None)
    monkeypatch.setattr(rs.lease_store, "renew", lambda key: True)
    state = rs.ConsumerState(session_key=world["task"].runtime_session_key,
                             task_id=world["task"].id, organization_id=world["org"].id)
    asyncio.run(rs._consume(state))
    return state, catchups


FINAL = [{"type": "chat.final", "terminal": True}]


def test_gateway_restart_mid_run_reconnects_and_finishes(db, world, monkeypatch):
    import websockets
    closed = websockets.exceptions.ConnectionClosedError(None, None)
    rt = _Flaky([closed, ConnectionRefusedError(111, "refused"), FINAL])
    state, catchups = _run_consume(db, world, monkeypatch, rt)
    assert state.status == "finished" and state.reconnects == 2 and rt.subscribes == 3
    assert catchups == [0, 1, 2]  # bắt kịp trước MỖI lần nghe lại


def test_protocol_error_is_not_retried(db, world, monkeypatch):
    rt = _Flaky([OpenClawProtocolError("bad params"), FINAL])
    state, _ = _run_consume(db, world, monkeypatch, rt)
    assert state.status == "failed" and rt.subscribes == 1


def test_gives_up_after_max_reconnects(db, world, monkeypatch):
    rt = _Flaky([OSError("down")] * 3 + [FINAL])
    state, _ = _run_consume(db, world, monkeypatch, rt, max_reconnects=2)
    assert state.status == "failed" and rt.subscribes == 3


def test_idle_timeout_does_not_count_as_failure(db, world, monkeypatch):
    rt = _Flaky([asyncio.TimeoutError(), asyncio.TimeoutError(), FINAL])
    state, _ = _run_consume(db, world, monkeypatch, rt, max_reconnects=0)
    assert state.status == "finished" and state.reconnects == 2


def test_events_reset_the_failure_budget(db, world, monkeypatch):
    class Mid(_Flaky):
        async def stream_run(self, key):
            self.subscribes += 1
            step = self.script.pop(0)
            if step == "event-then-drop":
                yield {"type": "agent"}
                raise OSError("drop")
            if isinstance(step, BaseException):
                raise step
            for e in step:
                yield e
    rt = Mid([OSError("a"), "event-then-drop", OSError("b"), FINAL])
    state, _ = _run_consume(db, world, monkeypatch, rt, max_reconnects=2)
    assert state.status == "finished" and state.reconnects == 3


def test_doctor_explains_disabled_uploads_instead_of_offering_a_failing_button(db, world, native):
    out = _doc(db, world, _GW(skill=False, raw_config='{"gateway": {"mode": "local"}}'))
    c = _by_id(out)["heartbeat"]
    assert "action" not in c and "allowUploadedArchives true" in c["fix"]
    ok = _doc(db, world, _GW(skill=False, raw_config='{"skills": {"install": {"allowUploadedArchives": true}}}'))
    assert "action" in _by_id(ok)["heartbeat"]
