"""M4a — Công việc & lượt chạy: một nguồn cho danh sách, bảng, side-peek.

Trước M4a màn hình việc ghép từ 5 router (``/v17/workspace/tasks`` cho thẻ,
``/v27/tasks/{id}/move`` để kéo, ``/tasks/{id}/runs``, ``/tasks/{id}/journal``,
``/tasks/{id}/execution-policy``) — mỗi thẻ thiếu một thứ: không có chi phí,
không biết đang chạy, không biết ai review. File này gom về ``/api/work``.

Không có luật mới cho trạng thái: mọi chuyển vẫn đi qua ``task_lifecycle`` (CI
``lint_task_status.py``), mọi chặng review qua ``execution_policy``, mọi lượt
chạy qua ``wakeup`` (có cổng ngân sách) — ở đây chỉ đọc gộp và ghép lệnh.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.models import Agent, Company, Department, Member, Project, Task, TaskRun
from app.models.work_graph import OPEN_RUN_STATUSES
from app.services import task_lifecycle as lifecycle

STATUS_VI = lifecycle.STATUS_VI
PRIORITY_VI = {"urgent": "Khẩn", "high": "Cao", "medium": "Vừa", "low": "Thấp"}
PRIORITY_RANK = {"urgent": 0, "high": 1, "medium": 2, "low": 3}
RUN_STATUS_VI = {"queued": "Chờ chạy", "dispatched": "Đã gửi", "running": "Đang chạy", "completed": "Xong",
                 "failed": "Lỗi", "cancelled": "Đã huỷ", "skipped": "Bỏ qua"}
TRIGGER_VI = {"manual": "Giao tay", "assigned": "Được giao việc", "mentioned": "Được nhắc tên",
              "handoff": "Nhận bàn giao", "approval_resolved": "Có kết quả phê duyệt",
              "blocker_cleared": "Hết bị chặn", "review_requested": "Được nhờ review",
              "routine": "Việc định kỳ", "goal_created": "Mục tiêu mới", "changes_requested": "Bị yêu cầu sửa",
              "routed": "Trưởng phòng chọn người", "run_now": "Chạy ngay"}
REVIEW_STATE_VI = {"in_review": "Đang review", "changes_requested": "Được yêu cầu sửa", "approved": "Đã duyệt",
                   "needs_reviewer": "Thiếu người review"}
ENTRY_KIND_VI = {"attempt": "Bắt đầu làm", "result": "Kết quả", "review": "Review", "handoff": "Bàn giao",
                 "note": "Ghi chú", "decision": "Quyết định", "blocker": "Vướng"}


def _iso(v) -> str | None:
    return v.isoformat() if v else None


def _members(db: Session, ids) -> dict[int, Member]:
    ids = {i for i in ids if i}
    return {m.id: m for m in db.query(Member).filter(Member.id.in_(ids)).all()} if ids else {}


def _who(m: Member | None, agents: dict[int, Agent] | None = None) -> dict | None:
    if m is None:
        return None
    a = (agents or {}).get(m.id)
    return {"id": m.id, "name": m.name, "type": m.member_type, "role": m.role or "",
            "lifecycle": (a.lifecycle or "active") if a else None}


def _scope(db: Session, org_id: int):
    return (db.query(Task).join(Project, Project.id == Task.project_id)
            .join(Company, Company.id == Project.company_id).filter(Company.organization_id == org_id))


def revision(task: Task) -> str:
    from app.services import board_truth
    return board_truth.revision(task)


def review_of(task: Task, names: dict[int, Member]) -> dict:
    pol = task.execution_policy or {}
    st = task.execution_state or {}
    stages = pol.get("stages") or []
    rid = st.get("reviewer_member_id")
    status = st.get("status") or ("pending" if stages else None)
    return {"needed": bool(stages), "state": status, "state_vi": REVIEW_STATE_VI.get(status or "", "Chưa tới lượt review" if stages else ""),
            "round": int(st.get("round") or 0),
            "reviewer": _who(names.get(rid)) if rid else None,
            "reviewers": [_who(names.get(p)) or {"id": p, "name": f"#{p}"} for s in stages for p in s.get("participants") or []],
            "missing_report": bool(st.get("missing_report")),
            "inconclusive_room_id": st.get("review_inconclusive")}


# ------------------------------------------------------------------ danh sách / bảng


def list_items(db: Session, org_id: int, *, status: str | None = None, assignee: str | None = None,
               department_id: int | None = None, project_id: int | None = None, company_id: int | None = None,
               priority: str | None = None, q: str | None = None, me: int | None = None,
               include_closed: bool = True, limit: int = 500) -> dict:
    qry = _scope(db, org_id)
    if project_id:
        qry = qry.filter(Task.project_id == project_id)
    if company_id:
        qry = qry.filter(Project.company_id == company_id)
    if department_id:
        sub = db.query(Member.id).filter(Member.department_id == department_id)
        qry = qry.filter(or_(Task.assignee_department_id == department_id, Task.assignee_member_id.in_(sub)))
    if priority:
        qry = qry.filter(Task.priority.in_([p for p in priority.split(",") if p]))
    if assignee == "none":
        qry = qry.filter(Task.assignee_member_id.is_(None))
    elif assignee == "me" and me:
        qry = qry.filter(Task.assignee_member_id == me)
    elif assignee and assignee.isdigit():
        qry = qry.filter(Task.assignee_member_id == int(assignee))
    elif assignee in ("agent", "human"):
        qry = qry.filter(Task.assignee_member_id.in_(db.query(Member.id).filter(Member.member_type == assignee)))
    if q and q.strip():
        term = q.strip()
        qry = qry.filter(or_(Task.title.ilike(f"%{term}%"), Task.id == int(term.lstrip("#"))) if term.lstrip("#").isdigit()
                         else Task.title.ilike(f"%{term}%"))
    # Đếm theo trạng thái TRƯỚC khi lọc trạng thái: tab/cột luôn biết mình có bao nhiêu.
    counts = {s: 0 for s in lifecycle.TASK_STATUSES}
    for s, n in qry.with_entities(Task.status, func.count(Task.id)).group_by(Task.status).all():
        counts[s or "backlog"] = n
    if status:
        qry = qry.filter(Task.status.in_([s for s in status.split(",") if s]))
    elif not include_closed:
        qry = qry.filter(Task.status.in_(lifecycle.OPEN_TASK_STATUSES))
    tasks = qry.order_by(Task.id.desc()).limit(max(1, min(limit, 1000))).all()
    ids = [t.id for t in tasks]

    runs = defaultdict(lambda: {"count": 0, "cost_usd": 0.0, "tokens": 0, "running": False, "last_status": None,
                                "failed": 0})
    if ids:
        for tid, st, n, cost, ti, to in (db.query(TaskRun.task_id, TaskRun.status, func.count(TaskRun.id),
                                                  func.sum(TaskRun.cost_usd), func.sum(TaskRun.tokens_in),
                                                  func.sum(TaskRun.tokens_out))
                                         .filter(TaskRun.task_id.in_(ids)).group_by(TaskRun.task_id, TaskRun.status)):
            r = runs[tid]
            r["count"] += n; r["cost_usd"] += float(cost or 0); r["tokens"] += int(ti or 0) + int(to or 0)
            r["running"] = r["running"] or st in OPEN_RUN_STATUSES
            r["failed"] += n if st == "failed" else 0
        last = (db.query(TaskRun.task_id, func.max(TaskRun.id)).filter(TaskRun.task_id.in_(ids))
                .group_by(TaskRun.task_id).all())
        last_ids = {rid: tid for tid, rid in last}
        for r in db.query(TaskRun.id, TaskRun.status).filter(TaskRun.id.in_(list(last_ids))).all():
            runs[last_ids[r.id]]["last_status"] = r.status
        room_cost = _review_room_costs(db, org_id, ids)
        for tid, c in room_cost.items():
            runs[tid]["cost_usd"] += c

    names = _members(db, [t.assignee_member_id for t in tasks]
                     + [p for t in tasks for s in ((t.execution_policy or {}).get("stages") or [])
                        for p in s.get("participants") or []]
                     + [(t.execution_state or {}).get("reviewer_member_id") for t in tasks])
    agents = {a.member_id: a for a in db.query(Agent).filter(Agent.member_id.in_(list(names))).all()} if names else {}
    projects = {p.id: p for p in db.query(Project).filter(Project.id.in_({t.project_id for t in tasks})).all()} if tasks else {}
    companies = {c.id: c for c in db.query(Company).filter(Company.id.in_({p.company_id for p in projects.values()})).all()} if projects else {}
    dept_ids = {t.assignee_department_id for t in tasks} | {m.department_id for m in names.values()}
    depts = {d.id: d for d in db.query(Department).filter(Department.id.in_({i for i in dept_ids if i})).all()}
    blocked = _open_blocker_counts(db, ids)
    now = datetime.utcnow()
    items = []
    for t in tasks:
        p = projects.get(t.project_id)
        c = companies.get(p.company_id) if p else None
        who = names.get(t.assignee_member_id)
        dept = depts.get(t.assignee_department_id) or (depts.get(who.department_id) if who else None)
        r = runs[t.id]
        items.append({
            "id": t.id, "title": t.title, "status": t.status, "status_vi": STATUS_VI.get(t.status, t.status),
            "priority": t.priority, "priority_vi": PRIORITY_VI.get(t.priority, t.priority),
            "project": {"id": p.id, "name": p.name} if p else None,
            "company": {"id": c.id, "name": c.name} if c else None,
            "assignee": _who(who, agents), "department": {"id": dept.id, "name": dept.name} if dept else None,
            "routed_to_department": bool(t.assignee_department_id and not t.assignee_member_id),
            "due_at": _iso(t.due_at),
            "overdue": bool(t.due_at and t.due_at < now and t.status not in ("done", "cancelled")),
            "updated_at": _iso(t.updated_at), "created_at": _iso(t.created_at), "revision": revision(t),
            "parent_task_id": t.parent_task_id, "goal_id": t.goal_id,
            "runs": {**r, "cost_usd": round(r["cost_usd"], 6), "last_status_vi": RUN_STATUS_VI.get(r["last_status"] or "", "")},
            "review": review_of(t, names),
            "blocked_by": blocked.get(t.id, 0) if t.status not in ("done", "cancelled") else 0,
        })
    return {"items": items, "counts": counts, "total": sum(counts.values()), "statuses": statuses()}


def _open_blocker_counts(db: Session, ids: list[int]) -> dict[int, int]:
    from sqlalchemy.orm import aliased
    from app.models.work_graph import TaskDependency
    from app.services.task_graph import CLOSED_STATUSES
    if not ids:
        return {}
    blocker = aliased(Task)
    rows = (db.query(TaskDependency.task_id, func.count(TaskDependency.id))
            .join(blocker, blocker.id == TaskDependency.blocked_by_task_id)
            .filter(TaskDependency.task_id.in_(ids), blocker.status.not_in(CLOSED_STATUSES))
            .group_by(TaskDependency.task_id).all())
    return dict(rows)


def statuses() -> list[dict]:
    return [{"key": s, "label": STATUS_VI[s], "next": [{"key": n, "label": STATUS_VI[n]} for n in lifecycle.TASK_TRANSITIONS[s]]}
            for s in lifecycle.TASK_STATUSES]


def _review_room_costs(db: Session, org_id: int, task_ids: list[int]) -> dict[int, float]:
    """Chi phí các phòng review (room_key ``review-t{task}-r{n}-s{k}``) — lượt của reviewer
    không phải ``task_runs`` nên phải cộng riêng, nếu không thẻ báo rẻ hơn thật."""
    from app.models.v16 import CollaborationRoom
    from app.models.v37 import RoomConductorRun
    out: dict[int, float] = {}
    rows = (db.query(CollaborationRoom.room_key, func.sum(RoomConductorRun.cost_usd))
            .join(RoomConductorRun, RoomConductorRun.room_id == CollaborationRoom.id)
            .filter(CollaborationRoom.organization_id == org_id, CollaborationRoom.room_key.like("review-t%"))
            .group_by(CollaborationRoom.room_key).all())
    wanted = set(task_ids)
    for key, cost in rows:
        try:
            tid = int(key.split("-")[1][1:])
        except (IndexError, ValueError):
            continue
        if tid in wanted:
            out[tid] = out.get(tid, 0.0) + float(cost or 0)
    return out


# ------------------------------------------------------------------ side-peek

EVENT_VI = {"task.created": "Tạo việc", "task.assigned": "Giao việc", "task.routed_to_department": "Giao cho phòng",
            "task.review.requested": "Nhờ review", "task.review.changes_requested": "Review: yêu cầu sửa",
            "task.review.approved": "Review: duyệt", "task.review.stage_passed": "Qua một chặng review",
            "task.review.no_reviewer": "Thiếu người review", "task.review.inconclusive": "Review chưa ra quyết định",
            "task.report.missing": "Agent không ghi báo cáo", "task.routed": "Trưởng phòng giao việc",
            "task.dispatch_decided": "Quyết định chạy", "task.dispatched": "Gửi cho agent"}
VIA_VI = {"move": "kéo thẻ", "api": "API", "run_finished": "lượt chạy kết thúc", "tool": "agent tự báo"}


def _event_label(ev_type: str, payload: dict, names: dict[int, Member]) -> str:
    if ev_type in EVENT_VI:
        label = EVENT_VI[ev_type]
        if ev_type == "task.assigned" and payload.get("to"):
            label += f" cho {names[payload['to']].name}" if payload["to"] in names else ""
        if ev_type == "task.review.requested" and payload.get("reviewer_member_id") in names:
            label += f" {names[payload['reviewer_member_id']].name}"
        return label
    to = ev_type.split(".", 1)[1] if ev_type.startswith("task.") else ""
    if to in STATUS_VI:
        frm = payload.get("from")
        via = payload.get("via") or ""
        how = VIA_VI.get(via, via.replace("execution_policy:", "review ")) if via else ""
        return (f"{STATUS_VI.get(frm, frm)} → {STATUS_VI[to]}" if frm else f"→ {STATUS_VI[to]}") + (f" ({how})" if how else "")
    return ev_type


def detail(db: Session, org_id: int, task: Task) -> dict:
    import json
    from app.models.v10 import CompanyEvent
    from app.models.v16 import CollaborationRoom
    from app.models.v37 import RoomConductorRun, TaskJournalEntry
    from app.services import task_graph

    runs = db.query(TaskRun).filter(TaskRun.task_id == task.id).order_by(TaskRun.id).all()
    entries = (db.query(TaskJournalEntry).filter(TaskJournalEntry.task_id == task.id)
               .order_by(TaskJournalEntry.seq).limit(300).all())
    rooms = (db.query(CollaborationRoom).filter(CollaborationRoom.organization_id == org_id,
                                                CollaborationRoom.room_key.like(f"review-t{task.id}-%"))
             .order_by(CollaborationRoom.id).all())
    turns = (db.query(RoomConductorRun).filter(RoomConductorRun.room_id.in_([r.id for r in rooms]))
             .order_by(RoomConductorRun.id).all()) if rooms else []
    events = (db.query(CompanyEvent).filter(CompanyEvent.organization_id == org_id,
                                            CompanyEvent.aggregate_type == "task",
                                            CompanyEvent.aggregate_id == str(task.id))
              .order_by(CompanyEvent.id).limit(300).all())
    payloads = {}
    for ev in events:
        try:
            payloads[ev.id] = json.loads(ev.payload_json or "{}")
        except ValueError:
            payloads[ev.id] = {}
    pol = task.execution_policy or {}
    st = task.execution_state or {}
    ids = ([task.assignee_member_id] + [r.member_id for r in runs] + [e.actor_member_id for e in entries]
           + [t.speaker_member_id for t in turns] + [ev.actor_member_id for ev in events]
           + [p.get("to") for p in payloads.values()] + [p.get("reviewer_member_id") for p in payloads.values()]
           + [p for s in pol.get("stages") or [] for p in s.get("participants") or []]
           + [st.get("reviewer_member_id")] + [h.get("reviewer_member_id") for h in st.get("history") or []])
    names = _members(db, [i for i in ids if isinstance(i, int)])
    agents = {a.member_id: a for a in db.query(Agent).filter(Agent.member_id.in_(list(names))).all()} if names else {}

    by_run: dict[str, list] = defaultdict(list)
    loose = []
    run_keys = {r.runtime_run_id for r in runs if r.runtime_run_id}
    for e in entries:
        item = {"seq": e.seq, "kind": e.kind, "kind_vi": ENTRY_KIND_VI.get(e.kind, e.kind), "summary": e.summary,
                "detail": e.detail[:4000], "who": _who(names.get(e.actor_member_id)), "at": _iso(e.created_at),
                "outcome": e.outcome, "cost_usd": e.cost_usd}
        (by_run[e.runtime_run_id] if e.runtime_run_id in run_keys else loose).append(item)

    timeline: list[dict] = []
    for r in runs:
        dur = (r.ended_at - r.started_at).total_seconds() if r.started_at and r.ended_at else None
        timeline.append({"type": "run", "at": _iso(r.started_at or r.created_at), "id": r.id, "status": r.status,
                         "status_vi": RUN_STATUS_VI.get(r.status, r.status), "trigger": r.trigger_kind,
                         "trigger_vi": TRIGGER_VI.get(r.trigger_kind, r.trigger_kind), "who": _who(names.get(r.member_id), agents),
                         "started_at": _iso(r.started_at), "ended_at": _iso(r.ended_at), "duration_s": dur,
                         "cost_usd": round(r.cost_usd or 0, 6), "tokens_in": r.tokens_in or 0, "tokens_out": r.tokens_out or 0,
                         "error_reason": r.error_reason or "", "error_vi": explain_run_error(r.error_reason or ""),
                         "session_key": r.session_key, "runtime_run_id": r.runtime_run_id,
                         "holds_task": r.id == task.checkout_run_id, "entries": by_run.get(r.runtime_run_id, [])})
    for room in rooms:
        rt = [t for t in turns if t.room_id == room.id]
        parts = room.room_key.split("-")
        timeline.append({"type": "review_room", "at": _iso(rt[0].created_at if rt else room.created_at), "id": room.id,
                         "round": int(parts[2][1:]) if len(parts) > 2 and parts[2][1:].isdigit() else None,
                         "status": room.status, "turns": len(rt),
                         "cost_usd": round(sum(t.cost_usd or 0 for t in rt), 6),
                         "speakers": [{"who": _who(names.get(t.speaker_member_id), agents), "cost_usd": t.cost_usd,
                                       "session_key": t.runtime_session_key,
                                       "status": t.status, "elapsed_s": t.elapsed_seconds, "error": t.error}
                                      for t in rt]})
    for e in loose:
        timeline.append({"type": "entry", **e})
    for ev in events:
        p = payloads[ev.id]
        # task.journal.* trùng với mục sổ đã hiện ở trên (gate M4a: thẻ "task.journal.review" thô).
        if ev.event_type.startswith("task.") and not ev.event_type.startswith("task.journal."):
            timeline.append({"type": "event", "at": _iso(ev.occurred_at), "event": ev.event_type,
                             "label": _event_label(ev.event_type, p, names), "who": _who(names.get(ev.actor_member_id)),
                             "reason": p.get("reason") or ""})
    timeline.sort(key=lambda x: (x.get("at") or "", 0 if x["type"] == "event" else 1))

    run_cost = sum(r.cost_usd or 0 for r in runs)
    room_cost = sum(t.cost_usd or 0 for t in turns)
    project = db.get(Project, task.project_id)
    company = db.get(Company, project.company_id) if project else None
    dept = db.get(Department, task.assignee_department_id) if task.assignee_department_id else None
    who = names.get(task.assignee_member_id)
    if dept is None and who is not None and who.department_id:
        dept = db.get(Department, who.department_id)
    review = review_of(task, names)
    review["history"] = [{**h, "reviewer": _who(names.get(h.get("reviewer_member_id"))),
                          "decision_vi": "Duyệt" if h.get("decision") == "approve" else "Yêu cầu sửa"}
                         for h in st.get("history") or []]
    review["stages"] = pol.get("stages") or []
    blockers = task_graph.open_blockers(db, task.id)
    return {
        "id": task.id, "title": task.title, "description": task.description or "",
        "acceptance_criteria": task.acceptance_criteria or "", "status": task.status,
        "status_vi": STATUS_VI.get(task.status, task.status), "priority": task.priority,
        "priority_vi": PRIORITY_VI.get(task.priority, task.priority), "due_at": _iso(task.due_at),
        "created_at": _iso(task.created_at), "updated_at": _iso(task.updated_at), "revision": revision(task),
        "project": {"id": project.id, "name": project.name} if project else None,
        "company": {"id": company.id, "name": company.name} if company else None,
        "assignee": _who(who, agents), "department": {"id": dept.id, "name": dept.name} if dept else None,
        "routed_to_department": bool(task.assignee_department_id and not task.assignee_member_id),
        "next": [{"key": n, "label": STATUS_VI[n]} for n in lifecycle.TASK_TRANSITIONS.get(task.status or "backlog", ())],
        "blocked_by": [{"id": b.id, "title": b.title, "status": b.status, "status_vi": STATUS_VI.get(b.status, b.status)}
                       for b in blockers],
        "session_key": task.runtime_session_key,
        "totals": {"runs": len(runs), "failed": sum(1 for r in runs if r.status == "failed"),
                   "running": any(r.status in OPEN_RUN_STATUSES for r in runs),
                   "cost_usd": round(run_cost + room_cost, 6), "run_cost_usd": round(run_cost, 6),
                   "review_cost_usd": round(room_cost, 6),
                   "tokens_in": sum(r.tokens_in or 0 for r in runs), "tokens_out": sum(r.tokens_out or 0 for r in runs),
                   "review_rounds": review["round"]},
        "review": review, "timeline": timeline,
    }


def explain_run_error(reason: str) -> str:
    """Lý do lỗi của lượt chạy → một câu tiếng Việt kèm cách xử lý."""
    r = (reason or "").lower()
    if not r:
        return ""
    if "checkout lost" in r:
        return "Lượt khác đã nhận việc này trước — không cần làm gì."
    if "budget" in r or "hạn mức" in r:
        return "Hết hạn mức chi — nâng hạn mức trong Chi phí rồi chạy lại."
    if "abort" in r or "cancel" in r:
        return "Lượt bị dừng giữa chừng (tạm dừng agent hoặc huỷ tay) — chạy lại khi sẵn sàng."
    if "timeout" in r or "timed out" in r:
        return "Gateway không trả lời kịp — kiểm tra Lõi OpenClaw rồi chạy lại."
    if "missing_report" in r or "không ghi" in r:
        return "Agent làm xong nhưng không ghi báo cáo — nhắc agent ghi kết quả rồi chuyển Chờ duyệt."
    if "gateway" in r or "connect" in r or "websocket" in r:
        return "Mất kết nối gateway — mở Lõi OpenClaw, chạy kiểm tra, rồi chạy lại."
    return "Lượt chạy lỗi — xem chi tiết bên dưới, sửa nguyên nhân rồi bấm Chạy ngay."


# ------------------------------------------------------------------ lệnh ghi


class WorkError(HTTPException):
    def __init__(self, status: int, code: str, message: str, **extra: Any):
        super().__init__(status, {"error": code, "message": message, **extra})


def _parse_due(v) -> datetime | None:
    if v in (None, ""):
        return None
    if isinstance(v, datetime):
        return v
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return d.replace(tzinfo=None) if d.tzinfo is None else datetime.utcfromtimestamp(d.timestamp())
    except ValueError as exc:
        raise WorkError(422, "invalid_due", "Hạn chót không đúng định dạng ngày (YYYY-MM-DD)") from exc


def _active_member(db: Session, org_id: int, member_id: int, label: str) -> Member:
    m = db.get(Member, member_id)
    if m is None or m.organization_id != org_id:
        raise WorkError(404, "member_not_found", f"Không thấy {label} #{member_id} trong tổ chức")
    if m.status not in ("active", "onboarding"):
        raise WorkError(409, "member_inactive", f"{m.name} đang '{m.status}' — chọn người khác")
    if m.member_type == "agent":
        a = db.query(Agent).filter(Agent.member_id == m.id).first()
        if a is not None and (a.lifecycle or "active") != "active":
            from app.services.agent_hr import LIFECYCLE_VI
            raise WorkError(409, "agent_inactive",
                            f"{m.name} {LIFECYCLE_VI.get(a.lifecycle, a.lifecycle)} — chọn người khác hoặc cho agent làm tiếp")
    return m


def suggest_reviewer(db: Session, org_id: int, doer_id: int | None) -> Member | None:
    """Review chéo: trưởng phòng của người làm; không có thì đồng nghiệp agent cùng phòng; rồi quản lý."""
    doer = db.get(Member, doer_id) if doer_id else None
    if doer is None:
        return None
    cands: list[Member] = []
    if doer.department_id:
        d = db.get(Department, doer.department_id)
        if d and d.head_member_id:
            cands.append(db.get(Member, d.head_member_id))
        cands += (db.query(Member).filter(Member.department_id == doer.department_id, Member.id != doer.id,
                                          Member.member_type == "agent").order_by(Member.id).all())
    if doer.manager_id:
        cands.append(db.get(Member, doer.manager_id))
    for m in cands:
        if m is None or m.id == doer.id or m.organization_id != org_id or m.status != "active":
            continue
        a = db.query(Agent).filter(Agent.member_id == m.id).first() if m.member_type == "agent" else None
        if a is not None and (a.lifecycle or "active") != "active":
            continue
        return m
    return None


def set_review(db: Session, org_id: int, task: Task, reviewer_ids: list[int]) -> dict:
    """Đặt review chéo = một chặng ``review`` với các reviewer. ``[]`` bỏ review."""
    from app.services import execution_policy as ep
    st = task.execution_state or {}
    if task.status == "review" and st.get("status") == "in_review":
        raise WorkError(409, "review_in_progress",
                        "Việc đang được review — đợi reviewer quyết xong rồi mới đổi người review")
    clean: list[int] = []
    for rid in reviewer_ids:
        if rid in clean:
            continue
        if rid == task.assignee_member_id:
            raise WorkError(422, "self_review", "Review chéo: người làm không tự review việc của mình — chọn người khác")
        _active_member(db, org_id, rid, "người review")
        clean.append(rid)
    ep.set_policy(db, task, {"stages": [{"type": "review", "participants": clean}]} if clean else None)
    db.refresh(task)
    return review_of(task, _members(db, clean))


def create(db: Session, org_id: int, principal, data: dict) -> Task:
    from app.services import workspace_ops as ops
    from app.core.tenancy import ensure_project
    project = ensure_project(db, int(data["project_id"]), principal)
    title = (data.get("title") or "").strip()
    if not title:
        raise WorkError(422, "title_required", "Cần đặt tên cho việc")
    priority = data.get("priority") or "medium"
    if priority not in PRIORITY_VI:
        raise WorkError(422, "invalid_priority", "Ưu tiên phải là Khẩn / Cao / Vừa / Thấp")
    assignee = data.get("assignee_member_id")
    if assignee:
        _active_member(db, org_id, int(assignee), "người nhận")
    reviewers = [int(x) for x in data.get("reviewer_member_ids") or []]
    if assignee and int(assignee) in reviewers:
        raise WorkError(422, "self_review", "Review chéo: người làm không tự review việc của mình — chọn người khác")
    for rid in reviewers:
        _active_member(db, org_id, rid, "người review")
    task = ops.create_task(db, project, org_id, title=title, description=data.get("description") or "",
                           priority=priority, actor_member_id=principal.member_id)
    task.due_at = _parse_due(data.get("due_at"))
    task.acceptance_criteria = (data.get("acceptance_criteria") or "").strip()
    db.add(task); db.commit(); db.refresh(task)
    if reviewers:
        from app.services import execution_policy as ep
        ep.set_policy(db, task, {"stages": [{"type": "review", "participants": reviewers}]})
    start = bool(data.get("start", True))
    if start:
        lifecycle.transition(db, task, "todo", via="work", actor_member_id=principal.member_id,
                             organization_id=org_id, company_id=project.company_id)
    if assignee:
        if start:  # giao → seat agent thức dậy (wakeup 'assigned'), qua cổng ngân sách
            ops.assign_task(db, task, project, org_id, assignee_member_id=int(assignee),
                            actor_member_id=principal.member_id)
        else:      # bản nháp: ghi người nhận, KHÔNG đánh thức
            task.assignee_member_id = int(assignee)
            db.add(task); db.commit()
    elif data.get("department_id"):
        from app.services import routing
        try:
            routing.route_to_department(db, task, int(data["department_id"]), organization_id=org_id,
                                        actor_member_id=principal.member_id, reason="tạo việc")
        except routing.RoutingError as exc:
            raise WorkError(404 if exc.code == "not_found" else 409, f"routing_{exc.code}", exc.message) from exc
    db.refresh(task)
    return task


def update(db: Session, org_id: int, principal, task: Task, data: dict) -> Task:
    from app.services import board_truth, workspace_ops as ops
    from app.core.tenancy import ensure_project
    board_truth.check_revision(db, task, data.get("expected_revision"), organization_id=org_id)
    project = ensure_project(db, task.project_id, principal)
    changed = False
    if "title" in data:
        t = (data["title"] or "").strip()
        if not t:
            raise WorkError(422, "title_required", "Tên việc không được để trống")
        task.title, changed = t[:220], True
    if "description" in data:
        task.description, changed = data["description"] or "", True
    if "acceptance_criteria" in data:
        task.acceptance_criteria, changed = (data["acceptance_criteria"] or "").strip(), True
    if "priority" in data:
        if data["priority"] not in PRIORITY_VI:
            raise WorkError(422, "invalid_priority", "Ưu tiên phải là Khẩn / Cao / Vừa / Thấp")
        task.priority, changed = data["priority"], True
    if "due_at" in data:
        task.due_at, changed = _parse_due(data["due_at"]), True
    if changed:
        db.add(task); db.commit(); db.refresh(task)
    if "assignee_member_id" in data:
        new = data["assignee_member_id"]
        if new:
            _active_member(db, org_id, int(new), "người nhận")
            reviewers = [p for s in (task.execution_policy or {}).get("stages") or [] for p in s.get("participants") or []]
            if int(new) in reviewers and len(reviewers) == 1:
                raise WorkError(422, "self_review",
                                "Người này đang là reviewer duy nhất — đổi reviewer trước rồi mới giao việc cho họ")
        try:
            ops.assign_task(db, task, project, org_id, assignee_member_id=int(new) if new else None,
                            actor_member_id=principal.member_id)
        except HTTPException as exc:
            if exc.status_code == 400 and "unassign" in str(exc.detail).lower():
                raise WorkError(409, "cannot_unassign", "Việc đang làm/chờ duyệt — không bỏ người nhận được. "
                                                        "Chuyển về Cần làm trước.") from exc
            raise
    elif data.get("department_id"):
        from app.services import routing
        try:
            routing.route_to_department(db, task, int(data["department_id"]), organization_id=org_id,
                                        actor_member_id=principal.member_id, reason="đổi phòng")
        except routing.RoutingError as exc:
            raise WorkError(404 if exc.code == "not_found" else 409, f"routing_{exc.code}", exc.message) from exc
    db.refresh(task)
    return task


def move(db: Session, org_id: int, principal, task: Task, to: str, expected_revision: str | None) -> Task:
    from app.services import board_truth, workspace_ops as ops
    from app.core.tenancy import ensure_project
    board_truth.check_revision(db, task, expected_revision, organization_id=org_id)
    project = ensure_project(db, task.project_id, principal)
    return ops.move_task(db, task, project, org_id, status=to, actor_member_id=principal.member_id)


SKIP_VI = {"not_an_agent_seat": "Người nhận là người, không phải agent — họ tự làm trên app.",
           "seat_inactive": "Agent đang tạm dừng hoặc đã nghỉ — cho agent làm tiếp trong Đội ngũ rồi chạy lại.",
           "outside_active_hours": "Ngoài giờ làm của agent — lượt sẽ chạy khi tới giờ.",
           "not_assignee": "Agent không còn là người nhận việc này.",
           "no_task": "Không thấy việc."}


def explain_skip(reason: str) -> str:
    r = reason or ""
    if r in SKIP_VI:
        return SKIP_VI[r]
    if r.startswith("seat_busy"):
        return f"Agent đang bận lượt khác ({r.split(':', 1)[1].strip()}) — lượt này sẽ chạy khi xong."
    if r.startswith("task_status"):
        st = r.split(":", 1)[1].strip()
        return f"Việc đang '{STATUS_VI.get(st, st)}' — chỉ chạy được khi Tồn đọng / Cần làm / Đang làm."
    if r.startswith("budget"):
        return "Vượt hạn mức chi — nâng hạn mức trong Chi phí rồi chạy lại. (" + r.split(":", 1)[1].strip() + ")"
    if r.startswith("dispatch_error"):
        return "Không giao được cho agent: " + r.split(":", 1)[1].strip()
    if r.startswith("runtime_error"):
        return "Gateway lỗi khi gửi việc — kiểm tra Lõi OpenClaw rồi chạy lại. (" + r.split(":", 1)[1].strip()[:160] + ")"
    if r == "no_dispatchable_task":
        return "Không có việc nào chạy được cho agent này lúc này."
    return r


async def run_now(db: Session, org_id: int, task: Task) -> dict:
    """"Chạy ngay": một wakeup riêng rồi drain ngay seat đó — đi qua đúng đường
    của hệ thống (cổng ngân sách, giờ làm, seat bận, follower), không gọi tắt
    ``dispatch_task``."""
    from app.core.config import settings
    from app.services import wakeup
    if not task.assignee_member_id:
        raise WorkError(409, "no_assignee", "Việc chưa có người nhận — giao cho một agent trước")
    m = db.get(Member, task.assignee_member_id)
    if m is None or m.member_type != "agent":
        raise WorkError(409, "not_agent", "Người nhận là người, không phải agent — họ tự làm trên app")
    if task.status not in wakeup.DISPATCHABLE:
        raise WorkError(409, "not_runnable",
                        f"Việc đang '{STATUS_VI.get(task.status, task.status)}' — chỉ chạy được khi Tồn đọng / Cần làm / Đang làm")
    wk, _ = wakeup.enqueue(db, organization_id=org_id, member_id=m.id, reason="assigned", task_id=task.id,
                           dedupe_key=f"run_now:t{task.id}:{datetime.utcnow().timestamp():.6f}",
                           payload={"run_now": True})
    out = await wakeup.drain(db, member_id=m.id, force=True, follow=settings.wakeup_follow)
    mine = next((o for o in out if wk and wk.id in (o.get("wakeups") or []) + (o.get("coalesced") or [])), None)
    mine = mine or (out[0] if out else {"decision": "skipped", "reason": "no_dispatchable_task"})
    reason = mine.get("reason") or ""
    return {"decision": mine.get("decision"), "run_id": mine.get("run_id"), "reason": reason,
            "message": "Đã gửi cho agent" if mine.get("decision") == "dispatched" else explain_skip(reason)}
