"""M5b việc 9 — lỗ hổng kiến thức, khoá học, ghi danh/chứng chỉ của agent."""
from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class KnowledgeGap(Base):
    __tablename__ = "knowledge_gaps"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    member_id: Mapped[int | None] = mapped_column(ForeignKey("members.id"), nullable=True, index=True)
    question: Mapped[str] = mapped_column(Text)
    question_key: Mapped[str] = mapped_column(String(64), index=True, default="")
    source: Mapped[str] = mapped_column(String(24), default="search")   # search | report | exam
    task_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    count: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(16), default="open", index=True)   # open | resolved | dismissed
    resolved_document_id: Mapped[int | None] = mapped_column(ForeignKey("knowledge_documents.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Course(Base):
    __tablename__ = "courses"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(220))
    goal: Mapped[str] = mapped_column(Text, default="")
    document_ids: Mapped[list] = mapped_column(JSON, default=list)          # module = 1 tài liệu, theo thứ tự
    study_hour: Mapped[int | None] = mapped_column(Integer, nullable=True)  # giờ học hằng ngày (theo study_tz)
    study_tz: Mapped[str] = mapped_column(String(64), default="Asia/Ho_Chi_Minh")
    pass_score: Mapped[int] = mapped_column(Integer, default=80)
    quiz: Mapped[list] = mapped_column(JSON, default=list)                  # [{question, options[4], answer, document_id}]
    status: Mapped[str] = mapped_column(String(16), default="active")       # active | archived
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class CourseEnrollment(Base):
    __tablename__ = "course_enrollments"
    __table_args__ = (UniqueConstraint("course_id", "agent_id", name="uq_course_enrollments_course_agent"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), index=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id"), index=True)
    module_index: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="learning", index=True)  # learning | exam | passed | failed | stale
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    certified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_session_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    log: Mapped[list] = mapped_column(JSON, default=list)
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
