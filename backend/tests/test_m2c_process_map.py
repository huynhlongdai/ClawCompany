"""M2c D4 — bản đồ quy trình chạy được trên động cơ việc sẵn có: một lần chạy sinh task cho
người ngồi chức danh của từng bước, chặn nối tiếp bằng task_dependencies, bước có loại việc
xin duyệt theo ma trận (chặng approval), thời gian chu trình ghi theo bước và theo lần chạy.
ORM thật trên SQLite, gateway giả."""
from datetime import datetime, timedelta

import pytest

from app.models import Approval, Member, Task, Wakeup
from app.models.company_ops import ProcessInstance, ProcessStepRun
from app.models.work_graph import TaskDependency
from app.services import execution_policy, task_lifecycle as lifecycle
from tests.test_m2b_company_foundation import E, mkpos  # noqa: F401  (fixture)
from tests.test_m3_agents import env, hire  # noqa: F401  (fixture)


def _setup(E):
    cskh = mkpos(E, title="Nhân viên CSKH", department_id=E.sales.id, headcount=2)
    agent = hire(E, position_id=cskh["id"], role="")
    kho = mkpos(E, title="Thủ kho", department_id=E.mkt.id, headcount=1)
    keeper = Member(organization_id=E.org.id, company_id=E.co.id, department_id=E.mkt.id, name="Anh Kho",
                    member_type="human", role="Thủ kho", manager_id=E.lead_m.id, status="active")
    E.db.add(keeper); E.db.commit()
    assert E.c.post(f"/api/team/positions/{kho['id']}/seats", json={"member_id": keeper.id},
                    headers=E.tok("manager")).status_code == 200
    owner_pos = mkpos(E, title="Trưởng phòng bán hàng", department_id=E.sales.id, headcount=1)
    assert E.c.post("/api/team/authority/seed-defaults", json={"company_id": E.co.id},
                    headers=E.tok("owner")).status_code == 200
    return cskh, agent, kho, keeper, owner_pos


def _process(E, cskh, kho, owner_pos, **extra):
    body = {"company_id": E.co.id, "name": "Hoàn tiền / đổi trả", "category": "6",
            "owner_position_id": owner_pos["id"],
            "steps": [{"name": "Tiếp nhận yêu cầu", "position_id": cskh["id"], "expected_minutes": 20,
                       "instructions": "Xin ảnh hàng vỡ."},
                      {"name": "Hoàn tiền cho khách", "position_id": cskh["id"], "expected_minutes": 30,
                       "action_type": "hoàn tiền"},
                      {"name": "Nhận hàng hoàn & kiểm kho", "position_id": kho["id"], "expected_minutes": 60}]}
    body.update(extra)
    r = E.c.post("/api/team/processes", json=body, headers=E.tok("manager"))
    assert r.status_code == 200, r.text
    return r.json()


def _finish(E, task_id, actor=None):
    t = E.db.get(Task, task_id); E.db.refresh(t)
    for to in ("in_progress", "review", "done"):
        if t.status == "review" and execution_policy.has_policy(t):
            break
        lifecycle.transition(E.db, t, to, system=True, reason="test", via="test", actor_member_id=actor)
    return t


def test_start_creates_tasks_for_step_owners_chained_with_approval_from_matrix(E):
    cskh, agent, kho, keeper, owner_pos = _setup(E)
    p = _process(E, cskh, kho, owner_pos)
    assert p["owner_position"] == "Trưởng phòng bán hàng" and [s["position"] for s in p["steps"]] == \
        ["Nhân viên CSKH", "Nhân viên CSKH", "Thủ kho"]
    assert p["steps"][1]["action_type"] == "refund"            # từ đồng nghĩa → loại việc chuẩn
    r = E.c.post(f"/api/team/processes/{p['id']}/start", json={"title": "Khách Lan — bình vỡ", "amount_usd": 80,
                                                               "input": {"order": "DH-1024"}},
                 headers=E.tok("member"))
    assert r.status_code == 200, r.text
    inst = r.json()
    assert inst["status"] == "running" and len(inst["steps"]) == 3
    s1, s2, s3 = inst["steps"]
    # người nhận = người ngồi chức danh của từng bước
    assert s1["assignee_member_id"] == agent["member_id"] and s3["assignee"] == "Anh Kho"
    assert [s["status"] for s in inst["steps"]] == ["active", "waiting", "waiting"]
    assert [s["task_status"] for s in inst["steps"]] == ["todo", "backlog", "backlog"]
    t1 = E.db.get(Task, s1["task_id"])
    assert "Bước 1/3" in t1.description and "Xin ảnh hàng vỡ." in t1.description and "DH-1024" in t1.description
    # chuỗi chặn bằng task_dependencies (động cơ việc sẵn có)
    deps = {(d.task_id, d.blocked_by_task_id) for d in E.db.query(TaskDependency).all()}
    assert (s2["task_id"], s1["task_id"]) in deps and (s3["task_id"], s2["task_id"]) in deps
    # seat agent của bước 1 được đánh thức
    assert E.db.query(Wakeup).filter(Wakeup.member_id == agent["member_id"], Wakeup.task_id == s1["task_id"]).count() == 1
    # hoàn $80: mặc định $20–100 → trưởng phòng duyệt (agent standard không tự làm được dải này)
    assert s2["approval_required"] is True and s2["approver"] == "Anh Minh" and s2["authority_rule_id"]
    t2 = E.db.get(Task, s2["task_id"])
    assert t2.execution_policy["stages"][0] == {"type": "approval", "participants": [E.lead_s.id]}
    assert s1["approval_required"] is False and s3["approval_required"] is False


