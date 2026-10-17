"""Giọng thương hiệu (brand voice) — văn bản có cấu trúc theo phiên bản + giọng nói (TTS) theo công ty.
Spec: _reports/brand-voice.md. Migration 0065_brand_voice."""
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, LargeBinary, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class BrandVoice(Base):
    """Một PHIÊN BẢN giọng văn bản của một công ty. draft → in_review → published (bản trước → archived) | rejected.
    Bản đã rời nháp không sửa được (sửa = bản nháp mới). Chỉ bản ``published`` được biên dịch vào AGENTS.md và dùng để chấm."""
    __tablename__ = "brand_voices"
    __table_args__ = (UniqueConstraint("company_id", "version_no", name="uq_brand_voice_version"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    version_no: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(16), default="draft", index=True)
    spec: Mapped[dict] = mapped_column(JSON, default=dict)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    change_note: Mapped[str] = mapped_column(Text, default="")
    review_note: Mapped[str] = mapped_column(Text, default="")
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    submitted_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    decided_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class BrandVoiceSettings(Base):
    """Cách cưỡng chế của công ty (không theo phiên bản — đổi không cần ban hành lại)."""
    __tablename__ = "brand_voice_settings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), unique=True, index=True)
    enforcement: Mapped[str] = mapped_column(String(12), default="flag")      # off | flag | rework
    min_score: Mapped[float] = mapped_column(Float, default=0.7)
    model_check: Mapped[bool] = mapped_column(Boolean, default=False)         # chấm giọng bằng model (tốn quota)
    eval_suite_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class VoiceCheck(Base):
    """Một lần chấm giọng (tất định, có thể kèm chấm bằng model)."""
    __tablename__ = "voice_checks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    member_id: Mapped[int | None] = mapped_column(ForeignKey("members.id"), nullable=True, index=True)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id"), nullable=True, index=True)
    task_output_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source: Mapped[str] = mapped_column(String(16), default="try")            # try | submit_output | review | eval
    channel: Mapped[str] = mapped_column(String(16), default="zalo")
    segment: Mapped[str] = mapped_column(String(40), default="")
    voice_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    voice_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    lease_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    score: Mapped[float] = mapped_column(Float, default=1.0)
    passed: Mapped[bool] = mapped_column(Boolean, default=True)
    action: Mapped[str] = mapped_column(String(12), default="none")          # none | flag | rework
    violations: Mapped[list | None] = mapped_column(JSON, nullable=True)
    model_result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    text_excerpt: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class VoiceProfile(Base):
    """Giọng nói của công ty (một hàng / công ty): nhà cung cấp TTS, giọng, tốc độ, kịch bản chào/kết cuộc gọi."""
    __tablename__ = "voice_profiles"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), unique=True, index=True)
    provider: Mapped[str] = mapped_column(String(24), default="cometapi")
    model: Mapped[str] = mapped_column(String(64), default="gpt-4o-mini-tts")
    voice_name: Mapped[str] = mapped_column(String(64), default="nova")
    language: Mapped[str] = mapped_column(String(16), default="vi-VN")
    speed: Mapped[float] = mapped_column(Float, default=1.0)
    pitch: Mapped[str] = mapped_column(String(16), default="medium")         # low | medium | high (gợi ý cho model)
    style: Mapped[str] = mapped_column(Text, default="")
    greeting_script: Mapped[str] = mapped_column(Text, default="")
    closing_script: Mapped[str] = mapped_column(Text, default="")
    sample_text: Mapped[str] = mapped_column(Text, default="")
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class VoiceSample(Base):
    """Một lần "Nghe thử": văn bản gốc, văn bản đã áp từ điển phát âm, và file âm thanh (hoặc lỗi thật của nhà cung cấp)."""
    __tablename__ = "voice_samples"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    provider: Mapped[str] = mapped_column(String(24), default="")
    model: Mapped[str] = mapped_column(String(64), default="")
    voice_name: Mapped[str] = mapped_column(String(64), default="")
    settings: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    text_in: Mapped[str] = mapped_column(Text, default="")
    text_spoken: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(12), default="ok")            # ok | error
    error: Mapped[str] = mapped_column(Text, default="")
    mime: Mapped[str] = mapped_column(String(40), default="audio/mpeg")
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    sha256: Mapped[str] = mapped_column(String(64), default="")
    audio: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
