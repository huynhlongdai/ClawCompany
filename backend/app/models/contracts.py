"""M3h — hợp đồng & đối tác của doanh nghiệp người dùng. Spec: docs/company-knowledge-library-and-gaps.md §B5, §C M3h.

``biz_partners``   nhà cung cấp / đối tác / khách doanh nghiệp / bên dịch vụ (MST, người liên hệ, đánh giá).
``biz_contracts``  sổ hợp đồng: bên, loại, giá trị (mặc định VND — tiền kinh doanh; chi phí nền tảng vẫn USD), hiệu lực, gia hạn tự
                   động + hạn báo trước, SLA có cấu trúc (agent đọc số từ đây, không đọc tệp ký), điều khoản chính, tệp ký là record
                   M3a (``document_id``), ký đi loại việc ``contract`` của ma trận thẩm quyền. Hạn báo trước / hết hạn → lịch tuân thủ
                   (``compliance_rules`` key ``contract_notice:<id>`` / ``contract_end:<id>``) + việc + Hộp việc ``contract_due``."""
from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

PARTNER_KINDS = ("supplier", "partner", "customer", "service")
CONTRACT_KINDS = ("purchase", "sale", "service", "lease", "nda", "partnership", "other")
CONTRACT_STATUSES = ("draft", "pending", "active", "expired", "terminated", "rejected")


class BizPartner(Base):
    __tablename__ = "biz_partners"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    kind: Mapped[str] = mapped_column(String(16), default="supplier")
    name: Mapped[str] = mapped_column(String(220))
    tax_code: Mapped[str] = mapped_column(String(20), default="")
    contact_person: Mapped[str] = mapped_column(String(160), default="")
    phone: Mapped[str] = mapped_column(String(40), default="")
    email: Mapped[str] = mapped_column(String(200), default="")
    address: Mapped[str] = mapped_column(Text, default="")
    rating: Mapped[int | None] = mapped_column(Integer, nullable=True)       # 1..5
    notes: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="active")       # active | inactive
    search_text: Mapped[str] = mapped_column(Text, default="")
    created_by_member_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class BizContract(Base):
    __tablename__ = "biz_contracts"
    __table_args__ = (UniqueConstraint("company_id", "code", name="uq_biz_contract_code"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    partner_id: Mapped[int | None] = mapped_column(ForeignKey("biz_partners.id"), nullable=True, index=True)
    code: Mapped[str] = mapped_column(String(48))
    title: Mapped[str] = mapped_column(String(220))
    kind: Mapped[str] = mapped_column(String(16), default="service")
    value_amount: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="VND")
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    auto_renew: Mapped[bool] = mapped_column(Boolean, default=False)
    renewal_months: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notice_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sla: Mapped[dict | None] = mapped_column(JSON, nullable=True)            # {response_hours, delivery_days, payment_days, warranty_months, penalty}
    key_terms: Mapped[str] = mapped_column(Text, default="")                 # tóm tắt điều khoản chính cho agent
    status: Mapped[str] = mapped_column(String(16), default="draft")
    document_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # bản ký (record M3a)
    owner_member_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    requested_by_member_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    approver_member_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    approval_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    decided_by_member_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    review_note: Mapped[str] = mapped_column(Text, default="")
    terminated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    notice_reminded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    end_reminded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


__all__ = ["BizPartner", "BizContract", "PARTNER_KINDS", "CONTRACT_KINDS", "CONTRACT_STATUSES"]
