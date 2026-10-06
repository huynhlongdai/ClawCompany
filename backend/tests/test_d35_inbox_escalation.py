"""D3.5 — Hộp việc gộp theo task + approval hết hạn / leo thang. ORM thật,
HTTP thật (TestClient + JWT), approval tạo bằng nhiều đường khác nhau."""
import json
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.security import create_access_token
from app.db.base import Base
import app.models  # noqa: F401
from app.db.session import get_db
from app.main import app
from app.models import Approval, AuditEvent, CompanyEvent
from app.models.auth import User
from app.models.entities import Agent, Company, Member, Organization, Project, Task
from app.models.extended import InboxItem
from app.services import inbox, task_journal, task_lifecycle as lifecycle
from app.services import runtime_stream as stream


@pytest.fixture()
def env():
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
    org = Organization(name="Nova", slug="nova-d35"); db.add(org); db.commit()
    co = Company(organization_id=org.id, name="Nova", status="active"); db.add(co); db.commit()
    long_ = Member(organization_id=org.id, company_id=co.id, name="Long", member_type="human", role="CEO", status="active")
    db.add(long_); db.commit()
    minh = Member(organization_id=org.id, company_id=co.id, name="Minh", member_type="human", role="Trưởng nhóm",
                  status="active", manager_id=long_.id)
    db.add(minh); db.commit()
    mia = Member(organization_id=org.id, company_id=co.id, name="Mia", member_type="agent", role="AI", status="active",
                 manager_id=minh.id)
    db.add(mia); db.commit()
    db.add(Agent(member_id=mia.id, runtime_agent_id="mia", lifecycle="active")); db.commit()
    proj = Project(company_id=co.id, name="P", status="active"); db.add(proj); db.commit()
    t = Task(project_id=proj.id, title="Viết bài ra mắt", status="in_progress", assignee_member_id=mia.id)
    db.add(t); db.commit()
    users = {}
    for m, email in ((long_, "long@nova.test"), (minh, "minh@nova.test")):
        u = User(email=email, password_hash="x", member_id=m.id); db.add(u); db.commit()
        users[m.name] = {"Authorization": f"Bearer {create_access_token(u.id, org.id, 'admin')}"}
    yield {"db": db, "org": org, "co": co, "long": long_, "minh": minh, "mia": mia, "proj": proj, "t": t,
           "client": TestClient(app), "H": users}
    app.dependency_overrides.pop(get_db, None)


def _items(env, member=None):
    env["db"].expire_all()
    q = env["db"].query(InboxItem)
    if member is not None:
        q = q.filter(InboxItem.recipient_member_id == env[member].id)
    return q.order_by(InboxItem.id).all()


def _approval(env, **kw):
    kw.setdefault("organization_id", env["org"].id)
    kw.setdefault("company_id", env["co"].id)
    kw.setdefault("requester_member_id", env["mia"].id)
    kw.setdefault("action", "Chi $50 quảng cáo")
    kw.setdefault("status", "pending")
    a = Approval(**kw)
    env["db"].add(a); env["db"].commit(); env["db"].refresh(a)
    return a


def test_new_approval_gets_24h_deadline_escalation_target_and_inbox_for_human_manager(env):
    before = datetime.utcnow()
    a = _approval(env)
    assert before + timedelta(hours=23.9) <= a.expires_at <= datetime.utcnow() + timedelta(hours=24.1)
    assert a.escalate_to_member_id == env["long"].id        # quản lý của Minh
    items = _items(env)
    assert [(i.recipient_member_id, i.item_type, i.related_id) for i in items] == [
        (env["minh"].id, "approval_pending", str(a.id))]     # agent Mia không nhận; quản lý của Mia nhận


