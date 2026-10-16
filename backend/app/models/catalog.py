"""M3f — sản phẩm/dịch vụ & bảng giá của DOANH NGHIỆP NGƯỜI DÙNG (khác bảng giá nền tảng). Spec:
docs/company-knowledge-library-and-gaps.md §B2, §C M3f.

``catalog_products``: mỗi dòng một sản phẩm/dịch vụ (mã SKU duy nhất trong công ty, đơn vị, trạng thái, chính sách riêng
như số ngày đổi trả / bảo hành, tài liệu mô tả ``product_sheet`` liên kết).
``catalog_prices``: LỊCH SỬ GIÁ — mỗi lần đổi giá là một dòng mới (không sửa dòng cũ): số tiền + tiền tệ (mặc định VND —
tiền kinh doanh của khách Việt; chi phí nền tảng vẫn USD), kênh, hiệu lực từ/đến, trạng thái duyệt qua ma trận
``price_change``. Giá đang áp dụng = dòng ``approved`` có hiệu lực tại thời điểm hỏi."""
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

PRODUCT_STATUSES = ("active", "draft", "discontinued")
PRICE_STATUSES = ("pending", "approved", "rejected", "cancelled")


class CatalogProduct(Base):
    __tablename__ = "catalog_products"
    __table_args__ = (UniqueConstraint("company_id", "sku", name="uq_catalog_product_sku"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    sku: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(220))
    description: Mapped[str] = mapped_column(Text, default="")
    kind: Mapped[str] = mapped_column(String(16), default="product")       # product | service
    category: Mapped[str] = mapped_column(String(120), default="")
    unit: Mapped[str] = mapped_column(String(32), default="cái")
    status: Mapped[str] = mapped_column(String(16), default="active")
    policies: Mapped[dict | None] = mapped_column(JSON, nullable=True)     # {return_days, warranty_months, note}
    document_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # tài liệu product_sheet (M3a)
    search_text: Mapped[str] = mapped_column(Text, default="")            # tên + mã + nhóm, bỏ dấu (tra cứu)
    created_by_member_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class CatalogPrice(Base):
    __tablename__ = "catalog_prices"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("catalog_products.id"), index=True)
    channel: Mapped[str] = mapped_column(String(32), default="default")
    amount: Mapped[float] = mapped_column(Numeric(16, 2))
    currency: Mapped[str] = mapped_column(String(3), default="VND")
    effective_from: Mapped[datetime] = mapped_column(DateTime)
    effective_to: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    previous_price_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    change_pct: Mapped[float | None] = mapped_column(Numeric(8, 2), nullable=True)   # so với giá đang áp dụng; None = giá mới
    risk: Mapped[str] = mapped_column(String(16), default="normal")
    note: Mapped[str] = mapped_column(Text, default="")
    approval_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    requested_by_member_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    approver_member_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    decided_by_member_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    review_note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


__all__ = ["CatalogProduct", "CatalogPrice", "PRODUCT_STATUSES", "PRICE_STATUSES"]
