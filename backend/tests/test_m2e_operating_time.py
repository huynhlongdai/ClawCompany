"""M2e.4 — vận hành 24/7: ghế agent luôn trực, ghế người có giờ làm + nghỉ phép + nghỉ lễ (giờ VN), SLA theo bước /
chức danh có đồng hồ (phút trực của ghế), quá hạn → leo thang tới người + Hộp việc, việc ngoài giờ → agent cùng chức danh
hoặc xếp hàng "người xử lý lúc HH:MM", lưới độ phủ 7×24, KPI % đạt SLA, giao ban có ca đêm của agent.
Thời điểm truyền tường minh (không phụ thuộc giờ chạy test). ORM thật trên SQLite."""
from datetime import date, datetime, timedelta

from app.models import Agent, Member, Task
from app.models.agent_native import AfterHoursRoute, SlaTimer
from app.models.company_ops import PublicHoliday
from app.models.extended import InboxItem
from app.services import operating_time as ot
from tests.test_m2b_company_foundation import E, mkpos  # noqa: F401  (fixture)
from tests.test_m2c_process_map import _setup
from tests.test_m3_agents import env, hire  # noqa: F401  (fixture)


def vn(y, mo, d, h, mi=0):
    """Giờ Việt Nam → UTC naive (VN = UTC+7, không đổi giờ mùa)."""
    return datetime(y, mo, d, h, mi) - timedelta(hours=7)


MON_9 = vn(2026, 10, 19, 9)          # thứ Hai 19/10/2026 09:00
MON_22 = vn(2026, 10, 19, 22)


def _human(E, name="Chị Hoa", pos=None):
    m = Member(organization_id=E.org.id, company_id=E.co.id, department_id=E.sales.id, name=name, member_type="human",
               role="CSKH", manager_id=E.lead_m.id, status="active")
    E.db.add(m); E.db.commit()
    if pos:
        assert E.c.post(f"/api/team/positions/{pos['id']}/seats", json={"member_id": m.id}, headers=E.tok("manager")).status_code == 200
        E.db.refresh(m)
    return m


def test_schedules_leaves_holidays_and_working_minutes(E):
    h = _human(E)
    a = hire(E)
    ag = E.db.get(Member, E.db.get(Agent, a["agent_id"]).member_id)
    assert ot.on_duty(E.db, h, MON_9) and not ot.on_duty(E.db, h, MON_22)
    assert not ot.on_duty(E.db, h, vn(2026, 10, 18, 10))                        # Chủ nhật
    assert ot.on_duty(E.db, ag, MON_22) and ot.on_duty(E.db, ag, vn(2026, 10, 18, 3))    # agent 24/7
    assert ot.next_on_duty(E.db, h, MON_22) == vn(2026, 10, 20, 8)
    assert ot.local_hm(E.db, h, vn(2026, 10, 20, 8)).startswith("08:00")
    # 60 phút trực từ thứ Sáu 17:00 → 30 phút thứ Sáu + 30 phút sáng thứ Bảy
    assert ot.add_working_minutes(E.db, h, vn(2026, 10, 23, 17), 60) == vn(2026, 10, 24, 8, 30)
    assert ot.add_working_minutes(E.db, ag, vn(2026, 10, 23, 17), 60) == vn(2026, 10, 23, 18)
    # nghỉ phép + lễ
    r = E.c.post(f"/api/team/seats/{h.id}/leaves", json={"start_date": "2026-10-19", "end_date": "2026-10-19", "kind": "sick"},
                 headers=E.tok("manager"))
    assert r.status_code == 200, r.text
    assert not ot.on_duty(E.db, h, MON_9) and ot.next_on_duty(E.db, h, MON_9) == vn(2026, 10, 20, 8)
    E.db.add(PublicHoliday(organization_id=E.org.id, year=2026, day=date(2026, 10, 20), name="Lễ thử", kind="holiday"))
    E.db.commit()
    assert ot.next_on_duty(E.db, h, MON_9) == vn(2026, 10, 21, 8)
    assert E.c.post(f"/api/team/seats/{ag.id}/leaves", json={"start_date": "2026-10-19"}, headers=E.tok("manager")).status_code == 422
    # giờ làm riêng: ca tối 18:00–23:00 mọi ngày
    bad = E.c.put(f"/api/team/seats/{h.id}/schedule", json={"weekly": {"0": [["08:00", "12:00"], ["11:00", "13:00"]]}}, headers=E.tok("manager"))
    assert bad.status_code == 422 and "chồng" in bad.json()["detail"]
    ok = E.c.put(f"/api/team/seats/{h.id}/schedule", json={"weekly": {str(d): [["18:00", "23:00"]] for d in range(7)},
                                                          "observe_holidays": False}, headers=E.tok("manager")).json()
    assert ok["weekly_hours"] == 35.0 and ok["default_schedule"] is False
    assert ot.on_duty(E.db, h, vn(2026, 10, 20, 22)) and not ot.on_duty(E.db, h, vn(2026, 10, 20, 9))
    assert E.c.put(f"/api/team/seats/{ag.id}/schedule", json={"weekly": {}}, headers=E.tok("manager")).status_code == 422


