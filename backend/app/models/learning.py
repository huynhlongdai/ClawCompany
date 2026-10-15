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


class CompanySkill(Base):
    """M5b việc 10 — một kỹ năng trong thư viện công ty (nội dung nằm ở các phiên bản)."""
    __tablename__ = "company_skills"
    __table_args__ = (UniqueConstraint("organization_id", "slug", name="uq_company_skills_org_slug"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    slug: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(220), default="")
    status: Mapped[str] = mapped_column(String(16), default="active")   # active | retired
    current_version_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class CompanySkillVersion(Base):
    __tablename__ = "company_skill_versions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    skill_id: Mapped[int] = mapped_column(ForeignKey("company_skills.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    description: Mapped[str] = mapped_column(String(160), default="")
    content: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(16), default="manual")    # manual | workshop
    origin_agent_id: Mapped[int | None] = mapped_column(ForeignKey("agents.id"), nullable=True)
    workshop_proposal_id: Mapped[str] = mapped_column(String(160), default="", index=True)
    workshop_revision_hash: Mapped[str] = mapped_column(String(80), default="")
    scan: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    eval_cases: Mapped[list] = mapped_column(JSON, default=list)          # [{prompt, must_include[], must_not_include[]}]
    eval_report: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="draft", index=True)  # draft|in_review|approved|rejected|superseded
    approval_id: Mapped[int | None] = mapped_column(ForeignKey("approvals.id"), nullable=True)
    note: Mapped[str] = mapped_column(Text, default="")
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class CompanySkillInstall(Base):
    __tablename__ = "company_skill_installs"
    __table_args__ = (UniqueConstraint("skill_id", "agent_id", name="uq_company_skill_installs_skill_agent"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    skill_id: Mapped[int] = mapped_column(ForeignKey("company_skills.id"), index=True)
    version_id: Mapped[int] = mapped_column(ForeignKey("company_skill_versions.id"))
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id"), index=True)
    status: Mapped[str] = mapped_column(String(16), default="installed")   # installed | failed
    error: Mapped[str] = mapped_column(Text, default="")
    installed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
