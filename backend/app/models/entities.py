from datetime import date, datetime
from sqlalchemy import JSON, String, Integer, DateTime, Date, ForeignKey, Text, Float, Boolean
from sqlalchemy.dialects.postgresql import JSONB
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
    # D3.1 (0024): hướng dẫn phòng — trưởng phòng đọc khi định tuyến việc.
    guide: Mapped[str] = mapped_column(Text, default="")

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
    # M2b (0038): chức danh mà người/agent này đang ngồi. NULL = chưa xếp ghế.
    position_id: Mapped[int | None] = mapped_column(ForeignKey("positions.id"), nullable=True, index=True)

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
    # v36: hạn chót. Nullable vì phần lớn dự án cũ không có hạn, và "chưa đặt
    # hạn" là một câu trả lời hợp lệ — khác hẳn với một ngày mặc định nào đó.
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)

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
    # D1.3 (0018_task_graph): task biết nó phục vụ mục tiêu nào và nằm dưới
    # task nào. Không có hai cột này thì agent không trả lời được "vì sao làm
    # việc này" — gói ngữ cảnh chỉ có dự án.
    parent_task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id"), nullable=True, index=True)
    goal_id: Mapped[int | None] = mapped_column(ForeignKey("executive_goals.id"), nullable=True, index=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    acceptance_criteria: Mapped[str] = mapped_column(Text, default="")
    # D1.4 (0019_task_runs): lượt chạy đang giữ task. Chỉ đổi qua
    # task_lifecycle.checkout/release bằng một UPDATE có điều kiện, nên hai
    # agent không thể cùng nhận một việc. Không khai FK để tránh vòng
    # tasks <-> task_runs khi create_all.
    checkout_run_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    # D2.2 (0022_execution_policy): các chặng phải qua trước khi việc được
    # "done" ({"stages": [{"type": "review"|"approval", "participants": [id]}]})
    # và vị trí hiện tại trên các chặng đó. Chỉ services/execution_policy.py ghi.
    execution_policy: Mapped[dict | None] = mapped_column(JSON().with_variant(JSONB(), "postgresql"), nullable=True)
    execution_state: Mapped[dict | None] = mapped_column(JSON().with_variant(JSONB(), "postgresql"), nullable=True)
    # D3.1 (0024_department_routing): việc giao cho phòng ban; trưởng phòng
    # được đánh thức (lý do ``routed``) để chọn người. Chỉ services/routing.py ghi.
    assignee_department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id"), nullable=True, index=True)
    # M2d.2 (0045_kpi_history): lúc việc chuyển sang "done" — mốc "xong trong kỳ" của KPI/giao ban
    # (trước đó dùng updated_at, lệch khi việc đã xong bị sửa lại). Ghi bởi listener bên dưới cho MỌI
    # đường đổi trạng thái qua ORM; rời "done" (mở lại) thì xoá.
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)

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
    # M5b việc 9: nguồn đồng bộ + khoá trùng + phạm vi riêng một agent.
    source_url: Mapped[str] = mapped_column(String(1000), default="", server_default="")
    content_hash: Mapped[str] = mapped_column(String(64), default="", server_default="", index=True)
    synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    agent_id: Mapped[int | None] = mapped_column(ForeignKey("agents.id"), nullable=True, index=True)
    # Kiến thức cốt lõi (luôn nằm trong AGENTS.md của seat) + lớp nghề nghiệp (chức danh chứa chữ này).
    is_core: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    role_keyword: Mapped[str] = mapped_column(String(120), default="", server_default="")
    # M3a (0053_document_library): sổ tài liệu chuẩn — loại, lớp (document/record), chủ, đối tượng, nhạy cảm,
    # cách agent dùng, vòng đời, phiên bản, hiệu lực/rà soát, tệp gốc, lưu trữ. Nội dung ở ``content`` luôn là
    # BẢN ĐÃ BAN HÀNH (agent chỉ đọc bản này); bản nháp / chờ duyệt nằm ở knowledge_document_versions.
    doc_code: Mapped[str] = mapped_column(String(40), default="", server_default="", index=True)
    doc_class: Mapped[str] = mapped_column(String(16), default="document", server_default="document")
    doc_type: Mapped[str] = mapped_column(String(40), default="other", server_default="other", index=True)
    owner_position_id: Mapped[int | None] = mapped_column(ForeignKey("positions.id"), nullable=True)
    owner_member_id: Mapped[int | None] = mapped_column(ForeignKey("members.id"), nullable=True)
    audience: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    sensitivity: Mapped[str] = mapped_column(String(32), default="internal", server_default="internal")
    agent_use: Mapped[str] = mapped_column(String(16), default="retrieve", server_default="retrieve")
    customer_facing: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    lease_shareable: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    exportable: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    status: Mapped[str] = mapped_column(String(16), default="published", server_default="published", index=True)
    version_no: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    current_version_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    effective_from: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    effective_to: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    review_interval_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    review_due_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    review_notified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("members.id"), nullable=True)
    supersedes_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_of_truth: Mapped[str] = mapped_column(String(80), default="internal", server_default="internal")
    file_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    retention_class: Mapped[str] = mapped_column(String(32), default="", server_default="")
    retain_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    legal_hold: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    reuse_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # M3b (0054): bản tóm tắt cốt lõi (biên dịch vào AGENTS.md thay vì cắt cụt nội dung)
    core_summary: Mapped[str] = mapped_column(Text, default="", server_default="")
    flag_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

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
    # D3.5 (0025_inbox_escalation): hạn duyệt và người nhận khi quá hạn.
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    escalate_to_member_id: Mapped[int | None] = mapped_column(ForeignKey("members.id"), nullable=True)
    escalated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # D3.3: kế hoạch chiến lược (action='strategy') — nội dung có cấu trúc + số lần sửa.
    payload: Mapped[dict | None] = mapped_column(JSON().with_variant(JSONB(), "postgresql"), nullable=True)
    revision: Mapped[int] = mapped_column(Integer, default=1, server_default="1")


from sqlalchemy import event as _sa_event  # noqa: E402


@_sa_event.listens_for(Task.status, "set")
def _task_completed_at(target, value, oldvalue, initiator):  # noqa: ARG001
    if value == "done" and oldvalue != "done":
        target.completed_at = datetime.utcnow()
    elif value != "done" and oldvalue == "done":
        target.completed_at = None
