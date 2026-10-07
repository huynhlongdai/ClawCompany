"""M2 — lời mời vào tổ chức. Token chỉ lưu sha256; link mời hết hạn sau 7 ngày."""
from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base

__all__ = ["Invitation"]


class Invitation(Base):
    __tablename__ = "invitations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"), nullable=True)
    department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id"), nullable=True)
    manager_member_id: Mapped[int | None] = mapped_column(ForeignKey("members.id"), nullable=True)
    # Ghế người đã có sẵn (vd. nhập từ CSV): nhận lời mời thì gắn user vào ghế này.
    member_id: Mapped[int | None] = mapped_column(ForeignKey("members.id"), nullable=True)
    email: Mapped[str] = mapped_column(String(240), index=True)
    display_name: Mapped[str] = mapped_column(String(160), default="")
    role: Mapped[str] = mapped_column(String(24), default="member")        # quyền trong tổ chức
    job_title: Mapped[str] = mapped_column(String(160), default="")        # chức danh trên sơ đồ
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(24), default="pending", index=True)  # pending|accepted|revoked
    invited_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    accepted_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
