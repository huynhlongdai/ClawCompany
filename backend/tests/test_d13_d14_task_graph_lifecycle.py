"""D1.3 (đồ thị công việc) + D1.4 (vòng đời task, giữ chỗ, lượt chạy).

Kiểm hành vi, không kiểm cấu trúc:
* thêm phụ thuộc tạo vòng → 422; khác tenant → 404;
* task còn blocker mở không vào được in_progress/review/done, kể cả qua dispatch;
* gói ngữ cảnh khối 2 có đúng một dòng chuỗi mục tiêu ≤240 ký tự;
* mỗi dispatch tạo một hàng task_runs và giữ task; lượt thứ hai thua → 409;
* run kết thúc thì hàng task_runs đóng lại và task được thả;
* công cụ của agent không còn nhận trạng thái tuỳ ý;
* lint: không còn chỗ ghi task.status ngoài task_lifecycle.
"""
import asyncio
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
import app.models  # noqa: F401
from app.core.authz import Principal
from app.models import ExecutiveGoal, TaskRun
from app.models.entities import Agent, Company, Member, Organization, Project, Task

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)()
    try:
        yield session
    finally:
        session.close()


def _world(db: Session, slug: str = "g"):
    org = Organization(name=f"Org {slug}", slug=slug)
    db.add(org); db.commit(); db.refresh(org)
    company = Company(organization_id=org.id, name="Nova", status="active")
    db.add(company); db.commit(); db.refresh(company)
    boss = Member(organization_id=org.id, company_id=company.id, name="Long",
                  member_type="human", role="Founder", status="active")
    mia = Member(organization_id=org.id, company_id=company.id, name="Mia",
                 member_type="agent", role="Content", status="active")
    db.add_all([boss, mia]); db.commit(); db.refresh(boss); db.refresh(mia)
    db.add(Agent(member_id=mia.id, runtime_provider="openclaw",
                 runtime_agent_id=f"mia-{slug}", lifecycle="active"))
    project = Project(company_id=company.id, name="Ra mắt mùa hè", status="active", progress=0)
    db.add(project); db.commit(); db.refresh(project)

    def task(title, status="todo", assignee=mia.id, **kw):
        t = Task(project_id=project.id, title=title, description="", status=status,
                 assignee_member_id=assignee, priority="medium", **kw)
        db.add(t); db.commit(); db.refresh(t)
        return t

    principal = Principal(user_id=1, organization_id=org.id, role="owner",
                          auth_type="jwt", scopes=[], member_id=boss.id)
    return {"org": org, "company": company, "boss": boss, "mia": mia,
            "project": project, "task": task, "p": principal}


# ------------------------------------------------------------------ D1.3 thuần

def test_cycle_detection_follows_indirect_edges():
    from app.services.task_graph import would_create_cycle

    edges = [(1, 2), (2, 3)]          # 1 chờ 2, 2 chờ 3
    assert would_create_cycle(edges, 3, 1)       # 3 chờ 1 → vòng 1→2→3→1
    assert would_create_cycle(edges, 1, 1)
    assert not would_create_cycle(edges, 1, 3)   # thêm cạnh tắt, không vòng
    assert not would_create_cycle(edges, 4, 1)


def test_chain_line_keeps_both_ends_and_stays_under_limit():
    from app.services.task_graph import chain_line

    line = chain_line("Tăng doanh thu Q3", "Ra mắt", ["#1 Chiến dịch"], "#2 Viết bài")
    assert line == "Tăng doanh thu Q3 → Ra mắt → #1 Chiến dịch → #2 Viết bài"
    long = chain_line("Mục tiêu", "Dự án", [f"#{i} " + "x" * 60 for i in range(6)], "#9 Việc này")
    assert len(long) <= 240
    assert long.startswith("Mục tiêu → Dự án → …") and long.endswith("#9 Việc này")
    assert "#5 " in long and "#0 " not in long   # giữ cha gần nhất, bỏ cha xa


# ------------------------------------------------------------------ D1.3 API

