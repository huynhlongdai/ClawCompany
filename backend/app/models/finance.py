"""M3j — tài chính kinh doanh ĐƠN GIẢN của doanh nghiệp người dùng (sổ thu chi + ngân sách theo tháng). KHÔNG phải sổ kế toán
theo chế độ kế toán (TT 133/2016, TT 200/2014) — không thay phần mềm kế toán / kế toán viên. Spec:
docs/company-knowledge-library-and-gaps.md §B7, §C M3j.

Tiền: VND (tiền kinh doanh của khách Việt) — chi phí nền tảng (model, ghế) vẫn USD ở ``cost_ledger`` / ``budget_envelopes`` và
KHÔNG quy đổi trộn vào đây. Dòng USD được ghi nhưng báo cáo lãi lỗ tách theo tiền tệ."""
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class FinCategory(Base):
    __tablename__ = "fin_categories"
    __table_args__ = (UniqueConstraint("company_id", "kind", "name", name="uq_fin_category_name"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    kind: Mapped[str] = mapped_column(String(8))                 # income | expense
    key: Mapped[str] = mapped_column(String(40), default="")    # mã mặc định (UI dịch); "" = do công ty tự đặt
    name: Mapped[str] = mapped_column(String(120))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class FinEntry(Base):
    __tablename__ = "fin_entries"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    kind: Mapped[str] = mapped_column(String(8))
    category_id: Mapped[int] = mapped_column(ForeignKey("fin_categories.id"), index=True)
    amount: Mapped[float] = mapped_column(Numeric(18, 2))
    currency: Mapped[str] = mapped_column(String(3), default="VND")
    occurred_on: Mapped[date] = mapped_column(Date, index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    department_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    partner_id: Mapped[int | None] = mapped_column(Integer, nullable=True)      # M3h
    contact_id: Mapped[int | None] = mapped_column(Integer, nullable=True)      # M3g
    contract_id: Mapped[int | None] = mapped_column(Integer, nullable=True)     # M3h
    product_id: Mapped[int | None] = mapped_column(Integer, nullable=True)      # M3f (bán hàng)
    quantity: Mapped[float | None] = mapped_column(Numeric(14, 3), nullable=True)
    document_id: Mapped[int | None] = mapped_column(Integer, nullable=True)     # chứng từ (record M3a)
    status: Mapped[str] = mapped_column(String(8), default="recorded")         # recorded | void
    void_reason: Mapped[str] = mapped_column(Text, default="")
    voided_by_member_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source: Mapped[str] = mapped_column(String(12), default="manual")
    created_by_member_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class FinBudget(Base):
    __tablename__ = "fin_budgets"
    __table_args__ = (UniqueConstraint("company_id", "category_id", "department_id", "period", name="uq_fin_budget"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("fin_categories.id"), index=True)
    department_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    period: Mapped[str] = mapped_column(String(7))               # YYYY-MM
    amount: Mapped[float] = mapped_column(Numeric(18, 2))        # VND
    alert_pct: Mapped[int] = mapped_column(Integer, default=80)
    alerted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_by_member_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


__all__ = ["FinCategory", "FinEntry", "FinBudget"]
