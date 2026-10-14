"""M4b — /api/inbox + /api/costs: Hộp việc gộp nhóm, duyệt một chạm (đua, revision cũ, sai người duyệt),
leo thang quá hạn (có / không có cấp trên), ngân sách ba nấc (cảnh báo → dừng mềm cần duyệt → dừng cứng)
chặn dispatch thật. ORM thật (SQLite) + HTTP thật; runtime giả chỉ ghi lời gọi chat.send."""
import asyncio
import json
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.authz import Principal
from app.core.security import create_access_token, hash_password
from app.db.base import Base
import app.models  # noqa: F401
from app.db.session import get_db
from app.main import app
from app.models import (Agent, Approval, AuditEvent, BudgetEnvelope, Company, Department, Member, Organization,
                        Project, Task, TaskRun, UsageEvent, User, UserOrganizationAccess, Wakeup)
from app.models.extended import InboxItem
from app.services import budget_scope, inbox_hub, wakeup
from app.services.work_board import WorkError


class FakeRuntime:
    def __init__(self):
        self.calls, self.approvals = [], []

    async def run_agent(self, runtime_agent_id, input_text, metadata=None, session_key=None):
        from app.runtime.base import RuntimeRun
        self.calls.append({"agent": runtime_agent_id, "session_key": session_key})
        return RuntimeRun(task_id="t", run_id=f"run-{len(self.calls)}", session_key=session_key or "",
                          status="running", raw={})

    async def respond_approval(self, request_id, decision, session_key=None):
        self.approvals.append({"request_id": request_id, "decision": decision})
        return {"ok": True}


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
    rt = FakeRuntime()
    monkeypatch.setattr("app.services.agent_dispatch.get_runtime", lambda: rt)
    monkeypatch.setattr("app.services.approval_bridge.get_runtime", lambda: rt)

    async def no_hours(agent):
        return None
    monkeypatch.setattr(wakeup, "ACTIVE_HOURS_LOOKUP", no_hours)
    org = Organization(name="Nova M4b", slug="nova-m4b"); other = Organization(name="Khác", slug="khac-m4b")
    db.add_all([org, other]); db.commit()
    co = Company(organization_id=org.id, name="Nova Shop", status="active"); db.add(co); db.commit()
    co2 = Company(organization_id=other.id, name="Khác", status="active"); db.add(co2); db.commit()
    mkt = Department(company_id=co.id, name="Marketing"); db.add(mkt); db.commit()

    def human(name, role, manager=None, company=co):
        m = Member(organization_id=company.organization_id, company_id=company.id, name=name, member_type="human",
                   role=role, status="active", manager_id=manager.id if manager else None)
        db.add(m); db.commit()
        return m

    boss = human("Chị Lan", "CEO")
    hung = human("Anh Hùng", "Trưởng marketing", boss)
    minh = human("Minh", "Nhân viên", hung)
    stranger = human("Người ngoài", "CEO", company=co2)

    def seat(name, rid, manager, dept=None):
        m = Member(organization_id=org.id, company_id=co.id, name=name, member_type="agent", role="AI",
                   status="active", manager_id=manager.id, department_id=dept)
        db.add(m); db.commit()
        db.add(Agent(member_id=m.id, runtime_agent_id=rid, lifecycle="active")); db.commit()
        return m

    mai = seat("Mai Anh", "mai-anh", hung, mkt.id)
    lam = seat("Lâm", "lam", hung)
    proj = Project(company_id=co.id, name="BST hè", status="active"); db.add(proj); db.commit()
    users = {}
    for key, member, role, org_id in (("boss", boss, "owner", org.id), ("hung", hung, "manager", org.id),
                                      ("minh", minh, "member", org.id), ("stranger", stranger, "owner", other.id)):
        u = User(email=f"{key}@m4b.test", password_hash=hash_password("Matkhau123"), display_name=member.name,
                 member_id=member.id)
        db.add(u); db.commit()
        db.add(UserOrganizationAccess(user_id=u.id, organization_id=org_id, role=role, is_default=True,
                                      status="active"))
        db.commit(); users[key] = (u, role, org_id)

    def tok(key):
        u, role, org_id = users[key]
        return {"Authorization": "Bearer " + create_access_token(u.id, org_id, role)}

    def principal(key):
        u, role, org_id = users[key]
        return Principal(u.id, org_id, role, "jwt", [], u.member_id)

    yield type("E", (), dict(db=db, Maker=Maker, org=org, other=other, co=co, co2=co2, mkt=mkt, boss=boss,
                             hung=hung, minh=minh, stranger=stranger, mai=mai, lam=lam, proj=proj, rt=rt,
                             tok=staticmethod(tok), principal=staticmethod(principal), c=TestClient(app)))
    app.dependency_overrides.pop(get_db, None)


