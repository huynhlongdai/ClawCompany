"""M2d.1 — quy trình v2: rẽ nhánh theo điều kiện (số tiền / dữ liệu vào / kết quả bước trước) và bước song
song (fan-out/fan-in bằng task_dependencies); thời gian chu trình theo nhánh; quy trình tuyến tính cũ chạy
như trước. ORM thật trên SQLite, gateway giả."""
from datetime import datetime, timedelta

from app.models import Task
from app.models.company_ops import ProcessInstance, ProcessStep, ProcessStepRun
from app.models.work_graph import TaskDependency
from app.services import process_map
from tests.test_m2b_company_foundation import E, mkpos  # noqa: F401  (fixture)
from tests.test_m2c_process_map import _finish, _setup
from tests.test_m3_agents import env, hire  # noqa: F401  (fixture)


def _branching(E, cskh, kho, owner_pos):
    """Tiếp nhận → (≥ $50: trưởng phòng duyệt) → hoàn tiền → song song {kiểm kho, báo khách} → đóng hồ sơ."""
    body = {"company_id": E.co.id, "name": "Hoàn tiền v2", "category": "6", "owner_position_id": owner_pos["id"],
            "steps": [
                {"name": "Tiếp nhận", "position_id": cskh["id"], "expected_minutes": 20, "depends_on": []},
                {"name": "Trưởng phòng duyệt", "position_id": owner_pos["id"], "expected_minutes": 30,
                 "depends_on": [1], "branch": "Duyệt", "condition": {"field": "amount_usd", "op": ">=", "value": 50}},
                {"name": "Hoàn tiền", "position_id": cskh["id"], "expected_minutes": 10, "depends_on": [1, 2]},
                {"name": "Kiểm kho", "position_id": kho["id"], "expected_minutes": 60, "depends_on": [3]},
                {"name": "Báo khách", "position_id": cskh["id"], "expected_minutes": 5, "depends_on": [3]},
                {"name": "Đóng hồ sơ", "position_id": cskh["id"], "expected_minutes": 5, "depends_on": [4, 5]}]}
    r = E.c.post("/api/team/processes", json=body, headers=E.tok("manager"))
    assert r.status_code == 200, r.text
    return r.json()


def _inst(E, iid):
    return E.c.get(f"/api/team/process-instances/{iid}", headers=E.tok("member")).json()


def _st(inst):
    return [s["status"] for s in inst["steps"]]


def test_small_amount_skips_approval_branch_and_parallel_steps_fan_out_and_in(E):
    cskh, agent, kho, keeper, owner_pos = _setup(E)
    p = _branching(E, cskh, kho, owner_pos)
    assert [s["depends_on"] for s in p["steps"]] == [[], [1], [1, 2], [3], [3], [4, 5]]
    assert p["steps"][1]["condition"] == {"field": "amount_usd", "op": ">=", "value": 50.0}
    # thời lượng kỳ vọng = đường dài nhất (song song không cộng dồn): 20+30+10+60+5
    assert p["expected_minutes"] == 125
    inst = E.c.post(f"/api/team/processes/{p['id']}/start", json={"amount_usd": 30}, headers=E.tok("member")).json()
    # fan-in dùng task_dependencies: B3 bị chặn bởi B1 và B2; B6 bởi B4 và B5
    deps = {(d.task_id, d.blocked_by_task_id) for d in E.db.query(TaskDependency).all()}
    t = [s["task_id"] for s in inst["steps"]]
    assert {(t[2], t[0]), (t[2], t[1]), (t[5], t[3]), (t[5], t[4]), (t[3], t[2]), (t[4], t[2])} <= deps
    assert _st(inst) == ["active", "waiting", "waiting", "waiting", "waiting", "waiting"]
    _finish(E, t[0])
    got = _inst(E, inst["id"])
    # $30 < $50 → nhánh duyệt bị bỏ qua (task huỷ có lý do), hoàn tiền mở luôn
    assert _st(got)[:3] == ["done", "skipped", "active"]
    assert "Điều kiện không thỏa" in got["steps"][1]["skip_reason"]
    assert E.db.get(Task, t[1]).status == "cancelled" and E.db.get(Task, t[2]).status == "todo"
    assert got["status"] == "running"
    _finish(E, t[2])
    got = _inst(E, inst["id"])
    # fan-out: kiểm kho và báo khách cùng mở
    assert _st(got)[3:] == ["active", "active", "waiting"]
    assert E.db.get(Task, t[3]).status == "todo" and E.db.get(Task, t[4]).status == "todo"
    _finish(E, t[4])
    assert _st(_inst(E, inst["id"]))[5] == "waiting"          # fan-in chờ cả hai nhánh
    _finish(E, t[3])
    got = _inst(E, inst["id"])
    assert _st(got)[5] == "active"
    _finish(E, t[5])
    got = _inst(E, inst["id"])
    assert got["status"] == "done" and got["cycle_minutes"] is not None


