"""D3.5 — Hộp việc của **người**: gộp theo task, approval hết hạn thì leo thang.

Năm nguồn ghi vào ``inbox_items``: approval đang chờ (``approval_pending``),
run lỗi (``run_failed``), task vào review (``task_review``), @mention
(``mention``), ngân sách chạm nấc (``budget_warned``/``budget_exhausted``); và
``approval_escalated`` khi approval quá hạn được chuyển lên quản lý.

- **Agent không đọc inbox**: người nhận là seat agent thì báo được chuyển lên
  người quản lý gần nhất là người (``human_recipients``).
- **Gộp theo task**: mỗi (người nhận, ``group_key``) chỉ có một dòng còn mở
  (unread/read). Báo mới cho cùng việc cộng ``count``, thêm loại vào ``kinds``,
  thêm một dòng vào ``body`` (giữ 10 dòng gần nhất) và đặt lại ``unread``.
- **Approval**: mọi chỗ tạo ``Approval`` (gateway, chặng duyệt D2.2, tool,
  API…) đều đi qua hook ORM ``after_flush``/``after_flush_postexec`` ở cuối file
  — đặt ``expires_at``/``escalate_to_member_id`` mặc định và ghi inbox; khi
  approval có kết quả thì dòng inbox tương ứng được đóng.
- ``escalate_overdue`` (Celery beat ``approvals.escalate_overdue``, hoặc vòng
  trong tiến trình API) chuyển approval quá hạn lên quản lý, ghi audit
  ``approval.escalated``.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from typing import Iterable

from sqlalchemy import event
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import Approval, Member, Task
from app.models.extended import InboxItem

KINDS = ("approval_pending", "approval_escalated", "run_failed", "task_review", "mention",
         "budget_warned", "budget_exhausted", "routine_paused", "goal_completed")
KIND_VI = {
    "approval_pending": "Chờ duyệt", "approval_escalated": "Duyệt quá hạn — chuyển lên anh",
    "run_failed": "Run lỗi", "task_review": "Vào review", "mention": "Được nhắc tên",
    "budget_warned": "Ngân sách chạm nấc cảnh báo", "budget_exhausted": "Hết ngân sách",
    "routine_paused": "Routine tự dừng",
    "goal_completed": "Mục tiêu hoàn thành",
}
PRIO = {"low": 0, "normal": 1, "medium": 1, "high": 2, "urgent": 3}
OPEN = ("unread", "read")
MAX_BODY_LINES = 10
TASK_STAGE = re.compile(r"task_stage:t(\d+)")


# ------------------------------------------------------------------ người nhận


def human_recipients(db: Session, member_id: int | None, *, depth: int = 6) -> list[int]:
    """Người là chính họ; seat agent → người quản lý gần nhất là người."""
    seen, mid = set(), member_id
    while mid and mid not in seen and depth > 0:
        seen.add(mid); depth -= 1
        m = db.get(Member, mid)
        if m is None:
            return []
        if m.member_type == "human":
            return [m.id] if (m.status or "active") in ("active", "onboarding") else _up(db, m)
        mid = m.manager_id
    return []


def _up(db: Session, m: Member) -> list[int]:
    return human_recipients(db, m.manager_id) if m.manager_id else []


def manager_of(db: Session, member_id: int | None) -> int | None:
    """Quản lý là người của một người (hoặc của người quản lý seat agent)."""
    m = db.get(Member, member_id) if member_id else None
    if m is None or not m.manager_id:
        return None
    up = human_recipients(db, m.manager_id)
    return up[0] if up else None


def _top_humans(db: Session, organization_id: int, company_id: int | None) -> list[int]:
    q = db.query(Member.id).filter(Member.organization_id == organization_id, Member.member_type == "human",
                                   Member.status == "active", Member.manager_id.is_(None))
    if company_id:
        q = q.filter((Member.company_id == company_id) | (Member.company_id.is_(None)))
    return [i for (i,) in q.order_by(Member.id).limit(3).all()]


# ------------------------------------------------------------------ ghi


def notify(db: Session, *, organization_id: int, recipients: Iterable[int | None], kind: str, title: str,
           task_id: int | None = None, related_type: str = "", related_id: str = "",
           priority: str = "normal", line: str = "", source: str = "", commit: bool = True) -> list[InboxItem]:
    if kind not in KINDS:
        raise ValueError(f"kind phải là một trong {', '.join(KINDS)}")
    people: list[int] = []
    for r in recipients:
        for h in human_recipients(db, r):
            if h not in people:
                people.append(h)
    group = f"task:{task_id}" if task_id else (f"{related_type}:{related_id}" if related_type else kind)
    stamp = datetime.utcnow().strftime("%d/%m %H:%M")
    text = f"[{stamp}] {KIND_VI.get(kind, kind)}: {line or title}"[:400]
    out = []
    with db.no_autoflush:
        for rid in people:
            item = (db.query(InboxItem).filter(InboxItem.organization_id == organization_id,
                                               InboxItem.recipient_member_id == rid,
                                               InboxItem.group_key == group, InboxItem.status.in_(OPEN))
                    .order_by(InboxItem.id.desc()).first())
            if item is None:
                item = InboxItem(organization_id=organization_id, recipient_member_id=rid, source=source or kind,
                                 title=title[:220], item_type=kind, priority=priority, status="unread",
                                 related_type=related_type, related_id=str(related_id or ""), task_id=task_id,
                                 group_key=group, kinds=kind, count=1, body=text)
                db.add(item)
            else:
                kinds = [k for k in (item.kinds or "").split(",") if k]
                if kind not in kinds:
                    kinds.append(kind)
                item.kinds = ",".join(kinds)[:200]
                item.count = int(item.count or 1) + 1
                item.title, item.item_type, item.status = title[:220], kind, "unread"
                if PRIO.get(priority, 1) > PRIO.get(item.priority or "normal", 1):
                    item.priority = priority
                if related_type:
                    item.related_type, item.related_id = related_type, str(related_id or "")
                item.body = "\n".join(([text] + (item.body or "").splitlines())[:MAX_BODY_LINES])
                item.updated_at = datetime.utcnow()
                db.add(item)
            out.append(item)
    if commit:
        db.commit()
    return out


def public(item: InboxItem) -> dict:
    return {"id": item.id, "recipient_member_id": item.recipient_member_id, "title": item.title,
            "kind": item.item_type, "kinds": [k for k in (item.kinds or "").split(",") if k],
            "kinds_vi": [KIND_VI.get(k, k) for k in (item.kinds or "").split(",") if k],
            "count": item.count or 1, "priority": item.priority, "status": item.status, "task_id": item.task_id,
            "group_key": item.group_key, "related_type": item.related_type, "related_id": item.related_id,
            "lines": (item.body or "").splitlines(), "source": item.source,
            "created_at": item.created_at.isoformat() if item.created_at else None,
            "updated_at": item.updated_at.isoformat() if item.updated_at else None}


# ------------------------------------------------------------------ nguồn: task / run / mention


def _org_of_task(db: Session, task: Task) -> int | None:
    from app.services.task_journal import _organization_of
    try:
        return _organization_of(db, task)
    except Exception:  # noqa: BLE001
        return None


def task_review(db: Session, task: Task) -> list[InboxItem]:
    """Task vào review: người duyệt của chặng hiện tại (nếu là người), không thì quản lý người làm."""
    try:
        org = _org_of_task(db, task)
        if org is None:
            return []
        from app.services import execution_policy
        st = execution_policy.current_stage(task) or {}
        doer = (task.execution_state or {}).get("doer_member_id") or task.assignee_member_id
        others = [db.get(Member, p) for p in (st.get("participants") or []) if p != doer]
        humans = [m.id for m in others if m is not None and m.member_type == "human"]
        if not humans and any(m is not None and m.member_type == "agent" for m in others):
            return []   # G5: reviewer là agent (review chéo) — người không bị ping, agent được đánh thức
        recipients = humans or ([manager_of(db, task.assignee_member_id)] if task.assignee_member_id else [])
        if not recipients:
            return []
        return notify(db, organization_id=org, recipients=recipients, kind="task_review",
                      title=f"Task #{task.id} chờ review: {task.title}", task_id=task.id,
                      related_type="task", related_id=str(task.id), source="task_lifecycle")
    except Exception as exc:  # noqa: BLE001
        db.rollback(); print(f"[D3.5] inbox task_review #{task.id} failed: {exc}")
        return []


def run_failed(db: Session, task: Task, why: str, *, member_id: int | None = None) -> list[InboxItem]:
    try:
        org = _org_of_task(db, task)
        mid = member_id or task.assignee_member_id
        if org is None or not mid:
            return []
        return notify(db, organization_id=org, recipients=[mid], kind="run_failed", priority="high",
                      title=f"Run lỗi ở task #{task.id}: {task.title}", line=f"task #{task.id}: {why}"[:300],
                      task_id=task.id, related_type="task", related_id=str(task.id), source="runtime")
    except Exception as exc:  # noqa: BLE001
        db.rollback(); print(f"[D3.5] inbox run_failed #{task.id} failed: {exc}")
        return []


def human_mentions(db: Session, organization_id: int, text: str, *, exclude: int | None = None) -> list[Member]:
    low = (text or "").lower()
    if "@" not in low:
        return []
    rows = db.query(Member).filter(Member.organization_id == organization_id, Member.member_type == "human").all()
    return [m for m in rows if m.id != exclude and m.name and f"@{m.name.lower()}" in low]


def mention(db: Session, task: Task, entry, organization_id: int) -> list[InboxItem]:
    try:
        people = human_mentions(db, organization_id, f"{entry.summary}\n{entry.detail or ''}",
                                exclude=entry.actor_member_id)
        if not people:
            return []
        who = db.get(Member, entry.actor_member_id) if entry.actor_member_id else None
        return notify(db, organization_id=organization_id, recipients=[m.id for m in people], kind="mention",
                      title=f"{who.name if who else 'Ai đó'} nhắc anh ở task #{task.id}: {task.title}",
                      line=f"{who.name if who else '—'}: {entry.summary}"[:300], task_id=task.id,
                      related_type="task", related_id=str(task.id), source="task_journal")
    except Exception as exc:  # noqa: BLE001
        db.rollback(); print(f"[D3.5] inbox mention failed: {exc}")
        return []


# ------------------------------------------------------------------ approval


def task_of_approval(a: Approval) -> int | None:
    m = TASK_STAGE.search(a.policy_key or "")
    if m:
        return int(m.group(1))
    try:
        ev = json.loads(a.evidence or "{}")
        tid = ev.get("task_id") if isinstance(ev, dict) else None
        return int(tid) if tid else None
    except Exception:  # noqa: BLE001
        return None


def approval_recipients(db: Session, a: Approval) -> list[int]:
    if a.approver_member_id:
        got = human_recipients(db, a.approver_member_id)
        if got:
            return got
    if a.requester_member_id:
        boss = manager_of(db, a.requester_member_id)
        req = db.get(Member, a.requester_member_id)
        if req is not None and req.member_type == "agent":
            boss = (human_recipients(db, req.manager_id) or [None])[0] if req.manager_id else None
        if boss:
            return [boss]
    return _top_humans(db, a.organization_id, a.company_id)


def _gateway_expiry(a: Approval) -> datetime | None:
    try:
        ms = (json.loads(a.evidence or "{}") or {}).get("expires_at_ms")
        return datetime.utcfromtimestamp(float(ms) / 1000.0) if ms else None
    except Exception:  # noqa: BLE001
        return None


def _on_new_approval(db: Session, a: Approval) -> None:
    if a.status != "pending":
        return
    now = datetime.utcnow()
    gateway = (a.policy_key or "").startswith("openclaw:")
    if a.expires_at is None:
        a.expires_at = _gateway_expiry(a) if gateway else now + timedelta(hours=float(settings.approval_ttl_hours))
    recipients = approval_recipients(db, a)
    if a.escalate_to_member_id is None and recipients and not gateway:
        a.escalate_to_member_id = manager_of(db, recipients[0])
    db.add(a)
    task_id = task_of_approval(a)
    notify(db, organization_id=a.organization_id, recipients=recipients, kind="approval_pending",
           title=f"Chờ duyệt: {a.action}"[:220], line=f"#{a.id} {a.action}"[:300], task_id=task_id,
           related_type="approval", related_id=str(a.id),
           priority="high" if (a.risk or "") in ("high", "critical") else "normal", source="approvals", commit=False)


def _on_resolved_approval(db: Session, a: Approval) -> None:
    with db.no_autoflush:
        items = db.query(InboxItem).filter(InboxItem.organization_id == a.organization_id,
                                           InboxItem.related_type == "approval", InboxItem.related_id == str(a.id),
                                           InboxItem.status.in_(OPEN)).all()
        for item in items:
            kinds = {k for k in (item.kinds or "").split(",") if k}
            item.body = "\n".join(([f"[{datetime.utcnow():%d/%m %H:%M}] Phê duyệt #{a.id}: {a.status}"]
                                   + (item.body or "").splitlines())[:MAX_BODY_LINES])
            if kinds <= {"approval_pending", "approval_escalated"}:
                item.status = "done"
            db.add(item)


def escalate_overdue(db: Session, *, now: datetime | None = None,
                     organization_id: int | None = None) -> list[dict]:
    """Approval quá hạn → chuyển cho quản lý; ghi audit ``approval.escalated``.

    Approval của gateway (``openclaw:``) không leo thang: gateway tự huỷ khi hết
    hạn của nó, chuyển lên chỉ cho quản lý một nút bấm vô hiệu."""
    from app.services.audit import log_event
    from app.services.company_event_bus import emit_event
    now = now or datetime.utcnow()
    ttl = timedelta(hours=float(settings.approval_ttl_hours))
    q = db.query(Approval).filter(Approval.status == "pending", Approval.expires_at.isnot(None),
                                  Approval.expires_at <= now)
    if organization_id is not None:
        q = q.filter(Approval.organization_id == organization_id)
    rows = q.order_by(Approval.id).all()
    out = []
    for a in rows:
        if (a.policy_key or "").startswith("openclaw:"):
            continue
        prev = a.approver_member_id
        primary = approval_recipients(db, a)
        target = a.escalate_to_member_id or (manager_of(db, primary[0]) if primary else None)
        if target is not None and target == prev:
            target = manager_of(db, prev)
        overdue_h = round((now - a.expires_at).total_seconds() / 3600 + float(settings.approval_ttl_hours), 1)
        if target is None:
            a.expires_at = now + ttl            # thử lại sau một chu kỳ, không spam audit mỗi phút
            db.add(a); db.commit()
            log_event(db, a.organization_id, "approval.escalation_failed", "approvals", str(a.id),
                      actor_name="system:approval-escalation", result="no_manager", risk=a.risk or "medium",
                      payload={"approver_member_id": prev, "reason": "không có quản lý để chuyển lên"})
            out.append({"approval_id": a.id, "escalated": False, "reason": "no_manager"})
            continue
        a.approver_member_id = target
        a.escalated_at = now
        a.expires_at = now + ttl
        a.escalate_to_member_id = manager_of(db, target)
        db.add(a); db.commit()
        payload = {"from_member_id": prev, "to_member_id": target, "pending_hours": overdue_h,
                   "next_escalate_to": a.escalate_to_member_id, "action": a.action}
        log_event(db, a.organization_id, "approval.escalated", "approvals", str(a.id),
                  actor_name="system:approval-escalation", result="success", risk=a.risk or "medium", payload=payload)
        emit_event(db, organization_id=a.organization_id, company_id=a.company_id, event_type="approval.escalated",
                   source="approvals", aggregate_type="approval", aggregate_id=str(a.id), payload=payload)
        notify(db, organization_id=a.organization_id, recipients=[target], kind="approval_escalated", priority="high",
               title=f"Quá hạn {overdue_h:g}h, chuyển lên anh: {a.action}"[:220],
               line=f"#{a.id} {a.action} (quá hạn, từ người duyệt #{prev or '—'})"[:300],
               task_id=task_of_approval(a), related_type="approval", related_id=str(a.id), source="approvals")
        out.append({"approval_id": a.id, "escalated": True, **payload})
    return out


async def escalate_forever(interval_seconds: float) -> None:
    import asyncio
    from app.db.session import SessionLocal
    while True:
        db = SessionLocal()
        try:
            escalate_overdue(db)
        except Exception as exc:  # noqa: BLE001
            print(f"[D3.5] escalate loop: {exc}")
        finally:
            db.close()
        await asyncio.sleep(interval_seconds)


# ------------------------------------------------------------------ hook ORM

_KEY = "_d35_approvals"


@event.listens_for(Session, "after_flush")
def _collect(session: Session, _ctx) -> None:
    try:
        from sqlalchemy import inspect
        todo = session.info.setdefault(_KEY, [])
        for obj in session.new:
            if isinstance(obj, Approval):
                todo.append(("new", obj))
        for obj in session.dirty:
            if isinstance(obj, Approval):
                hist = inspect(obj).attrs.status.history
                if hist.has_changes() and obj.status != "pending":
                    todo.append(("resolved", obj))
                elif hist.has_changes() and obj.status == "pending":
                    todo.append(("new", obj))   # D3.3: gửi lại sau yêu cầu sửa → báo lại, hạn mới
        if not todo:
            session.info.pop(_KEY, None)
    except Exception as exc:  # noqa: BLE001 — hook không được làm hỏng flush
        print(f"[D3.5] collect approvals failed: {exc}")


@event.listens_for(Session, "after_flush_postexec")
def _process(session: Session, _ctx) -> None:
    todo = session.info.pop(_KEY, None)
    if not todo:
        return
    for kind, obj in todo:
        try:
            with session.no_autoflush:
                if kind == "new":
                    _on_new_approval(session, obj)
                else:
                    _on_resolved_approval(session, obj)
        except Exception as exc:  # noqa: BLE001
            print(f"[D3.5] inbox hook for approval failed: {exc}")
