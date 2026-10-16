"""M3a — thư viện tài liệu & hồ sơ công ty. Spec: docs/company-knowledge-library-and-gaps.md §A4–A5.

``knowledge_documents`` (entities.py) là SỔ TÀI LIỆU chuẩn: một dòng mỗi tài liệu, ``content`` = bản đã ban hành.
``knowledge_document_versions``: mọi phiên bản, BẤT BIẾN khi đã rời trạng thái nháp (sửa = tạo phiên bản mới).
``document_links``: tài liệu ↔ quy trình / bước / chức danh / SOP / hợp đồng dữ liệu / luật cứng.
``document_files``: tệp gốc (PDF/DOCX/MD…) + sha256, lưu trong DB (bytea trên Postgres) — tối đa 20 MB/tệp."""
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, LargeBinary, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

VERSION_STATUSES = ("draft", "in_review", "approved", "published", "superseded", "rejected")


class DocumentVersion(Base):
    __tablename__ = "knowledge_document_versions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("knowledge_documents.id"), index=True)
    version_no: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(16), default="draft", index=True)
    title: Mapped[str] = mapped_column(String(220), default="")
    content: Mapped[str] = mapped_column(Text, default="")
    content_hash: Mapped[str] = mapped_column(String(64), default="")
    file_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    change_note: Mapped[str] = mapped_column(Text, default="")
    author_member_id: Mapped[int | None] = mapped_column(ForeignKey("members.id"), nullable=True)
    author_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    approval_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    approver_member_id: Mapped[int | None] = mapped_column(ForeignKey("members.id"), nullable=True)
    approved_by_member_id: Mapped[int | None] = mapped_column(ForeignKey("members.id"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    review_note: Mapped[str] = mapped_column(Text, default="")
    effective_from: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # M3b (0054): tóm tắt cốt lõi của phiên bản + mâu thuẫn sự kiện phát hiện lúc gửi duyệt
    core_summary: Mapped[str] = mapped_column(Text, default="")
    conflicts: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class DocumentLink(Base):
    __tablename__ = "document_links"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("knowledge_documents.id"), index=True)
    target_type: Mapped[str] = mapped_column(String(32))     # process | process_step | position | sop | io_contract | company_rule | product
    target_id: Mapped[int] = mapped_column(Integer)
    note: Mapped[str] = mapped_column(String(300), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class DocumentFile(Base):
    __tablename__ = "document_files"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"), nullable=True, index=True)
    filename: Mapped[str] = mapped_column(String(300), default="")
    mime: Mapped[str] = mapped_column(String(120), default="application/octet-stream")
    size: Mapped[int] = mapped_column(Integer, default=0)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    data: Mapped[bytes] = mapped_column(LargeBinary)
    extracted_chars: Mapped[int] = mapped_column(Integer, default=0)
    meta: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class CompanyFact(Base):
    """M3b — sự kiện công ty có nguồn (khoá → giá trị): refund_window_days=7 ← CS-POL-003 v4 §2. Một khoá có một dòng
    ``active`` mỗi nguồn; hai nguồn khác giá trị cho cùng khoá = mâu thuẫn."""
    __tablename__ = "company_facts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    key: Mapped[str] = mapped_column(String(80), index=True)
    value: Mapped[str] = mapped_column(String(500), default="")
    value_num: Mapped[float | None] = mapped_column(nullable=True)
    unit: Mapped[str] = mapped_column(String(24), default="")
    source_kind: Mapped[str] = mapped_column(String(16), default="document")   # document | manual | structured
    source_doc_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    source_version_no: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_section: Mapped[str] = mapped_column(String(300), default="")
    excerpt: Mapped[str] = mapped_column(String(500), default="")
    status: Mapped[str] = mapped_column(String(16), default="active", index=True)   # active | superseded
    updated_by_member_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class DocumentFlag(Base):
    """M3b — agent/người đánh dấu tài liệu sai / cũ / mâu thuẫn / thiếu trường hợp (KCS "flag it")."""
    __tablename__ = "document_flags"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("knowledge_documents.id"), index=True)
    version_no: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reason: Mapped[str] = mapped_column(String(24))      # wrong | outdated | conflict | missing_case
    note: Mapped[str] = mapped_column(Text, default="")
    member_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    task_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="open", index=True)   # open | resolved | dismissed
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class DocumentRequirement(Base):
    """M3d — danh mục hồ sơ/tài liệu bắt buộc hoặc nên có, là DỮ LIỆU sửa được theo công ty (giống compliance_rules):
    điều kiện áp dụng (loại hình, số lao động là NGƯỜI, có xử lý dữ liệu cá nhân, ngành), mức, căn cứ pháp lý, cờ
    ``needs_review`` cho mục chưa đối chiếu văn bản gốc ("cần kiểm tra")."""
    __tablename__ = "document_requirements"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    key: Mapped[str] = mapped_column(String(64), default="")
    name: Mapped[str] = mapped_column(String(240))
    name_en: Mapped[str] = mapped_column(String(240), default="")
    pack: Mapped[str] = mapped_column(String(24), default="all")       # all | employees | personal_data | shop | agency | ketoan
    doc_types: Mapped[list | None] = mapped_column(JSON, nullable=True)
    condition: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # {entity_types, min_humans, max_humans, personal_data, templates}
    level: Mapped[str] = mapped_column(String(16), default="required")  # required | recommended
    legal_basis: Mapped[str] = mapped_column(Text, default="")
    note: Mapped[str] = mapped_column(Text, default="")
    needs_review: Mapped[bool] = mapped_column(default=False)
    enabled: Mapped[bool] = mapped_column(default=True)
    source: Mapped[str] = mapped_column(String(16), default="default")  # default | custom
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


__all__ = ["DocumentRequirement", "DocumentVersion", "DocumentLink", "DocumentFile", "CompanyFact", "DocumentFlag", "VERSION_STATUSES"]
