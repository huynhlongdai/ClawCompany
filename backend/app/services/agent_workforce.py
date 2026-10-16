"""M2e.5 — HR cho ghế agent: đo đúng những thứ nhân sự truyền thống không đo được ở người.

Mỗi ghế agent (30 ngày):
* **Tuân thủ luật cứng** — lượt chạy không vi phạm / tổng lượt (``runtime_rules.compliance``, M2e.2).
* **Đúng hợp đồng dữ liệu** — lần nộp hợp lệ / tổng lần nộp + đạt ngay lần đầu (``io_contracts.conformance``, M2e.3).
* **Nhất quán** — cùng một đầu vào có cho cùng chất lượng không: từ các lần đánh giá k lần (``eval_runs``, 90 ngày),
  chất lượng mỗi lần thử = tỷ lệ tiêu chí đạt (must_include / must_not_include); phương sai theo ca; điểm nhất quán =
  1 − 2 × độ lệch chuẩn trung bình (1 = lần nào cũng như nhau; 0 = nửa đạt nửa trượt).
* **Đạt SLA** — đồng hồ SLA đóng đúng hạn (``operating_time.attainment``, M2e.4).
* **Giờ làm 24/7** — tổng thời lượng lượt chạy, phần ngoài giờ hành chính (T2–T6 08:00–17:30 giờ VN), số ô giờ trong
  tuần (7×24) có hoạt động.
* **Chi phí mỗi việc (USD)** — chi phí lượt chạy / việc xong.

Ghế người giữ trường HR thường (chức danh, giờ làm/tuần, trong giờ hay không, nghỉ phép, việc xong, SLA)."""
from __future__ import annotations

import statistics
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.models import Agent, Member, Task
from app.models.company_foundation import Position

VN = ZoneInfo("Asia/Ho_Chi_Minh")
UTC = ZoneInfo("UTC")


def _office(local: datetime) -> bool:
    return local.weekday() < 5 and (8 * 60) <= local.hour * 60 + local.minute < (17 * 60 + 30)


def hours_worked(db: Session, member_id: int, since: datetime, now: datetime | None = None) -> dict:
    """Thời lượng lượt chạy (bắt đầu → kết thúc; lượt đang chạy tính tới ``now``), chia theo giờ hành chính / ngoài giờ
    theo từng phút ở giờ Việt Nam."""
    from app.models.work_graph import TaskRun
    now = now or datetime.utcnow()
    runs = db.query(TaskRun).filter(TaskRun.member_id == member_id, TaskRun.created_at >= since).all()
    total = after = 0.0
    slots: set[tuple[int, int]] = set()
    for r in runs:
        a = r.started_at or r.created_at
        b = r.ended_at or (now if r.status in ("running", "queued", "dispatched") else None)
        if a is None or b is None or b <= a:
            continue
        b = min(b, a + timedelta(hours=6))         # một lượt treo không được tính thành cả ngày công
        t = a
        while t < b:
            step = min(b, t + timedelta(minutes=5))
            mins = (step - t).total_seconds() / 60
            loc = t.replace(tzinfo=UTC).astimezone(VN)
            total += mins
            if not _office(loc):
                after += mins
            slots.add((loc.weekday(), loc.hour))
            t = step
    return {"hours": round(total / 60, 2), "after_hours": round(after / 60, 2),
            "after_hours_share": round(after / total, 4) if total else None, "active_slots": len(slots), "runs": len(runs)}


def consistency(db: Session, agent_id: int, *, days: int = 90) -> dict:
    from app.models.learning import EvalRun, EvalSuite
    since = datetime.utcnow() - timedelta(days=days)
    runs = db.query(EvalRun).filter(EvalRun.agent_id == agent_id, EvalRun.created_at >= since).all()
    stdevs, variances, cases = [], [], 0
    for r in runs:
        suite = db.get(EvalSuite, r.suite_id)
        spec = {c.get("prompt"): c for c in (suite.cases or [])} if suite else {}
        for res in r.results or []:
            tries = res.get("tries") or []
            if len(tries) < 2:
                continue
            c = spec.get(res.get("prompt")) or {}
            total = len(c.get("must_include") or []) + len(c.get("must_not_include") or [])
            q = [(1 - (len(t.get("missing") or []) + len(t.get("forbidden") or [])) / total) if total else float(bool(t.get("passed")))
                 for t in tries]
            stdevs.append(statistics.pstdev(q)); variances.append(statistics.pvariance(q)); cases += 1
    if not cases:
        return {"score": None, "variance": None, "cases": 0, "eval_runs": len(runs)}
    return {"score": round(max(0.0, 1 - 2 * statistics.mean(stdevs)), 4), "variance": round(statistics.mean(variances), 4),
            "cases": cases, "eval_runs": len(runs)}


