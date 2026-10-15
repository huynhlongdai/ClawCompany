"""M2c D5 — KPI chia tầng: mục tiêu công ty → phòng → chức danh (từ M2b) → seat; số tự tính từ dữ liệu
thật (việc xong, chu trình D4, phê duyệt), nhập tay khi không có dữ liệu, cuộn tiến độ lên, KPI seat vào
scorecard của agent. ORM thật trên SQLite."""
from datetime import datetime, timedelta

from app.models import ExecutiveGoal, Task
from app.models.company_ops import ProcessInstance, ProcessStepRun
from app.services import kpi_cascade as kc
from tests.test_m2b_company_foundation import E, mkpos  # noqa: F401  (fixture)
from tests.test_m2c_process_map import _finish, _process, _setup
from tests.test_m3_agents import env, hire  # noqa: F401  (fixture)


def kpi(E, role="manager", **body):
    r = E.c.post("/api/team/kpis", json={"company_id": E.co.id, **body}, headers=E.tok(role))
    assert r.status_code == 200, r.text
    return r.json()


def _run_once(E, cskh, kho, owner_pos, minutes=40):
    p = _process(E, cskh, kho, owner_pos)
    inst = E.c.post(f"/api/team/processes/{p['id']}/start", json={"amount_usd": 10}, headers=E.tok("member")).json()
    back = datetime.utcnow() - timedelta(minutes=minutes)
    pi = E.db.get(ProcessInstance, inst["id"]); pi.started_at = back
    r1 = E.db.get(ProcessStepRun, inst["steps"][0]["id"]); r1.activated_at = back
    E.db.commit()
    for s in inst["steps"]:
        _finish(E, s["task_id"])
    return p, inst


def test_period_windows_follow_vietnam_time():
    now = datetime(2026, 10, 15, 20, 0)          # 03:00 ngày 16/10 giờ VN
    assert kc.period_window("month", now)[0] == "2026-10"
    key, start, end = kc.period_window("month", now)
    assert start == datetime(2026, 9, 30, 17, 0) and end == datetime(2026, 10, 31, 17, 0)
    assert kc.period_window("week", now)[0] == "2026-W42"
    assert kc.period_window("quarter", now)[0] == "2026-Q4"
    assert kc.period_window("month", datetime(2026, 12, 31, 18, 0))[0] == "2027-01"   # 01:00 1/1 giờ VN
    assert kc.progress(30, 40, "down") == 133.3 and kc.progress(50, 100, "up") == 50.0 and kc.progress(None, 1, "up") is None


def test_cascade_company_goal_to_department_to_position_to_seat_with_real_numbers(E):
    cskh, agent, kho, keeper, owner_pos = _setup(E)
    goal = ExecutiveGoal(organization_id=E.org.id, company_id=E.co.id, title="Xử lý khiếu nại nhanh hơn",
                         objective="Rút ngắn hoàn tiền", status="active", progress=20)
    E.db.add(goal); E.db.commit()
    co = kpi(E, level="company", name="Lần chạy hoàn tiền xong", metric="process_runs_done", target=2, goal_id=goal.id)
    dept = kpi(E, level="department", department_id=E.sales.id, name="Việc xong của phòng bán hàng", metric="tasks_done",
               target=4, parent_id=co["id"])
    # KPI của chức danh (M2b) → tầng chức danh + seat
    E.c.patch(f"/api/team/positions/{cskh['id']}", headers=E.tok("manager"),
              json={"kpis": [{"name": "Thời gian chu trình hoàn tiền", "target": 60, "unit": "phút", "period": "month"},
                             {"name": "CSAT", "target": 4.5, "unit": "điểm", "period": "month"}]})
    r = E.c.post("/api/team/kpis/sync-positions", json={"company_id": E.co.id}, headers=E.tok("manager"))
    assert r.status_code == 200 and r.json()["created"] == 4          # 2 KPI chức danh + 2 KPI seat (1 người ngồi)
    assert E.c.post("/api/team/kpis/sync-positions", json={"company_id": E.co.id}, headers=E.tok("manager")).json()["created"] == 0
    p, inst = _run_once(E, cskh, kho, owner_pos, minutes=40)
    got = E.c.get(f"/api/team/kpis?company_id={E.co.id}", headers=E.tok("member")).json()
    items = {i["name"] + "/" + i["level"]: i for i in got["items"]}
    c = items["Lần chạy hoàn tiền xong/company"]
    assert c["value"] == 1 and c["progress"] == 50.0 and c["health"] == "off_track" and c["goal"]["title"] == goal.title
    d = items["Việc xong của phòng bán hàng/department"]
    assert d["value"] == 2 and d["progress"] == 50.0 and d["value_source"] == "auto"   # 2 bước của CSKH (phòng bán hàng)
    pos = items["Thời gian chu trình hoàn tiền/position"]
    assert pos["metric"] == "cycle_time_minutes" and pos["direction"] == "down"
    seat = items["Thời gian chu trình hoàn tiền/seat"]
    assert seat["owner"] == "Thu Trang" and seat["value"] is not None and seat["parent_id"] == pos["id"]
    csat = items["CSAT/seat"]
    assert csat["metric"] == "manual" and csat["value"] is None and csat["health"] == "no_data"
    # nhập tay CSAT cho kỳ này
    r = E.c.post(f"/api/team/kpis/{csat['id']}/measurements", json={"value": 4.8, "note": "khảo sát Zalo"}, headers=E.tok("member"))
    assert r.status_code == 200 and r.json()["value"] == 4.8 and r.json()["value_source"] == "manual" and r.json()["progress"] == 106.7
    # cây + cuộn lên: công ty → phòng
    got = E.c.get(f"/api/team/kpis?company_id={E.co.id}", headers=E.tok("member")).json()
    root = next(n for n in got["tree"] if n["id"] == co["id"])
    assert root["children"][0]["id"] == dept["id"] and root["rollup"] == 50.0
    assert got["summary"]["company_progress"] == 50.0 and got["summary"]["kpis"] == 6
    pos_node = next(n for n in got["tree"] if n["id"] == pos["id"])
    assert pos_node["rollup"] is not None and pos_node["children"][0]["id"] == seat["id"]
    # scorecard của agent nhận KPI seat
    card = E.c.get(f"/api/learning/career/{agent['agent_id']}", headers=E.tok("member")).json()["scorecard"]
    assert {k["name"] for k in card["kpis"]} == {"Thời gian chu trình hoàn tiền", "CSAT"}
    assert card["kpi_attainment"] is not None


