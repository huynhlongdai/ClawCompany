"""M2b — nền công ty: hồ sơ pháp nhân + hiến chương, chức danh (tách khỏi người ngồi),
ma trận phân quyền (DoA). Spec: docs/m2b-company-foundation.md."""
from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CompanyProfile(Base):
    """Một hàng / công ty. Phần pháp nhân để hiển thị và nhắc hạn; phần hiến chương
    được biên dịch vào lớp "Công ty" của tri thức cốt lõi trong AGENTS.md mọi seat."""
    __tablename__ = "company_profiles"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), unique=True, index=True)
    # pháp nhân
    legal_name: Mapped[str] = mapped_column(String(240), default="")
    entity_type: Mapped[str] = mapped_column(String(32), default="")
    tax_code: Mapped[str] = mapped_column(String(20), default="")
    legal_representative: Mapped[str] = mapped_column(String(160), default="")
    representative_title: Mapped[str] = mapped_column(String(120), default="")
    registered_address: Mapped[str] = mapped_column(String(400), default="")
    charter_capital_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    charter_capital_note: Mapped[str] = mapped_column(String(200), default="")
    business_lines: Mapped[list | None] = mapped_column(JSON, nullable=True)   # ["4791 — Bán lẻ qua internet", …]
    founded_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    # hiến chương
    mission: Mapped[str] = mapped_column(Text, default="")
    values: Mapped[list | None] = mapped_column(JSON, nullable=True)
    brand_voice: Mapped[str] = mapped_column(Text, default="")
    prohibitions: Mapped[list | None] = mapped_column(JSON, nullable=True)
    customer_promises: Mapped[list | None] = mapped_column(JSON, nullable=True)
    charter_version: Mapped[int] = mapped_column(Integer, default=0)
    # M2c D7 (0042): lựa chọn kê khai cho lịch tuân thủ — kỳ GTGT/TNCN, có lao động, chức danh kế toán…
    compliance: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # M3: đổi giá ≥ ngưỡng này (%) hoặc giá đầu tiên → rủi ro cao → chủ duyệt; NULL = catalog.HIGH_PCT (10)
    price_change_high_pct: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Position(Base):
    """Chức danh: một ghế trong sơ đồ, tồn tại kể cả khi chưa ai ngồi."""
    __tablename__ = "positions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(160))
    job_description: Mapped[str] = mapped_column(Text, default="")
    responsibilities: Mapped[list | None] = mapped_column(JSON, nullable=True)
    kpis: Mapped[list | None] = mapped_column(JSON, nullable=True)            # [{name, target, unit, period}]
    allowed_tools: Mapped[list | None] = mapped_column(JSON, nullable=True)   # tên tool company_*; rỗng = không giới hạn
    allowed_skills: Mapped[list | None] = mapped_column(JSON, nullable=True)
    headcount: Mapped[int] = mapped_column(Integer, default=1)
    reports_to_position_id: Mapped[int | None] = mapped_column(ForeignKey("positions.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class AuthorityRule(Base):
    """Một dòng của ma trận phân quyền: loại việc × dải tiền (USD) × mức rủi ro → người duyệt,
    và cấp tự chủ tối thiểu để một agent được tự làm không cần duyệt."""
    __tablename__ = "authority_rules"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    action_type: Mapped[str] = mapped_column(String(40), index=True)
    min_amount_usd: Mapped[float | None] = mapped_column(Float, nullable=True)   # dải [min, max)
    max_amount_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    min_risk: Mapped[str] = mapped_column(String(16), default="")               # "" = mọi mức
    approver_kind: Mapped[str] = mapped_column(String(24), default="manager")   # none|manager|department_head|position|owner
    approver_position_id: Mapped[int | None] = mapped_column(ForeignKey("positions.id"), nullable=True)
    agent_alone_level: Mapped[str] = mapped_column(String(16), default="")      # ""=không bao giờ | probation|standard|trusted
    note: Mapped[str] = mapped_column(String(400), default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    source: Mapped[str] = mapped_column(String(32), default="custom")           # default|template:<key>|custom
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


__all__ = ["CompanyProfile", "Position", "AuthorityRule"]