def approval(env, *, approver=None, requester=None, org=None, **kw):
    a = Approval(organization_id=(org or env.org).id, company_id=env.co.id,
                 requester_member_id=(requester or env.mai).id,
                 approver_member_id=approver.id if approver else None,
                 action=kw.pop("action", "Đăng 5 bài lên fanpage"), risk=kw.pop("risk", "medium"),
                 status="pending", evidence=kw.pop("evidence", "Bài đã soạn xong, chờ đăng"), **kw)
    env.db.add(a); env.db.commit(); env.db.refresh(a)
    return a


def task(env, title="Viết 5 caption", assignee=None, status="todo"):
    t = Task(project_id=env.proj.id, title=title, status=status,
             assignee_member_id=(assignee or env.mai).id)
    env.db.add(t); env.db.commit(); env.db.refresh(t)
    return t


def feed(env, who, **params):
    r = env.c.get("/api/inbox/items", params=params, headers=env.tok(who))
    assert r.status_code == 200, r.text
    return r.json()


def cards(body, group=None):
    return [c for g in body["groups"] for c in g["items"] if group is None or g["key"] == group]


def decide(env, who, aid, decision="approve", note="", expect=200, **kw):
    r = env.c.post(f"/api/inbox/approvals/{aid}/decide", json={"decision": decision, "note": note, **kw},
                   headers=env.tok(who))
    assert r.status_code == expect, r.text
    return r.json()


def drain(env):
    env.db.expire_all()
    return asyncio.run(wakeup.drain(env.db, now=datetime.utcnow() + timedelta(seconds=11)))


def enqueue(env, t, member=None):
    wakeup.enqueue(env.db, organization_id=env.org.id, member_id=(member or env.mai).id, reason="assigned",
                   task_id=t.id, dedupe_key=f"assigned:{t.id}:{datetime.utcnow().timestamp()}")


# ------------------------------------------------------------------ hộp việc: nhóm, đếm, tách người


def test_feed_groups_counts_and_keeps_each_persons_inbox_private(env):
    a = approval(env, approver=env.hung)
    t = task(env)
    from app.services import inbox
    inbox.notify(env.db, organization_id=env.org.id, recipients=[env.hung.id], kind="task_review",
                 title=f"Task #{t.id} chờ review", task_id=t.id, related_type="task", related_id=str(t.id))
    inbox.notify(env.db, organization_id=env.org.id, recipients=[env.hung.id], kind="budget_warned",
                 title="Ngân sách 80%", related_type="budget_envelope", related_id="9", priority="high")
    inbox.notify(env.db, organization_id=env.org.id, recipients=[env.hung.id], kind="mention",
                 title="Minh nhắc anh", related_type="note", related_id="1")
    approval(env, approver=env.stranger, org=env.other, requester=env.stranger)   # tổ chức khác

    body = feed(env, "hung")
    assert [g["key"] for g in body["groups"]] == ["approvals", "review", "budget", "lessons", "updates"]
    assert [g["label"] for g in body["groups"]] == ["Cần anh duyệt", "Cần anh xem", "Ngân sách", "Bài học đề xuất",
                                                    "Thông báo"]
    ap = cards(body, "approvals")
    assert len(ap) == 1 and ap[0]["approval"]["id"] == a.id and ap[0]["approval"]["can_decide"]
    assert ap[0]["approval"]["requester"] == "Mai Anh" and ap[0]["approval"]["summary"] == "Bài đã soạn xong, chờ đăng"
    assert ap[0]["approval"]["deadline_vi"].startswith("Còn 23 giờ")
    assert [c["task"]["id"] for c in cards(body, "review")] == [t.id]
    assert len(cards(body, "budget")) == 1 and len(cards(body, "updates")) == 1
    assert body["counts"]["by_group"] == {"approvals": 1, "review": 1, "budget": 1, "lessons": 0, "updates": 1}
    assert body["counts"]["need_action"] == 2 and body["counts"]["unread"] == 4
    assert env.c.get("/api/inbox/summary", headers=env.tok("hung")).json()["need_action"] == 2
    only = feed(env, "hung", group="approvals")
    assert [g["key"] for g in only["groups"]] == ["approvals"]
    assert env.c.get("/api/inbox/items?group=xyz", headers=env.tok("hung")).json()["detail"]["error"] == "bad_group"
    # Minh không thấy hộp việc của Hùng; người tổ chức khác không thấy gì của Nova.
    assert cards(feed(env, "minh")) == []
    assert all(c["approval"] is None or c["approval"]["id"] != a.id for c in cards(feed(env, "stranger")))
    # Đánh dấu dòng của người khác → 403 tiếng Việt.
    iid = cards(body, "review")[0]["id"]
    r = env.c.post(f"/api/inbox/items/{iid}/status", json={"status": "done"}, headers=env.tok("minh"))
    assert r.status_code == 403 and r.json()["detail"]["message"] == "Mục này thuộc hộp việc của người khác"
    r = env.c.post(f"/api/inbox/items/{iid}/status", json={"status": "done"}, headers=env.tok("hung"))
    assert r.status_code == 200 and r.json()["status"] == "done"
    assert feed(env, "hung")["counts"]["by_group"]["review"] == 0


