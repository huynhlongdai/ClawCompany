"""D3.1 — trưởng phòng định tuyến.

Việc có thể giao cho **phòng ban** (``tasks.assignee_department_id``) thay vì
một người. Khi đó trưởng phòng (``departments.head_member_id``) được đánh
thức với lý do ``routed`` và chạy một **lượt định tuyến**: phiên riêng
``agent:<id>:company-route-<task>``, gói ngữ cảnh riêng (giao thức định
tuyến, nhân sự phòng, hướng dẫn phòng), *không* giữ task (checkout) và *không*
đổi trạng thái task khi kết thúc. Việc duy nhất của lượt đó là gọi
``company_task_assign`` (ghi lý do), rồi dừng.

``should_wake_head`` là hàm **thuần** quyết định một sự kiện có đánh thức
trưởng phòng hay không (5 luật, xem docstring). Mọi quyết định giao việc nằm
trong ``company_events`` (``task.routed``), kèm lý do.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy.orm import Session

from app.models import Agent, Department, Member, Task, TaskRun, Wakeup
from app.models.work_graph import OPEN_RUN_STATUSES
from app.services.company_event_bus import emit_event

SOURCE = "routing"
ROUTE_SESSION = re.compile(r"company-route-(\d+)$")
COMMENT_KINDS = ("note", "result", "blocker", "decision")
UNROUTABLE = ("in_progress", "review", "done", "cancelled", "archived")


class RoutingError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


def route_session_key(runtime_agent_id: str, task_id: int) -> str:
    return f"agent:{runtime_agent_id}:company-route-{task_id}"


# ------------------------------------------------------------------ luật thuần


@dataclass(frozen=True)
class HeadEvent:
    """Một sự kiện trên việc của phòng.

    ``kind``: ``comment`` (một dòng sổ do member viết), ``reference`` (sự kiện
    chỉ tham chiếu tới việc: giao cho phòng, bàn giao, liên kết…).
    """
    kind: str
    head_member_id: int | None
    actor_member_id: int | None = None
    mentions: tuple[int, ...] = field(default_factory=tuple)
    pending: bool = False   # trưởng phòng đã có lý do routed đang chờ / lượt định tuyến đang mở


def should_wake_head(event: HeadEvent) -> tuple[bool, str]:
    """Năm luật, xét theo thứ tự:

    3. tự kích hoạt (người gây ra sự kiện là chính trưởng phòng) → không;
    5. đang có lượt chờ cho việc này → không (dedup);
    2. comment có @ → không (người được @ tự được đánh thức bằng ``mentioned``);
    1. comment không @ → đánh thức;
    4. sự kiện chỉ tham chiếu tới việc → đánh thức.
    """
    if not event.head_member_id:
        return False, "no_head"
    if event.actor_member_id is not None and event.actor_member_id == event.head_member_id:
        return False, "self_triggered"
    if event.pending:
        return False, "dedup_pending"
    if event.kind == "comment":
        if event.mentions:
            return False, "mention_routes_directly"
        return True, "comment_without_mention"
    if event.kind == "reference":
        return True, "task_reference"
    return False, f"unknown_kind: {event.kind}"


# ------------------------------------------------------------------ đọc


def department_of(db: Session, task: Task) -> Department | None:
    return db.get(Department, task.assignee_department_id) if task.assignee_department_id else None


def head_of(db: Session, department: Department | None) -> Member | None:
    if department is None or not department.head_member_id:
        return None
    return db.get(Member, department.head_member_id)


def pending_for(db: Session, head_id: int, task_id: int) -> bool:
    queued = db.query(Wakeup.id).filter(Wakeup.member_id == head_id, Wakeup.task_id == task_id,
                                        Wakeup.reason == "routed", Wakeup.status == "queued").first()
    if queued is not None:
        return True
    return open_routing_run(db, task_id, head_id) is not None


def open_routing_run(db: Session, task_id: int, member_id: int | None = None) -> TaskRun | None:
    q = db.query(TaskRun).filter(TaskRun.task_id == task_id, TaskRun.trigger_kind == "routed",
                                 TaskRun.status.in_(OPEN_RUN_STATUSES))
    if member_id is not None:
        q = q.filter(TaskRun.member_id == member_id)
    return q.order_by(TaskRun.id.desc()).first()


def run_for_session(db: Session, session_key: str) -> TaskRun | None:
    """Lượt định tuyến đang mở ứng với một phiên ``…:company-route-<task>``."""
    m = ROUTE_SESSION.search(session_key or "")
    if not m:
        return None
    return (db.query(TaskRun).filter(TaskRun.task_id == int(m.group(1)), TaskRun.trigger_kind == "routed",
                                     TaskRun.session_key == session_key)
            .order_by(TaskRun.id.desc()).first())


def roster(db: Session, department: Department) -> list[dict]:
    from sqlalchemy import func
    members = (db.query(Member).filter(Member.department_id == department.id)
               .order_by(Member.id).all())
    ids = [m.id for m in members]
    open_by = dict(db.query(TaskRun.member_id, func.count(TaskRun.id)).filter(
        TaskRun.member_id.in_(ids or [-1]), TaskRun.status.in_(OPEN_RUN_STATUSES),
        TaskRun.trigger_kind != "routed").group_by(TaskRun.member_id).all())
    open_tasks = dict(db.query(Task.assignee_member_id, func.count(Task.id)).filter(
        Task.assignee_member_id.in_(ids or [-1]), Task.status.in_(("todo", "in_progress", "review", "blocked")))
        .group_by(Task.assignee_member_id).all())
    return [{"id": m.id, "name": m.name, "role": m.role or "", "type": m.member_type, "status": m.status,
             "is_head": m.id == department.head_member_id, "open_runs": int(open_by.get(m.id, 0)),
             "open_tasks": int(open_tasks.get(m.id, 0))} for m in members]


# ------------------------------------------------------------------ đánh thức


def notify_head(db: Session, task: Task, *, kind: str, actor_member_id: int | None,
                mentions: tuple[int, ...] = (), source_key: str, cause: str = "") -> dict:
    """Áp ``should_wake_head`` cho một sự kiện trên việc của phòng; nếu cần thì xếp
    wakeup ``routed`` cho trưởng phòng. Không bao giờ ném."""
    try:
        dept = department_of(db, task)
        head = head_of(db, dept)
        ev = HeadEvent(kind=kind, head_member_id=head.id if head else None,
                       actor_member_id=actor_member_id, mentions=tuple(mentions),
                       pending=bool(head) and pending_for(db, head.id, task.id))
        wake, rule = should_wake_head(ev)
        out = {"wake": wake, "rule": rule, "head_member_id": ev.head_member_id, "wakeup_id": None}
        if wake and head is not None and head.member_type == "agent":
            from app.services import wakeup
            wk, _ = wakeup.enqueue(db, organization_id=head.organization_id, member_id=head.id,
                                   reason="routed", task_id=task.id, dedupe_key=f"routed:t{task.id}:{source_key}",
                                   payload={"rule": rule, "cause": cause, "by_member_id": actor_member_id,
                                            "department_id": dept.id if dept else None})
            out["wakeup_id"] = wk.id
        elif wake and head is not None:
            out["rule"] = rule + ":head_is_human"
        if dept is not None:
            emit_event(db, organization_id=_org(db, task, head), event_type="routing.head_wake",
                       source=SOURCE, aggregate_type="task", aggregate_id=str(task.id),
                       actor_member_id=actor_member_id,
                       payload={**out, "kind": kind, "cause": cause, "department_id": dept.id})
        return out
    except Exception as exc:  # noqa: BLE001 — thao tác gốc không được hỏng vì đánh thức
        db.rollback()
        print(f"[D3.1] notify head for task #{task.id} failed: {exc}")
        return {"wake": False, "rule": f"error: {exc}"}


def on_journal_entry(db: Session, task: Task, entry, mentions: list) -> None:
    """Gọi từ ``task_journal.append``: comment trên việc của phòng.

    Chỉ áp cho việc phòng đang giữ mà chưa có người nhận, hoặc comment là
    ``blocker`` (người nhận vướng → trưởng phòng có thể giao lại). Comment báo
    cáo cuối lượt của người nhận không đánh thức trưởng phòng.
    """
    if not task.assignee_department_id or entry.kind not in COMMENT_KINDS:
        return
    if task.assignee_member_id is not None and entry.kind != "blocker":
        return
    notify_head(db, task, kind="comment", actor_member_id=entry.actor_member_id,
                mentions=tuple(m.id for m in mentions), source_key=f"j{entry.id}",
                cause=f"comment {entry.kind} #{entry.seq}")


def _org(db: Session, task: Task, head: Member | None) -> int:
    if head is not None:
        return head.organization_id
    from app.services.task_journal import _organization_of
    return _organization_of(db, task)


# ------------------------------------------------------------------ ghi


def route_to_department(db: Session, task: Task, department_id: int, *, organization_id: int,
                        actor_member_id: int | None = None, reason: str = "") -> dict:
    """Giao việc cho phòng: phòng giữ việc, chưa có người nhận; đánh thức trưởng phòng."""
    dept = db.get(Department, department_id)
    if dept is None or (dept.status or "active") != "active":
        raise RoutingError("not_found", f"Không thấy phòng #{department_id} đang hoạt động")
    from app.models import Company
    company = db.get(Company, dept.company_id)
    if company is None or company.organization_id != organization_id:
        raise RoutingError("not_found", f"Không thấy phòng #{department_id}")
    if task.status in UNROUTABLE:
        raise RoutingError("conflict", f"Việc đang {task.status}, không giao lại cho phòng được")
    previous = {"department_id": task.assignee_department_id, "member_id": task.assignee_member_id}
    task.assignee_department_id = dept.id
    task.assignee_member_id = None
    db.add(task); db.commit(); db.refresh(task)
    emit_event(db, organization_id=organization_id, company_id=dept.company_id,
               event_type="task.routed_to_department", source=SOURCE, aggregate_type="task",
               aggregate_id=str(task.id), actor_member_id=actor_member_id,
               payload={"task_id": task.id, "department_id": dept.id, "head_member_id": dept.head_member_id,
                        "reason": reason, "from": previous})
    wake = notify_head(db, task, kind="reference", actor_member_id=actor_member_id,
                       source_key=f"d{dept.id}:{datetime.utcnow().timestamp():.6f}",
                       cause="giao cho phòng")
    return {"task_id": task.id, "department_id": dept.id, "head_member_id": dept.head_member_id, "wake": wake}


def assign(db: Session, task: Task, *, actor: Member, member_id: int | None, reason: str,
           run: TaskRun | None = None) -> dict:
    """``company_task_assign``: trưởng phòng (hoặc seat điều hành không thuộc phòng
    nào) giao việc cho một người. ``member_id`` trống → chọn theo tải (D3.2)."""
    from app.services import dispatch_policy, task_journal
    from app.services import workspace_ops as ops
    from app.models import Project
    reason = (reason or "").strip()
    if len(reason) < 5:
        raise RoutingError("invalid_argument", "reason là bắt buộc (vì sao giao cho người này)")
    dept = department_of(db, task)
    is_head = dept is not None and dept.head_member_id == actor.id
    if not is_head and actor.department_id is not None:
        raise RoutingError("forbidden", "Chỉ trưởng phòng đang giữ việc này mới giao được")
    decision = None
    if member_id is None:
        decision = dispatch_policy.decide(db, actor.organization_id, task=task,
                                          department_id=dept.id if dept else None)
        if decision.member_id is None:
            dispatch_policy.record(db, actor.organization_id, decision, task=task, actor_member_id=actor.id)
            raise RoutingError("no_candidate", decision.reason)
        member_id = decision.member_id
    target = db.get(Member, member_id)
    if target is None or target.organization_id != actor.organization_id:
        raise RoutingError("not_found", f"Không thấy thành viên #{member_id}")
    if dept is not None and target.department_id != dept.id:
        raise RoutingError("forbidden", f"{target.name} không thuộc phòng {dept.name}")
    if target.status not in ("active", "onboarding"):
        raise RoutingError("conflict", f"{target.name} đang {target.status}")
    project = db.get(Project, task.project_id)
    previous = task.assignee_member_id
    try:
        ops.assign_task(db, task, project, actor.organization_id, assignee_member_id=target.id,
                        actor_member_id=actor.id)
    except Exception as exc:  # HTTPException từ workspace_ops
        raise RoutingError("conflict", getattr(exc, "detail", str(exc))) from exc
    if decision is not None:
        dispatch_policy.record(db, actor.organization_id, decision, task=task, actor_member_id=actor.id)
    db.refresh(task)
    # Sổ ghi: actor là trưởng phòng → luật "tự kích hoạt" chặn vòng tự gọi.
    task_journal.append(db, task, kind="decision", actor_member_id=actor.id,
                        summary=f"Giao cho {target.name}: {reason}"[:400],
                        runtime_run_id=run.runtime_run_id if run else "",
                        runtime_session_key=run.session_key if run else "")
    ev = emit_event(db, organization_id=actor.organization_id, company_id=target.company_id,
                    event_type="task.routed", source=SOURCE, aggregate_type="task",
                    aggregate_id=str(task.id), actor_member_id=actor.id,
                    payload={"task_id": task.id, "department_id": dept.id if dept else None,
                             "from_member_id": previous, "to_member_id": target.id, "reason": reason,
                             "by_member_id": actor.id, "run_id": run.id if run else None,
                             "auto_pick": decision.reason if decision else None})
    return {"task_id": task.id, "assignee_member_id": target.id, "assignee": target.name,
            "reason": reason, "event_id": ev.id, "auto_pick": decision.reason if decision else None}


# ------------------------------------------------------------------ lượt định tuyến


def routable(db: Session, task: Task, member_id: int) -> str:
    """Lý do *không* chạy lượt định tuyến (rỗng = chạy được)."""
    dept = department_of(db, task)
    if dept is None:
        return "not_department_task"
    if dept.head_member_id != member_id:
        return "not_department_head"
    if task.status in UNROUTABLE:
        return f"task_status: {task.status}"
    if open_routing_run(db, task.id) is not None:
        return "routing_run_open"
    return ""


def build_routing_pack(db: Session, task: Task, head: Member) -> dict:
    """Gói ngữ cảnh cho trưởng phòng: cùng 7 khối, nội dung khác ở khối 4, 5, 7."""
    from app.services import task_graph
    from app.services import work_context as wc
    dept = department_of(db, task)
    project, company = wc._tenant_of(db, task)
    b1 = wc._block1_identity(db, head)
    b1.lines.append(f"- Bạn là trưởng phòng {dept.name if dept else '—'}; việc này đang do phòng giữ.")
    b2 = wc._block2_task(task, task_graph.goal_line(db, task), task_graph.open_blockers(db, task.id))
    current = db.get(Member, task.assignee_member_id) if task.assignee_member_id else None
    b2.lines.append(f"- Người nhận hiện tại: {current.name if current else 'chưa có'}.")
    b3 = wc._block3_project(project, company, [])
    b4 = wc.Block(4, "Nhân sự phòng")
    for r in roster(db, dept) if dept else []:
        tag = " (bạn)" if r["is_head"] else ""
        b4.lines.append(f"- #{r['id']} {r['name']}{tag} — {r['role'] or 'chưa có mô tả vai'}; "
                        f"{r['type']}, {r['status']}, {r['open_tasks']} việc mở, {r['open_runs']} lượt đang chạy")
    if not b4.lines:
        b4.lines.append("- Phòng chưa có nhân sự nào.")
    b5 = wc.Block(5, "Hướng dẫn phòng")
    guide = (dept.guide or "").strip() if dept else ""
    b5.lines.extend([f"- {line.strip()}" for line in guide.splitlines() if line.strip()][:12]
                    or ["- Phòng chưa có hướng dẫn riêng; chọn theo vai và tải."])
    b6 = wc._block6_rules([], [], 0, wc._budget_lines(db, head, task))
    b7 = wc.Block(7, "Giao thức định tuyến")
    b7.lines.extend([
        "- Việc của bạn trong lượt này CHỈ là giao việc, không tự làm việc.",
        f"- Gọi `company_task_assign` với task_id={task.id}, member_id (người trong danh sách ở khối 4) "
        "và reason (vì sao người đó: vai, tải, kinh nghiệm). Bỏ member_id để hệ thống chọn theo tải.",
        "- Ghi đánh giá ngắn bằng `company_task_comment` (kind=decision) nếu cần nói thêm.",
        "- Rồi DỪNG. Không đổi trạng thái việc, không giao cho người ngoài phòng.",
    ])
    blocks = [b1, b2, b3, b4, b5, b6, b7]
    text = "\n\n".join(b.text() for b in blocks if b.text())
    return {"text": text, "chars": len(text), "kind": "routing",
            "blocks": [{"index": b.index, "title": b.title, "chars": b.chars, "lines": len(b.lines)} for b in blocks]}


async def dispatch_routing(db: Session, task: Task, head: Member, agent: Agent, *,
                           wakeup_id: int | None = None) -> TaskRun:
    from app.runtime.factory import get_runtime
    from app.services import task_lifecycle as lifecycle
    run = lifecycle.open_run(db, task, organization_id=head.organization_id, member_id=head.id,
                             trigger_kind="routed", wakeup_id=wakeup_id)
    session_key = route_session_key(agent.runtime_agent_id, task.id)
    pack = build_routing_pack(db, task, head)
    try:
        rt = await get_runtime().run_agent(
            runtime_agent_id=agent.runtime_agent_id, input_text=pack["text"], session_key=session_key,
            metadata={"company_task_id": task.id, "organization_id": head.organization_id,
                      "label": f"Định tuyến task #{task.id}", "purpose": "routing"})
    except Exception as exc:
        lifecycle.finish_run(db, run, "failed", error_reason=str(exc))
        raise
    run.status, run.started_at = "running", datetime.utcnow()
    run.runtime_run_id, run.session_key = rt.run_id or "", rt.session_key or session_key
    db.add(run); db.commit(); db.refresh(run)
    emit_event(db, organization_id=head.organization_id, event_type="routing.run_started", source=SOURCE,
               aggregate_type="task", aggregate_id=str(task.id), actor_member_id=head.id,
               payload={"run_id": run.id, "session_key": run.session_key, "pack_chars": pack["chars"]})
    return run


def finish_routing_run(db: Session, run: TaskRun, event: dict) -> TaskRun:
    """Lượt định tuyến kết thúc: đóng run, quyết toán ngân sách. Task giữ nguyên trạng thái."""
    from app.services import budget_scope
    from app.services import task_lifecycle as lifecycle
    state = str(event.get("state") or "")
    status = {"final": "succeeded", "completed": "succeeded", "error": "failed"}.get(state, "cancelled")
    lifecycle.finish_run(db, run, status, error_reason=str(event.get("errorMessage") or ""))
    try:
        db.refresh(run)
        budget_scope.settle_run(db, run, final=True)
        budget_scope.schedule_true_up(run.id)
    except Exception as exc:  # noqa: BLE001
        print(f"[D3.1] settle routing run #{run.id} failed: {exc}")
    task = db.get(Task, run.task_id)
    routed = task is not None and task.assignee_member_id is not None
    emit_event(db, organization_id=run.organization_id, event_type="routing.run_finished", source=SOURCE,
               aggregate_type="task", aggregate_id=str(run.task_id), actor_member_id=run.member_id,
               payload={"run_id": run.id, "state": state, "assigned": routed,
                        "assignee_member_id": task.assignee_member_id if task else None})
    if run.member_id:
        from app.services import wakeup
        try:
            wakeup.requeue_deferred(db, run.member_id, after_run_id=run.id)
        except Exception as exc:  # noqa: BLE001
            print(f"[D3.1] requeue after routing run #{run.id} failed: {exc}")
    return run
