"""Cờ LAB_JOBS_ENABLED (plan-v2-modules §2): 6 job nền của module Phòng thí nghiệm.

Kiểm bằng hành vi, không grep source:
- beat chỉ lập lịch 6 job khi cờ bật; mặc định (cờ tắt) không có;
- gọi thẳng task khi cờ tắt → không mở phiên DB, không ghi gì;
- cờ bật → task chạy thật trên DB (control_plane_tick đăng ký scheduler node);
- /api/health/lab báo đúng trạng thái cờ cho trang Cài đặt › Phòng thí nghiệm.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.core.config import settings
from app.db.base import Base
from app.main import app
from app.models import SchedulerNode
from app.models.entities import Organization
from app.tasks import dev_cloud, v14, v15
from app import worker

LAB_TASKS = {
    "devcloud.cleanup_expired": (dev_cloud, dev_cloud.cleanup_expired_task),
    "v14.reap_runner_leases": (v14, v14.reap_runner_leases),
    "v14.evaluate_slos": (v14, v14.evaluate_slos),
    "v14.review_portfolios": (v14, v14.review_portfolios),
    "v15.control_plane_tick": (v15, v15.control_plane_tick),
    "v15.export_telemetry": (v15, v15.export_telemetry),
}


@pytest.fixture()
def maker():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False)


def test_default_flag_is_off_and_beat_has_no_lab_jobs():
    assert settings.lab_jobs_enabled is False
    scheduled = {v["task"] for v in worker.celery_app.conf.beat_schedule.values()}
    assert scheduled.isdisjoint(LAB_TASKS), scheduled & set(LAB_TASKS)
    # job lõi vẫn còn
    assert {"routines.tick", "wakeups.drain", "approvals.escalate_overdue"} <= scheduled


def test_beat_schedule_follows_flag():
    off = {v["task"] for v in worker.build_beat_schedule(False).values()}
    on = {v["task"] for v in worker.build_beat_schedule(True).values()}
    assert off.isdisjoint(LAB_TASKS)
    assert set(LAB_TASKS) <= on
    assert on - off == set(LAB_TASKS)
    assert set(worker.LAB_TASK_NAMES) == set(LAB_TASKS)


def test_tasks_do_not_touch_db_when_off(monkeypatch):
    monkeypatch.setattr(settings, "lab_jobs_enabled", False)
    opened = []
    for name, (mod, task) in LAB_TASKS.items():
        monkeypatch.setattr(mod, "SessionLocal", lambda: opened.append(name) or (_ for _ in ()).throw(AssertionError("DB opened")))
        assert task() == {"skipped": "lab_jobs_disabled"}, name
    assert opened == []


def test_tasks_run_when_on(monkeypatch, maker):
    monkeypatch.setattr(settings, "lab_jobs_enabled", True)
    opened = []
    def session():
        opened.append(1)
        return maker()
    for name, (mod, task) in LAB_TASKS.items():
        monkeypatch.setattr(mod, "SessionLocal", session)
        out = task()
        assert "skipped" not in out, (name, out)
    assert len(opened) == len(LAB_TASKS)


def test_control_plane_tick_writes_only_when_on(monkeypatch, maker):
    db = maker()
    db.add(Organization(name="Gốm Mộc", slug="gom-moc")); db.commit()
    monkeypatch.setattr(v15, "SessionLocal", maker)

    monkeypatch.setattr(settings, "lab_jobs_enabled", False)
    v15.control_plane_tick()
    assert db.query(SchedulerNode).count() == 0

    monkeypatch.setattr(settings, "lab_jobs_enabled", True)
    out = v15.control_plane_tick()
    assert out["leaders"] == 1
    assert db.query(SchedulerNode).count() == 1


def test_health_lab_reports_flag(monkeypatch):
    client = TestClient(app)
    monkeypatch.setattr(settings, "lab_jobs_enabled", False)
    body = client.get("/api/health/lab").json()
    assert body["lab_jobs_enabled"] is False and body["env"] == "LAB_JOBS_ENABLED"
    assert set(body["jobs"]) == set(LAB_TASKS)
    monkeypatch.setattr(settings, "lab_jobs_enabled", True)
    assert client.get("/api/health/lab").json()["lab_jobs_enabled"] is True