def test_approval_without_inbox_row_still_shows_for_its_approver(env):
    a = approval(env, approver=env.hung)
    env.db.query(InboxItem).delete(); env.db.commit()           # tạo trước D3.5 / báo đi chỗ khác
    ap = cards(feed(env, "hung"), "approvals")
    assert [c["key"] for c in ap] == [f"approval:{a.id}"] and ap[0]["approval"]["can_decide"]
    assert cards(feed(env, "boss"), "approvals") == []


# ------------------------------------------------------------------ duyệt một chạm


def test_one_tap_approve_closes_inbox_audits_and_wakes_requester(env):
    t = task(env)
    env.db.add(TaskRun(organization_id=env.org.id, task_id=t.id, member_id=env.mai.id, status="succeeded"))
    env.db.commit()
    a = approval(env, approver=env.hung)
    out = decide(env, "hung", a.id)
    assert out["status"] == "approved" and out["message"] == "Đã duyệt" and out["effect"] == "wake_requester"
    env.db.expire_all()
    assert env.db.get(Approval, a.id).status == "approved"
    row = env.db.query(InboxItem).filter_by(related_type="approval", related_id=str(a.id)).one()
    assert row.status == "done"
    audit = env.db.query(AuditEvent).filter_by(action="approval.decided", object_id=str(a.id)).one()
    assert json.loads(audit.payload_json)["via"] == "inbox"
    wk = env.db.query(Wakeup).filter_by(member_id=env.mai.id, reason="approval_resolved").one()
    assert wk.task_id == t.id
    assert cards(feed(env, "hung"), "approvals") == []


def test_reject_needs_a_reason_in_vietnamese(env):
    a = approval(env, approver=env.hung)
    r = decide(env, "hung", a.id, "reject", "  ", expect=422)
    assert r["detail"] == {"error": "note_required", "message": "Ghi lý do từ chối để người gửi biết cần sửa gì"}
    env.db.expire_all(); assert env.db.get(Approval, a.id).status == "pending"
    out = decide(env, "hung", a.id, "reject", "Thiếu ảnh sản phẩm")
    assert out["status"] == "rejected" and out["message"] == "Đã từ chối"
    env.db.expire_all(); assert env.db.get(Approval, a.id).resolution_note == "Thiếu ảnh sản phẩm"


def test_unauthorized_approver_is_refused(env):
    a = approval(env, approver=env.hung)
    for who in ("minh", "boss"):                     # nhân viên, và cả chủ nhưng không phải người duyệt
        r = decide(env, who, a.id, expect=403)
        assert r["detail"]["error"] == "not_the_approver"
        assert r["detail"]["message"] == "Anh không phải người duyệt yêu cầu này — người duyệt hiện tại là Anh Hùng"
    assert decide(env, "stranger", a.id, expect=404)["detail"]["error"] == "not_found"
    open_ = approval(env)                            # chưa có người duyệt → quản lý trở lên
    assert decide(env, "minh", open_.id, expect=403)["detail"]["message"] == "Chỉ quản lý trở lên được duyệt yêu cầu này"
    assert decide(env, "boss", open_.id)["status"] == "approved"
    env.db.expire_all(); assert env.db.get(Approval, open_.id).approver_member_id == env.boss.id
    agent_ap = approval(env, approver=env.lam)       # người duyệt là seat agent → quản lý người của seat
    assert decide(env, "hung", agent_ap.id)["status"] == "approved"


