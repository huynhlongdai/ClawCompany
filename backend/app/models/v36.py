"""v36: bốn thứ bản thiết kế cần mà hệ thống chưa có.

Mỗi bảng ở đây sinh ra vì một khối trên màn hình không có nguồn dữ liệu, và
lựa chọn trước đó là "vẽ số bịa" hoặc "để trống". Không bảng nào ở đây tự
sinh dữ liệu: chúng chỉ mở chỗ để dữ liệu thật đi vào.

Ranh giới cố ý:

* ``MetricSample`` là chuỗi thời gian của ``analytics_metrics``. Bảng cũ chỉ
  giữ hai mốc (hiện tại, kỳ trước) nên biểu đồ nhiều kỳ là bịa. Bảng này
  không thay bảng cũ — nó là *lịch sử*, ghi theo từng lần chốt số.
* ``CalendarEvent`` là lịch do người và agent tạo, không đồng bộ từ đâu cả.
  Chưa nối Google/Outlook thì lịch trống là câu trả lời đúng.
* ``AgentDailyStat`` là số theo ngày cho từng agent. Nguồn duy nhất có thật
  hôm nay là ``usage_events`` (lượt chạy, chi phí) và ``company_events``
  (việc chuyển trạng thái), nên service v36 dẫn xuất từ hai bảng đó chứ không
  nhận số do người gõ vào.
* ``projects.due_date`` là cột, không phải bảng — thêm vào ``Project`` trong
  ``entities.py`` để không phải tạo một bảng phụ chỉ để giữ một ngày.
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.entities import TimestampMixin


class MetricSample(Base):
    """Một lần chốt số của một chỉ số, tại một thời điểm.

    ``metric_key`` cố ý trùng tên với ``analytics_metrics.metric_key`` thay vì
    khoá ngoại: chỉ số có thể bị xoá khỏi bảng hiện trạng mà lịch sử vẫn phải
    giữ được, và nguồn số có thể là một scope chưa có hàng trong bảng kia.
    """

    __tablename__ = "metric_samples"
    __table_args__ = (
        # Một chỉ số, một scope, một mốc thời gian -> đúng một hàng. Nhờ vậy
        # chạy lại job chốt số hai lần không nhân đôi biểu đồ.
        UniqueConstraint("organization_id", "metric_key", "scope_type", "scope_id",
                         "period", name="uq_metric_samples_point"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    metric_key: Mapped[str] = mapped_column(String(120), index=True)
    scope_type: Mapped[str] = mapped_column(String(64), default="organization")
    scope_id: Mapped[str] = mapped_column(String(120), default="")
    # "2026-09" cho tháng, "2026-09-15" cho ngày. Chuỗi thay vì Date để một
    # bảng giữ được cả hai độ mịn mà không cần cột thứ hai nói "đây là tháng".
    period: Mapped[str] = mapped_column(String(20), index=True)
    value: Mapped[float] = mapped_column(Float, default=0)
    unit: Mapped[str] = mapped_column(String(40), default="")
    # Ai ghi con số này: "manual", "analytics_snapshot", "usage_events"...
    source: Mapped[str] = mapped_column(String(64), default="manual")
    recorded_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class CalendarEvent(Base, TimestampMixin):
    """Một mục lịch: họp, hạn chót, mốc.

    Không có trường "đồng bộ từ nhà cung cấp nào" vì chưa có tích hợp nào.
    Thêm sau thì thêm cột, đừng để một cột rỗng hứa hẹn điều chưa có.
    """

    __tablename__ = "calendar_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(220))
    description: Mapped[str] = mapped_column(Text, default="")
    starts_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    location: Mapped[str] = mapped_column(String(200), default="")
    # "meeting" | "deadline" | "milestone" | "review"
    event_type: Mapped[str] = mapped_column(String(32), default="meeting")
    # Người hoặc agent chủ trì; cùng bảng members nên agent cũng chủ trì được.
    owner_member_id: Mapped[int | None] = mapped_column(ForeignKey("members.id"), nullable=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="scheduled")


class AgentDailyStat(Base):
    """Số của một agent trong một ngày.

    Do service v36 dẫn xuất từ ``usage_events`` và ``company_events``; không
    có endpoint cho người gõ số vào. ``derived_at`` để biết hàng này được tính
    lúc nào, và tính lại thì ghi đè đúng hàng đó.
    """

    __tablename__ = "agent_daily_stats"
    __table_args__ = (
        UniqueConstraint("agent_id", "day", name="uq_agent_daily_stats_day"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id"), index=True)
    day: Mapped[date] = mapped_column(Date, index=True)
    runs: Mapped[int] = mapped_column(Integer, default=0)
    tasks_completed: Mapped[int] = mapped_column(Integer, default=0)
    tasks_failed: Mapped[int] = mapped_column(Integer, default=0)
    cost: Mapped[float] = mapped_column(Float, default=0)
    # Tỉ lệ thành công của riêng ngày đó, tính từ completed/(completed+failed).
    # NULL khi ngày đó không có việc nào kết thúc — "không đo được" khác "0%".
    success_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    derived_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
