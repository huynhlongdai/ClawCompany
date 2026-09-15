"""v36: chuỗi thời gian chỉ số, lịch, số theo ngày của agent, hạn chót.

Cách viết test ở đây theo đúng bài học của lượt tiếp nhận: **kiểm hành vi trên
database thật (SQLite), không grep source, không test double bỏ qua WHERE**.
Mỗi test dựng dữ liệu tối thiểu rồi gọi service như production gọi.
"""
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
import app.models  # noqa: F401
from app.models.entities import Agent, Company, Member, Organization, Project
from app.models.extended import AnalyticsMetric
from app.models.v7 import UsageEvent
from app.models.v10 import CompanyEvent
from app.models.v36 import AgentDailyStat, CalendarEvent, MetricSample
from app.services import v36_insights as v36


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def org(db):
    organization = Organization(name="Nova", slug="nova-v36")
    db.add(organization); db.commit(); db.refresh(organization)
    company = Company(organization_id=organization.id, name="Nova Fashion", status="active")
    db.add(company); db.commit(); db.refresh(company)
    return organization, company


# --------------------------------------------------------------- chỉ số

def test_snapshot_writes_one_point_per_metric(db, org):
    organization, _ = org
    db.add(AnalyticsMetric(organization_id=organization.id, metric_key="revenue",
                           current_value=1000.0, previous_value=900.0,
                           target_value=1200.0, unit="USD"))
    db.commit()

    out = v36.snapshot_metrics(db, organization.id, grain="month")
    assert out["metrics_seen"] == 1 and out["written"] == 1

    history = v36.metric_history(db, organization.id)
    points = history["series"][0]["points"]
    assert [p["value"] for p in points] == [1000.0]
    assert history["points_are_measurements"] is True


def test_snapshot_twice_in_one_period_updates_not_duplicates(db, org):
    """Một cron gọi mỗi ngày không được nhân bản điểm của cùng một kỳ."""
    organization, _ = org
    metric = AnalyticsMetric(organization_id=organization.id, metric_key="revenue",
                             current_value=1000.0, previous_value=900.0, unit="USD")
    db.add(metric); db.commit()

    v36.snapshot_metrics(db, organization.id)
    metric.current_value = 1100.0
    db.add(metric); db.commit()
    second = v36.snapshot_metrics(db, organization.id)

    assert second["written"] == 0 and second["updated"] == 1
    points = v36.metric_history(db, organization.id)["series"][0]["points"]
    assert len(points) == 1, "cùng kỳ phải ghi đè, không thêm điểm"
    assert points[0]["value"] == 1100.0


def test_backfilled_points_are_not_claimed_as_measurements(db, org):
    """Điểm do migration backfill không được coi là chuỗi đo liên tục.

    Đây là lời thừa nhận quan trọng nhất của v36: ai vẽ biểu đồ từ hai điểm
    backfill phải biết đó là hai mốc mà bảng cũ vốn đã biết.
    """
    organization, _ = org
    now = datetime.utcnow()
    for period, value in (("2026-08", 900.0), ("2026-09", 1000.0)):
        db.add(MetricSample(organization_id=organization.id, metric_key="revenue",
                            period=period, value=value, unit="USD",
                            source="analytics_backfill", recorded_at=now))
    db.commit()

    history = v36.metric_history(db, organization.id)
    assert history["sample_count"] == 2
    assert history["sources"] == ["analytics_backfill"]
    assert history["points_are_measurements"] is False


def test_history_is_scoped_to_one_organization(db, org):
    organization, _ = org
    other = Organization(name="Rival", slug="rival-v36")
    db.add(other); db.commit(); db.refresh(other)
    now = datetime.utcnow()
    db.add(MetricSample(organization_id=organization.id, metric_key="revenue",
                        period="2026-09", value=1.0, recorded_at=now))
    db.add(MetricSample(organization_id=other.id, metric_key="revenue",
                        period="2026-09", value=999.0, recorded_at=now))
    db.commit()

    points = v36.metric_history(db, organization.id)["series"][0]["points"]
    assert [p["value"] for p in points] == [1.0], "không được rò rỉ chéo tenant"


# ------------------------------------------------------------------ lịch

