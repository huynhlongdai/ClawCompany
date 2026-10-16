"""W0 — mỗi loại việc nền một chủ (docs/work-module-review.md G4).

Trước W0 beat lõi chạy song song ba cặp: ``operations.tick_cycles`` (chu kỳ mục tiêu cũ) ↔ strategy/Nina,
``events.monitor_sla`` (SLAProfile) ↔ ``sla.tick``, ``operations.scan_recurring`` ↔ ``routines.tick``. Trên VM
(17/10/2026) việc định kỳ cũ "Daily growth & risk review" tạo mỗi sáng một mục tiêu + chu kỳ cũ, chu kỳ chạy mãi.

Test hành vi trên SQLite thật:
* beat chỉ còn một chủ cho mỗi loại;
* mục tiêu Nina đã nhận → không dựng chu kỳ cũ, chu kỳ cũ sót lại không phát việc (không giao đôi);
* việc định kỳ cũ chạy đúng MỘT lần cho một mốc giờ dù hai tick chạy đồng thời;
* một việc quá hạn chỉ bị leo thang bởi MỘT bộ máy SLA, tick lặp không leo thang lại.
"""
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app import worker
from app.db.base import Base
from app.models import (AgentMessage, DelegationAssignment, ExecutiveGoal, OperatingCycle, Project,
                        RecurringOperation, SLAIncident, SLAProfile, Wakeup)
from app.models.agent_native import SlaTimer
from app.models.entities import Agent, Company, Member, Organization, Task
from app.models.extended import InboxItem
from app.services import operating_time, orchestration, recurring_ops, routines, strategy


@pytest.fixture()
def maker():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False)


@pytest.fixture()
def env(maker):
    db = maker()
    org = Organization(name="Gốm", slug="gom-w0"); db.add(org); db.commit()
    co = Company(organization_id=org.id, name="Tiệm Gốm Mộc", status="active"); db.add(co); db.commit()
    boss = Member(organization_id=org.id, company_id=co.id, name="Long", member_type="human", role="Chủ",
                  status="active")
    db.add(boss); db.commit()
    nina = Member(organization_id=org.id, company_id=co.id, name="Nina", member_type="agent", role="Điều hành",
                  status="active", manager_id=boss.id)
    db.add(nina); db.commit()
    db.add(Agent(member_id=nina.id, runtime_agent_id="nina", lifecycle="active")); db.commit()
    cskh = Member(organization_id=org.id, company_id=co.id, name="Lan", member_type="agent", role="CSKH",
                  status="active", manager_id=boss.id)
    db.add(cskh); db.commit()
    db.add(Agent(member_id=cskh.id, runtime_agent_id="cskh", lifecycle="active")); db.commit()
    pr = Project(company_id=co.id, name="Vận hành", status="active"); db.add(pr); db.commit()

    class E:
        pass
    e = E()
    e.db, e.org, e.co, e.boss, e.nina, e.cskh, e.pr, e.maker = db, org, co, boss, nina, cskh, pr, maker
    yield e
    db.close()


# ------------------------------------------------------------------ beat

def test_beat_has_exactly_one_owner_per_background_concern():
    for lab in (False, True):
        tasks = [v["task"] for v in worker.build_beat_schedule(lab).values()]
        assert len(tasks) == len(set(tasks))
        for gone in ("operations.tick_cycles", "events.monitor_sla", "operations.scan_recurring"):
            assert gone not in tasks, gone
        # chủ còn lại
        assert {"routines.tick", "sla.tick", "wakeups.drain"} <= set(tasks)


# ------------------------------------------------------------------ mục tiêu: strategy là chủ

def test_goal_taken_by_nina_never_gets_a_legacy_cycle(env):
    goal = orchestration.create_goal(env.db, organization_id=env.org.id, user_id=None, company_id=env.co.id,
                                     title="Ra mắt bộ sưu tập hè", objective="Bán 50 bình gốm trong tháng 11")
    assert strategy.owns_goal(env.db, goal)
    planning = strategy.planning_task(env.db, goal.id)
    assert planning.assignee_member_id == env.nina.id
    # Đường cũ (API v9 /goals/{id}/run) bị từ chối thay vì giao việc song song.
    goal.execution_plan_id = 999; env.db.add(goal); env.db.commit()
    with pytest.raises(ValueError, match="Nina"):
        orchestration.create_cycle(env.db, goal)
    assert env.db.query(OperatingCycle).count() == 0
    assert env.db.query(DelegationAssignment).count() == 0


