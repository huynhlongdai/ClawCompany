"""M2c — vận hành công ty: bản đồ quy trình (D4), KPI chia tầng (D5), nhịp vận hành (D6),
lịch tuân thủ VN (D7), chẩn đoán sẵn sàng agent (D8). Spec: docs/m2c-company-operations.md.

Quy trình KHÔNG có động cơ riêng: mỗi bước của một lần chạy là một ``tasks`` bình thường
(giao seat đang ngồi chức danh, chặn bằng ``task_dependencies``, duyệt bằng chặng
``execution_policy``), nên agent nhận việc, đánh thức, review, Hộp việc… đi đường cũ.
Bảng ở đây chỉ ghi định nghĩa và thời gian chu trình."""
from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
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
    # v2 (0044): đồ thị bước. ``depends_on`` = danh sách seq bước đứng trước (rỗng = chạy ngay khi bắt đầu;
    # nhiều bước cùng phụ thuộc một bước = song song; một bước phụ thuộc nhiều bước = gộp nhánh).
    # ``condition`` = {field, op, value} xét lúc bước tới lượt; sai → bước bị bỏ qua (nhánh không áp dụng).
    depends_on: Mapped[list | None] = mapped_column(JSON, nullable=True)
    condition: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    branch: Mapped[str] = mapped_column(String(60), default="")
    # M2e.3 (0049): hợp đồng dữ liệu của bước — việc sinh ra mang dữ liệu vào + phải nộp kết quả đúng schema
    contract_id: Mapped[int | None] = mapped_column(ForeignKey("io_contracts.id"), nullable=True)
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
    status: Mapped[str] = mapped_column(String(16), default="waiting")   # waiting|active|done|skipped|cancelled
    approval_required: Mapped[bool] = mapped_column(Boolean, default=False)
    approver_member_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    authority_rule_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    expected_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    note: Mapped[str] = mapped_column(String(400), default="")
    # v2 (0044): ảnh chụp đồ thị lúc bắt đầu chạy + kết quả bước (dùng cho điều kiện của bước sau)
    depends_on: Mapped[list | None] = mapped_column(JSON, nullable=True)
    condition: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    branch: Mapped[str] = mapped_column(String(60), default="")
    outcome: Mapped[str] = mapped_column(String(200), default="")
    skip_reason: Mapped[str] = mapped_column(String(300), default="")
    output_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)    # M2e.3: kết quả đạt hợp đồng của bước
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


