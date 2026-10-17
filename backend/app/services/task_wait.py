"""W1 — việc CHỜ người không giữ chỗ chạy của ghế, và tiếp tục đúng phiên khi hết chờ (kiểu interrupt/resume).

Hai dạng chờ, cùng một sổ (``tasks.wait_kind / wait_ref / wait_since``):

1. **Chờ trong lượt** — agent xin chạy lệnh exec, gateway giữ lượt lại chờ người duyệt. Lượt vẫn mở trên gateway
   (không huỷ được mà không mất ngữ cảnh), nên ta chỉ đánh dấu ``task_runs.waiting_since`` → lượt không còn tính
   vào chỗ chạy của ghế, các lý do bị bỏ vì ghế bận được xếp lại ngay. Có quyết định → gateway tự chạy tiếp ĐÚNG
   lượt đó; ta xoá dấu chờ và lượt nhận lại chỗ (``seat_concurrency.resume_run``). Việc vẫn ``in_progress``.
2. **Chờ ngoài lượt** — agent xin duyệt nghiệp vụ (``company_approval_request`` → ``approval_required``) hoặc hỏi
   người (``company_task_status`` status=blocked, ``wait_for=human``) rồi kết thúc lượt. Lượt kết thúc thật
   (``completed``), việc sang ``blocked`` kèm ``wait_kind`` (KHÔNG sang review, không thẻ "run lỗi"), ghế rảnh.
   Có quyết định / câu trả lời → việc về ``todo`` + wakeup mang ``resume`` → drain gửi một tin NGẮN vào đúng phiên
   ``agent:<rid>:company-task-<id>`` (lịch sử phiên còn nguyên trên gateway = "điểm dừng"), không dựng lại gói 7 khối.

``wait_kind`` ∈ ``WAIT_KINDS``; W1 dùng ``human`` (duyệt / trả lời / review). ``children``/``external``/``budget``
để dành cho W3/W7/W2 — đã có trong từ vựng nhưng chưa có nguồn phát.
"""
from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy.orm import Session

from app.models import Member, Task, TaskRun
from app.models.work_graph import OPEN_RUN_STATUSES
from app.services.company_event_bus import emit_event

SOURCE = "task_wait"
WAIT_KINDS = ("human", "children", "external", "budget")


def is_waiting(task: Task | None) -> bool:
    return bool(task is not None and task.wait_kind)


def _org(db: Session, task: Task) -> int | None:
    from app.services.task_journal import _organization_of
    try:
        return _organization_of(db, task)
    except Exception:  # noqa: BLE001
        return None


def _emit(db: Session, task: Task, event_type: str, payload: dict, actor: int | None = None) -> None:
    org = _org(db, task)
    if org is None:
        return
    try:
        emit_event(db, organization_id=org, event_type=event_type, source=SOURCE, aggregate_type="task",
                   aggregate_id=str(task.id), actor_member_id=actor, payload={"task_id": task.id, **payload})
    except Exception as exc:  # noqa: BLE001
        db.rollback(); print(f"[W1] emit {event_type} #{task.id} failed: {exc}")


def _journal(db: Session, task: Task, summary: str, actor: int | None) -> None:
    from app.services import task_journal
    try:
        task_journal.append(db, task, kind="note", summary=summary[:390],
                            actor_member_id=actor or task.assignee_member_id)
    except Exception as exc:  # noqa: BLE001 — sổ hỏng không được chặn luồng chờ
        db.rollback(); print(f"[W1] journal #{task.id} failed: {exc}")


def open_run_of(db: Session, task: Task) -> TaskRun | None:
    return (db.query(TaskRun).filter(TaskRun.task_id == task.id, TaskRun.status.in_(OPEN_RUN_STATUSES))
            .order_by(TaskRun.id.desc()).first())


def begin(db: Session, task: Task, *, kind: str, ref: str, run: TaskRun | None = None, in_turn: bool = False,
          note: str = "", actor_member_id: int | None = None, now: datetime | None = None) -> bool:
    """Bắt đầu chờ. Idempotent theo ``ref``. ``in_turn`` = lượt còn mở trên gateway (exec chờ duyệt)."""
    if kind not in WAIT_KINDS:
        raise ValueError(f"wait_kind phải là một trong {', '.join(WAIT_KINDS)}")
    now = now or datetime.utcnow()
    if task.wait_ref == ref and task.wait_kind == kind:
        fresh = False
    else:
        task.wait_kind, task.wait_ref, task.wait_since = kind, ref[:64], now
        db.add(task); db.commit(); db.refresh(task)
        fresh = True
    released = False
    if in_turn and run is not None:
        from app.services import seat_concurrency
        released = seat_concurrency.mark_waiting(db, run, now=now)
    if fresh:
        _journal(db, task, f"Đang chờ người ({ref})" + (f": {note}" if note else "")
                 + (" — lượt tạm dừng trên gateway, ghế được nhả" if in_turn else " — sẽ tiếp tục đúng phiên này"),
                 actor_member_id)
        _emit(db, task, "task.waiting", {"kind": kind, "ref": ref, "in_turn": in_turn,
                                         "run_id": run.id if run is not None else None, "note": note[:300]},
              actor_member_id)
    if released and run is not None and run.member_id:
        # ghế vừa có chỗ: các lý do bị bỏ vì ghế bận được xếp lại ngay (không đợi lượt đang chờ kết thúc)
        from app.services import wakeup
        try:
            wakeup.requeue_deferred(db, run.member_id, after_run_id=run.id, suffix=f"wait-{run.id}")
        except Exception as exc:  # noqa: BLE001
            print(f"[W1] requeue after wait of run #{run.id} failed: {exc}")
    return fresh or released