@pytest.mark.asyncio
async def test_leftover_legacy_cycle_of_a_nina_goal_dispatches_nothing(env):
    goal = orchestration.create_goal(env.db, organization_id=env.org.id, user_id=None, company_id=env.co.id,
                                     title="Mục tiêu", objective="x")
    cycle = OperatingCycle(organization_id=env.org.id, goal_id=goal.id, status="running", mode="auto",
                           snapshot_json="{}")
    env.db.add(cycle); env.db.commit()
    env.db.add(DelegationAssignment(organization_id=env.org.id, cycle_id=cycle.id, goal_id=goal.id,
                                    assignee_member_id=env.cskh.id, instruction="làm", status="queued",
                                    max_attempts=1, estimated_cost=0.1))
    env.db.commit()
    tasks_before = env.db.query(Task).count()
    await orchestration.tick_cycle(env.db, cycle, capture_runtime=False)
    a = env.db.query(DelegationAssignment).one()
    assert a.status == "queued" and env.db.query(Task).count() == tasks_before


def _daily_op(db, org, co, when):
    op = recurring_ops.create_recurring_operation(
        db, organization_id=org.id, company_id=co.id, name="Morning Executive Operating Cycle",
        schedule="0 8 * * *", timezone_name="Asia/Ho_Chi_Minh", operation_type="nina_goal",
        payload={"title": "Daily growth & risk review", "objective": "Rà soát việc tăng trưởng", "risk": "low"},
        enabled=True)
    op.next_run_at = when; db.add(op); db.commit()
    return op


def test_recurring_nina_goal_runs_once_per_slot_and_goes_to_nina_only(env):
    due = datetime(2026, 10, 17, 1, 0)                         # 08:00 giờ VN
    _daily_op(env.db, env.org, env.co, due)
    now = due + timedelta(seconds=20)
    # Hai tiến trình (beat + vòng trong API) cùng đọc hàng tới hạn TRƯỚC khi ai kịp giành.
    s1, s2 = env.maker(), env.maker()
    i1 = recurring_ops.due_operations(s1, now)[0]
    i2 = recurring_ops.due_operations(s2, now)[0]
    won = [recurring_ops.claim(s1, i1, now), recurring_ops.claim(s2, i2, now)]
    assert won == [True, False]
    s1.close(); s2.close()
    # Đường chạy thật: tick_all hai lần trong cùng mốc giờ → đúng một mục tiêu.
    env.db.query(RecurringOperation).update({"next_run_at": due}); env.db.commit()
    first = routines.tick_all(env.db, now=now)
    second = routines.tick_all(env.db, now=now)
    assert len(first["recurring_operations"]) == 1 and second["recurring_operations"] == []
    goals = env.db.query(ExecutiveGoal).all()
    assert len(goals) == 1
    assert first["recurring_operations"][0]["owner"] == "strategy"
    assert strategy.owns_goal(env.db, goals[0])
    assert env.db.query(OperatingCycle).count() == 0                 # không có chu kỳ cũ song song
    assert env.db.query(Wakeup).filter(Wakeup.reason == "goal_created").count() == 1
    op = env.db.query(RecurringOperation).one()
    assert op.next_run_at == datetime(2026, 10, 18, 1, 0)           # mốc kế tiếp: 08:00 hôm sau


# ------------------------------------------------------------------ SLA: sla.tick là chủ

def _profile(env, minutes=60):
    p = SLAProfile(organization_id=env.org.id, company_id=env.co.id, name="Việc gấp", resource_type="task",
                   priority="*", completion_minutes=minutes, escalation_target_member_id=env.boss.id, enabled=True)
    env.db.add(p); env.db.commit()
    return p


