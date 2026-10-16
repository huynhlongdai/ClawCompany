"""M3g — khách hàng của DOANH NGHIỆP NGƯỜI DÙNG + đồng ý xử lý dữ liệu cá nhân (Luật BVDLCN 91/2025/QH15, NĐ 356/2025/NĐ-CP
thay NĐ 13/2023 từ 1/1/2026). Khác hẳn bảng ``customers`` (tenant nền tảng mua ghế). Spec:
docs/company-knowledge-library-and-gaps.md §B4, §C M3g.

``crm_contacts``       liên hệ (người / doanh nghiệp) theo công ty. PII (điện thoại, email, địa chỉ) ở cột riêng; ``search_text``
                       KHÔNG chứa PII (tên bỏ dấu + nhãn) → không vào RAG, không vào chỉ mục tri thức.
``crm_consents``       mỗi lần đồng ý = một dòng (mục đích, kênh, thời điểm, bằng chứng, bản thông báo); rút đồng ý ghi thời điểm +
                       lý do lên đúng dòng đó; KHÔNG sửa / xoá dòng (chứng minh được đồng ý — NĐ 356). Im lặng ≠ đồng ý: không có
                       bằng chứng thì không ghi được.
``crm_interactions``   nhật ký tương tác, nối tới việc (task), Hộp việc (inbox_items), hội thoại / phiên cổng khách (conversations).
``crm_data_requests``  yêu cầu của chủ thể dữ liệu (xem / sửa / xoá / rút đồng ý / hạn chế / phản đối) có hạn phản hồi 02 ngày làm việc
                       và hạn thực hiện theo loại (NĐ 356 Đ5: 10 / 15 / 20 ngày), việc + Hộp việc cho người xử lý, hồ sơ bằng chứng."""
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

PURPOSES = ("service", "marketing", "analytics", "third_party", "ai_processing")
CHANNELS = ("phone", "sms", "zalo", "email", "web", "in_person", "social", "other")
DSR_KINDS = ("access", "correct", "delete", "withdraw", "restrict", "object")
DSR_STATUSES = ("open", "in_progress", "done", "rejected")


class CrmContact(Base):
    __tablename__ = "crm_contacts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    kind: Mapped[str] = mapped_column(String(16), default="person")          # person | business
    name: Mapped[str] = mapped_column(String(200))
    phone: Mapped[str] = mapped_column(String(40), default="")
    email: Mapped[str] = mapped_column(String(200), default="")
    address: Mapped[str] = mapped_column(Text, default="")
    org_name: Mapped[str] = mapped_column(String(200), default="")           # công ty của liên hệ (nếu có)
    tags: Mapped[list | None] = mapped_column(JSON, nullable=True)
    segment: Mapped[str] = mapped_column(String(60), default="")
    source: Mapped[str] = mapped_column(String(24), default="manual")        # manual | chat | portal | import | agent
    owner_member_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    department_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # phòng phụ trách → agent cùng phòng mới thấy
    notes: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="active")       # active | restricted | erased
    restricted: Mapped[bool] = mapped_column(Boolean, default=False)         # hạn chế xử lý (yêu cầu chủ thể)
    search_text: Mapped[str] = mapped_column(Text, default="")
    created_by_member_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    erased_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class CrmConsent(Base):
    __tablename__ = "crm_consents"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("crm_contacts.id"), index=True)
    purpose: Mapped[str] = mapped_column(String(24))
    channel: Mapped[str] = mapped_column(String(16), default="other")
    status: Mapped[str] = mapped_column(String(16), default="granted")     # granted | withdrawn
    granted_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    evidence: Mapped[str] = mapped_column(Text, default="")                 # cách thu: "form web, ô tích chưa tích sẵn, IP…"
    evidence_doc_id: Mapped[int | None] = mapped_column(Integer, nullable=True)   # tệp bằng chứng (record M3a)
    notice_ref: Mapped[str] = mapped_column(String(80), default="")        # mã/phiên bản thông báo xử lý DLCN đã đưa khách
    recorded_by_member_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    withdrawn_reason: Mapped[str] = mapped_column(Text, default="")
    withdrawn_by_member_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class CrmInteraction(Base):
    __tablename__ = "crm_interactions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("crm_contacts.id"), index=True)
    kind: Mapped[str] = mapped_column(String(24), default="note")    # note|call|chat|email|meeting|task|inbox|portal|outreach|outreach_blocked|dsr|consent
    channel: Mapped[str] = mapped_column(String(16), default="")
    direction: Mapped[str] = mapped_column(String(8), default="")    # in | out
    purpose: Mapped[str] = mapped_column(String(24), default="service")
    summary: Mapped[str] = mapped_column(Text, default="")
    code: Mapped[str] = mapped_column(String(48), default="")        # mã sự kiện hệ thống (UI dịch), vd consent_withdrawn
    params: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    task_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    inbox_item_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    conversation_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    member_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class CrmDataRequest(Base):
    __tablename__ = "crm_data_requests"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("crm_contacts.id"), index=True)
    kind: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), default="open")
    channel: Mapped[str] = mapped_column(String(16), default="other")
    received_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    ack_due_at: Mapped[datetime] = mapped_column(DateTime)          # phản hồi: 02 ngày làm việc
    due_at: Mapped[datetime] = mapped_column(DateTime)              # thực hiện: theo loại (NĐ 356 Đ5)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    requester_note: Mapped[str] = mapped_column(Text, default="")
    handler_member_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    task_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    result_note: Mapped[str] = mapped_column(Text, default="")
    evidence: Mapped[dict | None] = mapped_column(JSON, nullable=True)   # bằng chứng thực hiện: hash bản xuất, số dòng xoá…
    reminded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    closed_by_member_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


__all__ = ["CrmContact", "CrmConsent", "CrmInteraction", "CrmDataRequest", "PURPOSES", "CHANNELS", "DSR_KINDS", "DSR_STATUSES"]
