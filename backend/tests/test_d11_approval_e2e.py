"""D1.1 — approval đầu–cuối: exec bị chặn → hàng approvals → duyệt trong Hộp
việc → ``exec.approval.resolve`` → gateway xác nhận → ``audit_events`` đủ ba mốc.

Frame dùng ở đây là frame THẬT ghi từ gateway OpenClaw 2026.9.8 (băng ghi
``OPENCLAW_FRAME_LOG``, xem ``_reports/approval-e2e.md``), cắt bớt trường
không liên quan. Bốn lỗi mà phép thử thật tìm ra đều có test ở đây:

1. Nút Duyệt của Hộp việc chỉ đổi cột status, không gửi gì cho gateway.
2. Hàng duyệt ghi "action" thay vì lệnh (lệnh nằm trong ``request.command``).
3. Frame resolved mang ``allow-once`` — không có trong danh sách từ cũ — nên
   hàng đã duyệt bị nhân đôi thành một hàng pending mới.
4. Lượt chạy kết thúc bằng ``chat`` state ``final``; thiếu nó follower không
   dừng và việc kẹt ở in_progress.
"""
import asyncio

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.core.security import create_access_token
from app.db.base import Base
import app.models  # noqa: F401
from app.db.session import get_db
from app.main import app
from app.models import Approval, AuditEvent
from app.models.auth import User
from app.models.entities import Company, Member, Organization, Project, Task
from app.runtime import openclaw_protocol as ocp
from app.runtime.openclaw_native import NativeOpenClawRuntime, normalize_event
from app.services import approval_bridge, runtime_stream as stream

SESSION = "agent:dev:company-task-13"
REQ_ID = "3a6d106d-ed9b-4afb-b3eb-309c326058a7"
# Nguyên văn (rút gọn) frame in của lượt chạy thật số 3.
REQUESTED = {"type": "event", "event": "exec.approval.requested", "payload": {
    "approvalKind": "exec", "id": REQ_ID,
    "request": {"command": "echo clawcompany-approval-e2e && date -u +%Y-%m-%dT%H:%M:%SZ",
                "cwd": "/data/oc/home/.openclaw/workspace-dev", "host": "gateway",
                "security": "allowlist", "ask": "on-miss",
                "commandAnalysis": {"commandCount": 2, "nestedCommandCount": 0, "riskKinds": [],
                                    "warningLines": []},
                "allowedDecisions": ["allow-once", "allow-always", "deny"], "agentId": "dev",
                "sessionKey": SESSION, "runId": "clawcompany:agent:dev:company-task-13:task-13:6f146b8bb155",
                "turnSourceChannel": "webchat"},
    "createdAtMs": 1791221619020, "expiresAtMs": 1791223419020}}
RESOLVED = {"type": "event", "event": "exec.approval.resolved", "payload": {
    "id": REQ_ID, "decision": "allow-once", "resolvedBy": "clawcompany", "ts": 1791221630000}}


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
    org = Organization(name="Nova", slug="nova-d11"); db.add(org); db.commit()
    co = Company(organization_id=org.id, name="Nova Labs", status="active"); db.add(co); db.commit()
    boss = Member(organization_id=org.id, company_id=co.id, name="Long", member_type="human",
                  role="CEO", status="active")
    nina = Member(organization_id=org.id, company_id=co.id, name="Nina", member_type="agent",
                  role="Chief of Staff", status="active")
    db.add_all([boss, nina]); db.commit()
    user = User(email="long@nova.test", password_hash="x", member_id=boss.id); db.add(user); db.commit()
    proj = Project(company_id=co.id, name="P"); db.add(proj); db.commit()
    task = Task(project_id=proj.id, title="Chạy lệnh", status="in_progress", assignee_member_id=nina.id,
                runtime_session_key=SESSION)
    db.add(task); db.commit()
    state = stream.ConsumerState(session_key=SESSION, task_id=task.id, organization_id=org.id)

    sent = []

    class Runtime:
        async def respond_approval(self, **kw):
            sent.append(kw)
            return {"id": kw["request_id"], "decision": kw["decision"]}

    monkeypatch.setattr(settings, "openclaw_request_approvals_scope", True, raising=False)
    monkeypatch.setattr(settings, "openclaw_approval_reply_method", ocp.M_EXEC_APPROVAL_RESOLVE, raising=False)
    monkeypatch.setattr(approval_bridge, "get_runtime", lambda: Runtime())
    token = create_access_token(user.id, org.id, "admin")
    yield {"db": db, "org": org, "nina": nina, "boss": boss, "task": task, "state": state, "sent": sent,
           "client": TestClient(app), "H": {"Authorization": f"Bearer {token}"}}
    app.dependency_overrides.pop(get_db, None)


def _feed(env, frame):
    stream.handle_event(env["db"], env["state"], normalize_event(frame))


def _trail(env, approval_id):
    env["db"].expire_all()
    return [a.action for a in env["db"].query(AuditEvent).filter(
        AuditEvent.object_type == "approval", AuditEvent.object_id == str(approval_id)).order_by(AuditEvent.id)]


def test_real_requested_frame_becomes_a_readable_row_and_first_milestone(env):
    _feed(env, REQUESTED)
    row = env["db"].query(Approval).one()
    assert row.status == "pending"
    assert row.policy_key == f"openclaw:{SESSION}:{REQ_ID}"
    assert row.action.startswith("Chạy lệnh: echo clawcompany-approval-e2e")  # không còn "action"
    assert _trail(env, row.id) == ["approval.requested"]
    _feed(env, REQUESTED)  # gateway/backfill phát lại → không nhân đôi
    assert env["db"].query(Approval).count() == 1
    assert _trail(env, row.id) == ["approval.requested"]