def test_agent_approver_routes_to_its_human_manager_and_agents_never_get_inbox(env):
    a = _approval(env, approver_member_id=env["mia"].id, policy_key=f"task_stage:t{env['t'].id}:r1:s0")
    items = _items(env)
    assert {i.recipient_member_id for i in items} == {env["minh"].id}
    assert items[0].task_id == env["t"].id and items[0].group_key == f"task:{env['t'].id}"
    assert env["db"].query(InboxItem).filter(InboxItem.recipient_member_id == env["mia"].id).count() == 0
    assert a.escalate_to_member_id == env["long"].id


def test_gateway_approval_uses_gateway_expiry_and_is_not_escalated(env):
    ms = (datetime.utcnow() - timedelta(minutes=1)).timestamp() * 1000
    a = _approval(env, policy_key="openclaw:exec:abc",
                  evidence=json.dumps({"task_id": env["t"].id, "expires_at_ms": ms}))
    assert abs((a.expires_at - datetime.utcfromtimestamp(ms / 1000)).total_seconds()) < 1
    assert a.escalate_to_member_id is None
    assert inbox.escalate_overdue(env["db"]) == []
    env["db"].refresh(a)
    assert a.escalated_at is None and a.approver_member_id is None


def test_events_for_one_task_group_into_one_row(env):
    db, t = env["db"], env["t"]
    _approval(env, policy_key=f"task_stage:t{t.id}:r1:s0", approver_member_id=env["minh"].id)
    inbox.run_failed(db, t, "gateway timeout")
    task_journal.append(db, t, kind="note", summary="@Minh xem giúp đoạn mở bài", actor_member_id=env["mia"].id)
    rows = _items(env, "minh")
    assert len(rows) == 1
    row = rows[0]
    assert row.count == 3 and row.kinds.split(",") == ["approval_pending", "run_failed", "mention"]
    assert row.priority == "high" and row.status == "unread" and len(row.body.splitlines()) == 3
    # đã đọc → có báo mới thì quay lại chưa đọc, vẫn một dòng
    row.status = "read"; db.commit()
    lifecycle.transition(db, t, "review", system=True, reason="xong bản nháp")
    rows = _items(env, "minh")
    assert len(rows) == 1 and rows[0].count == 4 and rows[0].status == "unread" and "task_review" in rows[0].kinds
    # xong → báo sau mở dòng mới
    rows[0].status = "done"; db.commit()
    inbox.run_failed(db, t, "lại lỗi")
    assert len(_items(env, "minh")) == 2


def test_task_review_goes_to_human_stage_reviewer(env):
    db, t = env["db"], env["t"]
    t.execution_policy = {"stages": [{"type": "review", "participants": [env["long"].id]}]}
    db.commit()
    lifecycle.transition(db, t, "review", system=True, reason="nộp")
    got = {(i.recipient_member_id, i.item_type) for i in _items(env)}
    assert (env["long"].id, "task_review") in got


def test_run_error_from_gateway_blocks_task_and_notifies_manager(env):
    db, t = env["db"], env["t"]
    t.runtime_session_key = "agent:mia:company-task-1"; db.commit()
    state = stream.ConsumerState(session_key=t.runtime_session_key, task_id=t.id, organization_id=env["org"].id)
    stream.handle_event(db, state, {"type": "chat", "family": "chat", "state": "error", "terminal": True,
                                    "errorMessage": "model quota exceeded"})
    db.expire_all(); db.refresh(t)
    assert t.status == "blocked"
    rows = _items(env, "minh")
    assert len(rows) == 1 and rows[0].item_type == "run_failed" and "model quota exceeded" in rows[0].body