def _clear(db: Session, task: Task) -> None:
    task.wait_kind, task.wait_ref, task.wait_since = None, None, None
    db.add(task)


def end(db: Session, task: Task, ref: str, *, outcome: dict | None = None, actor_member_id: int | None = None,
        now: datetime | None = None) -> dict | None:
    """Hết chờ ``ref``. Trả cách tiếp tục: ``in_turn`` (gateway chạy tiếp lượt cũ), ``in_run`` (agent còn trong
    lượt — chỉ đánh thức sau), ``resume`` (việc về todo + wakeup mang ``resume`` vào đúng phiên); None nếu việc
    không chờ ``ref`` này."""
    if task is None or task.wait_ref != ref:
        return None
    now = now or datetime.utcnow()
    outcome = dict(outcome or {})
    kind = task.wait_kind
    waited = int((now - task.wait_since).total_seconds()) if task.wait_since else None
    run = open_run_of(db, task)
    _clear(db, task)
    info = {"kind": kind, "ref": ref, "waited_seconds": waited, **outcome}
    if run is not None and run.waiting_since is not None:
        from app.services import seat_concurrency
        seat_concurrency.resume_run(db, run, now=now, commit=False)
        db.commit(); db.refresh(task)
        mode = "in_turn"
    elif run is not None:
        db.commit(); db.refresh(task)
        mode = "in_run"
        _wake(db, task, ref, info, outcome)
    else:
        from app.services import task_lifecycle as lifecycle
        db.commit(); db.refresh(task)
        if task.status == "blocked":
            lifecycle.transition(db, task, "todo", system=True, via="wait",
                                 reason=f"hết chờ {ref}", actor_member_id=actor_member_id)
        mode = "resume"
        _wake(db, task, ref, info, outcome)
    _journal(db, task, f"Hết chờ ({ref})" + (f": {outcome.get('decision')}" if outcome.get("decision") else "")
             + (f" — chờ {waited // 60} phút" if waited else ""), actor_member_id)
    _emit(db, task, "task.resumed", {**info, "mode": mode, "run_id": run.id if run is not None else None},
          actor_member_id)
    return {"mode": mode, **info}


def _wake(db: Session, task: Task, ref: str, info: dict, outcome: dict) -> None:
    from app.services import wakeup
    reason = "input_received" if ref.startswith("question:") else "approval_resolved"
    wakeup.enqueue_for_task(db, task, reason, dedupe_key=f"resume:t{task.id}:{ref}:{outcome.get('decision') or 'x'}",
                            payload={"resume": {k: v for k, v in info.items() if v is not None}})


def end_for_approval(db: Session, approval, *, actor_member_id: int | None = None) -> dict | None:
    """Phê duyệt có kết quả → việc nào đang chờ đúng phê duyệt này thì hết chờ."""
    ref = f"approval:{approval.id}"
    task = db.query(Task).filter(Task.wait_ref == ref).first()
    if task is None:
        return None
    decision = {"approved": "approved", "approved_always": "approved", "rejected": "rejected",
                "denied": "rejected"}.get(approval.status or "", approval.status or "")
    note = (approval.resolution_note or "").replace("[sending to OpenClaw]", "").strip()
    return end(db, task, ref, outcome={"decision": decision, "note": note[:500], "approval_id": approval.id,
                                       "action": (approval.action or "")[:200]},
               actor_member_id=actor_member_id)


def on_turn_end(db: Session, task: Task) -> bool:
    """Lượt kết thúc bình thường (``final``) trong khi việc đang chờ người → giữ chờ, việc sang ``blocked``."""
    if not is_waiting(task):
        return False
    if task.wait_ref and task.wait_ref.startswith("approval:"):
        from app.models import Approval
        a = db.get(Approval, int(task.wait_ref.split(":", 1)[1]))
        if a is not None and a.status != "pending":   # đã quyết trong lúc agent còn trong lượt
            _clear(db, task); db.commit(); db.refresh(task)
            return False
    return True