def test_large_amount_takes_approval_branch_and_cycle_time_per_branch(E):
    cskh, agent, kho, keeper, owner_pos = _setup(E)
    p = _branching(E, cskh, kho, owner_pos)

    def run(amount, minutes_back):
        inst = E.c.post(f"/api/team/processes/{p['id']}/start", json={"amount_usd": amount}, headers=E.tok("member")).json()
        pi = E.db.get(ProcessInstance, inst["id"]); pi.started_at = datetime.utcnow() - timedelta(minutes=minutes_back)
        E.db.commit()
        for i, s in enumerate(inst["steps"]):
            got = _inst(E, inst["id"])
            if got["steps"][i]["status"] != "active":
                continue
            if s["branch"] == "Duyệt":   # nhánh duyệt bắt đầu 40 phút trước
                r = E.db.get(ProcessStepRun, s["id"]); r.activated_at = datetime.utcnow() - timedelta(minutes=40)
                E.db.commit()
            _finish(E, s["task_id"])
        return _inst(E, inst["id"])

    big = run(80, 60)
    assert _st(big) == ["done"] * 6 and big["status"] == "done"
    small = run(20, 10)
    assert _st(small) == ["done", "skipped", "done", "done", "done", "done"] and small["status"] == "done"
    row = next(i for i in E.c.get(f"/api/team/processes?company_id={E.co.id}", headers=E.tok("member")).json()["items"]
               if i["id"] == p["id"])
    br = {b["branch"]: b for b in row["stats"]["branches"]}
    assert br["Duyệt"]["runs"] == 1 and 39 <= br["Duyệt"]["avg_minutes"] <= 41
    paths = {x["path"]: x for x in row["stats"]["paths"]}
    assert paths["Duyệt"]["instances"] == 1 and paths["—"]["instances"] == 1
    assert paths["Duyệt"]["avg_cycle_minutes"] > paths["—"]["avg_cycle_minutes"]


