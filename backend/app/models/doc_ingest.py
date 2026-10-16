"""M3c — nạp & phân loại tài liệu. Spec: docs/company-knowledge-library-and-gaps.md §A7, §C M3c.

``doc_imports``: một dòng mỗi lần nạp (tệp, URL, Google Drive, Notion, mẫu) — kết quả trích chữ (có OCR không),
sha256 để chống trùng, ĐỀ XUẤT phân loại (loại/độ nhạy/agent_use/mã/hiệu lực) và đề xuất trích sự kiện (hồ sơ pháp nhân,
company_facts) — không ghi thẳng vào hồ sơ công ty. Tài liệu sinh ra luôn ở trạng thái nháp (``draft``) chờ duyệt.
``doc_sources``: nguồn đồng bộ theo công ty (url | gdrive | notion), token mã hoá (Fernet, khoá dẫn từ JWT_SECRET),
không bao giờ trả ra API. ``doc_source_items``: mục ngoài ↔ tài liệu thư viện + phiên bản ngoài (modifiedTime /
last_edited_time / sha256) để biết khi nào cần một bản nháp mới."""
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

IMPORT_SOURCES = ("upload", "url", "gdrive", "notion", "template")
SOURCE_KINDS = ("url", "gdrive", "notion")


class DocImport(Base):
    __tablename__ = "doc_imports"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    source: Mapped[str] = mapped_column(String(16), default="upload")
    source_ref: Mapped[str] = mapped_column(String(500), default="")      # tên tệp / URL / id tệp Drive / id trang Notion
    source_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    filename: Mapped[str] = mapped_column(String(300), default="")
    sha256: Mapped[str] = mapped_column(String(64), default="", index=True)
    status: Mapped[str] = mapped_column(String(16), default="done", index=True)   # done | duplicate | empty | error
    document_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    version_no: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duplicate_of_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    extracted_chars: Mapped[int] = mapped_column(Integer, default=0)
    ocr_used: Mapped[bool] = mapped_column(Boolean, default=False)
    method: Mapped[str] = mapped_column(String(32), default="")           # pypdf | ocr:tesseract | docx | xlsx | html …
    suggestions: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # doc_type/sensitivity/agent_use/code/hiệu lực + lý do
    proposals: Mapped[dict | None] = mapped_column(JSON, nullable=True)    # trích sự kiện đề xuất (hồ sơ pháp nhân, facts)
    proposals_status: Mapped[str] = mapped_column(String(16), default="")  # "" | pending | applied | dismissed
    note: Mapped[str] = mapped_column(Text, default="")
    created_by_member_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class DocSource(Base):
    __tablename__ = "doc_sources"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    kind: Mapped[str] = mapped_column(String(16))                          # url | gdrive | notion
    name: Mapped[str] = mapped_column(String(200), default="")
    config: Mapped[dict | None] = mapped_column(JSON, nullable=True)       # {url} | {folder_id} | {page_ids:[..]}
    credential_enc: Mapped[str] = mapped_column(Text, default="")          # token mã hoá — không bao giờ trả ra
    credential_hint: Mapped[str] = mapped_column(String(16), default="")   # 4 ký tự cuối để người dùng nhận ra
    default_doc_type: Mapped[str] = mapped_column(String(40), default="")
    interval_minutes: Mapped[int] = mapped_column(Integer, default=60)
    status: Mapped[str] = mapped_column(String(24), default="needs_account")  # active | needs_account | error | paused
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str] = mapped_column(Text, default="")
    created_by_member_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class DocSourceItem(Base):
    __tablename__ = "doc_source_items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("doc_sources.id"), index=True)
    external_id: Mapped[str] = mapped_column(String(300))
    title: Mapped[str] = mapped_column(String(300), default="")
    external_version: Mapped[str] = mapped_column(String(120), default="")
    sha256: Mapped[str] = mapped_column(String(64), default="")
    document_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class DocProposal(Base):
    """M3e — đề xuất sửa tài liệu (vòng học): nguồn là cờ của agent, cụm lỗ hổng kiến thức, câu eval trượt, bài học, hoặc
    agent đề xuất trực tiếp (MCP company_doc_propose). Mỗi đề xuất gắn một PHIÊN BẢN NHÁP (hoặc tài liệu nháp mới) và đi
    đúng đường duyệt M3a; ban hành → đóng cờ/lỗ hổng nguồn + chạy lại eval (eval_after)."""
    __tablename__ = "doc_proposals"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    document_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    version_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    new_document: Mapped[bool] = mapped_column(Boolean, default=False)
    kind: Mapped[str] = mapped_column(String(16))                  # flag | gap | eval | lesson | agent
    status: Mapped[str] = mapped_column(String(16), default="open", index=True)  # open | published | rejected | dismissed
    title: Mapped[str] = mapped_column(String(300), default="")
    rationale: Mapped[str] = mapped_column(Text, default="")
    source_refs: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # {flags:[], gaps:[], questions:[], lesson_id}
    eval_before: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    eval_after: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    eval_pending: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by_member_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class RetrievalEvalRun(Base):
    """M3e — lần chạy bộ eval truy hồi theo công ty (để bảng vòng học thấy xu hướng, trước/sau mỗi lần ban hành)."""
    __tablename__ = "retrieval_eval_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    trigger: Mapped[str] = mapped_column(String(24), default="manual")   # manual | publish | tick
    questions: Mapped[int] = mapped_column(Integer, default=0)
    recall: Mapped[float] = mapped_column(Float, default=0.0)
    top1: Mapped[float] = mapped_column(Float, default=0.0)
    section_recall: Mapped[float] = mapped_column(Float, default=0.0)
    misses: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
