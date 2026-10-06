"""D3.2 — chọn seat theo tải. Phần thuần test bằng SeatState; phần dựng ảnh chụp
test bằng ORM thật (task_runs mở, phong bì ngân sách, seat paused)."""
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
import app.models  # noqa: F401
from app.models import BudgetEnvelope, CompanyEvent, TaskRun
from app.models.entities import Agent, Company, Department, Member, Organization, Project, Task
from app.services import dispatch_policy as dp
from app.services.dispatch_policy import Need, SeatState


def S(mid, **kw):
    kw.setdefault("name", f"S{mid}")
    return SeatState(member_id=mid, **kw)


# ------------------------------------------------------------ 6 tình huống thuần


def test_1_least_loaded_wins_and_reason_says_why():
    d = dp.choose(Need(), [S(1, open_runs=1), S(2, open_runs=0), S(3, open_runs=1)])
    assert d.member_id == 2
    assert "đang mở 0/2 run" in d.reason and "ít tải nhất trong 3 seat" in d.reason
    assert d.eligible == [2, 1, 3]


def test_2_department_filter_first():
    d = dp.choose(Need(department_id=7), [S(1, department_id=8), S(2, department_id=7, open_runs=1)])
    assert d.member_id == 2
    assert "phòng" in d.rejected[1] and "thuộc phòng 8" in d.rejected[1]
    assert "seat duy nhất" in d.reason


def test_3_skills_must_all_match_case_insensitive_unknown_excluded():
    seats = [S(1, skills=("python",)), S(2, skills=("Python", "SQL")), S(3, skills=None)]
    d = dp.choose(Need(skills=("python", "sql")), seats)
    assert d.member_id == 2
    assert d.rejected[1].endswith("thiếu kỹ năng: sql")
    assert "chưa đọc được kỹ năng" in d.rejected[3]
    # việc không yêu cầu kỹ năng thì seat chưa biết kỹ năng vẫn được xét
    assert dp.choose(Need(), [S(3, skills=None)]).member_id == 3


def test_4_inactive_seats_excluded():
    seats = [S(1, member_status="paused"), S(2, lifecycle="provisioning"), S(3, open_runs=1)]
    d = dp.choose(Need(), seats)
    assert d.member_id == 3
    assert "seat đang paused" in d.rejected[1] and "agent đang provisioning" in d.rejected[2]


def test_5_full_seat_and_budget_short_are_skipped_then_tiebreak_on_budget():
    seats = [S(1, open_runs=2), S(2, budget_remaining_usd=0.01, estimate_usd=0.05),
             S(3, budget_remaining_usd=1.0), S(4, budget_remaining_usd=3.0), S(5, budget_block="phong bì X đã hết hạn mức")]
    d = dp.choose(Need(max_open_runs=2), seats)
    assert d.member_id == 4                    # cùng tải 0 → nhiều hạn mức hơn
    assert "đang mở 2/2 run" in d.rejected[1]
    assert "còn $0.01, cần $0.05" in d.rejected[2]
    assert "hết hạn mức" in d.rejected[5]
    # không phong bì (None) = không giới hạn → xếp trước seat có hạn mức
    assert dp.choose(Need(), [S(3, budget_remaining_usd=1.0), S(9)]).member_id == 9


@pytest.mark.parametrize("seats,stage,needle", [
    ([], "none", "Không có seat agent nào"),
    ([S(1, department_id=2)], "department", "không thuộc phòng ban"),
    ([S(1, skills=("x",))], "skills", "thiếu kỹ năng"),
    ([S(1, member_status="paused"), S(2, lifecycle="retired")], "active", "không hoạt động"),
    ([S(1, open_runs=5), S(2, open_runs=2)], "load", "đang đầy việc"),
    ([S(1, budget_remaining_usd=0.0)], "budget", "không đủ hạn mức"),
])
def test_6_nobody_eligible_returns_clear_reason_never_guesses(seats, stage, needle):
    need = Need(department_id=1 if stage == "department" else None,
                skills=("y",) if stage == "skills" else ())
    d = dp.choose(need, seats)
    assert d.member_id is None and d.stage == stage
    assert d.reason.startswith("Không")
    assert needle in d.reason
    for s in seats:
        assert s.name in d.reason             # nói rõ ai bị loại
        assert s.member_id in d.rejected


def test_filters_run_in_order_reject_reason_is_earliest_stage():
    # seat sai phòng VÀ đầy việc → lý do loại là phòng ban (lớp đầu), không phải tải
    d = dp.choose(Need(department_id=1), [S(1, department_id=2, open_runs=9), S(2, department_id=1)])
    assert d.rejected[1].startswith("không thuộc phòng ban")


# ------------------------------------------------------------ ORM thật


