"""Hộp việc: bấm vào yêu cầu duyệt phải thấy đủ chi tiết trước khi duyệt."""
import json

from tests.test_m4b_inbox import approval, env, task  # noqa: F401  (fixture)


def detail(env, who, aid, expect=200):
    r = env.c.get(f"/api/inbox/approvals/{aid}", headers=env.tok(who))
    assert r.status_code == expect, r.text
    return r.json()


def test_gateway_command_detail_shows_command_cwd_task_and_people(env):
    t = task(env, title="Kiểm tra máy chủ")
    t.description = "Xem phiên bản hệ điều hành trước khi cài gói"; env.db.commit()
    ev = {"session_key": "agent:mai-anh:main", "task_id": t.id,
          "event": {"id": "x1", "request": {"command": "uname -a", "cwd": "/home/node/ws", "host": "gateway",
                                             "systemRunPlan": None}}}
    a = approval(env, approver=env.hung, action="Chạy lệnh: uname -a", policy_key="openclaw:agent:mai-anh:main:x1",
                 evidence=json.dumps(ev))
    d = detail(env, "hung", a.id)
    f = {x["label"]: x["value"] for x in d["fields"]}
    assert f["Lệnh"] == "uname -a" and f["Thư mục chạy"] == "/home/node/ws" and f["Nơi chạy"] == "gateway"
    assert next(x for x in d["fields"] if x["key"] == "command")["mono"]
    assert "id" not in {x["key"] for x in d["fields"]}
    assert d["requester_detail"]["name"] == "Mai Anh" and d["requester_detail"]["type"] == "agent"
    assert d["approver"] == "Anh Hùng" and d["can_decide"]
    assert d["task_detail"]["title"] == "Kiểm tra máy chủ"
    assert d["task_detail"]["description"].startswith("Xem phiên bản") and d["task_detail"]["project"] == "BST hè"
    assert d["kind_vi"].startswith("Lệnh agent")


def test_plain_text_and_payload_detail(env):
    a = approval(env, approver=env.hung, action="ads.spend", policy_key="ads-spend",
                 evidence="Q4 campaign budget increase")
    a.payload = {"amount_usd": 120, "reason": "Tăng ngân sách quảng cáo quý 4"}; env.db.commit()
    d = detail(env, "hung", a.id)
    assert d["text"] == "Q4 campaign budget increase"
    f = {x["label"]: x["value"] for x in d["fields"]}
    assert f["Số tiền (USD)"] == "120" and f["Lý do"].startswith("Tăng ngân sách")
    assert d["task_detail"] is None


def test_detail_is_private_to_people_involved_and_managers(env):
    a = approval(env, approver=env.hung)
    assert detail(env, "boss", a.id)["id"] == a.id          # owner/quản lý
    detail(env, "minh", a.id, expect=404)                   # nhân viên không liên quan
    detail(env, "stranger", a.id, expect=404)               # tổ chức khác
    detail(env, "hung", 99999, expect=404)


def test_detail_shows_deliverable_content_journal_and_run_error(env):
    from app.models.v10 import Artifact
    from app.models.v37 import TaskJournalEntry
    from app.models.work_graph import TaskRun
    t = task(env, title="Viết 5 caption")
    env.db.add(Artifact(organization_id=env.org.id, company_id=env.co.id, task_id=t.id, name="captions.md",
                        content_text="1. Gốm men lam cho bàn trà\n2. Quà Tết bền đẹp"))
    env.db.add(TaskJournalEntry(organization_id=env.org.id, task_id=t.id, seq=1, actor_member_id=env.mai.id,
                                kind="result", summary="Đã viết xong 5 caption", detail="Giọng ấm áp"))
    env.db.add(TaskRun(organization_id=env.org.id, task_id=t.id, member_id=env.mai.id, status="failed",
                       error_reason="HTTP 401 từ nhà cung cấp"))
    env.db.commit()
    a = approval(env, approver=env.hung, policy_key=f"task_stage:t{t.id}:review")
    td = detail(env, "hung", a.id)["task_detail"]
    assert td["id"] == t.id, td
    assert td["deliverables"][0]["content"].startswith("1. Gốm men lam")
    assert td["journal"][0]["summary"] == "Đã viết xong 5 caption" and td["journal"][0]["kind_vi"] == "Kết quả"
    assert td["last_run"]["status"] == "failed" and "401" in td["last_run"]["error"]


def test_inbox_item_detail_full_body_task_and_marks_read(env):
    from app.models.extended import InboxItem
    t = task(env, title="Chụp ảnh bình men")
    it = InboxItem(organization_id=env.org.id, recipient_member_id=env.hung.id, source="runs", title="Run lỗi ở task",
                   item_type="run_failed", kinds="run_failed", status="unread", task_id=t.id,
                   body="Dòng 1\nDòng 2: Authentication failed (HTTP 401) — chi tiết dài")
    env.db.add(it); env.db.commit()
    r = env.c.get(f"/api/inbox/items/{it.id}", headers=env.tok("hung"))
    assert r.status_code == 200, r.text
    d = r.json()
    assert "Dòng 2: Authentication failed" in d["body"] and d["task_detail"]["title"] == "Chụp ảnh bình men"
    assert d["status"] == "read"
    assert env.c.get(f"/api/inbox/items/{it.id}", headers=env.tok("minh")).status_code == 404
    assert env.c.get(f"/api/inbox/items/{it.id}", headers=env.tok("stranger")).status_code == 404