def test_double_approve_race_only_one_wins(env):
    a = approval(env, approver=env.hung)
    s1, s2 = env.Maker(), env.Maker()
    seen1, seen2 = s1.get(Approval, a.id), s2.get(Approval, a.id)   # cả hai đã "xem" thẻ ở trạng thái chờ
    assert seen1.status == seen2.status == "pending"
    p = env.principal("hung")
    first = asyncio.run(inbox_hub.decide(s1, env.org.id, p, a.id, decision="approve", expected_revision=1))
    assert first["status"] == "approved"
    # Yêu cầu thứ hai đã đọc hàng TRƯỚC khi yêu cầu đầu commit: trong bộ nhớ của nó hàng vẫn "chờ",
    # nên kiểm tra trạng thái đầu hàm cho qua — chỉ UPDATE có điều kiện chặn được.
    from sqlalchemy.orm.attributes import set_committed_value
    assert s2.get(Approval, a.id) is seen2 and seen2.status == "pending"   # bản trong bộ nhớ của yêu cầu 2
    set_committed_value(seen2, "status", "pending")
    with pytest.raises(WorkError) as e:
        asyncio.run(inbox_hub.decide(s2, env.org.id, p, a.id, decision="reject", note="đổi ý",
                                     expected_revision=1))
    assert e.value.status_code == 409 and e.value.detail["error"] == "already_decided"
    s3 = env.Maker()
    assert s3.get(Approval, a.id).status == "approved"
    assert s3.query(AuditEvent).filter_by(action="approval.decided", object_id=str(a.id)).count() == 1
    # Lần chạm thứ hai qua HTTP cũng chỉ nhận 409 có câu tiếng Việt.
    r = decide(env, "hung", a.id, expect=409)
    assert r["detail"]["error"] == "already_decided" and "đã được duyệt" in r["detail"]["message"]


def test_stale_revision_is_refused_until_reviewer_reloads(env):
    a = approval(env, approver=env.hung, revision=2)
    r = decide(env, "hung", a.id, expected_revision=1, expect=409)
    assert r["detail"]["error"] == "stale_revision" and r["detail"]["current_revision"] == 2
    assert "vừa đổi" in r["detail"]["message"]
    env.db.expire_all(); assert env.db.get(Approval, a.id).status == "pending"
    card = cards(feed(env, "hung"), "approvals")[0]["approval"]
    assert card["revision"] == 2
    assert decide(env, "hung", a.id, expected_revision=card["revision"])["status"] == "approved"


def test_gateway_approval_goes_through_the_bridge_once(env, monkeypatch):
    from app.core.config import settings
    lone = approval(env, approver=env.hung, policy_key="openclaw:agent:mai-anh:main:req-76")
    out = decide(env, "hung", lone.id)                     # chưa cấu hình trả lời gateway → nói thẳng
    assert out["delivered"] is False and "CHƯA gửi được tới OpenClaw" in out["message"]
    monkeypatch.setattr(settings, "openclaw_request_approvals_scope", True)
    a = approval(env, approver=env.hung, policy_key="openclaw:agent:mai-anh:main:req-77",
                 evidence=json.dumps({"command": "rm -rf build"}))
    card = cards(feed(env, "hung"), "approvals")[0]["approval"]
    assert card["kind"] == "gateway" and card["summary"] == "rm -rf build"
    out = decide(env, "hung", a.id)
    assert out["status"] == "approved" and out["delivered"] is True
    assert env.rt.approvals == [{"request_id": "req-77", "decision": "allow-once"}]
    assert decide(env, "hung", a.id, expect=409)["detail"]["error"] == "already_decided"
    assert len(env.rt.approvals) == 1


# ------------------------------------------------------------------ leo thang


def test_overdue_escalates_to_manager_and_old_approver_loses_the_button(env):
    a = approval(env, approver=env.minh)
    env.db.refresh(a)
    assert a.escalate_to_member_id == env.hung.id
    a.expires_at = datetime.utcnow() - timedelta(minutes=5); env.db.commit()
    card = cards(feed(env, "minh"), "approvals")[0]["approval"]
    assert card["overdue"] and card["deadline_vi"] == "Quá hạn — sắp chuyển lên Anh Hùng"
    assert env.c.post("/api/inbox/escalate", headers=env.tok("minh")).status_code == 403   # nhân viên không chạy
    r = env.c.post("/api/inbox/escalate", headers=env.tok("hung"))
    assert r.status_code == 200 and r.json()["message"] == "Đã chuyển 1 yêu cầu quá hạn lên cấp trên"
    env.db.expire_all()
    a = env.db.get(Approval, a.id)
    assert a.approver_member_id == env.hung.id and a.escalated_at is not None
    assert decide(env, "minh", a.id, expect=403)["detail"]["error"] == "not_the_approver"
    card = cards(feed(env, "hung"), "approvals")[0]
    assert "approval_escalated" in card["kinds"] and card["approval"]["can_decide"]
    assert card["approval"]["deadline_vi"].endswith("(đã được chuyển lên anh)")
    assert decide(env, "hung", a.id)["status"] == "approved"