def seat_metrics(db: Session, m: Member, *, days: int = 30, now: datetime | None = None) -> dict:
    from app.models.work_graph import TaskRun
    from app.services import io_contracts, operating_time, runtime_rules
    now = now or datetime.utcnow()
    since = now - timedelta(days=days)
    ag = db.query(Agent).filter(Agent.member_id == m.id).first()
    from sqlalchemy import func
    done = db.query(Task).filter(Task.assignee_member_id == m.id, Task.status == "done",
                                 func.coalesce(Task.completed_at, Task.updated_at) >= since).count()
    cost = round(sum(r.cost_usd or 0 for r in db.query(TaskRun).filter(TaskRun.member_id == m.id, TaskRun.created_at >= since).all()), 4)
    rules = runtime_rules.compliance(db, m, days=days, now=now)
    conf = io_contracts.conformance(db, member_ids=[m.id], days=days)
    sla = operating_time.attainment(db, member_ids=[m.id], days=days)
    return {"member_id": m.id, "agent_id": ag.id if ag else None, "days": days,
            "rule_compliance_rate": rules["rate"], "rule_violations": rules["violations"],
            "output_conformance_rate": conf["rate"], "output_first_try_rate": conf["first_try_rate"], "output_submissions": conf["submissions"],
            "consistency": consistency(db, ag.id) if ag else {"score": None, "variance": None, "cases": 0, "eval_runs": 0},
            "sla_attainment_rate": sla["rate"], "sla_closed": sla["closed"], "sla_breached": sla["breached"],
            "hours": hours_worked(db, m.id, since, now), "tasks_done": done, "cost_usd": cost,
            "cost_per_task_usd": round(cost / done, 4) if done else None}


def _avg(xs: list) -> float | None:
    xs = [x for x in xs if x is not None]
    return round(sum(xs) / len(xs), 4) if xs else None


def company_summary(db: Session, org_id: int, company_id: int | None, *, days: int = 30) -> dict:
    from app.services import authority, operating_time
    from app.services.company_foundation import _company
    co = _company(db, org_id, company_id)
    members = db.query(Member).filter(Member.company_id == co.id, Member.status.notin_(("archived", "retired"))).order_by(Member.id).all()
    titles = {p.id: p.title for p in db.query(Position).filter(Position.company_id == co.id).all()}
    agents, humans = [], []
    for m in members:
        if m.member_type == "agent":
            x = seat_metrics(db, m, days=days)
            x.update(name=m.name, position=titles.get(m.position_id), level=authority.career_level(db, m))
            agents.append(x)
        else:
            v = operating_time.seat_view(db, m)
            since = datetime.utcnow() - timedelta(days=days)
            humans.append({"member_id": m.id, "name": m.name, "position": titles.get(m.position_id), "role": m.role,
                           "weekly_hours": v["weekly_hours"], "on_duty": v["on_duty"], "next_on_duty_local": v["next_on_duty_local"],
                           "leaves": len(v["leaves"]), "off_today": v["off_today"],
                           "tasks_done": db.query(Task).filter(Task.assignee_member_id == m.id, Task.status == "done",
                                                               Task.completed_at >= since).count(),
                           "sla_attainment_rate": operating_time.attainment(db, member_ids=[m.id], days=days)["rate"]})
    hours = sum(a["hours"]["hours"] for a in agents)
    after = sum(a["hours"]["after_hours"] for a in agents)
    cost = round(sum(a["cost_usd"] for a in agents), 4)
    done = sum(a["tasks_done"] for a in agents)
    return {"company_id": co.id, "company_name": co.name, "days": days, "agents": agents, "humans": humans,
            "totals": {"agents": len(agents), "humans": len(humans),
                       "rule_compliance_rate": _avg([a["rule_compliance_rate"] for a in agents]),
                       "output_conformance_rate": _avg([a["output_conformance_rate"] for a in agents]),
                       "consistency": _avg([a["consistency"]["score"] for a in agents]),
                       "sla_attainment_rate": _avg([a["sla_attainment_rate"] for a in agents]),
                       "hours": round(hours, 2), "after_hours": round(after, 2),
                       "after_hours_share": round(after / hours, 4) if hours else None,
                       "cost_usd": cost, "tasks_done": done, "cost_per_task_usd": round(cost / done, 4) if done else None}}
