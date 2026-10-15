"""M2d.2 — lịch sử KPI: tasks.completed_at là mốc "xong trong kỳ" (không phải updated_at), số KPI lưu theo kỳ
(beat + bấm), kỳ vừa qua đóng băng, tính lại kỳ cũ có giới hạn, xu hướng trả về cho UI. ORM thật trên SQLite."""
from datetime import datetime, timedelta

from app.models import Task
from app.models.company_ops import KpiSnapshot
from app.services import kpi_cascade as kc
from app.services import task_lifecycle as lifecycle
from tests.test_m2b_company_foundation import E, mkpos  # noqa: F401  (fixture)
from tests.test_m2c_kpi_cascade import kpi
from tests.test_m2c_process_map import _finish, _setup
from tests.test_m3_agents import env, hire  # noqa: F401  (fixture)


def _task(E, member_id, title="Việc"):
    from app.models import Project
    pr = E.db.query(Project).filter(Project.company_id == E.co.id).first()
    if pr is None:
        pr = Project(company_id=E.co.id, name="P", status="active"); E.db.add(pr); E.db.commit()
    t = Task(project_id=pr.id, title=title, assignee_member_id=member_id, status="todo")
    E.db.add(t); E.db.commit()
    return t


def test_completed_at_is_set_on_done_cleared_on_reopen_and_not_moved_by_later_edits(E):
    cskh, agent, kho, keeper, owner_pos = _setup(E)
    t = _task(E, keeper.id)
    assert t.completed_at is None
    _finish(E, t.id)
    E.db.refresh(t)
    assert t.status == "done" and t.completed_at is not None
    first = t.completed_at
    t.title = "Sửa tên sau khi xong"; E.db.commit(); E.db.refresh(t)
    assert t.completed_at == first                                     # sửa sau đó không dời mốc xong
    lifecycle.transition(E.db, t, "in_progress", system=True, reason="mở lại")
    E.db.refresh(t)
    assert t.completed_at is None


def test_tasks_done_counts_by_completion_time_not_last_update(E):
    cskh, agent, kho, keeper, owner_pos = _setup(E)
    k = kpi(E, level="company", name="Việc xong", metric="tasks_done", target=10)
    old = _task(E, keeper.id, "Xong từ tháng trước")
    _finish(E, old.id)
    E.db.refresh(old)
    # xong 40 ngày trước, nhưng hôm nay mới bị sửa (updated_at = bây giờ) → KHÔNG tính vào kỳ này
    old.completed_at = datetime.utcnow() - timedelta(days=40); old.description = "ghi chú thêm"; E.db.commit()
    new = _task(E, keeper.id, "Xong hôm nay"); _finish(E, new.id)
    got = E.c.get(f"/api/team/kpis?company_id={E.co.id}", headers=E.tok("member")).json()
    row = next(i for i in got["items"] if i["id"] == k["id"])
    assert row["value"] == 1.0
    # hàng cũ chưa có completed_at (trước migration) → rơi về updated_at
    legacy = _task(E, keeper.id, "Hàng cũ"); _finish(E, legacy.id)
    E.db.query(Task).filter(Task.id == legacy.id).update({"completed_at": None}, synchronize_session=False); E.db.commit()
    got = E.c.get(f"/api/team/kpis?company_id={E.co.id}", headers=E.tok("member")).json()
    assert next(i for i in got["items"] if i["id"] == k["id"])["value"] == 2.0


