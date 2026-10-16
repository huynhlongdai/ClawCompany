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


__all__ = ["DocumentVersion", "DocumentLink", "DocumentFile", "VERSION_STATUSES"]