def test_escalation_without_manager_says_so_and_does_not_spam(env):
    a = approval(env, approver=env.boss, requester=env.hung)
    env.db.refresh(a)
    assert a.escalate_to_member_id is None
    a.expires_at = datetime.utcnow() - timedelta(minutes=1); env.db.commit()
    card = cards(feed(env, "boss"), "approvals")[0]["approval"]
    assert card["escalation_blocked"] is True
    assert card["deadline_vi"] == "Quá hạn — không có cấp trên để chuyển lên, cần anh quyết"
    r = env.c.post("/api/inbox/escalate", headers=env.tok("boss")).json()
    assert r["escalated"][0] == {"approval_id": a.id, "escalated": False, "reason": "no_manager"}
    assert "không có cấp trên để chuyển" in r["message"]
    env.db.expire_all()
    a = env.db.get(Approval, a.id)
    assert a.approver_member_id == env.boss.id and a.expires_at > datetime.utcnow()
    assert env.c.post("/api/inbox/escalate", headers=env.tok("boss")).json()["escalated"] == []
    assert env.db.query(AuditEvent).filter_by(action="approval.escalation_failed", object_id=str(a.id)).count() == 1


# ------------------------------------------------------------------ ngân sách ba nấc


def _budget(env, limit=10.0, spent=0.0, warn=50, soft=80, scope="member", sid=None):
    e = BudgetEnvelope(organization_id=env.org.id, company_id=env.co.id, name="Ngân sách Mai", amount_limit=limit,
                       amount_spent=spent, amount_reserved=0, status="active", scope_type=scope,
                       scope_id=sid if sid is not None else env.mai.id, warn_pct=warn, soft_stop_pct=soft,
                       threshold_state="ok")
    env.db.add(e); env.db.commit(); env.db.refresh(e)
    budget_scope.check_thresholds(env.db, e)
    env.db.refresh(e)
    return e


def test_soft_stop_needs_approval_before_any_dispatch_then_runs(env):
    e = _budget(env, spent=8.5)
    assert e.threshold_state == "soft_stopped"
    note = env.db.query(InboxItem).filter_by(related_type="budget_envelope", related_id=str(e.id)).one()
    assert note.recipient_member_id == env.hung.id and note.item_type == "budget_soft_stopped"
    t = task(env)
    enqueue(env, t)
    out = drain(env)
    assert out[0]["decision"] == "skipped" and out[0]["reason"].startswith("budget_approval:")
    assert env.rt.calls == []
    a = env.db.query(Approval).filter_by(policy_key=budget_scope.soft_key(e.id, t.id)).one()
    assert a.status == "pending" and a.approver_member_id == env.hung.id and a.requester_member_id == env.mai.id
    enqueue(env, t); drain(env)                                   # drain lại: không tạo phê duyệt thứ hai
    assert env.db.query(Approval).filter_by(policy_key=budget_scope.soft_key(e.id, t.id)).count() == 1
    card = [c for c in cards(feed(env, "hung"), "approvals") if c["approval"]["id"] == a.id][0]["approval"]
    assert card["kind"] == "budget" and card["kind_vi"] == "Chi tiếp khi chạm nấc ngân sách"
    assert "85%" in card["summary"]
    out = decide(env, "hung", a.id)
    assert out["effect"] == "budget" and out["woken"]
    res = drain(env)
    assert [r["decision"] for r in res] == ["dispatched"] and len(env.rt.calls) == 1


def test_soft_stop_rejected_keeps_the_task_from_running(env):
    e = _budget(env, spent=8.5)
    t = task(env)
    enqueue(env, t); drain(env)
    a = env.db.query(Approval).filter_by(policy_key=budget_scope.soft_key(e.id, t.id)).one()
    decide(env, "hung", a.id, "reject", "Để tháng sau")
    enqueue(env, t)
    out = drain(env)
    assert out[0]["reason"].startswith("budget_rejected:") and env.rt.calls == []
    assert env.db.query(Approval).filter_by(policy_key=budget_scope.soft_key(e.id, t.id)).count() == 1
    other = task(env, title="Việc khác của Mai")                 # phê duyệt theo từng việc
    enqueue(env, other); drain(env)
    assert env.db.query(Approval).filter_by(policy_key=budget_scope.soft_key(e.id, other.id)).count() == 1


def test_hard_stop_blocks_dispatch_even_with_soft_approval(env):
    e = _budget(env, spent=8.5)
    t = task(env)
    enqueue(env, t); drain(env)
    a = env.db.query(Approval).filter_by(policy_key=budget_scope.soft_key(e.id, t.id)).one()
    decide(env, "hung", a.id)
    env.db.expire_all()
    e = env.db.get(BudgetEnvelope, e.id)
    e.amount_spent = 10.0; env.db.commit()
    budget_scope.check_thresholds(env.db, e)
    env.db.expire_all()
    assert env.db.get(BudgetEnvelope, e.id).threshold_state == "exhausted"
    assert env.db.get(Member, env.mai.id).status == "paused"
    enqueue(env, task(env, title="Việc mới"))
    out = drain(env)
    assert all(r["decision"] == "skipped" and r["reason"].startswith("budget") for r in out)
    assert env.rt.calls == []