def test_task_with_timer_is_escalated_once_by_the_new_engine_only(env):
    _profile(env, minutes=30)
    t0 = datetime(2026, 10, 19, 2, 0)
    task = Task(project_id=env.pr.id, title="Khách hỏi đổi hàng", status="todo", assignee_member_id=env.cskh.id,
                created_at=t0)
    env.db.add(task); env.db.commit()
    timer = SlaTimer(organization_id=env.org.id, company_id=env.co.id, task_id=task.id, kind="resolution",
                     member_id=env.cskh.id, seat_type="agent", minutes=30, started_at=t0,
                     due_at=t0 + timedelta(minutes=30), status="running")
    env.db.add(timer); env.db.commit()
    later = t0 + timedelta(hours=3)                             # quá cả SLA mới lẫn hồ sơ cũ
    out1 = operating_time.tick(env.db, later)
    out2 = operating_time.tick(env.db, later + timedelta(minutes=5))
    assert (out1["breached"], out1["legacy_incidents"]) == (1, 0)
    assert (out2["breached"], out2["legacy_incidents"]) == (0, 0)
    env.db.refresh(timer)
    assert timer.status == "breached" and timer.escalated_to_member_id == env.boss.id
    cards = env.db.query(InboxItem).filter(InboxItem.task_id == task.id, InboxItem.kinds.contains("sla_breach")).all()
    assert len(cards) == 1 and cards[0].count == 1                 # thẻ gộp cũng không bị cộng lần hai
    assert env.db.query(SLAIncident).count() == 0                   # bộ máy cũ không leo thang lần hai
    from app.services.sla import monitor_sla
    assert monitor_sla(env.db, env.org.id, now=later) == []          # gọi thẳng (v10) cũng bỏ qua việc có đồng hồ
    assert env.db.query(AgentMessage).filter(AgentMessage.message_type == "sla_escalation").count() == 0


def test_legacy_profile_still_covers_untimed_tasks_once(env):
    _profile(env, minutes=60)
    t0 = datetime(2026, 10, 19, 2, 0)
    task = Task(project_id=env.pr.id, title="Việc không có đồng hồ", status="todo", assignee_member_id=env.cskh.id,
                created_at=t0)
    env.db.add(task); env.db.commit()
    assert operating_time.tick(env.db, t0 + timedelta(minutes=30))["legacy_incidents"] == 0
    assert operating_time.tick(env.db, t0 + timedelta(minutes=90))["legacy_incidents"] == 1
    assert operating_time.tick(env.db, t0 + timedelta(minutes=120))["legacy_incidents"] == 0
    inc = env.db.query(SLAIncident).one()
    assert inc.resource_id == str(task.id) and inc.status == "escalated"
    assert env.db.query(AgentMessage).filter(AgentMessage.message_type == "sla_escalation").count() == 1


def test_concurrent_sla_ticks_breach_a_timer_once(env):
    t0 = datetime(2026, 10, 19, 2, 0)
    task = Task(project_id=env.pr.id, title="Đơn 7", status="todo", assignee_member_id=env.cskh.id, created_at=t0)
    env.db.add(task); env.db.commit()
    env.db.add(SlaTimer(organization_id=env.org.id, company_id=env.co.id, task_id=task.id, kind="resolution",
                        member_id=env.cskh.id, seat_type="agent", minutes=10, started_at=t0,
                        due_at=t0 + timedelta(minutes=10), status="running"))
    env.db.commit()
    s1, s2 = env.maker(), env.maker()
    # tiến trình 2 đã đọc đồng hồ "running" trước khi tiến trình 1 giành được
    stale = s2.query(SlaTimer).filter(SlaTimer.status == "running").all()
    assert len(stale) == 1
    operating_time.tick(s1, t0 + timedelta(minutes=20))
    out = operating_time.tick(s2, t0 + timedelta(minutes=21))
    assert out["breached"] == 0
    cards = env.db.query(InboxItem).filter(InboxItem.task_id == task.id, InboxItem.kinds.contains("sla_breach")).all()
    assert len(cards) == 1 and cards[0].count == 1
    s1.close(); s2.close()
