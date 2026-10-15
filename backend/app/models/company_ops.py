"""M2c — vận hành công ty: bản đồ quy trình (D4), KPI chia tầng (D5), nhịp vận hành (D6),
lịch tuân thủ VN (D7), chẩn đoán sẵn sàng agent (D8). Spec: docs/m2c-company-operations.md.

Quy trình KHÔNG có động cơ riêng: mỗi bước của một lần chạy là một ``tasks`` bình thường
(giao seat đang ngồi chức danh, chặn bằng ``task_dependencies``, duyệt bằng chặng
``execution_policy``), nên agent nhận việc, đánh thức, review, Hộp việc… đi đường cũ.
Bảng ở đây chỉ ghi định nghĩa và thời gian chu trình."""
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


# ------------------------------------------------------------------ D4 bản đồ quy trình

class Process(Base):
    """Một quy trình chuỗi giá trị, xếp theo nhóm APQC PCF (1–13), có chức danh làm chủ."""
    __tablename__ = "processes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    category: Mapped[str] = mapped_column(String(8), default="6")           # mã nhóm APQC "1".."13"
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    owner_position_id: Mapped[int | None] = mapped_column(ForeignKey("positions.id"), nullable=True)
    template_key: Mapped[str] = mapped_column(String(64), default="")
    status: Mapped[str] = mapped_column(String(24), default="active")       # active | archived
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ProcessStep(Base):
    __tablename__ = "process_steps"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    process_id: Mapped[int] = mapped_column(ForeignKey("processes.id"), index=True)
    seq: Mapped[int] = mapped_column(Integer, default=1)
    name: Mapped[str] = mapped_column(String(200))
    instructions: Mapped[str] = mapped_column(Text, default="")
    position_id: Mapped[int | None] = mapped_column(ForeignKey("positions.id"), nullable=True)
    sop_id: Mapped[int | None] = mapped_column(ForeignKey("sops.id"), nullable=True)
    expected_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # loại việc của ma trận phân quyền (refund, spend, external_message…); rỗng = không xét duyệt
    action_type: Mapped[str] = mapped_column(String(40), default="")
    risk: Mapped[str] = mapped_column(String(16), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ProcessInstance(Base):
    __tablename__ = "process_instances"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    process_id: Mapped[int] = mapped_column(ForeignKey("processes.id"), index=True)
    title: Mapped[str] = mapped_column(String(220), default="")
    status: Mapped[str] = mapped_column(String(16), default="running", index=True)   # running|done|cancelled
    amount_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    input_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), nullable=True)
    started_by_member_id: Mapped[int | None] = mapped_column(ForeignKey("members.id"), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    cycle_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)


class ProcessStepRun(Base):
    """Một bước của một lần chạy = một task. ``activated_at`` là lúc bước tới lượt (bước trước
    xong) — thời gian chu trình của bước tính từ đó, không từ lúc tạo task."""
    __tablename__ = "process_step_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    instance_id: Mapped[int] = mapped_column(ForeignKey("process_instances.id"), index=True)
    step_id: Mapped[int | None] = mapped_column(ForeignKey("process_steps.id"), nullable=True)
    seq: Mapped[int] = mapped_column(Integer, default=1)
    name: Mapped[str] = mapped_column(String(200), default="")
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id"), nullable=True, index=True)
    position_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    assignee_member_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="waiting")   # waiting|active|done|cancelled
    approval_required: Mapped[bool] = mapped_column(Boolean, default=False)
    approver_member_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    authority_rule_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    expected_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    note: Mapped[str] = mapped_column(String(400), default="")
    activated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    cycle_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
