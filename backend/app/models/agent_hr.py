"""M3 — bản ClawCompany của 5 file hồ sơ agent.

Mỗi lần ClawCompany ghi (hoặc chấp nhận) một file bootstrap trên gateway, nó lưu
nội dung + hash ở đây. Hash trên gateway khác hash này nghĩa là file đã bị sửa
ngoài ClawCompany (tay trên máy gateway, hoặc chính agent tự sửa) → UI báo lệch
và cho "Đồng bộ lại" theo một trong hai chiều."""
from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base

__all__ = ["AgentFileSnapshot"]


class AgentFileSnapshot(Base):
    __tablename__ = "agent_file_snapshots"
    __table_args__ = (UniqueConstraint("agent_id", "name", name="uq_agent_file_snapshots_agent_name"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id"), index=True)
    name: Mapped[str] = mapped_column(String(40))
    content: Mapped[str] = mapped_column(Text, default="")
    hash: Mapped[str] = mapped_column(String(80), default="")
    # clawcompany | gateway_accepted | archived_on_retire
    source: Mapped[str] = mapped_column(String(24), default="clawcompany")
    updated_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
