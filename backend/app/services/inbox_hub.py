"""M4b — Hộp việc: một danh sách cho câu hỏi "có cần mình không?", duyệt một chạm.

Đọc gộp, không thêm bảng: ``inbox_items`` (D3.5, gộp theo task) + ``approvals``
đang chờ mà người đăng nhập được quyết. Ghi chỉ qua hai đường:

- ``decide`` — duyệt / từ chối một phê duyệt. Giành quyền quyết bằng UPDATE có
  điều kiện (``status='pending' AND revision=<bản đã xem>``) nên hai người (hoặc
  hai lần chạm) cùng bấm thì đúng một người thắng, người kia nhận 409
  ``already_decided``; nội dung đổi sau khi xem (kế hoạch được gửi lại) → 409
  ``stale_revision``. Chỉ người duyệt hiện tại (sau leo thang là cấp trên) được
  quyết; phê duyệt chưa có người duyệt → quản lý trở lên.
- ``set_status`` — đánh dấu đã đọc / xong một dòng của chính mình.

Hậu quả của quyết định đi đúng đường cũ: chặng duyệt (``task_stage:``) →
``execution_policy.on_approval_resolved``; kế hoạch Nina → ``strategy.on_resolved``;
chi tiếp ngân sách (``budget_soft:``) → đánh thức lại seat; gateway
(``openclaw:``) → ``approval_bridge.decide``; còn lại → đánh thức seat xin duyệt.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.core.authz import ROLE_ORDER, Principal
from app.models import Approval, Member, Task
from app.models.extended import InboxItem
from app.services import inbox
from app.services.work_board import WorkError

GROUPS = [
    ("approvals", "Cần anh duyệt"),
    ("review", "Cần anh xem"),
    ("budget", "Ngân sách"),
    ("lessons", "Bài học đề xuất"),   # M5: đề xuất bài học của agent chờ người duyệt
    ("updates", "Thông báo"),
]
GROUP_VI = dict(GROUPS)
REVIEW_KINDS = {"task_review", "run_failed"}
BUDGET_KINDS = {"budget_warned", "budget_soft_stopped", "budget_exhausted"}
LESSON_KINDS = {"lesson_proposal"}
RISK_VI = {"critical": "Nghiêm trọng", "high": "Cao", "medium": "Vừa", "low": "Thấp"}
STATUS_VI = {"approved": "duyệt", "rejected": "từ chối", "denied": "từ chối", "expired": "hết hiệu lực",
             "revision_requested": "yêu cầu sửa", "deciding": "xử lý", "pending": "chờ"}
KIND_OF = (("task_stage:", "stage", "Chặng duyệt của việc"), ("strategy:", "plan", "Kế hoạch của Nina"),
           ("budget_soft:", "budget", "Chi tiếp khi chạm nấc ngân sách"),
           ("openclaw:", "gateway", "Lệnh agent xin chạy (OpenClaw)"),
           ("lesson:", "lesson", "Bài học đề xuất ghi vào MEMORY.md"))


# ------------------------------------------------------------------ quyền


def is_manager(p: Principal) -> bool:
    return ROLE_ORDER.get(p.role, -1) >= ROLE_ORDER["manager"]


def deciders(db: Session, a: Approval) -> set[int]:
    """Người được quyết: người duyệt hiện tại; seat agent là người duyệt → người quản lý của seat."""
    if not a.approver_member_id:
        return set()
    out = {a.approver_member_id}
    m = db.get(Member, a.approver_member_id)
    if m is not None and m.member_type != "human":
        out |= set(inbox.human_recipients(db, a.approver_member_id))
    return out


def can_decide(db: Session, a: Approval, principal: Principal) -> bool:
    if a.status != "pending":
        return False
    allowed = deciders(db, a)
    if allowed:
        return principal.member_id is not None and principal.member_id in allowed
    return is_manager(principal)


# ------------------------------------------------------------------ đọc


def _kind(a: Approval) -> tuple[str, str]:
    for prefix, key, label in KIND_OF:
        if (a.policy_key or "").startswith(prefix):
            return key, label
    return "other", "Yêu cầu duyệt"


def _summary(a: Approval) -> str:
    raw = (a.evidence or "").strip()
    if raw.startswith("{"):
        try:
            ev = json.loads(raw)
        except Exception:  # noqa: BLE001
            return ""
        if isinstance(ev, dict):
            for k in ("summary", "command", "reason"):
                if isinstance(ev.get(k), str) and ev[k].strip():
                    return ev[k].strip()[:400]
            req = (ev.get("event") or {}).get("request") if isinstance(ev.get("event"), dict) else None
            if isinstance(req, dict) and req.get("command"):
                return str(req["command"])[:400]
        return ""
    return raw[:400]


def deadline_vi(seconds_left: int | None, escalate_to: str | None, escalated: bool) -> str:
    if seconds_left is None:
        return ""
    if seconds_left <= 0:
        if escalate_to:
            return f"Quá hạn — sắp chuyển lên {escalate_to}"
        return "Quá hạn — không có cấp trên để chuyển lên, cần anh quyết"
    h, m = seconds_left // 3600, seconds_left % 3600 // 60
    left = (f"{h} giờ " if h else "") + f"{m} phút"
    return f"Còn {left} để duyệt" + (" (đã được chuyển lên anh)" if escalated else "")


def approval_card(db: Session, a: Approval, principal: Principal, names: dict[int, str],
                  now: datetime | None = None) -> dict:
    now = now or datetime.utcnow()
    tid = inbox.task_of_approval(a)
    task = db.get(Task, tid) if tid else None
    left = int((a.expires_at - now).total_seconds()) if a.expires_at else None
    kind, kind_vi = _kind(a)
    esc_id = a.escalate_to_member_id or (None if (a.policy_key or "").startswith("openclaw:")
                                         else inbox.department_head_for(db, a, exclude=a.approver_member_id))
    esc_to = names.get(esc_id) if esc_id else None
    overdue = left is not None and left <= 0
    gateway = kind == "gateway"
    return {
        "id": a.id, "action": a.action, "kind": kind, "kind_vi": kind_vi, "risk": a.risk or "medium",
        "risk_vi": RISK_VI.get(a.risk or "medium", a.risk or ""), "status": a.status,
        "revision": a.revision or 1, "summary": _summary(a),
        "requester": names.get(a.requester_member_id) if a.requester_member_id else None,
        "approver": names.get(a.approver_member_id) if a.approver_member_id else None,
        "approver_member_id": a.approver_member_id,
        "can_decide": can_decide(db, a, principal),
        "task": {"id": task.id, "title": task.title, "status": task.status} if task else None,
        "expires_at": a.expires_at.isoformat() if a.expires_at else None, "seconds_left": left,
        "overdue": overdue, "escalated_at": a.escalated_at.isoformat() if a.escalated_at else None,
        "escalate_to": esc_to,
        # Quá hạn mà không có cấp trên: leo thang không làm được gì — nói thẳng thay vì im lặng.
        "escalation_blocked": overdue and not gateway and not esc_id,
        "deadline_vi": "" if gateway and left is None else deadline_vi(left, esc_to, bool(a.escalated_at)),
        "reject_needs_note": True,
        "grant_scopes": ["task", "seat", "department"] if kind == "budget" else [],
        "created_at": a.created_at.isoformat() if a.created_at else None,
    }


def group_of(kinds: set[str], actionable: bool) -> str:
    if kinds & LESSON_KINDS:
        return "lessons"
    if actionable:
        return "approvals"
    if kinds & REVIEW_KINDS:
        return "review"
    if kinds & BUDGET_KINDS:
        return "budget"
    return "updates"


def feed(db: Session, organization_id: int, principal: Principal, *, status: str = "open",
         group: str | None = None, member_id: int | None = None, department_id: int | None = None,
         now: datetime | None = None) -> dict:
    """Hộp việc của người đăng nhập, nhóm theo việc cần làm, kèm số đếm."""
    now = now or datetime.utcnow()
    me = principal.member_id
    names = {m.id: m.name for m in db.query(Member).filter(Member.organization_id == organization_id).all()}
    rows: list[InboxItem] = []
    if me is not None:
        q = db.query(InboxItem).filter(InboxItem.organization_id == organization_id,
                                       InboxItem.recipient_member_id == me)
        if status == "open":
            q = q.filter(InboxItem.status.in_(inbox.OPEN))
        elif status != "all":
            q = q.filter(InboxItem.status == status)
        rows = q.order_by(InboxItem.updated_at.desc(), InboxItem.id.desc()).limit(300).all()

    from app.models import Department
    depts = {d.id: d.name for d in db.query(Department).all()}
    pending = {a.id: a for a in db.query(Approval).filter(Approval.organization_id == organization_id,
                                                          Approval.status == "pending").all()}
    cards: list[dict] = []
    seen_approvals: set[int] = set()
    for item in rows:
        kinds = {k for k in (item.kinds or "").split(",") if k} or {item.item_type}
        appr, a = None, None
        if item.related_type == "approval" and str(item.related_id).isdigit():
            a = pending.get(int(item.related_id))
            if a is not None:
                appr = approval_card(db, a, principal, names, now)
                seen_approvals.add(a.id)
        actionable = bool(appr and appr["can_decide"])
        if a is not None and _kind(a)[0] == "lesson":
            kinds = kinds | LESSON_KINDS
        cards.append({**inbox.public(item), "key": f"item:{item.id}", "group": group_of(kinds, actionable),
                      "approval": appr, "task": _task(db, item.task_id),
                      **_subject(db, item.task_id, a, depts)})
    # Phê duyệt anh là người quyết nhưng không có dòng hộp việc (tạo trước D3.5, hoặc báo đi chỗ khác).
    if status in ("open", "all") and me is not None:
        for a in sorted(pending.values(), key=lambda x: x.id):
            if a.id in seen_approvals or me not in deciders(db, a):
                continue
            card = approval_card(db, a, principal, names, now)
            cards.append({**_subject(db, card["task"]["id"] if card["task"] else None, a, depts), "id": None, "key": f"approval:{a.id}", "title": f"Chờ duyệt: {a.action}"[:220],
                          "kind": "approval_pending", "kinds": ["approval_pending"],
                          "kinds_vi": [inbox.KIND_VI["approval_pending"]], "count": 1,
                          "priority": "high" if (a.risk or "") in ("high", "critical") else "normal",
                          "status": "unread", "task_id": card["task"]["id"] if card["task"] else None,
                          "group_key": f"approval:{a.id}", "related_type": "approval", "related_id": str(a.id),
                          "lines": [], "source": "approvals", "created_at": card["created_at"],
                          "updated_at": card["created_at"],
                          "group": "lessons" if card["kind"] == "lesson" else "approvals", "approval": card,
                          "task": card["task"]})

    def rank(c: dict):
        ap = c.get("approval") or {}
        return (c["status"] != "unread", not ap.get("overdue"), -inbox.PRIO.get(c.get("priority") or "normal", 1),
                -(_ts(c.get("updated_at"))))
    cards.sort(key=rank)
    counts = {
        "open": sum(1 for c in cards if c["status"] in inbox.OPEN),
        "unread": sum(1 for c in cards if c["status"] == "unread"),
        "need_action": sum(1 for c in cards if c["group"] in ("approvals", "review") and c["status"] in inbox.OPEN),
        "overdue": sum(1 for c in cards if (c.get("approval") or {}).get("overdue")),
        "by_group": {k: sum(1 for c in cards if c["group"] == k) for k, _ in GROUPS},
    }
    shown = [c for c in cards if (not group or c["group"] == group)
             and (member_id is None or (c.get("seat") or {}).get("id") == member_id)
             and (department_id is None or (c.get("department") or {}).get("id") == department_id)]
    return {"member_id": me, "linked": me is not None, "counts": counts,
            "groups": [{"key": k, "label": label, "items": [c for c in shown if c["group"] == k]}
                       for k, label in GROUPS if not group or k == group],
            "caps": {"escalate": is_manager(principal)}}


def _subject(db: Session, task_id: int | None, a: Approval | None, depts: dict[int, str]) -> dict:
    """Seat và phòng ban mà dòng này nói tới (người nhận việc, hoặc seat xin duyệt) — để lọc theo seat/phòng."""
    t = db.get(Task, task_id) if task_id else None
    mid = (t.assignee_member_id if t is not None else None) or (a.requester_member_id if a is not None else None)
    m = db.get(Member, mid) if mid else None
    dept_id = (m.department_id if m is not None else None) or (getattr(t, "assignee_department_id", None) if t else None)
    return {"seat": {"id": m.id, "name": m.name, "type": m.member_type} if m is not None else None,
            "department": {"id": dept_id, "name": depts.get(dept_id, "")} if dept_id else None}


def _ts(iso: str | None) -> float:
    try:
        return datetime.fromisoformat(iso).timestamp() if iso else 0.0
    except ValueError:
        return 0.0


def _task(db: Session, task_id: int | None) -> dict | None:
    t = db.get(Task, task_id) if task_id else None
    return {"id": t.id, "title": t.title, "status": t.status} if t else None


# ------------------------------------------------------------------ ghi


def set_status(db: Session, organization_id: int, principal: Principal, item_id: int, status: str) -> dict:
    if status not in ("unread", "read", "done"):
        raise WorkError(422, "bad_status", "Trạng thái chỉ được là chưa đọc, đã đọc hoặc xong")
    item = db.get(InboxItem, item_id)
    if item is None or item.organization_id != organization_id:
        raise WorkError(404, "not_found", "Không tìm thấy mục này trong hộp việc")
    if item.recipient_member_id not in (None, principal.member_id):
        raise WorkError(403, "not_yours", "Mục này thuộc hộp việc của người khác")
    item.status = status
    db.add(item); db.commit(); db.refresh(item)
    return inbox.public(item)


def mark_all_read(db: Session, organization_id: int, principal: Principal) -> int:
    if principal.member_id is None:
        return 0
    n = (db.query(InboxItem).filter(InboxItem.organization_id == organization_id,
                                    InboxItem.recipient_member_id == principal.member_id,
                                    InboxItem.status == "unread")
         .update({InboxItem.status: "read"}, synchronize_session=False))
    db.commit()
    return n


async def decide(db: Session, organization_id: int, principal: Principal, approval_id: int, *,
                 decision: str, note: str = "", expected_revision: int | None = None,
                 grant_scope: str | None = None) -> dict:
    a = db.get(Approval, approval_id)
    if a is None or a.organization_id != organization_id:
        raise WorkError(404, "not_found", "Không tìm thấy yêu cầu duyệt này")
    if decision not in ("approve", "reject"):
        raise WorkError(422, "bad_decision", "Chỉ có Duyệt hoặc Từ chối")
    _still_open(db, a, expected_revision)
    if not can_decide(db, a, principal):
        names = {m.id: m.name for m in db.query(Member).filter(Member.id.in_(list(deciders(db, a)) or [-1])).all()}
        who = names.get(a.approver_member_id) if a.approver_member_id else None
        raise WorkError(403, "not_the_approver",
                        f"Anh không phải người duyệt yêu cầu này — người duyệt hiện tại là {who}" if who
                        else "Chỉ quản lý trở lên được duyệt yêu cầu này",
                        approver_member_id=a.approver_member_id)
    note = (note or "").strip()
    if decision == "reject" and not note:
        raise WorkError(422, "note_required", "Ghi lý do từ chối để người gửi biết cần sửa gì")
    if grant_scope not in (None, "task"):
        if _kind(a)[0] != "budget":
            raise WorkError(422, "bad_grant_scope", "Chỉ phê duyệt chi tiếp ngân sách mới chọn được phạm vi seat / phòng")
        if grant_scope not in ("seat", "department"):
            raise WorkError(422, "bad_grant_scope", "Phạm vi chỉ được là việc này, cả seat hoặc cả phòng")
    me = principal.member_id
    status = "approved" if decision == "approve" else "rejected"
    rev = a.revision or 1

    if (a.policy_key or "").startswith("openclaw:"):
        # Giữ chỗ (khoá hàng tới khi bridge commit) rồi để bridge ghi + gửi gateway như D1.1.
        _claim(db, a, rev, values={"revision": Approval.revision})
        from app.services import approval_bridge
        try:
            out = await approval_bridge.decide(db, a, decision="approved" if status == "approved" else "denied",
                                               note=note, actor_member_id=me)
        except approval_bridge.ApprovalBridgeError as exc:
            raise WorkError(409, "gateway_error", f"Không gửi được quyết định lên OpenClaw: {exc}") from exc
        db.refresh(a)
        delivered = bool(out.get("delivered")) if isinstance(out, dict) else False
        msg = _done_vi(a)
        if not delivered:
            # Nói thẳng: quyết định chỉ nằm ở ClawCompany, lệnh của agent vẫn treo tới khi gateway hết hạn.
            msg += (" — nhưng CHƯA gửi được tới OpenClaw, lệnh của agent vẫn đang chờ "
                    f"({(out or {}).get('delivery_error') or 'không rõ lỗi'})")
        return {"approval_id": a.id, "status": a.status, "message": msg, "delivered": delivered}

    _claim(db, a, rev, values={"status": "deciding"})
    a.status = status
    a.resolution_note = note
    if grant_scope and _kind(a)[0] == "budget" and status == "approved":
        a.payload = {**(a.payload or {}), "grant_scope": grant_scope}
    if a.approver_member_id is None and me is not None:
        a.approver_member_id = me
    db.add(a); db.commit(); db.refresh(a)
    from app.services.runtime_stream import _audit
    _audit(db, a, "approval.decided", actor_member_id=me, actor_name="human", result=status,
           payload={"decision": status, "policy_key": a.policy_key, "via": "inbox", "revision": rev})
    extra = after_decision(db, a, me)
    db.refresh(a)
    return {"approval_id": a.id, "status": a.status, "message": _done_vi(a), **extra}


def _still_open(db: Session, a: Approval, expected_revision: int | None) -> None:
    if a.status != "pending":
        raise WorkError(409, "already_decided",
                        f"Yêu cầu này đã được {STATUS_VI.get(a.status, a.status)} — không cần quyết nữa",
                        current_status=a.status)
    if expected_revision is not None and int(expected_revision) != int(a.revision or 1):
        raise WorkError(409, "stale_revision",
                        f"Nội dung cần duyệt vừa đổi (bản {a.revision or 1}) — xem lại rồi quyết lần nữa",
                        current_revision=a.revision or 1)


def _claim(db: Session, a: Approval, rev: int, *, values: dict[str, Any]) -> None:
    """Giành quyền quyết: đúng một UPDATE thắng khi hai người bấm cùng lúc."""
    res = db.execute(update(Approval)
                     .where(Approval.id == a.id, Approval.status == "pending",
                            Approval.revision == rev)
                     .values(**values).execution_options(synchronize_session=False))
    if res.rowcount != 1:
        db.rollback()
        db.refresh(a)
        _still_open(db, a, rev)
        raise WorkError(409, "already_decided", "Yêu cầu này vừa được người khác quyết", current_status=a.status)


def _done_vi(a: Approval) -> str:
    return {"approved": "Đã duyệt", "rejected": "Đã từ chối", "denied": "Đã từ chối"}.get(a.status, a.status)


def after_decision(db: Session, a: Approval, actor_member_id: int | None) -> dict:
    key = a.policy_key or ""
    if key.startswith("task_stage:"):
        from app.services import execution_policy
        execution_policy.on_approval_resolved(db, a, actor_member_id=actor_member_id)
        return {"effect": "stage"}
    from app.services import strategy
    if strategy.is_strategy(a):
        try:
            strategy.on_resolved(db, a, actor_member_id=actor_member_id)
        except strategy.StrategyError as exc:
            raise WorkError(409, "plan_error", exc.message) from exc
        return {"effect": "plan"}
    if key.startswith("lesson:"):
        # M5 sẽ ghi bài học đã duyệt vào MEMORY.md của agent; M4b chỉ giữ chỗ cho luồng duyệt.
        return {"effect": "lesson", "applied": False}
    if key.startswith("budget_soft:"):
        from app.services import budget_scope
        return {"effect": "budget", **budget_scope.on_soft_decision(db, a)}
    from app.api.approvals import _wake_requester
    _wake_requester(db, a)
    return {"effect": "wake_requester"}


def escalate(db: Session, organization_id: int) -> dict:
    rows = inbox.escalate_overdue(db, organization_id=organization_id)
    ok = sum(1 for r in rows if r.get("escalated"))
    stuck = len(rows) - ok
    msg = (f"Đã chuyển {ok} yêu cầu quá hạn lên cấp trên" if ok else "Không có yêu cầu nào cần chuyển lên")
    if stuck:
        msg += f"; {stuck} yêu cầu quá hạn không có cấp trên để chuyển — người duyệt hiện tại vẫn phải quyết"
    return {"escalated": rows, "message": msg}
