"""M2c — vận hành công ty: bản đồ quy trình (D4), KPI chia tầng (D5), nhịp vận hành (D6),
lịch tuân thủ VN (D7), chẩn đoán sẵn sàng agent (D8). Spec: docs/m2c-company-operations.md.

Quy trình KHÔNG có động cơ riêng: mỗi bước của một lần chạy là một ``tasks`` bình thường
(giao seat đang ngồi chức danh, chặn bằng ``task_dependencies``, duyệt bằng chặng
``execution_policy``), nên agent nhận việc, đánh thức, review, Hộp việc… đi đường cũ.
Bảng ở đây chỉ ghi định nghĩa và thời gian chu trình."""
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
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


# ------------------------------------------------------------------ D5 KPI chia tầng

class KpiDefinition(Base):
    """Một KPI ở một tầng: công ty → phòng ban → chức danh → seat (``parent_id`` nối tầng).
    ``metric`` = nguồn số: ``manual`` (người nhập) hoặc một chỉ số tính từ dữ liệu thật
    (việc xong, thời gian chu trình D4, chi phí mỗi việc, tỷ lệ qua review lần đầu, phê duyệt…)."""
    __tablename__ = "kpi_definitions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    level: Mapped[str] = mapped_column(String(16), default="company")      # company|department|position|seat
    department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id"), nullable=True)
    position_id: Mapped[int | None] = mapped_column(ForeignKey("positions.id"), nullable=True)
    member_id: Mapped[int | None] = mapped_column(ForeignKey("members.id"), nullable=True, index=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("kpi_definitions.id"), nullable=True, index=True)
    goal_id: Mapped[int | None] = mapped_column(ForeignKey("executive_goals.id"), nullable=True)
    objective_id: Mapped[int | None] = mapped_column(ForeignKey("portfolio_objectives.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(200))
    unit: Mapped[str] = mapped_column(String(40), default="")
    target: Mapped[float | None] = mapped_column(Float, nullable=True)
    direction: Mapped[str] = mapped_column(String(8), default="up")          # up = càng cao càng tốt | down
    period: Mapped[str] = mapped_column(String(16), default="month")         # week|month|quarter
    metric: Mapped[str] = mapped_column(String(40), default="manual")
    process_id: Mapped[int | None] = mapped_column(ForeignKey("processes.id"), nullable=True)
    weight: Mapped[float] = mapped_column(Float, default=1.0)
    source: Mapped[str] = mapped_column(String(24), default="custom")       # custom | position
    status: Mapped[str] = mapped_column(String(16), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class KpiMeasurement(Base):
    """Số nhập tay (hoặc ảnh chụp số tự tính) của một KPI cho một kỳ (``2026-10``, ``2026-W42``, ``2026-Q4``)."""
    __tablename__ = "kpi_measurements"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kpi_id: Mapped[int] = mapped_column(ForeignKey("kpi_definitions.id"), index=True)
    period_key: Mapped[str] = mapped_column(String(16), index=True)
    value: Mapped[float] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(16), default="manual")
    note: Mapped[str] = mapped_column(String(400), default="")
    recorded_by_member_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


# ------------------------------------------------------------------ D6 nhịp vận hành

class RhythmConfig(Base):
    """Giao ban ngày / báo cáo tuần tự động của một công ty (giờ địa phương)."""
    __tablename__ = "rhythm_configs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), unique=True, index=True)
    standup_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    standup_hour: Mapped[int] = mapped_column(Integer, default=8)
    weekly_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    weekly_dow: Mapped[int] = mapped_column(Integer, default=4)               # 0 = thứ Hai … 4 = thứ Sáu
    weekly_hour: Mapped[int] = mapped_column(Integer, default=17)
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Ho_Chi_Minh")
    per_department: Mapped[bool] = mapped_column(Boolean, default=True)
    agent_author: Mapped[bool] = mapped_column(Boolean, default=True)        # trưởng phòng là agent viết (qua gateway)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class RhythmReport(Base):
    """Một bản giao ban / báo cáo tuần đã gửi. ``scope_key`` = ``c<id>`` (công ty) | ``d<id>`` (phòng);
    UNIQUE(công ty, scope, loại, kỳ) — beat và nút "Gửi ngay" không sinh hai bản cho cùng kỳ."""
    __tablename__ = "rhythm_reports"
    __table_args__ = (UniqueConstraint("company_id", "scope_key", "kind", "period_key", name="uq_rhythm_report_period"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id"), nullable=True)
    scope_key: Mapped[str] = mapped_column(String(24), default="")
    kind: Mapped[str] = mapped_column(String(16), default="standup")          # standup | weekly
    period_key: Mapped[str] = mapped_column(String(16), default="")
    title: Mapped[str] = mapped_column(String(220), default="")
    content: Mapped[str] = mapped_column(Text, default="")
    fallback: Mapped[str] = mapped_column(Text, default="")
    data_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    author: Mapped[str] = mapped_column(String(120), default="system")
    author_note: Mapped[str] = mapped_column(String(400), default="")
    recipients: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
