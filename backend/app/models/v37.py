"""v37 — Bộ nhớ công việc và phòng họp có chủ toạ.

Hai bảng/nhóm cột này sinh ra từ một phép đo, không từ một ý tưởng. Đo được
trong `_reports/work-memory-gap.md`: prompt mà agent nhận khi được giao việc dài
358 ký tự, trong đó 286 là văn bản cố định giống nhau cho mọi task, và **10
trong 12 dữ kiện mà công ty đã biết** (dự án, mục tiêu, hạn chót, người giao,
quản lý…) không hề đi vào prompt. Hỏi lại agent ba câu cần bối cảnh, nó trả lời
"không có thông tin" cả ba.

Vì sao là bảng mới chứ không nhét vào bảng cũ:

* ``task_journal_entries`` — OpenClaw **không có khái niệm tương ứng**. Bộ nhớ
  của nó có năm tầng nhưng tất cả đều per-agent hoặc per-session: ``MEMORY.md``
  là kinh nghiệm của một agent, transcript là của một phiên. Một *công việc* đi
  qua nhiều phiên, nhiều ngày, nhiều người làm thì không có chỗ nào để nhớ.
  Ranh giới đã chọn: kinh nghiệm cá nhân ở OpenClaw, còn sự thật về công việc ở
  ClawCompany.

* Cột mới trên ``collaboration_rooms`` — máy trạng thái phòng họp đã có sẵn và
  tốt (thứ tự lượt, quyền chốt, năm loại lượt, trần số lượt). Nó thiếu ba thứ
  để chạy thật với agent: ai giữ búa chủ toạ, tiền cho phiên họp, và lý do
  dừng. Một phòng họp toàn agent có thể nói mãi, và mỗi lượt là tiền thật.
"""
from datetime import datetime, timezone

from sqlalchemy import (Boolean, DateTime, Float, ForeignKey, Integer, String,
                        Text, UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class TaskJournalEntry(Base):
    """Sổ ghi của MỘT công việc, sống qua nhiều lượt chạy và nhiều người làm.

    Đây là tầng bộ nhớ mà OpenClaw không thể cung cấp, và là nguồn cho khối 4
    của gói ngữ cảnh ("những lần trước đã làm gì").

    Quy tắc để sổ không phình vô hạn: mỗi mục có ``summary`` ngắn (đi vào
    prompt) và ``detail`` dài (chỉ đọc khi cần). Gói ngữ cảnh chỉ lấy
    ``summary``, nên một task chạy 50 lần vẫn không làm nổ ngân sách ký tự.
    """
    __tablename__ = "task_journal_entries"
    __table_args__ = (UniqueConstraint("task_id", "seq", name="uq_task_journal_seq"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), index=True)
    # Số thứ tự trong sổ của task này. Có unique constraint nên hai lượt ghi
    # song song không thể chiếm cùng một số.
    seq: Mapped[int] = mapped_column(Integer, index=True)
    # Ai ghi. NULL nghĩa là hệ thống ghi (ví dụ tự động khi task chuyển trạng thái).
    actor_member_id: Mapped[int | None] = mapped_column(ForeignKey("members.id"), nullable=True, index=True)
    # attempt | result | review | handoff | note | decision | blocker
    kind: Mapped[str] = mapped_column(String(32), default="note", index=True)
    # Một câu. Đây là thứ đi vào prompt, nên nó phải ngắn.
    summary: Mapped[str] = mapped_column(String(400), default="")
    # Chi tiết đầy đủ. Không đi vào prompt; đọc khi người hoặc agent cần tra.
    detail: Mapped[str] = mapped_column(Text, default="")
    # Dấu vết runtime để truy lại đúng lượt chạy nào sinh ra mục này.
    runtime_run_id: Mapped[str] = mapped_column(String(160), default="")
    runtime_session_key: Mapped[str] = mapped_column(String(200), default="")
    # Kết quả của lượt đó, nếu đo được: thành công, thất bại, hay chưa rõ.
    outcome: Mapped[str] = mapped_column(String(32), default="")
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class RoomConductorRun(Base):
    """Một phiên điều phối phòng họp: ai nói, tốn bao nhiêu, dừng vì sao.

    Tách khỏi ``room_turns`` vì hai thứ khác nhau: ``room_turns`` là *biên bản*
    (ai nói gì), còn bảng này là *vận hành* (lượt gọi model nào, mất mấy giây,
    tốn bao nhiêu, có lỗi gì). Trộn hai thứ sẽ làm biên bản họp đầy dữ liệu kỹ
    thuật mà người đọc không cần.
    """
    __tablename__ = "room_conductor_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    room_id: Mapped[int] = mapped_column(ForeignKey("collaboration_rooms.id"), index=True)
    turn_id: Mapped[int | None] = mapped_column(ForeignKey("room_turns.id"), nullable=True)
    speaker_member_id: Mapped[int] = mapped_column(ForeignKey("members.id"), index=True)
    runtime_agent_id: Mapped[str] = mapped_column(String(160), default="")
    runtime_session_key: Mapped[str] = mapped_column(String(200), default="")
    runtime_run_id: Mapped[str] = mapped_column(String(160), default="")
    prompt_chars: Mapped[int] = mapped_column(Integer, default=0)
    reply_chars: Mapped[int] = mapped_column(Integer, default=0)
    elapsed_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    # ok | timeout | error | skipped
    status: Mapped[str] = mapped_column(String(32), default="ok", index=True)
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
