"""M3 — bản ClawCompany của 5 file hồ sơ agent.

Mỗi lần ClawCompany ghi (hoặc chấp nhận) một file bootstrap trên gateway, nó lưu
nội dung + hash ở đây. Hash trên gateway khác hash này nghĩa là file đã bị sửa
ngoài ClawCompany (tay trên máy gateway, hoặc chính agent tự sửa) → UI báo lệch
và cho "Đồng bộ lại" theo một trong hai chiều."""
from datetime import datetime
from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base

__all__ = ["AgentFileSnapshot", "AgentProfileVersion"]


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


class AgentProfileVersion(Base):
    """M5a — mỗi lần đổi hồ sơ (tính cách, mô tả việc, ghi chú quản lý, chức danh,
    phòng, quản lý, model) là một phiên bản. Khôi phục = áp lại hồ sơ của bản đó
    rồi sinh lại file, chứ không chép đè file cũ (file còn phụ thuộc tên công ty,
    quản lý hiện tại…). ``persona_*`` là kết quả "kiểm tra giữ vai" chạy trên bản này."""
    __tablename__ = "agent_profile_versions"
    __table_args__ = (UniqueConstraint("agent_id", "version", name="uq_agent_profile_versions_agent_version"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    profile_json: Mapped[str] = mapped_column(Text, default="{}")
    files_json: Mapped[str] = mapped_column(Text, default="{}")   # {tên file: hash} lúc chụp
    changed_json: Mapped[str] = mapped_column(Text, default="[]")
    note: Mapped[str] = mapped_column(String(300), default="")
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    persona_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    persona_report_json: Mapped[str] = mapped_column(Text, default="")
    persona_checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