def test_dependency_cycle_is_422_and_cross_tenant_is_404(db):
    from app.api.tasks import DependencyIn, task_dependency_add

    w = _world(db, "a")
    a, b, c = w["task"]("A"), w["task"]("B"), w["task"]("C")
    task_dependency_add(a.id, DependencyIn(blocked_by_task_id=b.id), w["p"], db)
    task_dependency_add(b.id, DependencyIn(blocked_by_task_id=c.id), w["p"], db)
    with pytest.raises(HTTPException) as exc:
        task_dependency_add(c.id, DependencyIn(blocked_by_task_id=a.id), w["p"], db)
    assert exc.value.status_code == 422

    other = _world(db, "b")
    foreign = other["task"]("Việc của người khác")
    with pytest.raises(HTTPException) as exc:
        task_dependency_add(a.id, DependencyIn(blocked_by_task_id=foreign.id), w["p"], db)
    assert exc.value.status_code == 404


def test_open_blocker_stops_move_and_dispatch_until_it_is_done(db, monkeypatch):
    from app.api.tasks import DependencyIn, task_dependency_add, task_dependency_remove
    from app.services import agent_dispatch, workspace_ops as ops

    w = _world(db, "c")
    design, build = w["task"]("Thiết kế"), w["task"]("Dựng trang")
    task_dependency_add(build.id, DependencyIn(blocked_by_task_id=design.id), w["p"], db)

    with pytest.raises(HTTPException) as exc:
        ops.move_task(db, build, w["project"], w["org"].id, status="in_progress")
    assert exc.value.status_code == 409
    assert exc.value.detail["blocked_by"] == [design.id]
    with pytest.raises(agent_dispatch.DispatchConflict):
        asyncio.run(agent_dispatch.dispatch_task(db, build))
    assert db.execute(select(TaskRun).where(TaskRun.task_id == build.id)).first() is None

    # Xong blocker → đi tiếp được.
    for status in ("in_progress", "review", "done"):
        ops.move_task(db, design, w["project"], w["org"].id, status=status)
    ops.move_task(db, build, w["project"], w["org"].id, status="in_progress")
    assert build.status == "in_progress"
    # Gỡ cạnh thì đồ thị phản ánh ngay.
    out = task_dependency_remove(build.id, design.id, w["p"], db)
    assert out["graph"]["blocked_by"] == []


def test_links_set_parent_goal_and_reject_parent_cycle(db):
    from app.api.tasks import TaskLinksIn, list_tasks, task_links_update

    w = _world(db, "d")
    goal = ExecutiveGoal(organization_id=w["org"].id, company_id=w["company"].id,
                         title="Tăng doanh thu Q3", objective="+20%", status="active")
    db.add(goal); db.commit(); db.refresh(goal)
    parent, child = w["task"]("Chiến dịch"), w["task"]("Viết bài")
    g = task_links_update(parent.id, TaskLinksIn(goal_id=goal.id), w["p"], db)
    assert g["goal"]["id"] == goal.id and not g["goal"]["inherited"]
    g = task_links_update(child.id, TaskLinksIn(parent_task_id=parent.id,
                                                acceptance_criteria="3 bài ≥800 chữ"), w["p"], db)
    assert g["goal"]["inherited"] and g["parents"][0]["id"] == parent.id
    assert g["goal_line"] == (f"Tăng doanh thu Q3 → Ra mắt mùa hè → #{parent.id} Chiến dịch"
                              f" → #{child.id} Viết bài")
    with pytest.raises(HTTPException) as exc:     # cha thành con của chính con mình
        task_links_update(parent.id, TaskLinksIn(parent_task_id=child.id), w["p"], db)
    assert exc.value.status_code == 422
    # Lọc theo mục tiêu chỉ lấy task gắn trực tiếp.
    assert [t.id for t in list_tasks(None, goal.id, w["p"], db)] == [parent.id]
    # Gửi null là gỡ; không gửi là giữ nguyên.
    g = task_links_update(child.id, TaskLinksIn(parent_task_id=None), w["p"], db)
    assert g["parents"] == [] and g["acceptance_criteria"] == "3 bài ≥800 chữ"