def test_overdue_approval_escalates_to_manager_with_audit_then_next_level(env):
    db = env["db"]
    a = _approval(env, approver_member_id=env["minh"].id)
    assert a.escalate_to_member_id == env["long"].id
    now = datetime.utcnow() + timedelta(hours=25)
    out = inbox.escalate_overdue(db, now=now)
    assert [r["approval_id"] for r in out] == [a.id] and out[0]["to_member_id"] == env["long"].id
    db.expire_all(); db.refresh(a)
    assert a.approver_member_id == env["long"].id and a.escalated_at == now
    assert a.expires_at == now + timedelta(hours=24) and a.status == "pending"
    audit = db.query(AuditEvent).filter(AuditEvent.action == "approval.escalated").one()
    p = json.loads(audit.payload_json) if hasattr(audit, "payload_json") else json.loads(audit.payload)
    assert p["from_member_id"] == env["minh"].id and p["to_member_id"] == env["long"].id
    assert db.query(CompanyEvent).filter(CompanyEvent.event_type == "approval.escalated").count() == 1
    esc = [i for i in _items(env, "long") if i.item_type == "approval_escalated"]
    assert len(esc) == 1 and esc[0].priority == "high"
    # chạy lại ngay: không leo thang hai lần
    assert inbox.escalate_overdue(db, now=now + timedelta(minutes=1)) == []
    # Long là đỉnh — quá hạn tiếp thì ghi audit thất bại, dời hạn, không spam
    out = inbox.escalate_overdue(db, now=now + timedelta(hours=25))
    assert out == [{"approval_id": a.id, "escalated": False, "reason": "no_manager"}]
    assert db.query(AuditEvent).filter(AuditEvent.action == "approval.escalation_failed").count() == 1
    assert inbox.escalate_overdue(db, now=now + timedelta(hours=25, minutes=1)) == []


def test_resolve_closes_inbox_row_and_api_views(env):
    db, c, H = env["db"], env["client"], env["H"]
    a = _approval(env, approver_member_id=env["minh"].id)
    r = c.get("/api/v9/approvals/quick", headers=H["Minh"])
    assert r.status_code == 200
    q = r.json()["approvals"]
    assert [x["id"] for x in q] == [a.id] and q[0]["is_mine"] and 86000 < q[0]["seconds_left"] <= 86400
    assert c.get("/api/v9/approvals/quick", headers=H["Long"]).json()["approvals"] == []
    mine = c.get("/api/v9/inbox/mine", headers=H["Minh"]).json()
    assert mine["unread"] == 1 and mine["items"][0]["kinds"] == ["approval_pending"]
    assert c.get("/api/v9/inbox/mine", headers=H["Long"]).json()["items"] == []
    r = c.post(f"/api/approvals/{a.id}/resolve", headers=H["Minh"], json={"status": "approved", "resolution_note": "ok"})
    assert r.status_code == 200, r.text
    rows = _items(env, "minh")
    assert rows[0].status == "done" and "approved" in rows[0].body
    assert c.get("/api/v9/inbox/mine", headers=H["Minh"]).json()["items"] == []
    # đổi trạng thái tay; không sửa được hộp việc của người khác
    r = c.post(f"/api/v9/inbox/{rows[0].id}/status", headers=H["Long"], json={"status": "read"})
    assert r.status_code == 403
    r = c.post(f"/api/v9/inbox/{rows[0].id}/status", headers=H["Minh"], json={"status": "read"})
    assert r.status_code == 200 and r.json()["status"] == "read"


def test_escalate_endpoint_and_quick_view_after_escalation(env):
    db, c, H = env["db"], env["client"], env["H"]
    a = _approval(env, approver_member_id=env["minh"].id)
    a.expires_at = datetime.utcnow() - timedelta(minutes=5); db.commit()
    r = c.post("/api/v9/approvals/escalate-overdue", headers=H["Long"])
    assert r.status_code == 200 and r.json()["escalated"][0]["to_member_id"] == env["long"].id
    q = c.get("/api/v9/approvals/quick", headers=H["Long"]).json()["approvals"]
    assert q[0]["id"] == a.id and q[0]["escalated_at"] and q[0]["is_mine"]
    # Minh vẫn thấy (có dòng inbox) nhưng không còn là người duyệt
    q2 = c.get("/api/v9/approvals/quick", headers=H["Minh"]).json()["approvals"]
    assert q2[0]["id"] == a.id and q2[0]["is_mine"] is False