def test_calendar_returns_only_the_requested_day(db, org):
    organization, company = org
    # WP-1.2: dùng giờ **địa phương**, không phải utcnow(). `starts_at` lưu giờ
    # treo tường của tổ chức (người tạo "họp 9 giờ" thì cột là 09:00), nên một
    # test lấy utcnow() làm "bây giờ" sẽ hỏng đúng 7 giờ mỗi ngày ở UTC+7 —
    # utcnow() lúc đó vẫn là hôm qua. Bản cũ chạy xanh chỉ vì chưa ai chạy nó
    # vào sáng sớm.
    today = datetime.now().replace(hour=9, minute=0, second=0, microsecond=0)
    v36.create_calendar_event(db, organization.id, title="Họp hôm nay",
                              starts_at=today, company_id=company.id)
    v36.create_calendar_event(db, organization.id, title="Họp tuần sau",
                              starts_at=today + timedelta(days=7))

    out = v36.calendar(db, organization.id, days=1)
    assert out["count"] == 1
    assert out["events"][0]["title"] == "Họp hôm nay"
    # Chưa có tích hợp nào, và API phải nói thẳng điều đó.
    assert out["synced_from_provider"] is False


def test_calendar_rejects_end_before_start(db, org):
    organization, _ = org
    start = datetime.utcnow()
    with pytest.raises(ValueError):
        v36.create_calendar_event(db, organization.id, title="Sai giờ",
                                  starts_at=start, ends_at=start - timedelta(hours=1))


def test_local_today_follows_the_configured_timezone(monkeypatch):
    """Chứng minh chốt múi giờ có hiệu lực, không phụ thuộc giờ chạy test.

    Lấy hai múi giờ cách nhau 26 tiếng: ở bất kỳ thời điểm nào trong năm, ngày
    lịch của chúng cũng khác nhau. Nếu ``local_today`` bỏ qua cấu hình thì hai
    lời gọi trả về cùng một ngày và test đỏ.
    """
    from app.core.config import settings

    monkeypatch.setattr(settings, "app_timezone", "Pacific/Kiritimati")   # UTC+14
    east = v36.local_today()
    monkeypatch.setattr(settings, "app_timezone", "Etc/GMT+12")           # UTC-12
    west = v36.local_today()
    assert east != west, "local_today phải đổi theo app_timezone"
    assert (east - west).days == 1

    # Múi giờ sai chính tả không được làm sập trang chủ.
    monkeypatch.setattr(settings, "app_timezone", "Mars/Olympus_Mons")
    assert v36.local_today() == date.today()


def test_deadline_days_left_is_not_off_by_one_in_utc_plus_seven(db, org, monkeypatch):
    """Chốt hồi quy cho đúng lỗi đã gặp lúc 06:00 giờ Việt Nam.

    Trước WP-1.2, ``days_left`` tính theo ``utcnow().date()``. Với UTC+7 thì
    trong 00:00-07:00 giờ địa phương, UTC còn là hôm qua, nên một dự án quá hạn
    3 ngày được báo là 2. Test đặt thẳng múi giờ Việt Nam và so với ngày lịch
    Việt Nam, nên nó đỏ nếu ai đó đổi lại về UTC.
    """
    from zoneinfo import ZoneInfo

    from app.core.config import settings
    monkeypatch.setattr(settings, "app_timezone", "Asia/Ho_Chi_Minh")

    organization, company = org
    vn_today = datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")).date()
    db.add(Project(company_id=company.id, name="Quá hạn ba ngày", status="active",
                   progress=0, due_date=vn_today - timedelta(days=3)))
    db.commit()

    out = v36.upcoming_deadlines(db, organization.id, days=30)
    assert out["projects"][0]["days_left"] == -3
    assert out["projects"][0]["overdue"] is True


def test_empty_calendar_is_an_answer_not_an_error(db, org):
    organization, _ = org
    out = v36.calendar(db, organization.id, days=1)
    assert out["count"] == 0 and out["events"] == []


# ------------------------------------------- số theo ngày của agent

def _seat(db, organization, company, *, runtime_id: str, name: str) -> Agent:
    member = Member(organization_id=organization.id, company_id=company.id,
                    name=name, member_type="agent", role="Agent", status="active")
    db.add(member); db.commit(); db.refresh(member)
    agent = Agent(member_id=member.id, runtime_provider="openclaw",
                  runtime_agent_id=runtime_id, lifecycle="active")
    db.add(agent); db.commit(); db.refresh(agent)
    return agent


def test_derive_reads_runs_and_cost_from_usage_events(db, org):
    organization, company = org
    agent = _seat(db, organization, company, runtime_id="dev", name="Nina")
    now = datetime.utcnow()
    for amount in (1.5, 2.25):
        db.add(UsageEvent(organization_id=organization.id, agent_id=agent.id,
                          event_type="agent_run", quantity=1, amount=amount,
                          created_at=now))
    db.commit()

    out = v36.derive_agent_stats(db, organization.id, days=7)
    assert out["rows_written"] == 1

    row = db.query(AgentDailyStat).one()
    assert row.runs == 2
    assert row.cost == pytest.approx(3.75)
    # Không có event kết thúc việc nào -> không đo được, KHÁC với 0%.
    assert row.success_rate is None


