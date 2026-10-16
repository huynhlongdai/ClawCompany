"""R2 — cho thuê agent (ghế). Spec: docs/r-rental-and-multi-company.md §R2.

``seat_leases``: hợp đồng thuê giữa bên cho thuê (tổ chức/công ty + ghế agent nguồn + phiên bản hồ sơ) và bên thuê
(tổ chức/công ty + chức danh ở công ty bên thuê). Khi bên thuê nhận lời (mã chào thuê), hệ thống tuyển một ghế agent
MỚI trong công ty bên thuê (workspace, bộ nhớ, phiên riêng) và gắn ``renter_member_id``. Chính sách xếp lớp: sàn của
bên cho thuê (không ghi đè) + lớp bên thuê (chỉ thêm/siết).

``lease_usage``: từng dòng đo đếm của một hợp đồng (lượt model thật, phí theo việc / giờ / tháng) với chi phí thật
(``cost_usd``) và số tiền tính cho bên thuê (``billed_usd`` = chi phí × (1 + markup) hoặc giá cố định)."""
from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

LEASE_STATUSES = ("draft", "active", "suspended", "ended")


class SeatLease(Base):
    __tablename__ = "seat_leases"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    offer_code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(16), default="draft", index=True)
    status_reason: Mapped[str] = mapped_column(Text, default="")
    # bên cho thuê
    provider_org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    provider_company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    provider_member_id: Mapped[int] = mapped_column(ForeignKey("members.id"), index=True)
    provider_agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id"), index=True)
    provider_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # bên thuê (điền khi nhận lời)
    renter_org_id: Mapped[int | None] = mapped_column(ForeignKey("organizations.id"), nullable=True, index=True)
    renter_company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"), nullable=True, index=True)
    renter_position_id: Mapped[int | None] = mapped_column(ForeignKey("positions.id"), nullable=True)
    renter_member_id: Mapped[int | None] = mapped_column(ForeignKey("members.id"), nullable=True, index=True)
    renter_agent_id: Mapped[int | None] = mapped_column(ForeignKey("agents.id"), nullable=True, index=True)
    # thời hạn
    starts_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    offer_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # giá (USD)
    price_per_task_usd: Mapped[float] = mapped_column(Float, default=0.0)
    price_per_hour_usd: Mapped[float] = mapped_column(Float, default=0.0)
    price_per_month_usd: Mapped[float] = mapped_column(Float, default=0.0)
    markup_pct: Mapped[float] = mapped_column(Float, default=0.0)
    monthly_cost_cap_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    # sàn của bên cho thuê
    allowed_tools: Mapped[list | None] = mapped_column(JSON, nullable=True)      # None/[] = theo chức danh nguồn
    knowledge_scope: Mapped[dict | None] = mapped_column(JSON, nullable=True)    # {"doc_ids": [...]}
    data_handling: Mapped[str] = mapped_column(Text, default="")
    # ai duyệt / ai trả (mặc định: business=renter, policy=provider, payer=renter)
    approval_policy: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    change_requests: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    accepted_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    wiped_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    wipe_report: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class LeaseUsage(Base):
    __tablename__ = "lease_usage"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lease_id: Mapped[int] = mapped_column(ForeignKey("seat_leases.id"), index=True)
    kind: Mapped[str] = mapped_column(String(16))          # model | task_fee | hour_fee | month_fee
    period: Mapped[str] = mapped_column(String(7), index=True)   # YYYY-MM (UTC)
    usage_event_id: Mapped[int | None] = mapped_column(ForeignKey("usage_events.id"), nullable=True, index=True)
    task_run_id: Mapped[int | None] = mapped_column(ForeignKey("task_runs.id"), nullable=True, index=True)
    task_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    session_key: Mapped[str] = mapped_column(String(200), default="")
    channel: Mapped[str] = mapped_column(String(16), default="task")   # task | a2a | portal | chat
    caller: Mapped[str] = mapped_column(String(200), default="")
    quantity: Mapped[float] = mapped_column(Float, default=1.0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    billed_usd: Mapped[float] = mapped_column(Float, default=0.0)
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