def test_condition_on_previous_step_outcome_and_dead_branch_propagates(E):
    cskh, agent, kho, keeper, owner_pos = _setup(E)
    body = {"company_id": E.co.id, "name": "Xử lý khiếu nại", "category": "6",
            "steps": [{"name": "Kiểm tra", "position_id": cskh["id"]},
                      {"name": "Đổi hàng", "position_id": kho["id"], "branch": "Đổi",
                       "condition": {"field": "step1.outcome", "op": "==", "value": "lỗi"}},
                      {"name": "Gửi hàng đổi", "position_id": kho["id"], "branch": "Đổi"},
                      {"name": "Cảm ơn khách", "position_id": cskh["id"], "depends_on": [1],
                       "condition": {"field": "input.vip", "op": "not_empty"}}]}
    p = E.c.post("/api/team/processes", json=body, headers=E.tok("manager")).json()
    # vắng depends_on → nối tiếp bước trước (hành vi tuyến tính cũ)
    assert [s["depends_on"] for s in p["steps"]] == [[], [1], [2], [1]]
    inst = E.c.post(f"/api/team/processes/{p['id']}/start", json={"input": {"vip": ""}}, headers=E.tok("member")).json()
    r = E.c.post(f"/api/team/process-step-runs/{inst['steps'][0]['id']}/outcome", json={"outcome": "Không lỗi"},
                 headers=E.tok("member"))
    assert r.status_code == 200 and r.json()["steps"][0]["outcome"] == "Không lỗi"
    _finish(E, inst["steps"][0]["task_id"])
    got = _inst(E, inst["id"])
    # outcome ≠ "lỗi" → B2 bỏ qua → B3 (chỉ phụ thuộc B2) cũng bỏ qua; vip trống → B4 bỏ qua → lần chạy xong
    assert _st(got) == ["done", "skipped", "skipped", "skipped"]
    assert "đều bị bỏ qua" in got["steps"][2]["skip_reason"] and got["status"] == "done"
    # outcome khớp (không phân biệt hoa thường) → nhánh Đổi chạy
    inst2 = E.c.post(f"/api/team/processes/{p['id']}/start", json={"input": {"vip": "có"}}, headers=E.tok("member")).json()
    E.c.post(f"/api/team/process-step-runs/{inst2['steps'][0]['id']}/outcome", json={"outcome": "LỖI"}, headers=E.tok("member"))
    _finish(E, inst2["steps"][0]["task_id"])
    assert _st(_inst(E, inst2["id"])) == ["done", "active", "waiting", "active"]
    # tổ chức khác không ghi được kết quả bước
    assert E.c.post(f"/api/team/process-step-runs/{inst2['steps'][1]['id']}/outcome", json={"outcome": "x"},
                    headers=E.tok("other")).status_code == 404


def test_graph_validation_and_legacy_linear_rows(E):
    cskh, agent, kho, keeper, owner_pos = _setup(E)

    def bad(steps):
        r = E.c.post("/api/team/processes", json={"company_id": E.co.id, "name": "X", "steps": steps},
                     headers=E.tok("manager"))
        assert r.status_code == 422, r.text
        return r.json()["detail"]
    assert "đứng trước" in bad([{"name": "a"}, {"name": "b", "depends_on": [2]}])          # tự phụ thuộc / vòng
    assert "đứng trước" in bad([{"name": "a", "depends_on": [2]}, {"name": "b"}])          # trỏ về sau
    assert "phép so sánh" in bad([{"name": "a", "condition": {"field": "amount_usd", "op": "~", "value": 1}}])
    assert "trường điều kiện" in bad([{"name": "a", "condition": {"field": "password", "op": "==", "value": 1}}])
    assert "con số" in bad([{"name": "a", "condition": {"field": "amount_usd", "op": ">=", "value": "nhiều"}}])
    assert "bước đứng trước" in bad([{"name": "a", "condition": {"field": "step1.outcome", "op": "==", "value": "x"}}])
    # hàng cũ chưa có đồ thị (depends_on NULL, như trước migration 0044) vẫn chạy tuyến tính
    p = E.c.post("/api/team/processes", json={"company_id": E.co.id, "name": "Cũ",
                                              "steps": [{"name": "a", "position_id": cskh["id"]},
                                                        {"name": "b", "position_id": kho["id"]}]},
                 headers=E.tok("manager")).json()
    for s in E.db.query(ProcessStep).filter(ProcessStep.process_id == p["id"]).all():
        s.depends_on = None
    E.db.commit()
    inst = E.c.post(f"/api/team/processes/{p['id']}/start", json={}, headers=E.tok("member")).json()
    assert _st(inst) == ["active", "waiting"] and inst["steps"][1]["depends_on"] == [1]
    _finish(E, inst["steps"][0]["task_id"])
    assert _st(_inst(E, inst["id"])) == ["done", "active"]


def test_eval_condition_rules():
    ev = process_map.eval_condition
    assert ev(None, {}) is True
    assert ev({"field": "amount_usd", "op": ">=", "value": 50}, {"amount_usd": 50}) is True
    assert ev({"field": "amount_usd", "op": ">=", "value": 50}, {"amount_usd": None}) is False
    assert ev({"field": "input.k", "op": "empty", "value": None}, {}) is True
    assert ev({"field": "input.k", "op": "!=", "value": "a"}, {"input.k": "A"}) is False
    assert ev({"field": "input.n", "op": "==", "value": "5"}, {"input.n": 5.0}) is True
