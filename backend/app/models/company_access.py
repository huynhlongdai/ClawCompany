"""R1 — vai trò theo công ty + một người nhiều ghế. Spec: docs/r-rental-and-multi-company.md §R1.

``company_access``: vai trò của một user trong MỘT công ty (owner | manager | approver | viewer). User có ít nhất
một dòng active (và vai trò org dưới admin) thì bị GIỚI HẠN vào đúng các công ty đó; owner/admin của org luôn
thấy mọi công ty. ``user_seats``: user ↔ ghế (members), mỗi công ty tối đa một ghế; ``users.member_id`` giữ là
ghế chính (tương thích cũ) và cũng có một dòng ở đây."""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

COMPANY_ROLES = ("viewer", "approver", "manager", "owner")


class CompanyAccess(Base):
    __tablename__ = "company_access"
    __table_args__ = (UniqueConstraint("user_id", "company_id", name="uq_company_access_user_company"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    role: Mapped[str] = mapped_column(String(16), default="viewer")
    status: Mapped[str] = mapped_column(String(16), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class UserSeat(Base):
    __tablename__ = "user_seats"
    __table_args__ = (UniqueConstraint("user_id", "company_id", name="uq_user_seats_user_company"),
                      UniqueConstraint("member_id", name="uq_user_seats_member"))
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id"), index=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