def test_raising_the_limit_leaves_soft_stop_and_expires_grants(env):
    e = _budget(env, spent=8.5)
    t = task(env)
    enqueue(env, t); drain(env)
    a = env.db.query(Approval).filter_by(policy_key=budget_scope.soft_key(e.id, t.id)).one()
    r = env.c.patch(f"/api/costs/budgets/{e.id}", json={"amount_limit": 20}, headers=env.tok("hung"))
    assert r.status_code == 200, r.text
    assert r.json()["budget"]["threshold_state"] == "ok" and r.json()["threshold"]["expired_approvals"] == [a.id]
    env.db.expire_all()
    assert env.db.get(Approval, a.id).status == "expired"
    assert decide(env, "hung", a.id, expect=409)["detail"]["message"].startswith("Yêu cầu này đã được hết hiệu lực")
    res = drain(env) or []
    enqueue(env, t)
    res = drain(env)
    assert [x["decision"] for x in res] == ["dispatched"]


def test_budget_levels_ordered_warn_soft_hard(env):
    e = _budget(env, spent=0, warn=50, soft=80)
    seen = []
    for spent in (4.0, 6.0, 8.5, 10.0):
        env.db.expire_all(); e = env.db.get(BudgetEnvelope, e.id)
        e.amount_spent = spent; env.db.commit()
        seen.append(budget_scope.check_thresholds(env.db, e)["state"])
    assert seen == ["ok", "warned", "soft_stopped", "exhausted"]
    legacy = _budget(env, spent=9.0, warn=80, soft=None, scope="member", sid=env.lam.id)
    assert legacy.threshold_state == "warned"                  # không đặt nấc mềm = hành vi D2.3 cũ


# ------------------------------------------------------------------ /api/costs


def test_costs_budget_crud_validates_in_vietnamese(env):
    H, Hm = env.tok("hung"), env.tok("minh")
    body = {"scope_type": "department", "scope_id": env.mkt.id, "amount_limit": 50, "warn_pct": 70,
            "soft_stop_pct": 90}
    assert env.c.post("/api/costs/budgets", json=body, headers=Hm).status_code == 403
    r = env.c.post("/api/costs/budgets", json={**body, "soft_stop_pct": 60}, headers=H)
    assert r.status_code == 422 and r.json()["detail"]["error"] == "bad_levels"
    assert "lớn hơn nấc cảnh báo (70%)" in r.json()["detail"]["message"]
    r = env.c.post("/api/costs/budgets", json={**body, "scope_id": 99999}, headers=H)
    assert r.status_code == 404 and r.json()["detail"]["error"] == "scope_not_found"
    r = env.c.post("/api/costs/budgets", json={**body, "scope_type": "member", "scope_id": env.stranger.id},
                   headers=H)
    assert r.status_code == 404                                 # thành viên tổ chức khác
    r = env.c.post("/api/costs/budgets", json=body, headers=H)
    assert r.status_code == 201, r.text
    b = r.json()
    assert b["name"] == "Phòng ban · Marketing" and b["scope_vi"] == "Phòng ban" and b["soft_stop_pct"] == 90
    assert [l["key"] for l in b["levels"]] == ["warned", "soft_stopped", "exhausted"]
    r = env.c.post("/api/costs/budgets", json=body, headers=H)
    assert r.status_code == 409 and r.json()["detail"]["error"] == "duplicate_scope"
    lst = env.c.get("/api/costs/budgets", headers=Hm).json()
    assert [x["id"] for x in lst["budgets"]] == [b["id"]] and lst["caps"]["manage"] is False
    assert {"company", "department", "team", "member"} == set(lst["scopes"])
    det = env.c.get(f"/api/costs/budgets/{b['id']}", headers=H).json()
    assert det["budget"]["id"] == b["id"] and det["ledger"] == []


def test_hard_stopped_budget_reopens_only_through_override_with_reason(env):
    e = _budget(env, spent=10.0)
    assert e.threshold_state == "exhausted"
    H = env.tok("hung")
    r = env.c.patch(f"/api/costs/budgets/{e.id}", json={"amount_limit": 30}, headers=H)
    assert r.status_code == 409 and r.json()["detail"]["error"] == "needs_override"
    r = env.c.post(f"/api/costs/budgets/{e.id}/override", json={"add_usd": 10}, headers=H)
    assert r.status_code == 422 and r.json()["detail"]["error"] == "reason_required"
    assert env.c.delete(f"/api/costs/budgets/{e.id}", headers=H).status_code == 409
    r = env.c.post(f"/api/costs/budgets/{e.id}/override", json={"add_usd": 20, "reason": "Chạy chiến dịch hè"},
                   headers=H)
    assert r.status_code == 200, r.text
    assert r.json()["budget"]["threshold_state"] == "ok" and env.mai.id in r.json()["restored_members"]
    assert env.db.query(AuditEvent).filter_by(action="budget.override", object_id=str(e.id)).count() == 1