def test_cycle_time_per_step_and_instance_and_next_step_opens(E):
    cskh, agent, kho, keeper, owner_pos = _setup(E)
    p = _process(E, cskh, kho, owner_pos)
    inst = E.c.post(f"/api/team/processes/{p['id']}/start", json={"amount_usd": 80}, headers=E.tok("member")).json()
    s1, s2, s3 = inst["steps"]
    # giả lập bước 1 tới lượt từ 25 phút trước (thời gian chu trình tính từ lúc tới lượt)
    r1 = E.db.get(ProcessStepRun, s1["id"]); r1.activated_at = datetime.utcnow() - timedelta(minutes=25)
    pi = E.db.get(ProcessInstance, inst["id"]); pi.started_at = datetime.utcnow() - timedelta(minutes=25)
    E.db.commit()
    _finish(E, s1["task_id"])
    got = E.c.get(f"/api/team/process-instances/{inst['id']}", headers=E.tok("member")).json()
    assert got["steps"][0]["status"] == "done" and 24.5 <= got["steps"][0]["cycle_minutes"] <= 26
    assert got["steps"][1]["status"] == "active" and got["steps"][1]["task_status"] == "todo"
    assert got["steps"][0]["finished_at"]
    # bước 2 cần trưởng phòng duyệt: nộp review → approval → duyệt → xong → bước 3 mở
    t2 = _finish(E, s2["task_id"])
    assert t2.status == "review"
    ap = E.db.query(Approval).filter(Approval.policy_key.like(f"task_stage:t{t2.id}:%")).one()
    assert ap.approver_member_id == E.lead_s.id
    execution_policy.decide(E.db, t2, member_id=E.lead_s.id, decision="approve")
    got = E.c.get(f"/api/team/process-instances/{inst['id']}", headers=E.tok("member")).json()
    assert got["steps"][1]["status"] == "done" and got["steps"][2]["status"] == "active"
    assert got["steps"][2]["task_status"] == "todo" and got["status"] == "running"
    _finish(E, s3["task_id"])
    got = E.c.get(f"/api/team/process-instances/{inst['id']}", headers=E.tok("member")).json()
    assert got["status"] == "done" and got["cycle_minutes"] >= 24.5 and got["finished_at"]
    lst = E.c.get(f"/api/team/processes?company_id={E.co.id}", headers=E.tok("member")).json()
    row = next(i for i in lst["items"] if i["id"] == p["id"])
    assert row["stats"]["done"] == 1 and row["stats"]["avg_cycle_minutes"] >= 24.5
    assert row["steps"][0]["avg_minutes"] >= 24.5 and row["expected_minutes"] == 110
    assert {c["key"] for c in lst["categories"]} == {str(i) for i in range(1, 14)}


