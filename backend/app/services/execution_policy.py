"""D2.2 — execution policy: các chặng review / approval trước khi task "done".

Quy tắc (đóng WP-4.4):

* Người làm báo xong (task vào ``review`` từ bất kỳ đường nào: run kết thúc,
  tool ``company_task_status``, API move) → chặng đầu bắt đầu.
* Chặng ``review``: chọn reviewer là participant đầu tiên **không phải người
  làm**. Reviewer là agent → đánh thức với lý do ``review_requested``; drain
  chạy một phòng họp 2 người (``room_conductor``, ``max_turns`` 4, reviewer
  làm chủ toạ) và đọc dòng ``QUYẾT ĐỊNH: DUYỆT`` / ``QUYẾT ĐỊNH: SỬA``.
  Reviewer là người → quyết qua ``POST /api/tasks/{id}/review``.
* Chặng ``approval``: tạo một hàng ``approvals`` (``policy_key``
  ``task_stage:...``) cho người duyệt; kết quả của hàng đó là quyết định.
* SỬA → mục ``review`` trong sổ, task về ``in_progress``, đánh thức người làm
  (``changes_requested``). DUYỆT → chặng kế; hết chặng → ``done``.
* ``done`` bị từ chối ở ``task_lifecycle`` khi policy chưa qua đủ chặng — mọi
  endpoint đều đi qua đó, nên không có đường vòng.
* Run kết thúc mà người làm không ghi comment nào trong sổ → cờ
  ``missing_report``, task sang ``blocked`` thay vì ``review``.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import Approval, Member, Task, TaskRun

STAGE_TYPES = ("review", "approval")
DECISIONS = ("approve", "revise")
REPORT_KINDS = ("note", "result", "decision", "blocker")
_DECISION_RE = re.compile(r"QUYẾT ĐỊNH:\s*(DUYỆT|SỬA)", re.IGNORECASE)


class PolicyError(HTTPException):
    def __init__(self, status: int, code: str, message: str, **extra: Any):
        super().__init__(status, {"error": code, "message": message, **extra})


# ---------------------------------------------------------------- pure helpers


def normalize(policy: dict | None) -> dict | None:
    """Kiểm và chuẩn hoá. ``None``/không có chặng = bỏ policy."""
    if not policy:
        return None
    stages = policy.get("stages") if isinstance(policy, dict) else None
    if not isinstance(stages, list):
        raise PolicyError(422, "invalid_policy", "stages phải là danh sách")
    if not stages:
        return None
    out = []
    for i, st in enumerate(stages):
        if not isinstance(st, dict) or st.get("type") not in STAGE_TYPES:
            raise PolicyError(422, "invalid_policy", f"chặng {i + 1}: type phải là review hoặc approval")
        parts = st.get("participants") or []
        if not isinstance(parts, list) or not parts or not all(isinstance(p, int) for p in parts):
            raise PolicyError(422, "invalid_policy", f"chặng {i + 1}: cần ít nhất một participant (member id)")
        out.append({"type": st["type"], "participants": list(dict.fromkeys(parts))})
    return {"stages": out}


def has_policy(task: Task) -> bool:
    return bool((task.execution_policy or {}).get("stages"))


def is_cleared(task: Task) -> bool:
    return not has_policy(task) or (task.execution_state or {}).get("status") == "approved"


def parse_decision(text: str) -> str | None:
    """``approve`` / ``revise`` từ dòng ``QUYẾT ĐỊNH:``; dòng cuối cùng thắng."""
    hits = _DECISION_RE.findall(text or "")
    if not hits:
        return None
    return "approve" if hits[-1].upper() == "DUYỆT" else "revise"


def guard_done(task: Task) -> None:
    """Gọi từ ``task_lifecycle`` trước mọi chuyển sang ``done``."""
    if is_cleared(task):
        return
    st = task.execution_state or {}
    stages = task.execution_policy["stages"]
    idx = int(st.get("stage_index") or 0)
    raise PolicyError(409, "execution_policy_pending",
                      f"Việc #{task.id} còn chặng {min(idx, len(stages) - 1) + 1}/{len(stages)} "
                      f"({'review' if stages[min(idx, len(stages) - 1)]['type'] == 'review' else 'phê duyệt'}) chưa qua"
                      " — chuyển sang Chờ duyệt để reviewer quyết, không đánh dấu Xong thẳng được",
                      stage_index=idx, state=st.get("status") or "not_started")


# ------------------------------------------------------------------- state


def _save(db: Session, task: Task, state: dict) -> None:
    task.execution_state = dict(state)  # gán mới để SQLAlchemy thấy JSON đổi
    db.add(task); db.commit(); db.refresh(task)


def _doer(task: Task, state: dict) -> int | None:
    return state.get("doer_member_id") or task.assignee_member_id


def current_stage(task: Task) -> dict | None:
    if not has_policy(task):
        return None
    st = task.execution_state or {}
    idx = int(st.get("stage_index") or 0)
    stages = task.execution_policy["stages"]
    return stages[idx] if idx < len(stages) else None


def is_current_reviewer(task: Task, member_id: int) -> bool:
    st = task.execution_state or {}
    return st.get("status") == "in_review" and st.get("reviewer_member_id") == member_id


def set_policy(db: Session, task: Task, policy: dict | None) -> Task:
    norm = normalize(policy)
    if norm:
        org = _org(db, task)
        for st in norm["stages"]:
            for mid in st["participants"]:
                m = db.get(Member, mid)
                if m is None or m.organization_id != org:
                    raise PolicyError(422, "invalid_participant", f"member #{mid} không thuộc tổ chức")
    if (task.execution_state or {}).get("status") == "in_review":
        raise PolicyError(409, "review_in_progress", "Không đổi policy khi đang có chặng chờ quyết")
    task.execution_policy = norm
    task.execution_state = {"status": "not_started", "round": 0, "history": []} if norm else None
    db.add(task); db.commit(); db.refresh(task)
    return task


def _org(db: Session, task: Task) -> int | None:
    from app.services.task_lifecycle import _tenant
    return _tenant(db, task)[0]


def on_submitted(db: Session, task: Task, *, actor_member_id: int | None = None) -> dict | None:
    """Task vừa vào ``review``: bắt đầu vòng mới từ chặng 1."""
    if not has_policy(task):
        return None
    st = dict(task.execution_state or {})
    st.update(status="in_review", stage_index=0, round=int(st.get("round") or 0) + 1,
              doer_member_id=task.assignee_member_id, missing_report=None,
              submitted_at=datetime.utcnow().isoformat())
    st.setdefault("history", [])
    _save(db, task, st)
    return start_stage(db, task)


def start_stage(db: Session, task: Task) -> dict:
    from app.services import wakeup
    st = dict(task.execution_state or {})
    stage = current_stage(task)
    doer = _doer(task, st)
    candidates = [m for m in stage["participants"] if m != doer]
    if not candidates:
        st.update(status="needs_reviewer", reviewer_member_id=None)
        _save(db, task, st)
        _emit(db, task, "task.review.no_reviewer", {"stage_index": st["stage_index"]})
        return st
    reviewer = candidates[0]
    st.update(reviewer_member_id=reviewer, approval_id=None)
    key = f"r{st['round']}:s{st['stage_index']}"
    if stage["type"] == "approval":
        org = _org(db, task)
        ap = Approval(organization_id=org, requester_member_id=doer, approver_member_id=reviewer,
                      action=f"Duyệt kết quả task #{task.id}: {task.title}"[:220], risk="medium",
                      policy_key=f"task_stage:t{task.id}:{key}", status="pending",
                      evidence=f"Chặng {st['stage_index'] + 1}, vòng {st['round']}")
        db.add(ap); db.commit(); db.refresh(ap)
        st["approval_id"] = ap.id
    _save(db, task, st)
    if stage["type"] == "review":
        wakeup.enqueue_for_task(db, task, "review_requested", member_id=reviewer,
                                dedupe_key=f"review_requested:t{task.id}:{key}",
                                payload={"stage_index": st["stage_index"], "round": st["round"]})
    _emit(db, task, "task.review.requested", {"stage_index": st["stage_index"], "round": st["round"],
                                              "type": stage["type"], "reviewer_member_id": reviewer,
                                              "approval_id": st.get("approval_id")})
    return st


def decide(db: Session, task: Task, *, member_id: int | None, decision: str, note: str = "",
           via: str = "api") -> dict:
    """Quyết định của reviewer cho chặng hiện tại."""
    from app.services import task_journal, task_lifecycle as lifecycle, wakeup
    if decision not in DECISIONS:
        raise PolicyError(422, "invalid_decision", "decision phải là approve hoặc revise")
    if not has_policy(task):
        raise PolicyError(409, "no_policy", "Task không có execution policy")
    st = dict(task.execution_state or {})
    if st.get("status") != "in_review" or task.status != "review":
        raise PolicyError(409, "not_in_review", "Task không có chặng nào đang chờ quyết")
    if member_id is None or member_id != st.get("reviewer_member_id"):
        raise PolicyError(403, "not_the_reviewer", "Chỉ reviewer của chặng này được quyết",
                          reviewer_member_id=st.get("reviewer_member_id"))
    if member_id == _doer(task, st):
        raise PolicyError(403, "self_review", "Người làm không được tự duyệt")
    stage = current_stage(task)
    entry = {"round": st["round"], "stage_index": st["stage_index"], "type": stage["type"],
             "reviewer_member_id": member_id, "decision": decision, "note": note[:2000], "via": via,
             "at": datetime.utcnow().isoformat()}
    st["history"] = [*(st.get("history") or []), entry]
    task_journal.append(db, task, kind="review",
                        summary=("DUYỆT" if decision == "approve" else "SỬA")
                        + f" — chặng {st['stage_index'] + 1} ({stage['type']}), vòng {st['round']}",
                        detail=note, actor_member_id=member_id,
                        outcome="success" if decision == "approve" else "partial")
    if decision == "revise":
        st.update(status="changes_requested", reviewer_member_id=None)
        _save(db, task, st)
        lifecycle.transition(db, task, "in_progress", system=True, via=f"execution_policy:{via}",
                             reason="changes_requested", actor_member_id=member_id)
        wakeup.enqueue_for_task(db, task, "changes_requested", member_id=_doer(task, st),
                                dedupe_key=f"changes_requested:t{task.id}:r{st['round']}:s{entry['stage_index']}",
                                payload={"note": note[:500], "round": st["round"]})
        _emit(db, task, "task.review.changes_requested", entry)
        return st
    nxt = st["stage_index"] + 1
    if nxt < len(task.execution_policy["stages"]):
        st.update(stage_index=nxt)
        _save(db, task, st)
        _emit(db, task, "task.review.stage_passed", entry)
        return start_stage(db, task)
    st.update(status="approved", stage_index=nxt, reviewer_member_id=None)
    _save(db, task, st)
    lifecycle.transition(db, task, "done", system=True, via=f"execution_policy:{via}",
                         reason="execution_policy_approved", actor_member_id=member_id)
    _emit(db, task, "task.review.approved", entry)
    return st


def on_approval_resolved(db: Session, ap: Approval, *, actor_member_id: int | None) -> dict | None:
    """Hàng ``task_stage:`` có kết quả → quyết định của chặng approval."""
    m = re.match(r"task_stage:t(\d+):r(\d+):s(\d+)$", ap.policy_key or "")
    if not m:
        return None
    task = db.get(Task, int(m.group(1)))
    if task is None:
        return None
    st = task.execution_state or {}
    if st.get("approval_id") != ap.id:
        return {"stale": True}
    return decide(db, task, member_id=actor_member_id,
                  decision="approve" if ap.status == "approved" else "revise",
                  note=ap.resolution_note or "", via="approval")


# ----------------------------------------------------------- missing report


def requires_report(task: Task) -> bool:
    return has_policy(task) or settings.require_run_report


def has_report(db: Session, task: Task, run: TaskRun | None) -> bool:
    from app.models import TaskJournalEntry
    q = db.query(TaskJournalEntry).filter(TaskJournalEntry.task_id == task.id,
                                          TaskJournalEntry.kind.in_(REPORT_KINDS))
    if run is not None:
        q = q.filter(TaskJournalEntry.actor_member_id == run.member_id)
        if run.started_at is not None:
            q = q.filter(TaskJournalEntry.created_at >= run.started_at)
    return db.query(q.exists()).scalar()


def flag_missing_report(db: Session, task: Task, run: TaskRun | None) -> None:
    st = dict(task.execution_state or {"history": []})
    st["missing_report"] = run.id if run else True
    _save(db, task, st)
    _emit(db, task, "task.report.missing", {"run_id": run.id if run else None})


# ------------------------------------------------------------- agent review


async def run_agent_review(db: Session, task: Task, reviewer: Member, runtime) -> dict:
    """Phòng 2 người, reviewer làm chủ toạ, tối đa 4 lượt; đọc ``QUYẾT ĐỊNH:``."""
    from app.services import collaboration_rooms as rooms, room_conductor
    st = task.execution_state or {}
    org = _org(db, task)
    key = f"review-t{task.id}-r{st.get('round')}-s{st.get('stage_index')}"
    from app.models.v16 import CollaborationRoom
    room = (db.query(CollaborationRoom).filter(CollaborationRoom.organization_id == org,
                                               CollaborationRoom.room_key == key).first())
    if room is None:
        room = rooms.open_room(db, organization_id=org, room_key=key, max_turns=4,
                               topic=f"Review task #{task.id}: {task.title}"[:200],
                               objective=("Xem kết quả của người làm theo tiêu chí nghiệm thu. Chủ toạ chốt "
                                          "bằng đúng một dòng 'QUYẾT ĐỊNH: DUYỆT' hoặc 'QUYẾT ĐỊNH: SỬA' "
                                          "kèm lý do. Tiêu chí: " + (task.acceptance_criteria or "(chưa ghi)")),
                               project_id=task.project_id, created_by_member_id=None,
                               seed_team_participants=False)
        rooms.join_room(db, room, member_id=reviewer.id, participant_role="lead", can_post=True,
                        can_decide=True, seat_order=1, emit=False)
        doer = _doer(task, st)
        if doer:
            rooms.join_room(db, room, member_id=doer, participant_role="contributor", can_post=True,
                            can_decide=False, seat_order=2, emit=False)
        room.chair_member_id = reviewer.id
        room.cost_budget_usd = settings.review_room_budget_usd
        db.add(room); db.commit(); db.refresh(room)
    out = await room_conductor.conduct(db, room, runtime, max_turns=4)
    # Đọc từ biên bản (room_turns), không từ bản xem trước 280 ký tự của kết quả.
    decision, text = None, ""
    for turn in rooms.transcript(db, room):
        if turn.member_id == reviewer.id and turn.turn_type == "decision":
            d = parse_decision(turn.content)
            if d:
                decision, text = d, turn.content
    if decision is None:
        st2 = dict(task.execution_state or {})
        st2["review_inconclusive"] = room.id
        _save(db, task, st2)
        _emit(db, task, "task.review.inconclusive", {"room_id": room.id, "stopped": out.get("stopped_reason")})
        return {"decision": None, "room_id": room.id, "stopped_reason": out.get("stopped_reason")}
    res = decide(db, task, member_id=reviewer.id, decision=decision, note=text[:2000], via="room")
    return {"decision": decision, "room_id": room.id, "state": res.get("status")}


def _emit(db: Session, task: Task, event_type: str, payload: dict) -> None:
    from app.services.company_event_bus import emit_event
    from app.services.task_lifecycle import _tenant
    org, company = _tenant(db, task)
    if org is None:
        return
    emit_event(db, organization_id=org, company_id=company, event_type=event_type, source="execution_policy",
               aggregate_type="task", aggregate_id=str(task.id), payload={"task_id": task.id, **payload})


def public(task: Task) -> dict:
    return {"task_id": task.id, "status": task.status, "policy": task.execution_policy,
            "state": task.execution_state, "cleared": is_cleared(task)}
