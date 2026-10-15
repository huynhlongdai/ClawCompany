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