def test_costs_overview_sums_model_usage_by_agent_department_company(env):
    ag = {a.member_id: a.id for a in env.db.query(Agent).all()}
    now = datetime.utcnow()
    for mid, amt, when in ((env.mai.id, 0.30, now), (env.mai.id, 0.20, now - timedelta(days=3)),
                           (env.lam.id, 0.10, now - timedelta(days=10)), (env.lam.id, 5.0, now - timedelta(days=60))):
        env.db.add(UsageEvent(organization_id=env.org.id, agent_id=ag[mid], event_type="model_usage", quantity=1,
                              unit="model_call", unit_cost=amt, amount=amt, created_at=when,
                              metadata_json=json.dumps({"total_tokens": 100})))
    env.db.add(UsageEvent(organization_id=env.org.id, agent_id=ag[env.mai.id], event_type="task_dispatch",
                          amount=9.0, created_at=now))              # không phải tiền model
    env.db.commit()
    _budget(env, spent=2.0)
    o = env.c.get("/api/costs/overview", headers=env.tok("minh")).json()
    assert o["totals"]["d7"] == pytest.approx(0.5) and o["totals"]["window"] == pytest.approx(0.6)
    assert o["totals"]["model_calls"] == 3 and o["totals"]["tokens"] == 300
    assert o["by_agent"] == [{"name": "Mai Anh", "cost_usd": 0.5}, {"name": "Lâm", "cost_usd": 0.1}]
    assert o["by_department"][0] == {"name": "Marketing", "cost_usd": 0.5}
    assert o["by_company"] == [{"name": "Nova Shop", "cost_usd": 0.6}]
    assert len(o["budgets"]) == 1 and o["alerts"] == 0


# ------------------------------------------------------------------ đường cũ = alias có Deprecation


def test_old_routes_still_work_with_deprecation_and_successor_link(env):
    a = approval(env, approver=env.hung)
    H = env.tok("hung")
    for path, succ in (("/api/v9/inbox/mine", "/api/inbox/items"), ("/api/inbox", "/api/inbox/items"),
                       ("/api/v9/approvals/quick", "/api/inbox/items?group=approvals"),
                       ("/api/v9/budgets", "/api/costs/budgets"), ("/api/v9/budgets-overview", "/api/costs/overview")):
        r = env.c.get(path, headers=H)
        assert r.status_code == 200, (path, r.text)
        assert r.headers.get("Deprecation") == "true" and r.headers["Link"] == f'<{succ}>; rel="successor-version"'
    r = env.c.post(f"/api/approvals/{a.id}/resolve", json={"status": "approved"}, headers=H)
    assert r.status_code == 200 and r.headers["Link"] == f'</api/inbox/approvals/{a.id}/decide>; rel="successor-version"'
    again = env.c.post(f"/api/approvals/{a.id}/resolve", json={"status": "rejected"}, headers=H)
    assert again.status_code == 409 and again.json()["detail"]["error"] == "already_decided"   # lỗi cũ: 200
    for path in ("/api/inbox/items", "/api/inbox/summary", "/api/costs/budgets", "/api/costs/overview"):
        assert "Deprecation" not in env.c.get(path, headers=H).headers


# ------------------------------------------------------------------ theo seat / phòng / nhóm (công ty agent)


def test_department_grant_clears_the_whole_department_queue(env):
    e = _budget(env, limit=10.0, spent=8.5, scope="department", sid=env.mkt.id)
    env.db.query(Member).filter_by(id=env.lam.id).update({"department_id": env.mkt.id}); env.db.commit()
    t1, t2 = task(env), task(env, title="Việc của Lâm", assignee=env.lam)
    enqueue(env, t1); enqueue(env, t2, env.lam); drain(env)
    a1 = env.db.query(Approval).filter_by(policy_key=budget_scope.soft_key(e.id, t1.id)).one()
    a2 = env.db.query(Approval).filter_by(policy_key=budget_scope.soft_key(e.id, t2.id)).one()
    card = [c for c in cards(feed(env, "hung", department_id=env.mkt.id), "approvals") if c["approval"]["id"] == a1.id][0]
    assert card["department"]["name"] == "Marketing" and card["seat"]["name"] == "Mai Anh"
    assert card["approval"]["grant_scopes"] == ["task", "seat", "department"]
    assert decide(env, "hung", a2.id, grant_scope="seat", expect=200)["grant_scope"] == "seat"
    assert decide(env, "hung", (approval(env, approver=env.hung)).id, grant_scope="department",
                  expect=422)["detail"]["error"] == "bad_grant_scope"
    out = decide(env, "hung", a1.id, grant_scope="department")
    assert out["grant_scope"] == "department"
    env.db.expire_all()
    t3 = task(env, title="Việc mới của Mai")                     # việc mới cùng phòng: không hỏi lại
    enqueue(env, t3)
    res = drain(env)
    assert {r["decision"] for r in res} == {"dispatched"}
    assert env.db.query(Approval).filter_by(policy_key=budget_scope.soft_key(e.id, t3.id)).count() == 0


