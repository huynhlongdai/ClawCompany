"""v37 — Sổ ghi của một công việc: tầng bộ nhớ mà OpenClaw không có.

Ranh giới đã chọn cho dự án này: **kinh nghiệm cá nhân ở OpenClaw, sự thật về
công việc ở ClawCompany.** Module này là nửa thứ hai.

Vì sao OpenClaw không thể giữ tầng này, không phải vì nó thiếu tính năng mà vì
*thiết kế của nó không có chỗ*:

* ``MEMORY.md`` là kinh nghiệm của **một agent** — task đi qua ba agent thì ba
  file, không ai đọc của ai. Tìm kiếm bộ nhớ chéo agent đã bị xoá ở v2026.8.1.
* Transcript là của **một phiên** — mỗi task mở phiên riêng
  (``agent:<id>:company-task-<n>``) nên lần chạy thứ hai không thấy lần đầu.
* Dreaming hợp nhất theo **agent**, lúc 3 giờ sáng, và chỉ ghi vào
  ``MEMORY.md``. Nó không biết "task #12" là gì.

Nên sổ ghi phải ở đây. Hai quy tắc giữ cho nó không thành bãi rác:

1. **``summary`` ngắn, ``detail`` dài.** Chỉ ``summary`` đi vào prompt. Một
   task chạy 50 lần vẫn không làm nổ ngân sách ký tự.
2. **``seq`` có ràng buộc unique theo task.** Hai lượt ghi song song không thể
   chiếm cùng số thứ tự; bên thua nhận lỗi và thử lại, thay vì hai mục cùng số.
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.entities import Company, Member, Project, Task
from app.models.v37 import TaskJournalEntry
from app.services.company_event_bus import emit_event

# Loại mục. Danh sách đóng, vì một sổ ghi mà ai muốn ghi kiểu gì cũng được thì
# không thống kê được và cũng không nén được.
KINDS = ("attempt", "result", "review", "handoff", "note", "decision", "blocker")

# Kết quả đo được của một lượt. Rỗng nghĩa là **chưa đo được**, khác với "thất
# bại" — cùng một lý lẽ với ``success_rate = null`` ở v36.
OUTCOMES = ("", "success", "partial", "failed", "rejected", "blocked", "cancelled")

SUMMARY_MAX = 400
MAX_RETRY = 3


class JournalError(RuntimeError):
    pass


def _organization_of(db: Session, task: Task) -> int:
    """Tenant của task, đi qua project → company.

    ``tasks`` không có ``organization_id``; đây là cùng cái bẫy đã làm
    ``live_channel`` của v35 nổ ``AttributeError`` vì lọc theo cột không tồn tại.
    """
    project = db.get(Project, task.project_id) if task.project_id else None
    if not project:
        raise JournalError(f"task #{task.id} không thuộc project nào, không xác định được tenant")
    company = db.get(Company, project.company_id) if project.company_id else None
    if not company:
        raise JournalError(f"project #{project.id} không thuộc company nào")
    return company.organization_id


def append(db: Session, task: Task, *, kind: str, summary: str,
           detail: str = "", actor_member_id: int | None = None,
           outcome: str = "", cost_usd: float = 0.0,
           runtime_run_id: str = "", runtime_session_key: str = "") -> TaskJournalEntry:
    """Ghi một mục vào sổ của task.

    ``seq`` được cấp bằng cách đọc max rồi +1, và ràng buộc unique là chốt thật:
    nếu hai lượt ghi cùng lúc, một lượt nhận ``IntegrityError`` và được thử lại
    với số mới. Không dùng lock bảng — sổ ghi không đáng để khoá cả bảng.
    """
    if kind not in KINDS:
        raise JournalError(f"kind không hợp lệ: {kind}; hợp lệ: {', '.join(KINDS)}")
    if outcome not in OUTCOMES:
        raise JournalError(f"outcome không hợp lệ: {outcome}; hợp lệ: {OUTCOMES}")
    summary = (summary or "").strip()
    if not summary:
        raise JournalError("summary không được rỗng — mục sổ ghi phải nói được một câu")
    if len(summary) > SUMMARY_MAX:
        # Cắt ở đây là đúng: summary dài quá thì nó không còn là summary. Phần
        # đầy đủ vẫn còn trong detail, nên không mất gì.
        detail = detail or summary
        summary = summary[: SUMMARY_MAX - 1] + "…"

    organization_id = _organization_of(db, task)

    for attempt in range(MAX_RETRY):
        next_seq = (db.execute(
            select(func.coalesce(func.max(TaskJournalEntry.seq), 0))
            .where(TaskJournalEntry.task_id == task.id)
        ).scalar() or 0) + 1
        entry = TaskJournalEntry(
            organization_id=organization_id, task_id=task.id, seq=next_seq,
            actor_member_id=actor_member_id, kind=kind, summary=summary,
            detail=detail, outcome=outcome, cost_usd=cost_usd,
            runtime_run_id=runtime_run_id, runtime_session_key=runtime_session_key,
        )
        db.add(entry)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            if attempt == MAX_RETRY - 1:
                raise JournalError(
                    f"không cấp được seq cho task #{task.id} sau {MAX_RETRY} lần thử; "
                    "có lượt ghi khác đang tranh cùng số")
            continue
        db.refresh(entry)
        break

    emit_event(db, organization_id=organization_id, company_id=None,
               event_type=f"task.journal.{kind}", source="task_journal",
               aggregate_type="task", aggregate_id=str(task.id),
               actor_member_id=actor_member_id,
               payload={"seq": entry.seq, "outcome": outcome, "kind": kind})
    return entry


def read(db: Session, task_id: int, *, limit: int = 100) -> list[TaskJournalEntry]:
    return list(db.execute(
        select(TaskJournalEntry).where(TaskJournalEntry.task_id == task_id)
        .order_by(TaskJournalEntry.seq).limit(max(1, min(limit, 500)))
    ).scalars().all())


def digest(db: Session, task_id: int) -> dict:
    """Tóm tắt sổ ghi để UI và báo cáo đọc, không cần tải toàn bộ.

    ``measurable_outcomes`` nói rõ bao nhiêu mục *đo được* kết quả. Mục có
    ``outcome`` rỗng không phải thất bại, nó là chưa đo — và tỉ lệ thành công
    tính trên mẫu chưa đo được là một con số nói dối.
    """
    entries = read(db, task_id, limit=500)
    measured = [e for e in entries if e.outcome]
    succeeded = [e for e in measured if e.outcome == "success"]
    actors = {e.actor_member_id for e in entries if e.actor_member_id}
    names = {m.id: m.name for m in db.execute(
        select(Member).where(Member.id.in_(actors))
    ).scalars().all()} if actors else {}
    return {
        "task_id": task_id,
        "entries": len(entries),
        "by_kind": {kind: sum(1 for e in entries if e.kind == kind)
                    for kind in KINDS if any(e.kind == kind for e in entries)},
        "measurable_outcomes": len(measured),
        "success_rate": round(100.0 * len(succeeded) / len(measured), 1) if measured else None,
        "hands": [names.get(a, f"member#{a}") for a in sorted(actors)],
        "total_cost_usd": round(sum(e.cost_usd for e in entries), 4),
        "first_at": entries[0].created_at.isoformat() if entries else None,
        "last_at": entries[-1].created_at.isoformat() if entries else None,
        "note": ("success_rate là null khi chưa có mục nào đo được kết quả — "
                 "khác với 0%."),
    }
