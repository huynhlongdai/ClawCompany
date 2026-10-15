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
