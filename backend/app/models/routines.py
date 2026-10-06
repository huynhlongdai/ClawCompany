"""D3.4 — routines: việc định kỳ / theo webhook của công ty.

``routines``: việc gì (``runbook``), giao ai (``assignee_member_id`` hoặc
``department_id``), chế độ ``create_task`` (mỗi lần một task mới) hoặc
``run_only`` (đánh thức seat trên một task thường trực của routine), múi giờ,
chính sách chạy bù và đồng thời, ngưỡng lỗi liên tiếp.

``routine_triggers``: ``cron`` (biểu thức 5 trường theo múi giờ của routine,
``next_run_at`` UTC) hoặc ``webhook`` (``secret``).

``routine_runs``: mỗi lần kích hoạt. ``idempotency_key`` UNIQUE — cùng một
lần cron (``cron:t<id>:<giờ>``) hay cùng ``Idempotency-Key`` của webhook chỉ
sinh một run, nên không bao giờ có task trùng.
"""
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

ROUTINE_MODES = ("create_task", "run_only")
CATCH_UP = ("skip_missed", "run_once")
TRIGGER_KINDS = ("cron", "webhook")
ROUTINE_RUN_STATUSES = ("queued", "running", "succeeded", "failed", "skipped")


class Routine(Base):
    __tablename__ = "routines"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"), nullable=True, index=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(200))
    template_key: Mapped[str] = mapped_column(String(64), default="")
    runbook: Mapped[str] = mapped_column(Text, default="")
    assignee_member_id: Mapped[int | None] = mapped_column(ForeignKey("members.id"), nullable=True, index=True)
    department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id"), nullable=True)
    owner_member_id: Mapped[int | None] = mapped_column(ForeignKey("members.id"), nullable=True)
    mode: Mapped[str] = mapped_column(String(16), default="create_task")
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Ho_Chi_Minh")
    catch_up: Mapped[str] = mapped_column(String(16), default="skip_missed")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    max_consecutive_failures: Mapped[int] = mapped_column(Integer, default=3)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    paused_reason: Mapped[str] = mapped_column(String(300), default="")
    standing_task_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # run_only
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class RoutineTrigger(Base):
    __tablename__ = "routine_triggers"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    routine_id: Mapped[int] = mapped_column(ForeignKey("routines.id"), index=True)
    kind: Mapped[str] = mapped_column(String(16), default="cron")
    cron: Mapped[str] = mapped_column(String(120), default="")
    secret: Mapped[str] = mapped_column(String(120), default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    last_fired_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class RoutineRun(Base):
    __tablename__ = "routine_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    routine_id: Mapped[int] = mapped_column(ForeignKey("routines.id"), index=True)
    trigger_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    trigger_kind: Mapped[str] = mapped_column(String(16), default="cron")  # cron|webhook|manual|catch_up
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True)
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)
    task_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    wakeup_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    task_run_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str] = mapped_column(Text, default="")
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