def test_snapshots_upsert_per_period_close_previous_and_trend_in_list(E):
    cskh, agent, kho, keeper, owner_pos = _setup(E)
    k = kpi(E, level="company", name="Việc xong tuần", metric="tasks_done", target=4, period="week")
    pend = kpi(E, level="company", name="Chờ duyệt", metric="approvals_pending", target=0, direction="down", period="week")
    now = datetime.utcnow()
    last_week = kc.previous_now("week", now, 1)
    # một việc xong tuần trước + hai việc xong tuần này
    a = _task(E, keeper.id); _finish(E, a.id); E.db.refresh(a); a.completed_at = last_week; E.db.commit()
    for _ in range(2):
        t = _task(E, keeper.id); _finish(E, t.id)
    # tuần trước đang có số "chạy" (ví dụ beat chạy giữa tuần trước) → lần chụp này đóng băng nó với số cuối kỳ
    kd = E.db.get(kc.KpiDefinition, k["id"])
    kc.snapshot(E.db, kd, now=last_week, trigger="beat")
    r = E.c.post("/api/team/kpis/snapshot", json={"company_id": E.co.id}, headers=E.tok("manager"))
    assert r.status_code == 200 and r.json()["closed"] == 1 and r.json()["snapshots"] == 2
    lw_key = kc.period_window("week", last_week)[0]
    cur_key = kc.period_window("week", now)[0]
    snaps = {s.period_key: s for s in E.db.query(KpiSnapshot).filter(KpiSnapshot.kpi_id == k["id"]).all()}
    assert snaps[lw_key].final is True and snaps[lw_key].value == 1.0 and snaps[lw_key].trigger == "close"
    assert snaps[cur_key].final is False and snaps[cur_key].value == 2.0 and snaps[cur_key].progress == 50.0
    # chụp lại trong cùng kỳ → cập nhật tại chỗ, không thêm hàng; kỳ đã đóng băng không bị ghi đè
    t = _task(E, keeper.id); _finish(E, t.id)
    kc.tick(E.db)
    rows = E.db.query(KpiSnapshot).filter(KpiSnapshot.kpi_id == k["id"]).all()
    assert len(rows) == 2 and {r.period_key: r.value for r in rows} == {lw_key: 1.0, cur_key: 3.0}
    got = E.c.get(f"/api/team/kpis?company_id={E.co.id}", headers=E.tok("member")).json()
    hist = next(i for i in got["items"] if i["id"] == k["id"])["history"]
    assert [h["period_key"] for h in hist] == [lw_key, cur_key] and [h["value"] for h in hist] == [1.0, 3.0]
    assert next(i for i in got["items"] if i["id"] == pend["id"])["history"][-1]["period_key"] == cur_key


def test_backfill_recomputes_old_periods_but_skips_point_in_time_metrics_and_is_manager_only(E):
    cskh, agent, kho, keeper, owner_pos = _setup(E)
    k = kpi(E, level="company", name="Việc xong", metric="tasks_done", target=2, period="week")
    pend = kpi(E, level="company", name="Chờ duyệt", metric="approvals_pending", target=0, direction="down", period="week")
    now = datetime.utcnow()
    for back in (1, 2, 2):
        t = _task(E, keeper.id); _finish(E, t.id); E.db.refresh(t)
        t.completed_at = kc.previous_now("week", now, back); E.db.commit()
    assert E.c.post("/api/team/kpis/snapshot", json={"company_id": E.co.id, "backfill": 3},
                    headers=E.tok("member")).status_code == 403
    assert E.c.post("/api/team/kpis/snapshot", json={"company_id": E.co.id, "backfill": 99},
                    headers=E.tok("manager")).status_code == 422
    r = E.c.post("/api/team/kpis/snapshot", json={"company_id": E.co.id, "backfill": 3}, headers=E.tok("manager")).json()
    assert r["backfilled"] == 3                                       # 3 kỳ cũ của "việc xong"; "chờ duyệt" bỏ qua
    hist = [h["value"] for h in kc.history(E.db, E.db.get(kc.KpiDefinition, k["id"]))]
    assert hist == [0.0, 2.0, 1.0, 0.0]
    assert [h["period_key"] for h in kc.history(E.db, E.db.get(kc.KpiDefinition, pend["id"]))] == \
        [kc.period_window("week", now)[0]]
    # tổ chức khác không chụp được công ty này
    assert E.c.post("/api/team/kpis/snapshot", json={"company_id": E.co.id}, headers=E.tok("other")).status_code in (403, 404)
