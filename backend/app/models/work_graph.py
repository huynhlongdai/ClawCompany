"""D1.3 + D1.4 — đồ thị phụ thuộc giữa task và bản ghi từng lượt chạy.

Bảng ở migration ``0018_task_graph`` và ``0019_task_runs``.
"""
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class TaskDependency(Base):
    """``task_id`` bị chặn bởi ``blocked_by_task_id`` cho tới khi task kia xong."""
    __tablename__ = "task_dependencies"
    __table_args__ = (UniqueConstraint("task_id", "blocked_by_task_id", name="uq_task_dependency"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), index=True)
    blocked_by_task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), index=True)
    created_by_member_id: Mapped[int | None] = mapped_column(ForeignKey("members.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


RUN_STATUSES = ("queued", "dispatched", "running", "completed", "failed", "cancelled", "skipped")
OPEN_RUN_STATUSES = ("queued", "dispatched", "running")


class TaskRun(Base):
    """Một lượt agent làm một task. Trước D1.4 chỉ có ``tasks.runtime_run_id`` —
    lượt sau ghi đè lượt trước, nên không ai biết một việc đã chạy mấy lần,
    tốn bao nhiêu, và lần nào hỏng vì sao."""
    __tablename__ = "task_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), index=True)
    member_id: Mapped[int | None] = mapped_column(ForeignKey("members.id"), nullable=True, index=True)
    trigger_kind: Mapped[str] = mapped_column(String(32), default="manual")
    wakeup_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)
    session_key: Mapped[str] = mapped_column(String(200), default="")
    runtime_run_id: Mapped[str] = mapped_column(String(160), default="", index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    error_reason: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