class PublicHoliday(Base):
    """M2d.3 — ngày nghỉ lễ (và ngày làm bù) theo năm, dữ liệu sửa được cho từng tổ chức. CHỈ dùng để tính hạn
    pháp lý (hạn rơi ngày nghỉ → ngày làm việc liền kề sau). Agent không có ngày nghỉ: lịch giao việc, giao ban,
    nhắc hạn không đọc bảng này."""
    __tablename__ = "public_holidays"
    __table_args__ = (UniqueConstraint("organization_id", "day", name="uq_public_holidays_org_day"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    year: Mapped[int] = mapped_column(Integer, index=True)
    day: Mapped[date] = mapped_column(Date)
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(16), default="holiday")          # holiday | makeup_workday
    status: Mapped[str] = mapped_column(String(24), default="official")       # official | needs_confirmation
    source_url: Mapped[str] = mapped_column(String(400), default="")
    note: Mapped[str] = mapped_column(String(400), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class KpiSnapshot(Base):
    """M2d.2 — số KPI đã tính, lưu theo kỳ (một hàng / KPI × kỳ; trong kỳ thì cập nhật tại chỗ, hết kỳ thì
    đóng băng). ``trigger``: beat | manual | backfill (tính lại kỳ cũ từ dữ liệu hiện có)."""
    __tablename__ = "kpi_snapshots"
    __table_args__ = (UniqueConstraint("kpi_id", "period_key", name="uq_kpi_snapshots_kpi_period"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kpi_id: Mapped[int] = mapped_column(ForeignKey("kpi_definitions.id"), index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    period: Mapped[str] = mapped_column(String(16), default="month")
    period_key: Mapped[str] = mapped_column(String(16), index=True)
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    value_source: Mapped[str] = mapped_column(String(16), default="")       # auto | manual | ""
    target: Mapped[float | None] = mapped_column(Float, nullable=True)
    progress: Mapped[float | None] = mapped_column(Float, nullable=True)
    health: Mapped[str] = mapped_column(String(16), default="no_data")
    trigger: Mapped[str] = mapped_column(String(16), default="beat")
    final: Mapped[bool] = mapped_column(Boolean, default=False)              # kỳ đã qua → không ghi đè nữa
    computed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


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


# ------------------------------------------------------------------ D7 lịch tuân thủ VN

class ComplianceRule(Base):
    """Một nghĩa vụ định kỳ (thuế, BHXH, báo cáo, giấy phép) lưu dưới dạng DỮ LIỆU sửa được: áp cho loại
    hình nào, điều kiện (kỳ kê khai, có lao động), cách tính hạn, căn cứ pháp lý, nhắc trước bao nhiêu ngày."""
    __tablename__ = "compliance_rules"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    key: Mapped[str] = mapped_column(String(64), default="")
    name: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(16), default="tax")          # tax|social|report|license
    entity_types: Mapped[list | None] = mapped_column(JSON, nullable=True)    # rỗng = mọi loại hình
    condition: Mapped[dict | None] = mapped_column(JSON, nullable=True)       # {"vat_period": "monthly", "has_employees": true}
    frequency: Mapped[str] = mapped_column(String(16), default="monthly")     # monthly|quarterly|yearly|once
    due_rule: Mapped[dict | None] = mapped_column(JSON, nullable=True)        # {"type": "next_month_day", "day": 20} …
    legal_basis: Mapped[str] = mapped_column(Text, default="")
    note: Mapped[str] = mapped_column(Text, default="")
    remind_days: Mapped[int] = mapped_column(Integer, default=7)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False)
    effective_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    source: Mapped[str] = mapped_column(String(16), default="default")       # default | custom
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ComplianceDeadline(Base):
    __tablename__ = "compliance_deadlines"
    __table_args__ = (UniqueConstraint("rule_id", "period_label", name="uq_compliance_deadline_period"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    rule_id: Mapped[int] = mapped_column(ForeignKey("compliance_rules.id"), index=True)
    period_label: Mapped[str] = mapped_column(String(32))
    statutory_date: Mapped[date] = mapped_column(Date)                         # hạn theo lịch (ngày luật ghi)
    # M2d.3: due_date = hạn NỘI BỘ = đúng ngày theo lịch (agent làm cả ngày nghỉ → nộp sớm); nhắc + task theo ngày này.
    due_date: Mapped[date] = mapped_column(Date, index=True)
    # hạn PHÁP LÝ: hạn theo lịch rơi vào cuối tuần/ngày lễ → ngày làm việc liền kề sau (chỉ để hiển thị/đối chiếu)
    legal_due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="upcoming")      # upcoming|done|skipped
    assignee_member_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    task_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reminded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    done_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


# ------------------------------------------------------------------ D8 chẩn đoán sẵn sàng agent

class ReadinessAssessment(Base):
    """Một lần chấm "sẵn sàng agent": câu trả lời bảng hỏi + kiểm tra tự động theo lớp công ty → điểm từng
    lớp, điểm chung, danh sách việc cần sửa (kèm đường dẫn) và quy trình lighthouse đề xuất."""
    __tablename__ = "readiness_assessments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    trigger: Mapped[str] = mapped_column(String(24), default="manual")      # manual | company_created
    answers: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    score: Mapped[int] = mapped_column(Integer, default=0)
    level: Mapped[str] = mapped_column(String(24), default="")
    layers: Mapped[list | None] = mapped_column(JSON, nullable=True)
    checks: Mapped[list | None] = mapped_column(JSON, nullable=True)
    lighthouse: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_by_member_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