def test_auto_metrics_cost_first_pass_and_approvals(E):
    cskh, agent, kho, keeper, owner_pos = _setup(E)
    p = _process(E, cskh, kho, owner_pos)
    E.c.post(f"/api/team/processes/{p['id']}/start", json={"amount_usd": 80}, headers=E.tok("member"))
    pend = kpi(E, level="seat", member_id=agent["member_id"], name="Phê duyệt đang chờ", metric="approvals_pending", target=0)
    assert pend["direction"] == "down" and pend["value"] == 0
    # bước hoàn tiền vào review → approval của chặng D2.2 đứng tên agent (người xin)
    inst = E.c.get(f"/api/team/processes/{p['id']}/instances", headers=E.tok("member")).json()["items"][0]
    _finish(E, inst["steps"][0]["task_id"]); _finish(E, inst["steps"][1]["task_id"])
    got = E.c.get(f"/api/team/kpis?company_id={E.co.id}", headers=E.tok("member")).json()
    assert next(i for i in got["items"] if i["id"] == pend["id"])["value"] == 1
    onetime = kpi(E, level="company", name="% bước đúng hạn", metric="on_time_rate", target=90)
    assert onetime["value"] == 100.0       # bước 1 xong ngay, trong 20 phút kỳ vọng
    fp = kpi(E, level="company", name="Qua review lần đầu", metric="first_pass_rate", target=80)
    assert fp["value"] is None and fp["health"] == "no_data"


def test_validation_cycles_scopes_and_permissions(E):
    a = kpi(E, level="company", name="A", target=1)
    b = kpi(E, level="company", name="B", target=1, parent_id=a["id"])
    r = E.c.patch(f"/api/team/kpis/{a['id']}", json={"parent_id": b["id"]}, headers=E.tok("manager"))
    assert r.status_code == 409 and "vòng" in r.json()["detail"]
    r = E.c.post("/api/team/kpis", json={"company_id": E.co.id, "level": "seat", "name": "x"}, headers=E.tok("manager"))
    assert r.status_code == 422 and "chọn người" in r.json()["detail"]
    r = E.c.post("/api/team/kpis", json={"company_id": E.co.id, "name": "x", "metric": "doanh_thu_ao"}, headers=E.tok("manager"))
    assert r.status_code == 422 and "Nhập tay" in r.json()["detail"]
    assert E.c.post("/api/team/kpis", json={"company_id": E.co.id, "name": "x"}, headers=E.tok("member")).status_code == 403
    assert E.c.post(f"/api/team/kpis/{a['id']}/measurements", json={"value": 1}, headers=E.tok("other")).status_code == 404
    # xoá cha → con lên tầng trên
    assert E.c.delete(f"/api/team/kpis/{a['id']}", headers=E.tok("manager")).status_code == 200
    got = E.c.get(f"/api/team/kpis?company_id={E.co.id}", headers=E.tok("member")).json()
    assert [i["id"] for i in got["items"]] == [b["id"]] and got["items"][0]["parent_id"] is None
    assert kc.guess_metric("Thời gian chu trình đơn") == "cycle_time_minutes" and kc.guess_metric("CSAT") == "manual"
