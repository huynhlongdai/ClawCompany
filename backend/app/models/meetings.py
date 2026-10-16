"""M3i — họp & quyết định. Spec: docs/company-knowledge-library-and-gaps.md §B6, §C M3i (Luật DN 2020 Đ11 k1 điểm d: lưu biên bản
họp và các quyết định).

``meetings``         cuộc họp (HĐTV / ĐHĐCĐ / HĐQT / giao ban / tuần / khác), người dự, chương trình, ghi chú thô, biên bản
                     (nháp → chờ duyệt → đã duyệt = khoá sửa, lưu thành hồ sơ ``meeting_minutes`` M3a), nối giao ban/báo cáo tuần.
``meeting_actions``  việc sau họp → task thật (đúng người, có hạn), trạng thái theo task.
Quyết định nằm ở bảng ``decisions`` (đã có, mở rộng ở 0062)."""
from datetime import date, datetime

from sqlalchemy import JSON, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

MEETING_KINDS = ("members_council", "shareholders", "board", "standup", "weekly", "other")
MINUTES_STATUSES = ("draft", "in_review", "approved")


class Meeting(Base):
    __tablename__ = "meetings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    kind: Mapped[str] = mapped_column(String(24), default="other")
    title: Mapped[str] = mapped_column(String(220))
    held_at: Mapped[datetime] = mapped_column(DateTime)
    location: Mapped[str] = mapped_column(String(200), default="")
    chair_member_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    secretary_member_id: Mapped[int | None] = mapped_column(Integer, nullable=True)   # có thể là agent (soạn biên bản)
    attendee_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    guests: Mapped[str] = mapped_column(Text, default="")
    agenda: Mapped[str] = mapped_column(Text, default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    minutes: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="draft")
    rhythm_report_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    minutes_document_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    approver_member_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    approved_by_member_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_by_member_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class MeetingAction(Base):
    __tablename__ = "meeting_actions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    meeting_id: Mapped[int] = mapped_column(ForeignKey("meetings.id"), index=True)
    title: Mapped[str] = mapped_column(String(220))
    assignee_member_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    decision_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    task_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


__all__ = ["Meeting", "MeetingAction", "MEETING_KINDS", "MINUTES_STATUSES"]