def drop(db: Session, task: Task, why: str) -> None:
    """Lượt lỗi / bị huỷ / việc bị đóng → bỏ chờ (không tiếp tục được nữa)."""
    if not is_waiting(task):
        return
    ref = task.wait_ref
    _clear(db, task); db.commit(); db.refresh(task)
    _emit(db, task, "task.wait_dropped", {"ref": ref, "why": why[:200]})


# ------------------------------------------------------------------ hỏi người (wait_for=human)


def ask_human(db: Session, task: Task, member: Member, question: str, *, run: TaskRun | None = None) -> dict:
    """Agent hỏi người (thiếu thông tin) → thẻ Hộp việc cho người chịu trách nhiệm + chờ ``question:<inbox id>``."""
    from app.services import inbox
    org = _org(db, task)
    to = inbox.manager_of(db, member.id)
    items = inbox.notify(db, organization_id=org, recipients=[to] if to else [], kind="agent_question",
                         priority="high", title=f"{member.name} hỏi ở việc #{task.id}: {task.title}"[:220],
                         line=question[:300], task_id=task.id, related_type="task", related_id=str(task.id),
                         source="task_wait", company_id=member.company_id) if org else []
    ref = f"question:{items[0].id}" if items else f"question:t{task.id}"
    begin(db, task, kind="human", ref=ref, run=run, note=question[:300], actor_member_id=member.id)
    return {"wait_ref": ref, "inbox_item_ids": [i.id for i in items], "recipient_member_id": to}


def answer(db: Session, task: Task, text: str, *, actor_member_id: int | None, actor_name: str = "") -> dict | None:
    """Người trả lời câu hỏi của agent → hết chờ, agent nhận câu trả lời trong đúng phiên."""
    if not is_waiting(task) or not (task.wait_ref or "").startswith("question:"):
        return None
    ref = task.wait_ref
    out = end(db, task, ref, outcome={"decision": "answered", "answer": text[:4000], "by": actor_name[:120]},
              actor_member_id=actor_member_id)
    if ref.split(":", 1)[1].isdigit():
        from app.models import InboxItem
        it = db.get(InboxItem, int(ref.split(":", 1)[1]))
        if it is not None and it.status in ("unread", "read"):
            it.status = "done"; db.add(it); db.commit()
    return out


# ------------------------------------------------------------------ tin tiếp tục


def resume_text(task: Task, resume: dict) -> str:
    """Tin ngắn gửi vào đúng phiên của việc khi hết chờ — lịch sử phiên là điểm dừng, không gửi lại gói ngữ cảnh."""
    ref = str(resume.get("ref") or "")
    d = str(resume.get("decision") or "")
    head = f"[Tiếp tục việc #{task.id} — {task.title}]"
    if ref.startswith("approval:"):
        verdict = {"approved": "ĐÃ ĐƯỢC DUYỆT", "rejected": "BỊ TỪ CHỐI"}.get(d, d or "đã có kết quả")
        lines = [head, f"Yêu cầu duyệt #{resume.get('approval_id') or ref.split(':', 1)[1]}"
                       + (f" ({resume['action']})" if resume.get("action") else "") + f": {verdict}."]
        if resume.get("note"):
            lines.append(f"Ghi chú của người duyệt: {resume['note']}")
        lines.append("Làm tiếp từ đúng chỗ đã dừng trong phiên này." if d == "approved" else
                     "Không thực hiện hành động đó. Làm tiếp phần còn lại hoặc đề xuất hướng khác, rồi báo kết quả.")
    elif ref.startswith("question:"):
        lines = [head, f"Câu trả lời{(' của ' + resume['by']) if resume.get('by') else ''}: {resume.get('answer') or ''}",
                 "Làm tiếp từ đúng chỗ đã dừng trong phiên này."]
    else:
        lines = [head, f"Hết chờ ({ref}): {d}", "Làm tiếp từ đúng chỗ đã dừng trong phiên này."]
    return "\n".join(lines)


def public(task: Task, now: datetime | None = None) -> dict | None:
    if not is_waiting(task):
        return None
    now = now or datetime.utcnow()
    ref = task.wait_ref or ""
    return {"kind": task.wait_kind, "ref": ref,
            "on": ref.split(":", 1)[0] if ":" in ref else ref,
            "since": task.wait_since.isoformat() if task.wait_since else None,
            "minutes": int((now - task.wait_since).total_seconds() // 60) if task.wait_since else None}


def resume_from_payloads(payloads: list[str | None]) -> dict | None:
    for p in payloads:
        try:
            meta = json.loads(p or "{}")
        except ValueError:
            continue
        if isinstance(meta.get("resume"), dict):
            return meta["resume"]
    return None
