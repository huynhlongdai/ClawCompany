"""WP-4.3 — Bàn giao gọi được agent: từ `artifact_handoffs` tới một lượt chạy thật.

Trước gói này, một bàn giao là ba hàng database và một tin nhắn: `handoff_artifact`
tạo hàng `artifact_handoffs`, gửi `agent_messages`, phát event — rồi **nằm im**.
Người nhận, kể cả khi là agent, không nhận được việc gì cho tới khi có người vào
bấm dispatch. Khối 5 của gói ngữ cảnh (`work_context`) đã đọc được bàn giao từ
v37, nhưng không ai gọi agent nên khối đó chỉ hiện ra khi người ta tình cờ
dispatch đúng task đó.

Module này nối dây còn thiếu, và nó phải giải quyết bốn câu hỏi mà "chỉ gọi
dispatch" không trả lời được.

**1. Ai là chủ việc sau khi bàn giao?**

Phải gán lại ``task.assignee_member_id`` cho người nhận. Đây không phải chi tiết
phụ: khối 1 của gói ngữ cảnh mở đầu bằng "Bạn là <người được giao>", nên nếu
task vẫn thuộc Nina mà lượt chạy lại gửi tới seat của Mia thì Mia nhận hồ sơ của
người khác. **Đúng lỗi đã đo được** trong `_reports/work-memory-gap.md`: một
agent nhận gói của người khác trả lời sai câu "ai là quản lý của tôi". Bài học
ghi ở đó là "gói phải tới đúng seat của người mà khối 1 đang nói về", và chỗ thi
hành bài học đó là đây.

**2. Bàn giao cho agent thì có cần bấm "accept" không?**

Không. Một nhân viên AI không bấm nút. Nhưng trạng thái vẫn phải đi đúng đường:
module này gọi ``accept_handoff`` của chính v10 thay vì tự đặt
``status = "accepted"``, để không sinh ra định nghĩa thứ hai của "đã nhận" —
đúng lớp lỗi mà ``row_guard.kind()`` so với ``row_revision.kind_of()`` đã gây ra
ở v28, và mà ``next_speaker`` so với ``expected_speaker`` vừa gây lại ở v37.

**3. Bàn giao nào cũng tự tiêu tiền?**

Không. Mỗi lượt dispatch là một lời gọi model có phí. Quyết định chạy hay không
theo thứ tự: tham số của lời gọi (nếu caller nói rõ) → ``openclaw_auto_dispatch``
trong cấu hình → không chạy. Và **mọi trường hợp đều trả về lý do**, kể cả khi
không chạy, để người vận hành không phải đoán vì sao bàn giao im lặng.

**4. Không dispatch được thì bàn giao có mất không?**

Không. Hàng ``artifact_handoffs`` và mục sổ ghi vẫn còn; chỉ lượt chạy là không
xảy ra. Một bàn giao đã ghi mà không chạy được vẫn là một bàn giao — người thật
vào dispatch tay được, và khối 5 của gói ngữ cảnh sẽ mang hướng dẫn theo.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import Agent, Artifact, ArtifactHandoff, Member, Task
from app.services import task_journal
from app.services.agent_dispatch import DispatchError, dispatch_task
from app.services.artifacts import accept_handoff
from app.services.company_event_bus import emit_event

SOURCE = "handoff_dispatch"

# Lý do không chạy. Danh sách đóng để UI hiển thị được và để test ghim được.
SKIP_NO_TASK = "no_task"
SKIP_TARGET_IS_HUMAN = "target_is_human"
SKIP_NO_SEAT = "target_has_no_active_seat"
SKIP_DISABLED = "auto_dispatch_disabled"
SKIP_ALREADY_RUNNING = "task_already_running"


def _agent_seat(db: Session, member_id: int) -> tuple[Member | None, Agent | None]:
    member = db.get(Member, member_id)
    if not member or member.member_type != "agent":
        return member, None
    agent = db.execute(select(Agent).where(Agent.member_id == member_id)).scalars().first()
    if not agent or not (agent.runtime_agent_id or "").strip():
        return member, None
    if agent.lifecycle != "active":
        return member, None
    return member, agent


def _summary_for(sender: Member | None, target: Member | None,
                 handoff: ArtifactHandoff) -> str:
    who = sender.name if sender else "hệ thống"
    to = target.name if target else f"member#{handoff.to_member_id}"
    note = (handoff.instructions or "").strip().replace("\n", " ")
    head = f"{who} bàn giao cho {to} ({handoff.purpose or 'không nêu mục đích'})"
    return f"{head}: {note}" if note else head


def record_handoff_in_journal(db: Session, handoff: ArtifactHandoff) -> dict:
    """Ghi bàn giao vào sổ của task. Chạy được cả khi không dispatch.

    Tách khỏi phần dispatch có chủ ý: **lịch sử công việc không phụ thuộc vào
    việc có tiêu tiền hay không.** Một bàn giao cho người thật, hoặc cho agent
    lúc auto-dispatch đang tắt, vẫn phải để lại dấu trong sổ — nếu không thì
    khối 4 của gói ngữ cảnh sẽ kể một lịch sử có lỗ.
    """
    if not handoff.task_id:
        return {"recorded": False, "reason": SKIP_NO_TASK}
    task = db.get(Task, handoff.task_id)
    if not task:
        return {"recorded": False, "reason": SKIP_NO_TASK}

    sender = db.get(Member, handoff.from_member_id) if handoff.from_member_id else None
    target = db.get(Member, handoff.to_member_id)
    artifact = db.get(Artifact, handoff.artifact_id)

    detail_lines = [
        f"handoff_id: {handoff.id}",
        f"purpose: {handoff.purpose}",
        f"artifact: #{handoff.artifact_id}"
        + (f" {artifact.logical_path} v{artifact.version}" if artifact else ""),
    ]
    if (handoff.instructions or "").strip():
        detail_lines.append("")
        detail_lines.append("Hướng dẫn bàn giao đầy đủ:")
        detail_lines.append(handoff.instructions.strip())

    try:
        entry = task_journal.append(
            db, task, kind="handoff", actor_member_id=handoff.from_member_id,
            summary=_summary_for(sender, target, handoff),
            detail="\n".join(detail_lines),
        )
    except task_journal.JournalError as exc:
        return {"recorded": False, "reason": "journal_error", "error": str(exc)}
    return {"recorded": True, "journal_seq": entry.seq}


def reassign_task(db: Session, task: Task, to_member_id: int) -> dict:
    """Chuyển chủ việc sang người nhận bàn giao.

    Trả về cả chủ cũ để báo cáo nói được "từ ai sang ai". Không đổi trạng thái
    task ở đây: việc đó thuộc ``dispatch_task`` (nó đặt ``in_progress``), và hai
    chỗ cùng đổi một cột là cách sinh ra lỗi khó tìm.
    """
    previous = task.assignee_member_id
    if previous == to_member_id:
        return {"reassigned": False, "reason": "already_owner", "owner": to_member_id}
    task.assignee_member_id = to_member_id
    db.add(task); db.commit(); db.refresh(task)
    return {"reassigned": True, "from_member_id": previous, "to_member_id": to_member_id}


async def dispatch_on_handoff(db: Session, handoff: ArtifactHandoff, *,
                              dispatch: bool | None = None) -> dict:
    """Ghi sổ, rồi giao việc cho người nhận nếu họ là agent đang hoạt động.

    ``dispatch=None`` nghĩa là theo cấu hình ``openclaw_auto_dispatch``.
    ``True``/``False`` là caller nói rõ, và lời nói rõ luôn thắng cấu hình.

    Phản hồi **luôn** có ``reason``, kể cả khi thành công — người đọc log không
    phải suy ra vì sao một bàn giao có chạy hay không.
    """
    result: dict[str, Any] = {
        "handoff_id": handoff.id,
        "task_id": handoff.task_id,
        "to_member_id": handoff.to_member_id,
        "journal": record_handoff_in_journal(db, handoff),
        "dispatched": False,
        "reason": "",
    }

    if not handoff.task_id:
        result["reason"] = SKIP_NO_TASK
        result["note"] = ("Bàn giao không gắn task nào, nên không có việc để "
                          "giao. Artifact vẫn được bàn giao và tin nhắn vẫn gửi.")
        return result

    target, agent = _agent_seat(db, handoff.to_member_id)
    if target and target.member_type != "agent":
        result["reason"] = SKIP_TARGET_IS_HUMAN
        result["note"] = (f"{target.name} là nhân sự người. Bàn giao đã vào hộp "
                          "thư của họ; hệ thống không tự làm việc thay người.")
        return result
    if not agent:
        result["reason"] = SKIP_NO_SEAT
        result["note"] = ("Người nhận là agent nhưng chưa có seat runtime đang "
                          "hoạt động, nên không giao được. Kiểm tra "
                          "`runtime_agent_id` và `lifecycle` của seat.")
        return result

    wants = settings.openclaw_auto_dispatch if dispatch is None else dispatch
    if not wants:
        result["reason"] = SKIP_DISABLED
        result["note"] = ("Auto-dispatch đang tắt (`openclaw_auto_dispatch`), nên "
                          "bàn giao chỉ được ghi sổ. Mỗi lượt chạy là một lời gọi "
                          "model có phí, nên bật nó là một quyết định phải nói ra. "
                          "Truyền `dispatch: true` để chạy lượt này.")
        return result

    task = db.get(Task, handoff.task_id)
    result["reassign"] = reassign_task(db, task, handoff.to_member_id)

    # Nhận bàn giao đi qua chính hàm của v10, không tự đặt status.
    if handoff.status in ("pending", "sent"):
        try:
            accept_handoff(db, handoff, member_id=handoff.to_member_id)
            result["accepted"] = True
        except ValueError as exc:
            result["accepted"] = False
            result["accept_error"] = str(exc)

    try:
        task = await dispatch_task(db, task)
    except DispatchError as exc:
        result["reason"] = "dispatch_error"
        result["error"] = str(exc)
        result["note"] = ("Ghi sổ xong nhưng không giao được việc. Bàn giao "
                          "không mất: người thật dispatch tay vẫn được, và gói "
                          "ngữ cảnh sẽ mang hướng dẫn bàn giao theo.")
        return result

    result.update({
        "dispatched": True,
        "reason": "ok",
        "runtime_run_id": task.runtime_run_id,
        "runtime_session_key": task.runtime_session_key,
        "task_status": task.status,
    })

    emit_event(db, organization_id=handoff.organization_id, company_id=None,
               event_type="artifact.handoff.dispatched", source=SOURCE,
               aggregate_type="artifact_handoff", aggregate_id=str(handoff.id),
               actor_member_id=handoff.from_member_id,
               payload={"handoff_id": handoff.id, "task_id": task.id,
                        "to_member_id": handoff.to_member_id,
                        "runtime_run_id": task.runtime_run_id})
    return result
