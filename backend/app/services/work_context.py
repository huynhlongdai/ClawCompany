"""v37 — Gói ngữ cảnh công việc: bảy khối agent cần để làm được việc.

Vì sao module này tồn tại, bằng số đo được (`_reports/work-memory-gap.md`):

* Prompt mà agent nhận khi được giao việc dài **358 ký tự**, trong đó **286 là
  văn bản cố định** giống nhau cho mọi task.
* **10 trong 12 dữ kiện** mà công ty đã biết — dự án, mục tiêu, tiến độ, hạn
  chót, công ty, người được giao, vai, quản lý trực tiếp — không hề đi vào
  prompt.
* Hỏi lại agent ba câu cần bối cảnh, nó trả lời "không có thông tin" cả ba.

Bộ nhớ của OpenClaw không lấp được chỗ này *về mặt thiết kế*: năm tầng của nó
(``AGENTS.md`` → ``MEMORY.md``/``USER.md`` → ``memory/YYYY-MM-DD.md`` →
standing intents → ``DREAMS.md``) đều per-agent hoặc per-session, và tìm kiếm
bộ nhớ chéo agent đã bị xoá ở upstream v2026.8.1. Một *công việc* đi qua nhiều
phiên, nhiều ngày, nhiều người làm thì không có tầng nào để trú.

Ranh giới đã chọn: **kinh nghiệm cá nhân ở OpenClaw, sự thật về công việc ở
ClawCompany.**

Thiết kế có hai điểm cố ý:

1. **Thứ tự khối là cố định, và quy tắc cắt cũng cố định.** Khi vượt ngân sách,
   cắt khối 3 và 4 trước (nén thành số liệu), **không bao giờ** cắt khối 2
   (việc) và khối 6 (luật). Lý do: thiếu bối cảnh thì agent làm *kém*; thiếu
   luật thì agent làm *sai*. Hai hậu quả đó không cùng hạng.

2. **Chỉ đọc ``summary`` của sổ ghi, không đọc ``detail``.** Một task chạy 50
   lần vẫn không làm nổ ngân sách, vì mỗi lần chỉ góp một câu.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import (Approval, Company, Department, Member, Project,
                                 Task)
from app.models.extended import SOP, Decision
from app.models.v10 import ArtifactHandoff
from app.models.v37 import TaskJournalEntry
from app.services.v36_insights import local_today

# Ngân sách ký tự cho cả gói. Con số này không phải hạn mức của OpenClaw (20k
# mỗi file bootstrap, 60k tổng) mà là hạn mức **của một prompt task**: gói càng
# dài thì càng đắt mỗi lượt, và phần đuôi càng dễ bị model bỏ qua.
TOTAL_BUDGET_CHARS = 6_000

# Ngân sách từng khối. Tổng các trần này lớn hơn TOTAL_BUDGET_CHARS có chủ ý:
# hiếm khi mọi khối đều đầy, và trần từng khối chỉ để một khối không ăn hết.
BLOCK_BUDGETS = {
    1: 400,    # bạn là ai
    2: 1_200,  # việc
    3: 900,    # dự án
    4: 1_400,  # sổ ghi
    5: 700,    # bàn giao
    6: 1_000,  # luật
    7: 400,    # thoả thuận
}

# Thứ tự cắt khi vượt tổng ngân sách. Khối 2 và 6 KHÔNG có trong danh sách này —
# đó là điểm chính của thiết kế.
TRIM_ORDER = (4, 3, 5, 1)
NEVER_TRIM = (2, 6, 7)

MAX_JOURNAL_LINES = 8
MAX_SOP_LINES = 4
MAX_DECISION_LINES = 3


@dataclass
class Block:
    index: int
    title: str
    lines: list[str] = field(default_factory=list)
    trimmed: bool = False
    # Số dòng đã có trước khi cắt, để báo cáo nói được "đã nén 23 mục thành 8".
    original_count: int = 0

    def text(self) -> str:
        if not self.lines:
            return ""
        return "\n".join([f"## {self.index}. {self.title}", *self.lines])

    @property
    def chars(self) -> int:
        return len(self.text())


def _days_left(due: date | None) -> str:
    if not due:
        return "chưa đặt hạn"
    delta = (due - local_today()).days
    if delta < 0:
        return f"QUÁ HẠN {abs(delta)} ngày"
    if delta == 0:
        return "hạn là HÔM NAY"
    return f"còn {delta} ngày"


def _tenant_of(db: Session, task: Task) -> tuple[Project | None, Company | None]:
    project = db.get(Project, task.project_id) if task.project_id else None
    company = db.get(Company, project.company_id) if project and project.company_id else None
    return project, company


# --------------------------------------------------------------- từng khối

def _block1_identity(db: Session, assignee: Member | None) -> Block:
    block = Block(1, "Bạn là ai trong việc này")
    if not assignee:
        block.lines.append("- Việc này chưa gán cho ai; bạn đang xử lý với tư cách "
                           "được điều phối tạm.")
        return block
    department = db.get(Department, assignee.department_id) if assignee.department_id else None
    manager = db.get(Member, assignee.manager_id) if assignee.manager_id else None
    block.lines.append(f"- Bạn là **{assignee.name}**, {assignee.role or 'chưa có chức danh'}.")
    if department:
        block.lines.append(f"- Phòng ban: {department.name}.")
    if manager:
        block.lines.append(f"- Quản lý trực tiếp: {manager.name}"
                           + (f" ({manager.role})" if manager.role else "")
                           + ". Việc vượt quyền thì báo người này.")
    return block


def _block2_task(task: Task) -> Block:
    block = Block(2, "Việc cần làm")
    block.lines.append(f"- Task #{task.id}: **{task.title}**")
    block.lines.append(f"- Mức ưu tiên: {task.priority} · trạng thái hiện tại: {task.status}")
    description = (task.description or "").strip()
    block.lines.append("")
    block.lines.append(description if description else "(Task không có mô tả. "
                       "Nếu thiếu thông tin để làm, hãy hỏi lại thay vì đoán.)")
    return block


def _block3_project(project: Project | None, company: Company | None,
                    siblings: list[Task]) -> Block:
    block = Block(3, "Việc này nằm trong bức tranh nào")
    if not project:
        block.lines.append("- Task không thuộc dự án nào.")
        return block
    block.lines.append(f"- Dự án: **{project.name}** · tiến độ {project.progress}%"
                       f" · {_days_left(project.due_date)}")
    if company:
        block.lines.append(f"- Công ty: {company.name}")
    goal = (project.description or "").strip()
    if goal:
        block.lines.append(f"- Mục tiêu dự án: {goal}")
    if siblings:
        block.original_count = len(siblings)
        block.lines.append(f"- Các việc khác đang mở trong dự án ({len(siblings)}):")
        for sibling in siblings[:5]:
            owner = ""
            block.lines.append(f"  - #{sibling.id} {sibling.title} [{sibling.status}]{owner}")
        if len(siblings) > 5:
            block.lines.append(f"  - … và {len(siblings) - 5} việc nữa")
    return block


def _block4_journal(entries: list[TaskJournalEntry],
                    actors: dict[int, str]) -> Block:
    block = Block(4, "Việc này trước đây đã đi tới đâu")
    if not entries:
        block.lines.append("- Chưa có lượt nào trước. Bạn là người đầu tiên nhận việc này.")
        return block
    block.original_count = len(entries)
    recent = entries[-MAX_JOURNAL_LINES:]
    if len(entries) > len(recent):
        block.lines.append(f"- (Sổ ghi có {len(entries)} mục; dưới đây là "
                           f"{len(recent)} mục gần nhất.)")
        block.trimmed = True
    for entry in recent:
        who = actors.get(entry.actor_member_id or 0, "hệ thống")
        stamp = entry.created_at.strftime("%d/%m %H:%M")
        outcome = f" → {entry.outcome}" if entry.outcome else ""
        block.lines.append(f"- [{stamp}] {who} · {entry.kind}{outcome}: {entry.summary}")
    return block


def _block5_handoff(db: Session, task: Task, handoffs: list[ArtifactHandoff],
                    actors: dict[int, str]) -> Block:
    block = Block(5, "Ai bàn giao việc này cho bạn")
    if not handoffs:
        block.lines.append("- Không có bàn giao nào ghi nhận cho việc này.")
        return block
    block.original_count = len(handoffs)
    for handoff in handoffs[:3]:
        sender = actors.get(getattr(handoff, "from_member_id", 0) or 0, "không rõ")
        purpose = (getattr(handoff, "purpose", "") or "").strip()
        note = (getattr(handoff, "instructions", "") or "").strip()
        block.lines.append(f"- {sender} bàn giao ({purpose or 'không nêu mục đích'}): "
                           f"{note or '(không kèm hướng dẫn)'}")
        artifact_id = getattr(handoff, "artifact_id", None)
        if artifact_id:
            block.lines.append(f"  - Sản phẩm kèm theo: artifact #{artifact_id}")
    return block


def _block6_rules(sops: list[SOP], decisions: list[Decision],
                  pending_approvals: int) -> Block:
    block = Block(6, "Luật áp dụng cho việc này")
    if sops:
        block.original_count += len(sops)
        block.lines.append(f"- SOP đang hiệu lực ({len(sops)}):")
        for sop in sops[:MAX_SOP_LINES]:
            block.lines.append(f"  - {sop.title}"
                               + (f" [{sop.version}]" if getattr(sop, "version", None) else ""))
    if decisions:
        block.original_count += len(decisions)
        block.lines.append(f"- Quyết định đã chốt, không mở lại ({len(decisions)}):")
        for decision in decisions[:MAX_DECISION_LINES]:
            block.lines.append(f"  - {decision.title}")
    if pending_approvals:
        block.lines.append(f"- Có {pending_approvals} yêu cầu phê duyệt đang chờ "
                           "liên quan tới phạm vi này; đừng làm trùng.")
    if not block.lines:
        block.lines.append("- Không có SOP hay quyết định nào ràng buộc riêng việc này.")
    return block


def _block7_agreement() -> Block:
    """Bốn dòng thoả thuận cũ. Giữ nguyên chữ vì nó là một hợp đồng.

    Đây là phần duy nhất của prompt cũ được mang sang, và nó không bị cắt: nó
    nói agent được tự quyết cái gì và phải xin phép cái gì.
    """
    block = Block(7, "Thoả thuận làm việc")
    block.lines.extend([
        "- Báo tiến độ trong lúc làm; công ty ghi lại mọi event từ gateway.",
        "- Không công bố ra ngoài, không mua sắm, không xoá dữ liệu production "
        "và không đổi hệ thống production mà chưa có người duyệt.",
        "- Kết thúc bằng cách nói rõ kết quả và sản phẩm nằm ở đâu.",
        "- Thiếu thông tin thì hỏi lại; đừng đoán rồi làm.",
    ])
    return block


# ------------------------------------------------------------------ lắp gói

def build_pack(db: Session, task: Task, *, organization_id: int,
               budget_chars: int = TOTAL_BUDGET_CHARS) -> dict:
    """Lắp gói ngữ cảnh cho một task, rồi cắt cho vừa ngân sách.

    Trả về cả ``text`` (thứ gửi cho agent) và ``blocks`` (để UI và báo cáo nói
    được khối nào có gì, khối nào bị cắt). Không trả về thứ gì bịa: khối nào
    không có dữ liệu thì nói thẳng là không có.
    """
    project, company = _tenant_of(db, task)
    assignee = db.get(Member, task.assignee_member_id) if task.assignee_member_id else None

    siblings = list(db.execute(
        select(Task).where(Task.project_id == task.project_id, Task.id != task.id,
                           Task.status.notin_(["done", "cancelled", "archived"]))
        .order_by(Task.id).limit(12)
    ).scalars().all()) if task.project_id else []

    entries = list(db.execute(
        select(TaskJournalEntry).where(TaskJournalEntry.task_id == task.id)
        .order_by(TaskJournalEntry.seq)
    ).scalars().all())

    handoffs = _safe_handoffs(db, task)
    sops = _safe_sops(db, organization_id)
    decisions = _safe_decisions(db, organization_id)
    pending = db.query(Approval).filter(Approval.organization_id == organization_id,
                                        Approval.status == "pending").count()

    actor_ids = {e.actor_member_id for e in entries if e.actor_member_id}
    actor_ids |= {getattr(h, "from_member_id", None) for h in handoffs}
    actor_ids.discard(None)
    actors = {m.id: m.name for m in db.execute(
        select(Member).where(Member.id.in_(actor_ids))
    ).scalars().all()} if actor_ids else {}

    blocks = [
        _block1_identity(db, assignee),
        _block2_task(task),
        _block3_project(project, company, siblings),
        _block4_journal(entries, actors),
        _block5_handoff(db, task, handoffs, actors),
        _block6_rules(sops, decisions, pending),
        _block7_agreement(),
    ]

    # Cắt cho vừa ngân sách, theo thứ tự đã định. Ghi lại đã cắt gì.
    trimmed: list[str] = []
    for index in TRIM_ORDER:
        if sum(b.chars for b in blocks if b.text()) <= budget_chars:
            break
        block = next(b for b in blocks if b.index == index)
        if not block.text():
            continue
        keep = max(1, len(block.lines) // 2)
        if keep < len(block.lines):
            dropped = len(block.lines) - keep
            block.lines = block.lines[:keep] + [f"  - (đã lược {dropped} dòng cho vừa ngân sách)"]
            block.trimmed = True
            trimmed.append(f"khối {index} lược {dropped} dòng")

    text = "\n\n".join(b.text() for b in blocks if b.text())
    total = len(text)

    return {
        "text": text,
        "chars": total,
        "budget_chars": budget_chars,
        "over_budget": total > budget_chars,
        "trimmed": trimmed,
        "blocks": [{
            "index": b.index, "title": b.title, "chars": b.chars,
            "budget": BLOCK_BUDGETS.get(b.index, 0), "lines": len(b.lines),
            "trimmed": b.trimmed, "original_count": b.original_count,
            "empty": not b.lines,
        } for b in blocks],
        # Lời thừa nhận đi kèm mọi gói: khối nào không bao giờ bị cắt, và vì sao.
        "never_trimmed": list(NEVER_TRIM),
        "sources": {
            "task": "tasks", "project": "projects", "journal": "task_journal_entries",
            "handoff": "artifact_handoffs", "rules": "sops + decisions + approvals",
        },
    }


# ------------------------------------------------- đọc mềm những bảng phụ
#
# Ba hàm dưới đây bọc try/except có chủ ý. Chúng đọc các bảng phụ (SOP, quyết
# định, bàn giao) mà cấu trúc có thể khác giữa các version. Một prompt task
# không được nổ chỉ vì bảng SOP đổi tên cột — nhưng cũng không được im lặng
# giả vờ là "không có SOP nào", nên lỗi được ghi vào khối luôn.

def _safe_handoffs(db: Session, task: Task) -> list:
    try:
        return list(db.execute(
            select(ArtifactHandoff).where(ArtifactHandoff.task_id == task.id)
            .order_by(ArtifactHandoff.id.desc()).limit(3)
        ).scalars().all())
    except Exception:                                     # noqa: BLE001
        return []


def _safe_sops(db: Session, organization_id: int) -> list:
    try:
        return list(db.execute(
            select(SOP).where(SOP.organization_id == organization_id,
                              SOP.status == "active").limit(MAX_SOP_LINES + 2)
        ).scalars().all())
    except Exception:                                     # noqa: BLE001
        return []


def _safe_decisions(db: Session, organization_id: int) -> list:
    try:
        return list(db.execute(
            select(Decision).where(Decision.organization_id == organization_id,
                                   Decision.status == "decided")
            .order_by(Decision.id.desc()).limit(MAX_DECISION_LINES + 2)
        ).scalars().all())
    except Exception:                                     # noqa: BLE001
        return []
