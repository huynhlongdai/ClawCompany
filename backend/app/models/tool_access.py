"""D1.6 — quyền dùng tool của seat agent, ba mức ``allowed | ask | off``.

Hàng gắn ``member_id`` thắng hàng gắn ``role`` (bậc seat: ``lead`` /
``executor``), hàng gắn role thắng mặc định trong code. Bảng ở migration
``0020_tool_permissions``.
"""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

TOOL_LEVELS = ("allowed", "ask", "off")


class ToolPermission(Base):
    __tablename__ = "tool_permissions"
    __table_args__ = (UniqueConstraint("organization_id", "role", "member_id", "tool",
                                       name="uq_tool_permission"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    role: Mapped[str | None] = mapped_column(String(32), nullable=True)
    member_id: Mapped[int | None] = mapped_column(ForeignKey("members.id"), nullable=True, index=True)
    tool: Mapped[str] = mapped_column(String(80), index=True)
    level: Mapped[str] = mapped_column(String(16), default="off")
    updated_by_member_id: Mapped[int | None] = mapped_column(ForeignKey("members.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow,
                                                 onupdate=datetime.utcnow)