def test_derive_is_idempotent_for_the_same_day(db, org):
    organization, company = org
    agent = _seat(db, organization, company, runtime_id="dev", name="Nina")
    db.add(UsageEvent(organization_id=organization.id, agent_id=agent.id,
                      event_type="agent_run", amount=1.0, created_at=datetime.utcnow()))
    db.commit()

    v36.derive_agent_stats(db, organization.id, days=7)
    v36.derive_agent_stats(db, organization.id, days=7)
    assert db.query(AgentDailyStat).count() == 1, "tính lại phải ghi đè, không nhân dòng"


def test_success_rate_uses_task_outcome_events_matched_by_runtime_id(db, org):
    organization, company = org
    agent = _seat(db, organization, company, runtime_id="dev", name="Nina")
    now = datetime.utcnow()
    db.add(UsageEvent(organization_id=organization.id, agent_id=agent.id,
                      event_type="agent_run", amount=0.5, created_at=now))
    # company_events không có cột agent_id, nên chỉ quy được qua payload.
    db.add(CompanyEvent(organization_id=organization.id, event_type="task.completed",
                        aggregate_type="task", aggregate_id="1",
                        payload_json='{"runtime_agent_id": "dev"}', occurred_at=now))
    db.add(CompanyEvent(organization_id=organization.id, event_type="task.failed",
                        aggregate_type="task", aggregate_id="2",
                        payload_json='{"runtime_agent_id": "dev"}', occurred_at=now))
    # Event không nói agent nào -> không được tính cho ai.
    db.add(CompanyEvent(organization_id=organization.id, event_type="task.completed",
                        aggregate_type="task", aggregate_id="3",
                        payload_json='{}', occurred_at=now))
    db.commit()

    out = v36.derive_agent_stats(db, organization.id, days=7)
    assert out["events_unattributed"] == 1

    row = db.query(AgentDailyStat).one()
    assert (row.tasks_completed, row.tasks_failed) == (1, 1)
    assert row.success_rate == pytest.approx(50.0)
    assert out["attribution"]["company_events_carry_agent_id"] is False


def test_derive_reports_when_org_has_no_agents(db, org):
    organization, _ = org
    out = v36.derive_agent_stats(db, organization.id)
    assert out["rows_written"] == 0 and out["agents"] == 0
    assert "chưa có agent" in out["note"]


# ------------------------------------------------------------- hạn chót

def test_deadlines_flag_overdue_and_days_left(db, org):
    organization, company = org
    today = date.today()
    late = Project(company_id=company.id, name="Quá hạn", status="active", progress=10,
                   due_date=today - timedelta(days=3))
    soon = Project(company_id=company.id, name="Sắp tới", status="active", progress=50,
                   due_date=today + timedelta(days=5))
    none = Project(company_id=company.id, name="Chưa đặt hạn", status="active", progress=0)
    db.add_all([late, soon, none]); db.commit()

    out = v36.upcoming_deadlines(db, organization.id, days=30)
    names = [p["name"] for p in out["projects"]]
    assert names == ["Quá hạn", "Sắp tới"], "dự án chưa đặt hạn không xuất hiện"
    assert out["projects"][0]["overdue"] is True
    assert out["projects"][0]["days_left"] == -3
    assert out["projects"][1]["days_left"] == 5
    # Và API nói rõ mình đã loại ai, để không ai đọc "2" thành "cả tổ chức".
    assert out["projects_without_due_date_excluded"] is True


def test_set_due_date_accepts_clearing_it(db, org):
    _, company = org
    project = Project(company_id=company.id, name="Dự án", status="active",
                      progress=0, due_date=date.today())
    db.add(project); db.commit(); db.refresh(project)

    v36.set_project_due_date(db, project, None)
    db.refresh(project)
    assert project.due_date is None, "bỏ hạn là một hành động hợp lệ"


def test_deadlines_do_not_leak_across_organizations(db, org):
    organization, company = org
    other_org = Organization(name="Rival", slug="rival-deadline")
    db.add(other_org); db.commit(); db.refresh(other_org)
    other_company = Company(organization_id=other_org.id, name="Rival Co", status="active")
    db.add(other_company); db.commit(); db.refresh(other_company)

    db.add(Project(company_id=company.id, name="Của mình", status="active",
                   progress=0, due_date=date.today()))
    db.add(Project(company_id=other_company.id, name="Của người khác", status="active",
                   progress=0, due_date=date.today()))
    db.commit()

    out = v36.upcoming_deadlines(db, organization.id, days=30)
    assert [p["name"] for p in out["projects"]] == ["Của mình"]