@pytest.fixture()
def env():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine, autoflush=False)()
    org = Organization(name="Nova", slug="nova-d32"); db.add(org); db.commit()
    co = Company(organization_id=org.id, name="Nova", status="active"); db.add(co); db.commit()
    mk = Department(company_id=co.id, name="Marketing"); db.add(mk); db.commit()
    eng = Department(company_id=co.id, name="Kỹ thuật"); db.add(eng); db.commit()
    proj = Project(company_id=co.id, name="P", status="active"); db.add(proj); db.commit()

    def seat(name, rid, dept, status="active", lifecycle="active"):
        m = Member(organization_id=org.id, company_id=co.id, department_id=dept.id, name=name,
                   member_type="agent", role="AI", status=status)
        db.add(m); db.commit()
        db.add(Agent(member_id=m.id, runtime_agent_id=rid, lifecycle=lifecycle)); db.commit()
        return m

    a, b, c = seat("An", "an", mk), seat("Bình", "binh", mk), seat("Chi", "chi", eng)
    human = Member(organization_id=org.id, company_id=co.id, department_id=mk.id, name="Long",
                   member_type="human", status="active")
    db.add(human); db.commit()
    yield {"db": db, "org": org, "co": co, "mk": mk, "eng": eng, "proj": proj, "a": a, "b": b, "c": c}


def _run(env, member, status):
    db = env["db"]
    t = Task(project_id=env["proj"].id, title=f"việc {member.name}", status="in_progress"); db.add(t); db.commit()
    db.add(TaskRun(organization_id=env["org"].id, task_id=t.id, member_id=member.id, status=status)); db.commit()


def test_snapshot_counts_open_runs_from_task_runs_and_reads_budget(env):
    db = env["db"]
    _run(env, env["a"], "running"); _run(env, env["a"], "queued"); _run(env, env["a"], "succeeded")
    _run(env, env["b"], "failed")
    db.add(BudgetEnvelope(organization_id=env["org"].id, company_id=env["co"].id, name="Bình",
                          amount_limit=1.0, amount_spent=0.3, amount_reserved=0.2, scope_type="member",
                          scope_id=env["b"].id, status="active"))
    db.commit()
    seats = {s.member_id: s for s in dp.snapshot(db, env["org"].id)}
    assert set(seats) == {env["a"].id, env["b"].id, env["c"].id}       # chỉ seat agent
    assert seats[env["a"].id].open_runs == 2                           # running + queued
    assert seats[env["b"].id].open_runs == 0
    assert seats[env["b"].id].budget_remaining_usd == pytest.approx(0.5)
    assert seats[env["a"].id].budget_remaining_usd is None
    assert seats[env["a"].id].skills is None                           # chưa đọc cấu hình gateway


def test_decide_routes_within_department_by_load_and_records_event(env):
    db = env["db"]
    _run(env, env["a"], "running"); _run(env, env["a"], "dispatched")   # An đầy (2/2)
    t = Task(project_id=env["proj"].id, title="Bài blog", status="todo"); db.add(t); db.commit()
    d = dp.decide(db, env["org"].id, task=t, department_id=env["mk"].id)
    assert d.member_id == env["b"].id
    assert env["c"].id in d.rejected and "phòng" in d.rejected[env["c"].id]
    assert "đang mở 2/2 run" in d.rejected[env["a"].id]
    ev = dp.record(db, env["org"].id, d, task=t)
    row = db.get(CompanyEvent, ev.id)
    p = json.loads(row.payload_json)
    assert row.event_type == "task.dispatch_decided" and row.aggregate_id == str(t.id)
    assert p["member_id"] == env["b"].id and p["reason"].startswith("Chọn Bình")
    assert str(env["a"].id) in p["rejected"]


def test_decide_nobody_when_department_paused_or_exhausted(env):
    db = env["db"]
    env["a"].status = "paused"; db.commit()
    db.add(BudgetEnvelope(organization_id=env["org"].id, company_id=env["co"].id, name="Phòng MK",
                          amount_limit=1.0, amount_spent=1.0, scope_type="department",
                          scope_id=env["mk"].id, status="active", threshold_state="exhausted"))
    db.commit()
    d = dp.decide(db, env["org"].id, department_id=env["mk"].id)
    assert d.member_id is None
    assert "seat đang paused" in d.rejected[env["a"].id]
    assert d.stage == "budget" and "Phòng MK" in d.rejected[env["b"].id]


def test_decide_uses_skills_from_gateway_mapping(env):
    db = env["db"]
    d = dp.decide(db, env["org"].id, skills=["seo"],
                  skills_of={env["a"].id: ["copywriting"], env["b"].id: ["SEO", "copywriting"]})
    assert d.member_id == env["b"].id
    assert "chưa đọc được kỹ năng" in d.rejected[env["c"].id]


def test_seat_skills_reads_effective_gateway_config(env):
    import asyncio

    class Reg:
        async def agent_entry(self, rid):
            if rid == "chi":
                raise RuntimeError("offline")
            return {"effective": {"skills": ["seo"] if rid == "an" else [{"name": "sql"}]}}

    got = asyncio.run(dp.seat_skills(Reg(), env["db"], env["org"].id))
    assert got == {env["a"].id: ["seo"], env["b"].id: ["sql"]}
