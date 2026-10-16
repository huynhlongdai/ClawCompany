"""M2e — công ty agent-native. Spec: docs/m2e-agent-native-company.md.

M2e.2 luật cứng: ``company_rules`` (luật cưỡng chế theo công ty / chức danh) + ``rule_violations`` (nhật ký vi phạm
do guard plugin trên gateway hoặc cổng MCP báo về)."""
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CompanyRule(Base):
    """Một luật cứng. ``position_id`` NULL = áp cho mọi ghế của công ty.

    kind:   phrase (cụm từ cấm) | regex | tool (công cụ cấm) | approval (công cụ phải có người duyệt) | pii (dữ liệu
            cá nhân không ra ngoài: phone / email / cccd / card)
    action: revise (bắt viết lại trước khi chốt) | block (chặn gửi / chặn gọi tool) | scrub (che chữ khi gửi ra kênh)
            | approve (tool chờ người duyệt)
    source: manual | charter (thực thi một điều cấm trong hiến chương, ``source_ref`` = chỉ số điều cấm) | template."""
    __tablename__ = "company_rules"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    position_id: Mapped[int | None] = mapped_column(ForeignKey("positions.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(16), default="phrase")
    pattern: Mapped[str] = mapped_column(Text, default="")
    action: Mapped[str] = mapped_column(String(16), default="revise")
    message: Mapped[str] = mapped_column(Text, default="")
    external_only: Mapped[bool] = mapped_column(Boolean, default=False)    # chỉ áp cho tin gửi ra ngoài (kênh, A2A)
    source: Mapped[str] = mapped_column(String(16), default="manual")
    source_ref: Mapped[str] = mapped_column(String(64), default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class RuleViolation(Base):
    """Một lần luật cứng bắt được. ``hook``: before_agent_finalize | message_sending | before_tool_call | mcp.
    ``excerpt`` đã che dữ liệu cá nhân, ≤ 300 ký tự."""
    __tablename__ = "rule_violations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"), nullable=True, index=True)
    member_id: Mapped[int | None] = mapped_column(ForeignKey("members.id"), nullable=True, index=True)
    rule_id: Mapped[int | None] = mapped_column(ForeignKey("company_rules.id"), nullable=True, index=True)
    agent_rid: Mapped[str] = mapped_column(String(120), default="")
    session_key: Mapped[str] = mapped_column(String(240), default="")
    run_id: Mapped[str] = mapped_column(String(120), default="")
    hook: Mapped[str] = mapped_column(String(40), default="")
    action_taken: Mapped[str] = mapped_column(String(16), default="")
    excerpt: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


# ------------------------------------------------------------------ M2e.3 hợp đồng dữ liệu vào/ra

class IoContract(Base):
    """Hợp đồng dữ liệu: schema vào, schema ra (tập con JSON Schema), tiêu chí nghiệm thu. Gắn một chức danh
    (đầu ra chuẩn của ghế, biên dịch vào AGENTS.md) và/hoặc nhiều bước quy trình (``process_steps.contract_id``).
    ``acceptance`` = [{text, field?, op?, value?}] — có field/op thì máy kiểm, chỉ có text thì người review đọc.
    ``outcome_field`` = trường của đầu ra được ghi làm kết quả bước (``step<N>.outcome``)."""
    __tablename__ = "io_contracts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    position_id: Mapped[int | None] = mapped_column(ForeignKey("positions.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    input_schema: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    output_schema: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    acceptance: Mapped[list | None] = mapped_column(JSON, nullable=True)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    outcome_field: Mapped[str] = mapped_column(String(80), default="")
    template_key: Mapped[str] = mapped_column(String(64), default="")
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(16), default="active")       # active | archived
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class TaskContract(Base):
    """Hợp đồng của MỘT việc: ảnh chụp schema/tiêu chí lúc giao (sửa hợp đồng sau đó không đổi luật của việc đang
    chạy), dữ liệu vào, số lần nộp. status: open | accepted | escalated."""
    __tablename__ = "task_contracts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), unique=True)
    contract_id: Mapped[int | None] = mapped_column(ForeignKey("io_contracts.id"), nullable=True, index=True)
    contract_version: Mapped[int] = mapped_column(Integer, default=1)
    name: Mapped[str] = mapped_column(String(200), default="")
    output_schema: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    acceptance: Mapped[list | None] = mapped_column(JSON, nullable=True)
    outcome_field: Mapped[str] = mapped_column(String(80), default="")
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    input_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    input_errors: Mapped[list | None] = mapped_column(JSON, nullable=True)
    step_run_id: Mapped[int | None] = mapped_column(ForeignKey("process_step_runs.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="open")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_errors: Mapped[list | None] = mapped_column(JSON, nullable=True)
    accepted_output_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    escalated_to_member_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class TaskOutput(Base):
    """Một lần nộp kết quả cho một việc có hợp đồng. ``valid`` + ``errors`` là kết quả kiểm máy (schema + tiêu chí
    có field). Tỷ lệ đạt chuẩn của ghế / chức danh tính từ bảng này."""
    __tablename__ = "task_outputs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"), nullable=True, index=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), index=True)
    contract_id: Mapped[int | None] = mapped_column(ForeignKey("io_contracts.id"), nullable=True, index=True)
    member_id: Mapped[int | None] = mapped_column(ForeignKey("members.id"), nullable=True, index=True)
    position_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    output_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    valid: Mapped[bool] = mapped_column(Boolean, default=False)
    errors: Mapped[list | None] = mapped_column(JSON, nullable=True)
    via: Mapped[str] = mapped_column(String(16), default="api")          # mcp | api | runtime
    run_id: Mapped[str] = mapped_column(String(120), default="")
    session_key: Mapped[str] = mapped_column(String(240), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