def test_after_hours_task_goes_to_agent_of_same_position_else_queued(E):
    cskh, agent, kho, keeper, owner_pos = _setup(E)
    ag = E.db.get(Member, E.db.get(Agent, agent["agent_id"]).member_id)
    h = _human(E, pos=cskh)
    t = Task(project_id=E.db.query(Task).first().project_id if E.db.query(Task).first() else None, title="Khách hỏi đổi hàng",
             status="todo", assignee_member_id=h.id)
    if t.project_id is None:
        from app.models import Project
        pr = Project(company_id=E.co.id, name="P", status="active"); E.db.add(pr); E.db.commit(); t.project_id = pr.id
    E.db.add(t); E.db.commit()
    assert ot.route(E.db, t, MON_9) is None                        # trong giờ: không đổi
    r = ot.route(E.db, t, MON_22)
    assert r["action"] == "rerouted" and r["to"] == ag.id and t.assignee_member_id == ag.id
    assert E.db.query(AfterHoursRoute).filter(AfterHoursRoute.task_id == t.id).one().from_member_id == h.id
    assert E.db.query(InboxItem).filter(InboxItem.recipient_member_id == h.id, InboxItem.task_id == t.id).count() == 1
    # chức danh chỉ có người (thủ kho) → xếp hàng, ghi giờ người xử lý
    t2 = Task(project_id=t.project_id, title="Kiểm hàng hoàn", status="todo", assignee_member_id=keeper.id)
    E.db.add(t2); E.db.commit()
    r2 = ot.route(E.db, t2, MON_22)
    assert r2["action"] == "queued" and r2["next_on_duty_local"].startswith("08:00") and t2.assignee_member_id == keeper.id
    assert ot.route(E.db, t2, MON_22) is None                      # idempotent
    # người trực lại → hàng chờ đóng
    ot.tick(E.db, vn(2026, 10, 20, 8, 5))
    assert E.db.query(AfterHoursRoute).filter(AfterHoursRoute.task_id == t2.id).one().status == "done"


def test_pick_assignee_prefers_on_duty_seat(E, monkeypatch):
    from app.services import process_map
    cskh, agent, *_ = _setup(E)
    ag = E.db.get(Member, E.db.get(Agent, agent["agent_id"]).member_id)
    h = _human(E, pos=cskh)
    monkeypatch.setattr(ot, "on_duty", lambda db, m, now=None: m.member_type == "agent" or now == "day")
    assert process_map.pick_assignee(E.db, E.org.id, E.co.id, cskh["id"])[0] == ag.id
    from app.models import Project
    pr = Project(company_id=E.co.id, name="Tải", status="active"); E.db.add(pr); E.db.commit()
    for _ in range(3):   # agent bận hơn nhưng người đang ngoài giờ → vẫn agent
        E.db.add(Task(project_id=pr.id, title="x", status="todo", assignee_member_id=ag.id))
    E.db.commit()
    assert process_map.pick_assignee(E.db, E.org.id, E.co.id, cskh["id"])[0] == ag.id
    monkeypatch.setattr(ot, "on_duty", lambda db, m, now=None: True)
    assert process_map.pick_assignee(E.db, E.org.id, E.co.id, cskh["id"])[0] == h.id     # ban ngày: ít việc hơn