def test_context_pack_block_two_carries_the_goal_chain(db):
    from app.services import task_graph, work_context

    w = _world(db, "e")
    goal = ExecutiveGoal(organization_id=w["org"].id, title="Tăng doanh thu Q3",
                         objective="x", status="active")
    db.add(goal); db.commit(); db.refresh(goal)
    parent = w["task"]("Chiến dịch", goal_id=goal.id)
    child = w["task"]("Viết bài", parent_task_id=parent.id, acceptance_criteria="Có số liệu")
    pack = work_context.build_pack(db, child, organization_id=w["org"].id)
    lines = [l for l in pack["text"].splitlines() if l.startswith("- Chuỗi mục tiêu:")]
    assert len(lines) == 1
    chain = lines[0].split(": ", 1)[1]
    assert chain == task_graph.goal_line(db, child) and len(chain) <= 240
    assert chain.startswith("Tăng doanh thu Q3 → ") and chain.endswith("Viết bài")
    assert "- Tiêu chí nghiệm thu: Có số liệu" in pack["text"]


# ------------------------------------------------------------------ D1.4

def test_dispatch_records_a_run_holds_the_task_and_a_second_dispatch_loses(db):
    from app.services import agent_dispatch

    w = _world(db, "f")
    t = w["task"]("Viết bài", status="todo")
    asyncio.run(agent_dispatch.dispatch_task(db, t))
    runs = db.execute(select(TaskRun).where(TaskRun.task_id == t.id)).scalars().all()
    assert len(runs) == 1 and runs[0].status == "running"
    assert runs[0].runtime_run_id == t.runtime_run_id and runs[0].started_at
    assert t.checkout_run_id == runs[0].id and t.status == "in_progress"

    with pytest.raises(agent_dispatch.DispatchConflict):
        asyncio.run(agent_dispatch.dispatch_task(db, t))
    runs = db.execute(select(TaskRun).where(TaskRun.task_id == t.id)
                      .order_by(TaskRun.id)).scalars().all()
    assert [r.status for r in runs] == ["running", "skipped"]
    db.refresh(t)
    assert t.checkout_run_id == runs[0].id     # người thua không cướp được chỗ


def test_terminal_event_closes_the_run_and_releases_the_task(db):
    from app.services import agent_dispatch, runtime_stream

    w = _world(db, "g")
    t = w["task"]("Viết bài")
    asyncio.run(agent_dispatch.dispatch_task(db, t))
    state = runtime_stream.ConsumerState(session_key=t.runtime_session_key, task_id=t.id,
                                         organization_id=w["org"].id)
    runtime_stream.apply_terminal_state(db, t, state, {"state": "error",
                                                       "errorMessage": "quota"})
    run = db.execute(select(TaskRun).where(TaskRun.task_id == t.id)).scalar_one()
    assert (run.status, run.error_reason) == ("failed", "quota") and run.ended_at
    assert t.status == "blocked" and t.checkout_run_id is None
    # Đã được thả thì giao lại được, và đó là lượt thứ hai.
    asyncio.run(agent_dispatch.dispatch_task(db, t))
    assert db.query(TaskRun).filter(TaskRun.task_id == t.id).count() == 2


def test_failed_runtime_call_marks_the_run_failed_and_frees_the_task(db, monkeypatch):
    from app.services import agent_dispatch

    class Broken:
        async def run_agent(self, **kw):
            raise RuntimeError("gateway down")

    monkeypatch.setattr("app.services.agent_dispatch.get_runtime", lambda: Broken())
    w = _world(db, "h")
    t = w["task"]("Viết bài")
    with pytest.raises(RuntimeError):
        asyncio.run(agent_dispatch.dispatch_task(db, t))
    run = db.execute(select(TaskRun).where(TaskRun.task_id == t.id)).scalar_one()
    db.refresh(t)
    assert run.status == "failed" and "gateway down" in run.error_reason
    assert t.checkout_run_id is None and t.status == "todo"


def test_agent_status_tool_follows_the_same_rules_as_people(db):
    from app.services import task_lifecycle

    w = _world(db, "i")
    t = w["task"]("Viết bài", status="backlog")
    with pytest.raises(HTTPException) as exc:
        task_lifecycle.transition(db, t, "done", via="agent_tool")   # nhảy cóc
    assert exc.value.status_code == 409
    with pytest.raises(HTTPException) as exc:
        task_lifecycle.transition(db, t, "finished", via="agent_tool")
    assert exc.value.status_code in (400, 409)
    from app.services.company_tools import execute_company_tool
    with pytest.raises(ValueError):
        execute_company_tool(db, "update_task_status", {"task_id": t.id, "status": "done"})
    db.refresh(t)
    assert t.status == "backlog"