def test_inbox_button_relays_to_gateway_and_resolved_frame_closes_the_loop(env):
    _feed(env, REQUESTED)
    row = env["db"].query(Approval).one()
    r = env["client"].post(f"/api/approvals/{row.id}/resolve", headers=env["H"],
                           json={"status": "approved", "resolution_note": "ok"})
    assert r.status_code == 200, r.text
    # Đúng hợp đồng exec.approval.resolve: theo id, quyết định ba giá trị.
    assert env["sent"] == [{"request_id": REQ_ID, "decision": ocp.D_ALLOW_ONCE, "session_key": SESSION}]
    assert r.json()["status"] == "approved"
    assert "decision relayed to OpenClaw" in r.json()["resolution_note"]

    _feed(env, RESOLVED)  # gateway xác nhận
    env["db"].expire_all()
    rows = env["db"].query(Approval).all()
    assert len(rows) == 1, "allow-once không được sinh ra một hàng pending thứ hai"
    assert rows[0].status == "approved" and "[gateway: allow-once]" in rows[0].resolution_note
    assert _trail(env, row.id) == ["approval.requested", "approval.decided", "approval.resolved"]
    _feed(env, RESOLVED)
    assert _trail(env, row.id).count("approval.resolved") == 1


def test_inbox_reject_sends_deny(env):
    _feed(env, REQUESTED)
    row = env["db"].query(Approval).one()
    r = env["client"].post(f"/api/approvals/{row.id}/resolve", headers=env["H"],
                           json={"status": "rejected", "resolution_note": "không"})
    assert r.status_code == 200, r.text
    assert env["sent"][0]["decision"] == ocp.D_DENY
    again = env["client"].post(f"/api/approvals/{row.id}/resolve", headers=env["H"],
                               json={"status": "approved", "resolution_note": ""})
    assert again.status_code == 409  # đã quyết rồi, không gửi lần hai
    assert len(env["sent"]) == 1


def test_decision_made_in_openclaw_ui_still_closes_the_row(env):
    _feed(env, REQUESTED)
    _feed(env, {"type": "event", "event": "exec.approval.resolved",
                "payload": {"id": REQ_ID, "decision": "deny"}})
    row = env["db"].query(Approval).one()
    assert row.status == "rejected"
    assert _trail(env, row.id) == ["approval.requested", "approval.resolved"]


def test_non_gateway_approvals_keep_local_resolution_with_audit(env):
    db = env["db"]
    row = Approval(organization_id=env["org"].id, action="tool:company_event_emit", risk="medium",
                   status="pending", policy_key="tool:company_event_emit", evidence="{}")
    db.add(row); db.commit()
    r = env["client"].post(f"/api/approvals/{row.id}/resolve", headers=env["H"],
                           json={"status": "approved", "resolution_note": ""})
    assert r.status_code == 200 and r.json()["status"] == "approved"
    assert env["sent"] == []
    assert _trail(env, row.id) == ["approval.decided"]


def test_chat_final_ends_the_run_and_moves_task_to_review(env):
    ev = normalize_event({"type": "event", "event": "chat", "payload": {
        "runId": "r1", "sessionKey": SESSION, "state": "final", "seq": 17}})
    assert ev["terminal"] is True
    stream.handle_event(env["db"], env["state"], ev)
    env["db"].refresh(env["task"])
    assert env["task"].status == "review"


def test_connect_declares_exec_approvals_only_when_opted_in(monkeypatch):
    rt = NativeOpenClawRuntime()
    monkeypatch.setattr(settings, "openclaw_request_approvals_scope", True, raising=False)
    params = rt._connect_params()
    assert params["caps"] == ["exec-approvals"] and "operator.approvals" in params["scopes"]
    monkeypatch.setattr(settings, "openclaw_request_approvals_scope", False, raising=False)
    assert "caps" not in rt._connect_params()


def test_readiness_says_cards_need_admin_scope(monkeypatch):
    monkeypatch.setattr(settings, "openclaw_request_approvals_scope", True, raising=False)
    monkeypatch.setattr(settings, "openclaw_request_admin_scope", False, raising=False)
    card = approval_bridge.upstream_readiness()["card_delivery"]
    assert card["ready"] is False and card["needs"] == ["OPENCLAW_REQUEST_ADMIN_SCOPE"]
    monkeypatch.setattr(settings, "openclaw_request_admin_scope", True, raising=False)
    assert approval_bridge.upstream_readiness()["card_delivery"]["ready"] is True


def test_resolved_frame_racing_the_rpc_keeps_human_attribution_and_order(env, monkeypatch):
    """Đo trên gateway thật: ``exec.approval.resolved`` tới follower TRƯỚC khi
    ``exec.approval.resolve`` trả lời. Follower dùng session DB riêng."""
    _feed(env, REQUESTED)
    row = env["db"].query(Approval).one()
    Maker = sessionmaker(bind=env["db"].get_bind(), autoflush=False)

    class Racing:
        async def respond_approval(self, **kw):
            other = Maker()
            try:
                stream.handle_event(other, env["state"], normalize_event(RESOLVED))
            finally:
                other.close()
            return {"ok": True}

    monkeypatch.setattr(approval_bridge, "get_runtime", lambda: Racing())
    r = env["client"].post(f"/api/approvals/{row.id}/resolve", headers=env["H"],
                           json={"status": "approved", "resolution_note": "ok"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "approved" and body["approver_member_id"] == env["boss"].id
    assert "decision relayed to OpenClaw" in body["resolution_note"]
    assert "[gateway: allow-once]" in body["resolution_note"]
    assert "Resolved in OpenClaw" not in body["resolution_note"]
    assert _trail(env, row.id) == ["approval.requested", "approval.decided", "approval.resolved"]