def test_sla_policy_timers_met_and_breach_escalates(E):
    cskh, agent, kho, keeper, owner_pos = _setup(E)
    body = {"company_id": E.co.id, "name": "Đổi trả", "category": "6", "owner_position_id": owner_pos["id"],
            "steps": [{"name": "Tiếp nhận", "position_id": cskh["id"]}, {"name": "Kiểm kho", "position_id": kho["id"]}]}
    p = E.c.post("/api/team/processes", json=body, headers=E.tok("manager")).json()
    s1, s2 = p["steps"]
    assert E.c.post("/api/team/sla-policies", json={"company_id": E.co.id, "position_id": cskh["id"], "process_step_id": s1["id"],
                                                   "first_response_minutes": 5}, headers=E.tok("manager")).status_code == 422
    assert E.c.post("/api/team/sla-policies", json={"company_id": E.co.id, "process_step_id": s1["id"]},
                    headers=E.tok("manager")).status_code == 422
    assert E.c.post("/api/team/sla-policies", json={"company_id": E.co.id, "process_step_id": s1["id"], "first_response_minutes": 30,
                                                   "resolution_minutes": 10}, headers=E.tok("manager")).status_code == 422
    r = E.c.post("/api/team/sla-policies", json={"company_id": E.co.id, "process_step_id": s1["id"], "name": "Phản hồi khách",
                                                "first_response_minutes": 5, "resolution_minutes": 60}, headers=E.tok("manager"))
    assert r.status_code == 200, r.text
    assert r.json()["step"].endswith("B1 Tiếp nhận")
    E.c.post("/api/team/sla-policies", json={"company_id": E.co.id, "position_id": kho["id"], "resolution_minutes": 120},
             headers=E.tok("manager"))
    inst = E.c.post(f"/api/team/processes/{p['id']}/start", json={"title": "Đơn 1"}, headers=E.tok("member")).json()
    t1, t2 = inst["steps"][0]["task_id"], inst["steps"][1]["task_id"]
    timers = E.db.query(SlaTimer).filter(SlaTimer.task_id == t1).order_by(SlaTimer.kind).all()
    assert [(x.kind, x.minutes, x.seat_type) for x in timers] == [("first_response", 5, "agent"), ("resolution", 60, "agent")]
    assert timers[0].due_at == timers[0].started_at + timedelta(minutes=5)         # agent: đồng hồ thật
    # phản hồi đầu: việc chuyển Đang làm
    from app.services import task_lifecycle as lifecycle
    task = E.db.get(Task, t1)
    lifecycle.transition(E.db, task, "in_progress", system=True, reason="t", via="t")
    E.db.refresh(timers[0])
    assert timers[0].status == "met"
    # xử lý xong quá hạn → tick leo thang tới người + Hộp việc
    out = ot.tick(E.db, timers[1].due_at + timedelta(minutes=1))
    assert out["breached"] == 1
    E.db.refresh(timers[1])
    assert timers[1].status == "breached" and timers[1].escalated_to_member_id
    assert E.db.get(Member, timers[1].escalated_to_member_id).member_type == "human"
    card = E.db.query(InboxItem).filter(InboxItem.task_id == t1, InboxItem.recipient_member_id == timers[1].escalated_to_member_id).all()
    assert card and any("SLA" in c.title for c in card)
    for to in ("review", "done"):
        lifecycle.transition(E.db, task, to, system=True, reason="t", via="t")
    a = ot.attainment(E.db, company_id=E.co.id, start=datetime.utcnow() - timedelta(days=1))
    assert (a["closed"], a["met"], a["breached"], a["rate"], a["agent"]) == (2, 1, 1, 0.5, 0.5)
    # bước 2 (người, SLA theo chức danh thủ kho): đồng hồ tính theo giờ làm của người
    t2_timers = E.db.query(SlaTimer).filter(SlaTimer.task_id == t2).all()
    assert [(x.kind, x.seat_type) for x in t2_timers] == [("resolution", "human")]
    x = t2_timers[0]
    assert x.due_at == ot.add_working_minutes(E.db, keeper, x.started_at, 120)
    # KPI % đạt SLA
    k = E.c.post("/api/team/kpis", json={"company_id": E.co.id, "name": "SLA", "level": "company", "metric": "sla_attainment_rate",
                                         "target": 95, "period": "month"}, headers=E.tok("manager"))
    assert k.status_code == 200 and k.json()["value"] == 50.0


def test_coverage_grid_and_standup_overnight(E):
    cskh, agent, kho, keeper, owner_pos = _setup(E)
    cov = E.c.get(f"/api/team/coverage?company_id={E.co.id}", headers=E.tok("member")).json()
    by = {p["title"]: p for p in cov["positions"]}
    assert by["Nhân viên CSKH"]["agent_hours"] == 168 and by["Nhân viên CSKH"]["covered_hours"] == 168
    # thủ kho là người, lịch mặc định: T2–T6 08:00–17:30 (10 giờ có ≥ 30 phút) + T7 08:00–12:00 (4 giờ)
    assert by["Thủ kho"]["human_hours"] == 54 and by["Thủ kho"]["agent_hours"] == 0
    assert by["Thủ kho"]["grid"][0][8] == {"agents": 0, "humans": 1} and by["Thủ kho"]["grid"][6][10] == {"agents": 0, "humans": 0}
    seat = next(s for s in by["Nhân viên CSKH"]["seats"] if s["member_type"] == "agent")
    assert seat["always_on"] and seat["weekly_hours"] == 168.0
    # giao ban: ca đêm của agent (18:00 hôm trước → 08:00)
    ag = E.db.get(Member, E.db.get(Agent, agent["agent_id"]).member_id)
    from app.models import Project
    pr = Project(company_id=E.co.id, name="Đêm", status="active"); E.db.add(pr); E.db.commit()
    t = Task(project_id=pr.id, title="Trả lời khách lúc 2 giờ sáng", status="done", assignee_member_id=ag.id,
             completed_at=vn(2026, 10, 20, 2))
    E.db.add(t); E.db.commit()
    o = ot.overnight(E.db, E.co.id, vn(2026, 10, 20, 8, 30))
    assert o["done"] == 1 and o["done_titles"] == ["Trả lời khách lúc 2 giờ sáng"] and o["window"].startswith("18:00 19/10")
    early = ot.overnight(E.db, E.co.id, vn(2026, 10, 20, 7, 30))          # giao ban trước 08:00: tới bây giờ
    assert early["window"] == "18:00 19/10–07:30 20/10" and early["done"] == 1
    from app.services import operating_rhythm
    d = operating_rhythm.collect(E.db, E.co.id, None, "standup", vn(2026, 10, 20, 8, 30))
    assert d["overnight"]["done"] == 1
    assert "Ca đêm của agent" in operating_rhythm.summarize("Giao ban", d)