def test_lifecycle_emits_reason_on_system_transitions(db):
    from app.models import CompanyEvent
    from app.services import task_lifecycle

    w = _world(db, "j")
    t = w["task"]("Viết bài", status="in_progress")
    task_lifecycle.transition(db, t, "cancelled", system=True, via="test",
                              reason="dọn bảng", actor_member_id=w["boss"].id)
    ev = db.query(CompanyEvent).filter(CompanyEvent.event_type == "task.cancelled").one()
    import json
    payload = json.loads(ev.payload_json)
    assert payload["reason"] == "dọn bảng" and payload["from"] == "in_progress"
    with pytest.raises(ValueError):
        task_lifecycle.transition(db, t, "backlog", system=True)   # hệ thống phải nói lý do


def test_task_runs_endpoint_lists_runs_newest_first(db):
    from app.api.tasks import task_runs_read
    from app.services import agent_dispatch, task_lifecycle

    w = _world(db, "k")
    t = w["task"]("Viết bài")
    asyncio.run(agent_dispatch.dispatch_task(db, t))
    task_lifecycle.finish_run(db, task_lifecycle.current_run(db, t), "completed")
    asyncio.run(agent_dispatch.dispatch_task(db, t))
    out = task_runs_read(t.id, 50, w["p"], db)
    assert [r["status"] for r in out["runs"]] == ["running", "completed"]
    assert out["runs"][0]["holds_task"] and out["runs"][0]["member_name"] == "Mia"


def test_lint_finds_no_status_writes_outside_lifecycle_and_catches_new_ones(tmp_path):
    lint = ROOT / "tools" / "lint_task_status.py"
    ok = subprocess.run([sys.executable, str(lint)], capture_output=True, text=True)
    assert ok.returncode == 0, ok.stdout + ok.stderr

    sys.path.insert(0, str(lint.parent))
    import lint_task_status as L
    bad = tmp_path / "bad.py"
    bad.write_text("def f(task, sub_task):\n    task.status = 'done'\n"
                   "    setattr(sub_task, 'status', 'x')\n    item.status = 'ok'\n")
    hits = L.scan(bad)
    assert len(hits) == 2, hits


# ------------------------------------------------------------------ Postgres thật

@pytest.mark.postgres
def test_parallel_checkout_has_exactly_one_winner_on_postgres():
    """Hai mươi luồng cùng giữ một task trên Postgres thật: đúng một thắng.

    Chạy khi có ``TEST_POSTGRES_URL`` (CI job ``postgres`` và máy dev có PG).
    SQLite tuần tự hoá mọi ghi nên không chứng minh được gì về điều này.
    """
    url = os.environ.get("TEST_POSTGRES_URL")
    if not url:
        pytest.skip("TEST_POSTGRES_URL chưa đặt")
    from app.services import task_lifecycle

    from sqlalchemy import text

    engine = create_engine(url, pool_size=25, max_overflow=5)

    def reset():
        # drop_all không sắp được thứ tự vì có vòng FK (members ↔ departments);
        # database này chỉ dành cho test nên xoá cả schema là sạch nhất.
        with engine.begin() as conn:
            conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public"))

    reset()
    Base.metadata.create_all(bind=engine)
    Maker = sessionmaker(bind=engine, autoflush=False)
    try:
        with Maker() as s:
            w = _world(s, "pg")
            t = w["task"]("Một việc")
            run_ids = [task_lifecycle.open_run(s, t, organization_id=w["org"].id,
                                               member_id=w["mia"].id).id for _ in range(20)]
            task_id = t.id
        barrier = threading.Barrier(len(run_ids))
        wins, losses = [], []

        def contend(run_id):
            with Maker() as s:
                task = s.get(Task, task_id)
                barrier.wait()
                try:
                    task_lifecycle.checkout(s, task, run_id)
                    wins.append(run_id)
                except task_lifecycle.CheckoutConflict:
                    losses.append(run_id)

        threads = [threading.Thread(target=contend, args=(r,)) for r in run_ids]
        [th.start() for th in threads]; [th.join() for th in threads]
        assert len(wins) == 1 and len(losses) == 19
        with Maker() as s:
            assert s.get(Task, task_id).checkout_run_id == wins[0]
    finally:
        reset()
        engine.dispose()
