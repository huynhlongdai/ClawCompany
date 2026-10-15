"""M6 việc 12b — A2A: thuê agent bên ngoài (outbound) và mở agent của công ty cho bên ngoài (inbound)."""
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ExternalAgent(Base):
    """Agent ngoài công ty nói giao thức A2A (Agent Card + JSON-RPC ``message/send``)."""
    __tablename__ = "external_agents"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text, default="")
    card_url: Mapped[str] = mapped_column(String(1000), default="")
    endpoint_url: Mapped[str] = mapped_column(String(1000))
    auth_header: Mapped[str] = mapped_column(Text, default="")      # "Bearer xxx" — không bao giờ trả ra API
    skills: Mapped[list | None] = mapped_column(JSON, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    calls: Mapped[int] = mapped_column(Integer, default=0)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class A2AExposure(Base):
    """Một seat AI được mở cho bên ngoài gọi qua A2A, kèm khoá truy cập riêng (chỉ lưu hash)."""
    __tablename__ = "a2a_exposures"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id"), unique=True, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    token_prefix: Mapped[str] = mapped_column(String(24), default="")
    token_hash: Mapped[str] = mapped_column(String(128), default="")
    calls: Mapped[int] = mapped_column(Integer, default=0)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