def test_department_grant_auto_approves_pending_siblings(env):
    e = _budget(env, limit=10.0, spent=8.5, scope="department", sid=env.mkt.id)
    env.db.query(Member).filter_by(id=env.lam.id).update({"department_id": env.mkt.id}); env.db.commit()
    t1, t2 = task(env), task(env, title="Việc của Lâm", assignee=env.lam)
    enqueue(env, t1); enqueue(env, t2, env.lam); drain(env)
    a1 = env.db.query(Approval).filter_by(policy_key=budget_scope.soft_key(e.id, t1.id)).one()
    a2 = env.db.query(Approval).filter_by(policy_key=budget_scope.soft_key(e.id, t2.id)).one()
    out = decide(env, "hung", a1.id, grant_scope="department")
    assert out["covered_approvals"] == [a2.id] and len(out["woken_all"]) == 2
    env.db.expire_all()
    assert env.db.get(Approval, a2.id).status == "approved"
    assert env.db.query(InboxItem).filter_by(related_type="approval", related_id=str(a2.id)).one().status == "done"
    res = drain(env)
    assert sorted(r["decision"] for r in res) == ["dispatched", "dispatched"] and len(env.rt.calls) == 2


def test_team_budget_covers_only_team_members(env):
    from app.models.v16 import AgentTeam, AgentTeamMember
    team = AgentTeam(organization_id=env.org.id, company_id=env.co.id, team_key="launch", name="Đội ra mắt")
    env.db.add(team); env.db.commit()
    env.db.add(AgentTeamMember(organization_id=env.org.id, team_id=team.id, member_id=env.mai.id)); env.db.commit()
    r = env.c.post("/api/costs/budgets", json={"scope_type": "team", "scope_id": team.id, "amount_limit": 1},
                   headers=env.tok("hung"))
    assert r.status_code == 201 and r.json()["scope_name"] == "Đội ra mắt" and r.json()["scope_vi"] == "Nhóm"
    e = env.db.get(BudgetEnvelope, r.json()["id"])
    assert [x.id for x in budget_scope.applicable(env.db, env.db.get(Member, env.mai.id))] == [e.id]
    assert budget_scope.applicable(env.db, env.db.get(Member, env.lam.id)) == []
    e.amount_spent = 1.0; env.db.commit(); budget_scope.check_thresholds(env.db, e)
    env.db.expire_all()
    assert env.db.get(Member, env.mai.id).status == "paused" and env.db.get(Member, env.lam.id).status == "active"


def test_lesson_proposals_have_their_own_group_and_decision_slot(env):
    from app.services import inbox
    inbox.notify(env.db, organization_id=env.org.id, recipients=[env.hung.id], kind="lesson_proposal",
                 title="Mai Anh đề xuất bài học: caption nên có CTA", related_type="lesson", related_id="1")
    a = approval(env, approver=env.hung, policy_key="lesson:m{0}".format(env.mai.id),
                 action="Ghi bài học vào MEMORY.md của Mai Anh")
    body = feed(env, "hung")
    lessons = cards(body, "lessons")
    assert len(lessons) == 2 and cards(body, "approvals") == []
    card = [c for c in lessons if c["approval"]][0]["approval"]
    assert card["kind"] == "lesson" and card["can_decide"]
    out = decide(env, "hung", a.id)
    assert out["effect"] == "lesson" and out["applied"] is False      # M5 sẽ ghi MEMORY.md


def test_escalation_without_manager_falls_back_to_department_head(env):
    env.mkt.head_member_id = env.hung.id; env.db.commit()
    a = approval(env, approver=env.boss, requester=env.mai)      # seat Marketing, người duyệt không có cấp trên
    a.expires_at = datetime.utcnow() - timedelta(minutes=1); env.db.commit()
    card = cards(feed(env, "boss"), "approvals")[0]["approval"]
    assert card["escalation_blocked"] is False and card["escalate_to"] == "Anh Hùng"
    r = env.c.post("/api/inbox/escalate", headers=env.tok("boss")).json()
    assert r["escalated"][0]["escalated"] is True and r["escalated"][0]["to_member_id"] == env.hung.id
