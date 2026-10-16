"""M2e.5 — HR agent: mỗi ghế agent có tỷ lệ tuân thủ luật, đúng hợp đồng dữ liệu, độ nhất quán (phương sai chất lượng
qua k lần đánh giá), đạt SLA, giờ làm 24/7 (phần ngoài giờ hành chính), chi phí mỗi việc USD — trên scorecard và trên
tổng hợp "Nhân sự agent" của công ty; ghế người giữ trường HR thường. ORM thật trên SQLite."""
from datetime import datetime, timedelta

from app.models import Agent, Member, Project, Task
from app.models.agent_native import RuleViolation, TaskOutput
from app.models.learning import EvalRun, EvalSuite
from app.models.work_graph import TaskRun
from app.services import agent_workforce as aw
from tests.test_m2b_company_foundation import E, mkpos  # noqa: F401  (fixture)
from tests.test_m3_agents import env, hire  # noqa: F401  (fixture)


def vn(y, mo, d, h, mi=0):
    return datetime(y, mo, d, h, mi) - timedelta(hours=7)


def _seat(E):
    pos = mkpos(E, title="CSKH online", department_id=E.sales.id, headcount=2)
    a = hire(E, position_id=pos["id"], role="")
    ag = E.db.get(Agent, a["agent_id"]); m = E.db.get(Member, ag.member_id)
    return pos, ag, m


def test_hours_split_office_vs_after_hours_and_slots(E):
    pos, ag, m = _seat(E)
    pr = Project(company_id=E.co.id, name="P", status="active"); E.db.add(pr); E.db.commit()
    t = Task(project_id=pr.id, title="x", status="done", assignee_member_id=m.id); E.db.add(t); E.db.commit()
    # thứ Hai 16:30–18:30 VN: 1 giờ trong giờ hành chính (tới 17:30), 1 giờ ngoài giờ; Chủ nhật 02:00–02:30: ngoài giờ
    E.db.add(TaskRun(organization_id=E.org.id, task_id=t.id, member_id=m.id, status="completed", started_at=vn(2026, 10, 19, 16, 30),
                     ended_at=vn(2026, 10, 19, 18, 30), created_at=vn(2026, 10, 19, 16, 30), cost_usd=0.3))
    E.db.add(TaskRun(organization_id=E.org.id, task_id=t.id, member_id=m.id, status="completed", started_at=vn(2026, 10, 18, 2),
                     ended_at=vn(2026, 10, 18, 2, 30), created_at=vn(2026, 10, 18, 2), cost_usd=0.1))
    E.db.commit()
    h = aw.hours_worked(E.db, m.id, vn(2026, 10, 1, 0), vn(2026, 10, 20, 0))
    assert (h["hours"], h["after_hours"], h["runs"]) == (2.5, 1.5, 2)
    assert h["after_hours_share"] == 0.6 and h["active_slots"] == 4         # T2 16h,17h,18h + CN 2h


def test_consistency_from_k_runs_variance(E):
    pos, ag, m = _seat(E)
    s = EvalSuite(organization_id=E.org.id, title="CSKH", k=3,
                  cases=[{"prompt": "hàng vỡ?", "must_include": ["đổi", "7 ngày"], "must_not_include": ["100%"]},
                         {"prompt": "giờ mở cửa?", "must_include": ["8 giờ"], "must_not_include": []}])
    E.db.add(s); E.db.commit()
    assert aw.consistency(E.db, ag.id)["score"] is None                  # chưa đánh giá → chưa có số (không bịa)
    ok = {"passed": True, "missing": [], "forbidden": []}
    E.db.add(EvalRun(suite_id=s.id, agent_id=ag.id, k=3, pass_at_1=0.83, pass_k=0.5, results=[
        {"prompt": "hàng vỡ?", "passed": 2, "k": 3, "tries": [ok, ok, {"passed": False, "missing": ["7 ngày"], "forbidden": ["100%"]}]},
        {"prompt": "giờ mở cửa?", "passed": 3, "k": 3, "tries": [ok, ok, ok]}]))
    E.db.commit()
    c = aw.consistency(E.db, ag.id)
    # ca 1: chất lượng [1, 1, 1/3] → độ lệch chuẩn 0.314; ca 2: [1,1,1] → 0 → điểm = 1 − 2 × 0.157
    assert c["cases"] == 2 and c["eval_runs"] == 1
    assert abs(c["score"] - (1 - 2 * (0.31427 / 2))) < 0.001 and c["variance"] > 0


def test_scorecard_and_company_summary_carry_agent_hr_metrics(E):
    pos, ag, m = _seat(E)
    pr = Project(company_id=E.co.id, name="P", status="active"); E.db.add(pr); E.db.commit()
    t = Task(project_id=pr.id, title="Trả lời khách", status="done", assignee_member_id=m.id, completed_at=datetime.utcnow())
    E.db.add(t); E.db.commit()
    now = datetime.utcnow()
    for i in range(4):
        E.db.add(TaskRun(organization_id=E.org.id, task_id=t.id, member_id=m.id, status="completed", started_at=now - timedelta(hours=3 + i),
                         ended_at=now - timedelta(hours=2 + i), created_at=now - timedelta(hours=3 + i), cost_usd=0.25,
                         runtime_run_id=f"r{i}"))
    E.db.add(RuleViolation(organization_id=E.org.id, company_id=E.co.id, member_id=m.id, run_id="r1", hook="mcp", action_taken="block"))
    E.db.add(TaskOutput(organization_id=E.org.id, company_id=E.co.id, task_id=t.id, member_id=m.id, attempt=1, valid=False))
    E.db.add(TaskOutput(organization_id=E.org.id, company_id=E.co.id, task_id=t.id, member_id=m.id, attempt=2, valid=True))
    E.db.commit()
    card = E.c.get(f"/api/learning/career/{ag.id}", headers=E.tok("manager")).json()
    card = card.get("scorecard", card)
    assert card["rule_compliance_rate"] == 0.75 and card["output_conformance_rate"] == 0.5
    assert card["hours"]["hours"] == 4.0 and card["cost_per_task_usd"] == 1.0 and card["consistency"]["score"] is None
    s = E.c.get(f"/api/team/agent-hr?company_id={E.co.id}", headers=E.tok("member")).json()
    row = next(a for a in s["agents"] if a["member_id"] == m.id)
    assert row["position"] == "CSKH online" and row["level"] in ("probation", "standard", "trusted")
    assert row["tasks_done"] == 1 and row["cost_usd"] == 1.0 and row["output_first_try_rate"] == 0.0
    assert s["totals"]["agents"] >= 1 and s["totals"]["hours"] >= 4.0
    # ghế người: trường HR thường (giờ làm/tuần, nghỉ), không có tỷ lệ tuân thủ / nhất quán
    human = next(h for h in s["humans"] if h["member_id"] == E.lead_m.id) if any(h["member_id"] == E.lead_m.id for h in s["humans"]) else s["humans"][0]
    assert human["weekly_hours"] == 51.5   # 5 × 9,5 giờ + 4 giờ thứ Bảy and "rule_compliance_rate" not in human and "consistency" not in human
