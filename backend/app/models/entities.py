from datetime import datetime
from sqlalchemy import String, Integer, DateTime, ForeignKey, Text, Float, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base

class RevisionMixin:
    # v30: monotonic counter bumped by guarded writes. Nullable because
    # rows written before migration 0013 have no counter, and those must
    # fall back to the v27 timestamp token rather than claim exactness.
    row_revision: Mapped[int | None] = mapped_column(Integer, nullable=True, default=1)

class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Organization(Base, TimestampMixin):
    __tablename__ = "organizations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    slug: Mapped[str] = mapped_column(String(160), unique=True, index=True)

class Company(Base, TimestampMixin, RevisionMixin):
    __tablename__ = "companies"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    industry: Mapped[str] = mapped_column(String(120), default="")
    status: Mapped[str] = mapped_column(String(32), default="active")

class Department(Base, TimestampMixin, RevisionMixin):
    __tablename__ = "departments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    head_member_id: Mapped[int | None] = mapped_column(ForeignKey("members.id"), nullable=True)
    access_level: Mapped[str] = mapped_column(String(32), default="restricted")
    # v31: departments were the only node in the org tree with no status
    # column, so v29 archived them by flipping access_level to
    # "confidential" -- overloading a permission field to mean "closed".
    status: Mapped[str] = mapped_column(String(32), default="active")

class Member(Base, TimestampMixin, RevisionMixin):
    __tablename__ = "members"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"), nullable=True, index=True)
    department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    member_type: Mapped[str] = mapped_column(String(24))  # human | agent
    role: Mapped[str] = mapped_column(String(160), default="")
    manager_id: Mapped[int | None] = mapped_column(ForeignKey("members.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="active")

class Agent(Base, TimestampMixin):
    __tablename__ = "agents"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id"), unique=True, index=True)
    runtime_provider: Mapped[str] = mapped_column(String(32), default="openclaw")
    runtime_agent_id: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    lifecycle: Mapped[str] = mapped_column(String(32), default="active")
    model: Mapped[str] = mapped_column(String(120), default="")
    success_rate: Mapped[float] = mapped_column(Float, default=0.0)
    cost_30d: Mapped[float] = mapped_column(Float, default=0.0)
    risk: Mapped[str] = mapped_column(String(32), default="low")

class Project(Base, TimestampMixin, RevisionMixin):
    __tablename__ = "projects"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    owner_member_id: Mapped[int | None] = mapped_column(ForeignKey("members.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="planning")
    progress: Mapped[int] = mapped_column(Integer, default=0)

class Task(Base, TimestampMixin, RevisionMixin):
    __tablename__ = "tasks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    title: Mapped[str] = mapped_column(String(220))
    description: Mapped[str] = mapped_column(Text, default="")
    assignee_member_id: Mapped[int | None] = mapped_column(ForeignKey("members.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="backlog")
    priority: Mapped[str] = mapped_column(String(24), default="medium")
    runtime_task_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    runtime_run_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    runtime_session_key: Mapped[str | None] = mapped_column(String(200), nullable=True)

class KnowledgeDocument(Base, TimestampMixin):
    __tablename__ = "knowledge_documents"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"), nullable=True, index=True)
    department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id"), nullable=True, index=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(220))
    source_type: Mapped[str] = mapped_column(String(64), default="upload")
    access_level: Mapped[str] = mapped_column(String(32), default="restricted")
    content: Mapped[str] = mapped_column(Text, default="")
    indexed: Mapped[bool] = mapped_column(Boolean, default=False)

class Approval(Base, TimestampMixin):
    __tablename__ = "approvals"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"), nullable=True)
    requester_member_id: Mapped[int | None] = mapped_column(ForeignKey("members.id"), nullable=True)
    approver_member_id: Mapped[int | None] = mapped_column(ForeignKey("members.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(220))
    risk: Mapped[str] = mapped_column(String(24), default="medium")
    policy_key: Mapped[str] = mapped_column(String(120), default="")
    status: Mapped[str] = mapped_column(String(24), default="pending")
    evidence: Mapped[str] = mapped_column(Text, default="")
    resolution_note: Mapped[str] = mapped_column(Text, default="")