def test_small_refund_needs_no_approval_and_cancel_closes_remaining(E):
    cskh, agent, kho, keeper, owner_pos = _setup(E)
    p = _process(E, cskh, kho, owner_pos)
    inst = E.c.post(f"/api/team/processes/{p['id']}/start", json={"amount_usd": 10}, headers=E.tok("member")).json()
    assert inst["steps"][1]["approval_required"] is False      # <$20: agent chính thức tự làm
    assert E.db.get(Task, inst["steps"][1]["task_id"]).execution_policy is None
    # đang có lần chạy dở → không cho sửa các bước (để chu trình không lẫn)
    r = E.c.patch(f"/api/team/processes/{p['id']}", json={"steps": [{"name": "X"}]}, headers=E.tok("manager"))
    assert r.status_code == 409 and "lần chạy dở" in r.json()["detail"]
    # huỷ một bước → huỷ lần chạy và các bước còn chờ
    t1 = E.db.get(Task, inst["steps"][0]["task_id"])
    lifecycle.transition(E.db, t1, "cancelled", system=True, reason="khách rút yêu cầu")
    got = E.c.get(f"/api/team/process-instances/{inst['id']}", headers=E.tok("member")).json()
    assert got["status"] == "cancelled" and [s["status"] for s in got["steps"]] == ["cancelled"] * 3
    assert all(s["task_status"] == "cancelled" for s in got["steps"])
    assert E.c.patch(f"/api/team/processes/{p['id']}", json={"steps": [{"name": "Một bước"}]},
                     headers=E.tok("manager")).status_code == 200


def test_vacant_position_falls_back_to_department_head_and_validation(E):
    cskh, agent, kho, keeper, owner_pos = _setup(E)
    empty = mkpos(E, title="Kiểm hàng", department_id=E.sales.id, headcount=1)
    p = _process(E, cskh, kho, owner_pos, steps=[{"name": "Kiểm hàng", "position_id": empty["id"]}])
    assert any("đang trống người" in x for x in p["issues"])
    inst = E.c.post(f"/api/team/processes/{p['id']}/start", json={}, headers=E.tok("member")).json()
    assert inst["steps"][0]["assignee_member_id"] == E.lead_s.id and "trống" in inst["steps"][0]["note"]
    bad = E.c.post("/api/team/processes", json={"company_id": E.co.id, "name": "X", "category": "99"}, headers=E.tok("manager"))
    assert bad.status_code == 422 and "APQC" in bad.json()["detail"]
    bad = E.c.post("/api/team/processes", json={"company_id": E.co.id, "name": "X",
                                                "steps": [{"name": "a", "action_type": "bay lên trời"}]}, headers=E.tok("manager"))
    assert bad.status_code == 422 and "ma trận phân quyền" in bad.json()["detail"]
    assert E.c.post("/api/team/processes", json={"company_id": E.co.id, "name": "X"}, headers=E.tok("member")).status_code == 403
    # công ty của tổ chức khác không thấy quy trình này
    assert E.c.get(f"/api/team/processes/{p['id']}/instances", headers=E.tok("other")).status_code == 404
    none = E.c.post("/api/team/processes", json={"company_id": E.co.id, "name": "Trống"}, headers=E.tok("manager")).json()
    r = E.c.post(f"/api/team/processes/{none['id']}/start", json={}, headers=E.tok("member"))
    assert r.status_code == 409 and "Thêm ít nhất một bước" in r.json()["detail"]


def test_seed_shop_templates_map_steps_to_positions_with_sop(E):
    for title, dept in (("Trưởng phòng bán hàng", E.sales.id), ("Chăm sóc khách hàng online", E.sales.id),
                        ("Trưởng kho vận", E.mkt.id), ("Trưởng phòng marketing", E.mkt.id), ("Viết nội dung", E.mkt.id)):
        mkpos(E, title=title, department_id=dept)
    r = E.c.post("/api/team/processes/seed", json={"company_id": E.co.id, "template": "shop"}, headers=E.tok("manager"))
    assert r.status_code == 200 and len(r.json()["created"]) == 3
    again = E.c.post("/api/team/processes/seed", json={"company_id": E.co.id, "template": "shop"}, headers=E.tok("manager")).json()
    assert again["created"] == [] and len(again["skipped"]) == 3
    lst = E.c.get(f"/api/team/processes?company_id={E.co.id}", headers=E.tok("member")).json()
    order = next(i for i in lst["items"] if i["name"].startswith("Đơn hàng"))
    assert order["category"] == "4" and order["owner_position"] == "Trưởng phòng bán hàng"
    assert [s["position"] for s in order["steps"]] == ["Chăm sóc khách hàng online", "Trưởng kho vận",
                                                        "Trưởng kho vận", "Chăm sóc khách hàng online"]
    assert all(s["sop"] == "SOP: Đơn hàng → giao hàng → hậu mãi" for s in order["steps"])
    refund = next(i for i in lst["items"] if i["name"].startswith("Hoàn tiền"))
    assert refund["steps"][1]["action_type"] == "refund"
