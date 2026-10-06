"""D3.3 — Nina phân rã mục tiêu thành kế hoạch, người duyệt, hệ thống áp kế hoạch.

Luồng::

    goal mới (orchestration.create_goal) → on_goal_created:
        việc "Lập kế hoạch: <goal>" (goal_id, giao seat chiến lược) + wakeup goal_created
    Nina gọi company_plan_submit(goal_id, summary, tasks[...]) → submit():
        approvals(action='strategy', policy_key='strategy:goal:<id>', payload, revision=1)
    người duyệt:
        Duyệt   → plan_apply: task con (goal_id, parent_task_id = việc lập kế hoạch,
                  phụ thuộc), giao phòng (D3.1) / seat / tự chọn theo tải (D3.2)
        Yêu cầu sửa → status 'revision_requested', ghi sổ việc lập kế hoạch,
                  đánh thức Nina (changes_requested); Nina gửi lại → revision+1, pending
        Từ chối → goal 'plan_rejected'

Một mục tiêu chỉ có một kế hoạch đang mở (pending | revision_requested). Áp kế
hoạch là idempotent (``payload.applied``): bấm duyệt hai lần không sinh việc đôi.
"""
from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.models import Approval, Company, Department, ExecutiveGoal, Member, Project, Task
from app.services.company_event_bus import emit_event

SOURCE = "strategy"
ACTION = "strategy"
OPEN = ("pending", "revision_requested")
MAX_TASKS = 20
PRIORITIES = ("low", "medium", "high", "urgent")


class StrategyError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


def policy_key(goal_id: int) -> str:
    return f"strategy:goal:{goal_id}"


# ------------------------------------------------------------------ ai lập kế hoạch

def strategy_seat(db: Session, organization_id: int, company_id: int | None) -> Member | None:
    """Seat chiến lược: agent tên Nina; không có thì seat agent điều hành (không thuộc phòng nào)."""
    q = db.query(Member).filter(Member.organization_id == organization_id, Member.member_type == "agent",
                                Member.status == "active")
    if company_id:
        q = q.filter(Member.company_id == company_id)
    nina = q.filter(Member.name.ilike("nina%")).order_by(Member.id).first()
    return nina or q.filter(Member.department_id.is_(None)).order_by(Member.id).first()


def approver_for(db: Session, goal: ExecutiveGoal, seat: Member | None) -> int | None:
    from app.models.auth import User
    from app.services import inbox
    user = db.get(User, goal.created_by_user_id) if goal.created_by_user_id else None
    if user is not None and user.member_id:
        return user.member_id
    return inbox.manager_of(db, seat.id) if seat else None


def _roster(db: Session, company_id: int | None) -> list[dict]:
    if not company_id:
        return []
    out = []
    for d in (db.query(Department).filter(Department.company_id == company_id).order_by(Department.id)):
        if (d.status or "active") != "active":
            continue
        head = db.get(Member, d.head_member_id) if d.head_member_id else None
        people = (db.query(Member).filter(Member.department_id == d.id, Member.status == "active")
                  .order_by(Member.id).all())
        out.append({"department_id": d.id, "name": d.name, "head": head.name if head else None,
                    "members": [{"member_id": m.id, "name": m.name, "role": m.role or "",
                                 "type": m.member_type} for m in people]})
    return out


def _goal_budget(db: Session, goal: ExecutiveGoal):
    from app.models import BudgetEnvelope
    return (db.query(BudgetEnvelope).filter(BudgetEnvelope.goal_id == goal.id)
            .order_by(BudgetEnvelope.id.desc()).first())


def planning_brief(db: Session, goal: ExecutiveGoal, company_id: int | None) -> str:
    env = _goal_budget(db, goal)
    lines = [f"Mục tiêu #{goal.id}: {goal.title}", "", goal.objective or ""]
    if goal.expected_outcome:
        lines += ["", f"Kết quả mong đợi: {goal.expected_outcome}"]
    if goal.deadline:
        lines.append(f"Hạn: {goal.deadline}")
    lines.append(f"Ngân sách mục tiêu: ${env.amount_limit:.2f}" if env else "Ngân sách mục tiêu: chưa đặt")
    lines += ["", "## Phòng ban và nhân sự (dùng đúng id)"]
    for d in _roster(db, company_id):
        ppl = ", ".join(f"{m['name']} (#{m['member_id']}, {m['role'] or m['type']})" for m in d["members"]) or "chưa có ai"
        lines.append(f"- Phòng #{d['department_id']} {d['name']} — trưởng phòng: {d['head'] or 'chưa có'} — {ppl}")
    lines += ["", "## Giao thức",
              f"1. Phân rã mục tiêu thành 3–{MAX_TASKS} việc. Mỗi việc: key, title, description, "
              "acceptance_criteria (bắt buộc), department_id (giao phòng — trưởng phòng chọn người) "
              "hoặc member_id (giao thẳng), budget_usd, depends_on (danh sách key), priority.",
              f"2. Gọi `company_plan_submit` với goal_id={goal.id}, summary (vì sao chia như vậy) và tasks.",
              "3. Kế hoạch đi vào hàng duyệt. Nếu người duyệt yêu cầu sửa, ghi chú nằm trong sổ của việc này: "
              "sửa theo ghi chú rồi gọi lại `company_plan_submit`.",
              "4. Không tự tạo việc con bằng tool khác. Gửi xong thì dừng."]
    return "\n".join(lines)


def on_goal_created(db: Session, goal: ExecutiveGoal) -> dict:
    """Tạo việc lập kế hoạch cho seat chiến lược và đánh thức (goal_created). Không bao giờ ném."""
    from app.services import wakeup
    try:
        seat = strategy_seat(db, goal.organization_id, goal.company_id)
        if seat is None:
            emit_event(db, organization_id=goal.organization_id, company_id=goal.company_id,
                       event_type="goal.no_strategy_seat", source=SOURCE, aggregate_type="goal",
                       aggregate_id=str(goal.id), payload={"goal_id": goal.id})
            return {"woken": False, "reason": "no_strategy_seat"}
        company_id = goal.company_id or seat.company_id
        project = Project(company_id=company_id, name=f"Mục tiêu #{goal.id} · {goal.title}"[:200],
                          description=goal.objective or "", status="active")
        db.add(project); db.commit(); db.refresh(project)
        task = Task(project_id=project.id, title=f"Lập kế hoạch: {goal.title}"[:220], goal_id=goal.id,
                    description=planning_brief(db, goal, company_id), assignee_member_id=seat.id,
                    status="todo", priority=goal.priority if goal.priority in PRIORITIES else "high",
                    acceptance_criteria="Kế hoạch được duyệt qua company_plan_submit")
        db.add(task); db.commit(); db.refresh(task)
        wk = wakeup.enqueue_for_task(db, task, "goal_created", dedupe_key=f"goal_created:g{goal.id}",
                                     payload={"goal_id": goal.id})
        emit_event(db, organization_id=goal.organization_id, company_id=company_id, event_type="goal.planning_started",
                   source=SOURCE, aggregate_type="goal", aggregate_id=str(goal.id),
                   payload={"goal_id": goal.id, "planning_task_id": task.id, "seat_member_id": seat.id,
                            "wakeup_id": wk.id if wk else None})
        return {"woken": wk is not None, "planning_task_id": task.id, "wakeup_id": wk.id if wk else None}
    except Exception as exc:  # noqa: BLE001 — tạo goal không được hỏng vì bước đánh thức
        db.rollback()
        print(f"[D3.3] goal #{goal.id} planning wake failed: {exc}")
        return {"woken": False, "reason": f"error: {exc}"}


def planning_task(db: Session, goal_id: int) -> Task | None:
    return (db.query(Task).filter(Task.goal_id == goal_id, Task.parent_task_id.is_(None),
                                  Task.title.like("Lập kế hoạch:%")).order_by(Task.id).first())


# ------------------------------------------------------------------ gửi kế hoạch

def _clean(db: Session, goal: ExecutiveGoal, company_id: int | None, tasks) -> list[dict]:
    if not isinstance(tasks, list) or not tasks:
        raise StrategyError("invalid_argument", "tasks phải là danh sách ít nhất 1 việc")
    if len(tasks) > MAX_TASKS:
        raise StrategyError("invalid_argument", f"Tối đa {MAX_TASKS} việc mỗi kế hoạch")
    out, keys = [], set()
    for i, t in enumerate(tasks, 1):
        if not isinstance(t, dict):
            raise StrategyError("invalid_argument", f"Việc thứ {i} phải là object")
        key = str(t.get("key") or i).strip()[:40]
        if key in keys:
            raise StrategyError("invalid_argument", f"key '{key}' bị trùng")
        keys.add(key)
        title = str(t.get("title") or "").strip()
        if not title:
            raise StrategyError("invalid_argument", f"Việc '{key}' thiếu title")
        ac = str(t.get("acceptance_criteria") or "").strip()
        if not ac:
            raise StrategyError("invalid_argument", f"Việc '{key}' thiếu acceptance_criteria")
        dept_id, member_id = t.get("department_id"), t.get("member_id")
        try:
            dept_id = int(dept_id) if dept_id not in (None, "") else None
            member_id = int(member_id) if member_id not in (None, "") else None
            budget = float(t.get("budget_usd") or 0)
        except (TypeError, ValueError):
            raise StrategyError("invalid_argument", f"Việc '{key}': department_id/member_id/budget_usd sai kiểu") from None
        if budget < 0:
            raise StrategyError("invalid_argument", f"Việc '{key}': budget_usd ≥ 0")
        if dept_id is not None:
            d = db.get(Department, dept_id)
            if d is None or d.company_id != company_id or (d.status or "active") != "active":
                raise StrategyError("invalid_argument", f"Việc '{key}': không có phòng #{dept_id} trong công ty")
        if member_id is not None:
            m = db.get(Member, member_id)
            if m is None or m.organization_id != goal.organization_id or m.company_id != company_id \
                    or (m.status or "active") not in ("active", "onboarding"):
                raise StrategyError("invalid_argument", f"Việc '{key}': không có thành viên #{member_id} đang làm việc")
            if dept_id is not None and m.department_id != dept_id:
                raise StrategyError("invalid_argument", f"Việc '{key}': #{member_id} không thuộc phòng #{dept_id}")
        deps = t.get("depends_on") or []
        if not isinstance(deps, list):
            raise StrategyError("invalid_argument", f"Việc '{key}': depends_on phải là danh sách key")
        prio = str(t.get("priority") or "medium")
        out.append({"key": key, "title": title[:220], "description": str(t.get("description") or "")[:4000],
                    "acceptance_criteria": ac[:2000], "department_id": dept_id, "member_id": member_id,
                    "budget_usd": round(budget, 4), "depends_on": [str(x) for x in deps],
                    "priority": prio if prio in PRIORITIES else "medium"})
    for t in out:
        for k in t["depends_on"]:
            if k not in keys:
                raise StrategyError("invalid_argument", f"Việc '{t['key']}' phụ thuộc key không có: '{k}'")
            if k == t["key"]:
                raise StrategyError("invalid_argument", f"Việc '{k}' phụ thuộc chính nó")
    order(out)  # ném nếu có vòng
    env = _goal_budget(db, goal)
    total = sum(t["budget_usd"] for t in out)
    if env is not None and total > float(env.amount_limit or 0) + 1e-9:
        raise StrategyError("invalid_argument", f"Tổng ngân sách các việc ${total:.2f} vượt ngân sách mục tiêu "
                                                f"${float(env.amount_limit):.2f}")
    return out


def order(tasks: list[dict]) -> list[dict]:
    """Thứ tự topo theo depends_on; có vòng → StrategyError."""
    by_key = {t["key"]: t for t in tasks}
    state, out = {}, []

    def visit(k: str, path: tuple[str, ...]):
        if state.get(k) == "done":
            return
        if state.get(k) == "doing":
            raise StrategyError("invalid_argument", "Phụ thuộc tạo vòng: " + " → ".join((*path, k)))
        state[k] = "doing"
        for d in by_key[k]["depends_on"]:
            visit(d, (*path, k))
        state[k] = "done"
        out.append(by_key[k])
    for t in tasks:
        visit(t["key"], ())
    return out


def submit(db: Session, *, actor: Member, goal_id: int, summary: str, tasks, run_task_id: int | None = None) -> dict:
    from app.services import inbox
    goal = db.get(ExecutiveGoal, goal_id)
    if goal is None or goal.organization_id != actor.organization_id:
        raise StrategyError("not_found", f"Không thấy mục tiêu #{goal_id}")
    plan_task = planning_task(db, goal.id)
    seat_ok = (plan_task is not None and plan_task.assignee_member_id == actor.id) or actor.department_id is None
    if not seat_ok:
        raise StrategyError("forbidden", "Chỉ seat lập kế hoạch của mục tiêu (hoặc seat điều hành) mới gửi được kế hoạch")
    summary = (summary or "").strip()
    if len(summary) < 10:
        raise StrategyError("invalid_argument", "summary là bắt buộc (vì sao chia việc như vậy)")
    company_id = goal.company_id or actor.company_id
    clean = _clean(db, goal, company_id, tasks)
    rows = (db.query(Approval).filter(Approval.organization_id == goal.organization_id,
                                      Approval.policy_key == policy_key(goal.id)).order_by(Approval.id.desc()).all())
    if any(a.status == "approved" for a in rows):
        raise StrategyError("conflict", f"Mục tiêu #{goal.id} đã có kế hoạch được duyệt")
    current = next((a for a in rows if a.status in OPEN), None)
    if current is not None and current.status == "pending":
        raise StrategyError("conflict", f"Kế hoạch rev {current.revision} đang chờ duyệt (#{current.id}) — chờ kết quả")
    body = {"goal_id": goal.id, "summary": summary[:4000], "tasks": clean,
            "planning_task_id": plan_task.id if plan_task else run_task_id,
            "submitted_by": actor.id, "submitted_at": datetime.utcnow().isoformat() + "Z"}
    evidence = json.dumps({"goal_id": goal.id, "task_id": body["planning_task_id"]})
    if current is not None:   # revision_requested → gửi lại
        prev = current.payload or {}
        history = list(prev.get("history") or [])
        history.append({"revision": current.revision, "note": current.resolution_note or "",
                        "summary": prev.get("summary", ""), "tasks": len(prev.get("tasks") or [])})
        current.payload = {**body, "history": history}
        flag_modified(current, "payload")
        current.revision = (current.revision or 1) + 1
        current.status = "pending"
        current.resolution_note = ""
        current.expires_at = None            # hook D3.5 đặt lại hạn và báo lại người duyệt
        current.escalated_at = None
        current.evidence = evidence
        db.add(current); db.commit(); db.refresh(current)
        a, event = current, "goal.plan_resubmitted"
    else:
        a = Approval(organization_id=goal.organization_id, company_id=company_id, requester_member_id=actor.id,
                     approver_member_id=approver_for(db, goal, actor), action=ACTION, risk="medium",
                     policy_key=policy_key(goal.id), status="pending", evidence=evidence, payload=body, revision=1)
        db.add(a); db.commit(); db.refresh(a)
        event = "goal.plan_submitted"
    goal.status = "plan_pending"
    db.commit()
    emit_event(db, organization_id=goal.organization_id, company_id=company_id, event_type=event, source=SOURCE,
               aggregate_type="goal", aggregate_id=str(goal.id), actor_member_id=actor.id,
               payload={"goal_id": goal.id, "approval_id": a.id, "revision": a.revision, "tasks": len(clean),
                        "budget_usd": round(sum(t["budget_usd"] for t in clean), 4)})
    _ = inbox  # hook ORM của D3.5 tự báo người duyệt (cả lần gửi lại)
    return {"approval_id": a.id, "revision": a.revision, "status": a.status, "tasks": len(clean),
            "approver_member_id": a.approver_member_id}


# ------------------------------------------------------------------ quyết định

def is_strategy(a: Approval) -> bool:
    return a.action == ACTION and (a.policy_key or "").startswith("strategy:goal:")


def request_revision(db: Session, a: Approval, *, note: str, actor_member_id: int | None) -> dict:
    from app.services import task_journal, wakeup
    from app.services import task_lifecycle as lifecycle
    from app.services.audit import log_event
    if not is_strategy(a):
        raise StrategyError("invalid_argument", "Chỉ kế hoạch chiến lược mới yêu cầu sửa được")
    if a.status != "pending":
        raise StrategyError("conflict", f"Kế hoạch đang {a.status}")
    note = (note or "").strip()
    if len(note) < 5:
        raise StrategyError("invalid_argument", "Ghi rõ cần sửa gì")
    a.status, a.resolution_note = "revision_requested", note[:4000]
    db.add(a); db.commit(); db.refresh(a)
    log_event(db, a.organization_id, "approval.decided", "approvals", str(a.id), actor_member_id=actor_member_id,
              actor_name="human", result="revision_requested", risk=a.risk or "medium",
              payload={"decision": "revision_requested", "policy_key": a.policy_key, "revision": a.revision})
    payload = a.payload or {}
    task = db.get(Task, payload.get("planning_task_id")) if payload.get("planning_task_id") else None
    wk = None
    if task is not None:
        if task.status not in ("backlog", "todo", "in_progress"):
            lifecycle.transition(db, task, "todo", reason=f"kế hoạch rev {a.revision} cần sửa", via="strategy",
                                 system=True, organization_id=a.organization_id, company_id=a.company_id)
        task_journal.append(db, task, kind="note", summary=f"Yêu cầu sửa kế hoạch rev {a.revision}: {note}"[:400],
                            detail=note, actor_member_id=actor_member_id)
        wk = wakeup.enqueue_for_task(db, task, "changes_requested",
                                     dedupe_key=f"changes_requested:a{a.id}:r{a.revision}",
                                     payload={"approval_id": a.id, "revision": a.revision, "note": note[:1000]})
    goal_id = payload.get("goal_id")
    goal = db.get(ExecutiveGoal, goal_id) if goal_id else None
    if goal is not None:
        goal.status = "plan_revision"
        db.commit()
    emit_event(db, organization_id=a.organization_id, company_id=a.company_id,
               event_type="goal.plan_revision_requested", source=SOURCE, aggregate_type="goal",
               aggregate_id=str(goal_id), actor_member_id=actor_member_id,
               payload={"goal_id": goal_id, "approval_id": a.id, "revision": a.revision, "note": note[:1000],
                        "wakeup_id": wk.id if wk else None})
    return {"approval_id": a.id, "status": a.status, "revision": a.revision, "wakeup_id": wk.id if wk else None}


def on_resolved(db: Session, a: Approval, *, actor_member_id: int | None) -> dict:
    """Gọi sau khi người duyệt bấm Duyệt/Từ chối trên một kế hoạch chiến lược."""
    payload = a.payload or {}
    goal = db.get(ExecutiveGoal, payload.get("goal_id")) if payload.get("goal_id") else None
    if a.status == "approved":
        return plan_apply(db, a, actor_member_id=actor_member_id)
    if goal is not None:
        goal.status = "plan_rejected"
        db.commit()
    emit_event(db, organization_id=a.organization_id, company_id=a.company_id, event_type="goal.plan_rejected",
               source=SOURCE, aggregate_type="goal", aggregate_id=str(payload.get("goal_id")),
               actor_member_id=actor_member_id,
               payload={"goal_id": payload.get("goal_id"), "approval_id": a.id, "note": a.resolution_note or ""})
    return {"applied": False, "status": a.status}


def plan_apply(db: Session, a: Approval, *, actor_member_id: int | None = None) -> dict:
    """Kế hoạch đã duyệt → task con có goal_id, parent_task_id, phụ thuộc; giao phòng/seat."""
    from app.services import dispatch_policy, routing, task_graph, wakeup
    from app.services import task_lifecycle as lifecycle
    from app.services.audit import log_event
    payload = dict(a.payload or {})
    if payload.get("applied"):
        return {"applied": True, "already": True, **payload["applied"]}
    goal = db.get(ExecutiveGoal, payload.get("goal_id"))
    if goal is None:
        raise StrategyError("not_found", "Mục tiêu của kế hoạch không còn")
    parent = db.get(Task, payload.get("planning_task_id")) if payload.get("planning_task_id") else None
    company_id = a.company_id or goal.company_id
    if parent is not None:
        project = db.get(Project, parent.project_id)
    else:
        project = Project(company_id=company_id, name=f"Mục tiêu #{goal.id} · {goal.title}"[:200], status="active")
        db.add(project); db.commit(); db.refresh(project)
    made: dict[str, Task] = {}
    plan = order(payload.get("tasks") or [])
    for t in plan:
        desc = t["description"]
        if t["budget_usd"]:
            desc += f"\n\nNgân sách cho việc này: ${t['budget_usd']:.2f} (kế hoạch mục tiêu #{goal.id}, rev {a.revision})"
        task = Task(project_id=project.id, title=t["title"], description=desc, goal_id=goal.id,
                    parent_task_id=parent.id if parent else None, acceptance_criteria=t["acceptance_criteria"],
                    priority=t["priority"], status="todo")
        db.add(task); db.commit(); db.refresh(task)
        made[t["key"]] = task
    for t in plan:
        for k in t["depends_on"]:
            task_graph.add_dependency(db, made[t["key"]], made[k], actor_member_id=actor_member_id)
    assigned = {}
    for t in plan:
        task = made[t["key"]]
        why = f"Kế hoạch mục tiêu #{goal.id} rev {a.revision}: {t['title']}"[:300]
        if t["department_id"]:
            routing.route_to_department(db, task, t["department_id"], organization_id=a.organization_id,
                                        actor_member_id=actor_member_id, reason=why)
            assigned[t["key"]] = {"task_id": task.id, "department_id": t["department_id"]}
            continue
        member_id = t["member_id"]
        pick = None
        if member_id is None:
            pick = dispatch_policy.decide(db, a.organization_id, task=task, company_id=company_id)
            dispatch_policy.record(db, a.organization_id, pick, task=task, actor_member_id=actor_member_id,
                                   company_id=company_id)
            member_id = pick.member_id
        task.assignee_member_id = member_id
        db.commit()
        if member_id and not task_graph.open_blockers(db, task.id):
            wakeup.enqueue_for_task(db, task, "assigned", dedupe_key=f"plan:a{a.id}:t{task.id}",
                                    payload={"approval_id": a.id, "goal_id": goal.id})
        assigned[t["key"]] = {"task_id": task.id, "member_id": member_id,
                              **({"auto_pick": pick.reason} if pick is not None else {})}
    applied = {"at": datetime.utcnow().isoformat() + "Z", "task_ids": {k: v.id for k, v in made.items()},
               "assigned": assigned, "revision": a.revision}
    payload["applied"] = applied
    a.payload = payload
    flag_modified(a, "payload")
    goal.status = "active"
    db.commit()
    if parent is not None and parent.status not in ("done", "cancelled"):
        try:
            lifecycle.transition(db, parent, "done", reason=f"kế hoạch rev {a.revision} đã duyệt và áp dụng",
                                 via="strategy", system=True, organization_id=a.organization_id,
                                 company_id=company_id)
        except Exception as exc:  # noqa: BLE001 — policy review của việc lập kế hoạch có thể chặn done
            db.rollback()
            print(f"[D3.3] planning task #{parent.id} not closed: {exc}")
    payload_ev = {"goal_id": goal.id, "approval_id": a.id, "revision": a.revision,
                  "task_ids": applied["task_ids"], "assigned": assigned}
    log_event(db, a.organization_id, "strategy.plan_applied", "approvals", str(a.id), actor_member_id=actor_member_id,
              actor_name="system:strategy", result="success", risk=a.risk or "medium", payload=payload_ev)
    emit_event(db, organization_id=a.organization_id, company_id=company_id, event_type="goal.plan_applied",
               source=SOURCE, aggregate_type="goal", aggregate_id=str(goal.id), actor_member_id=actor_member_id,
               payload=payload_ev)
    return {"applied": True, **applied}


# ------------------------------------------------------------------ đọc

def goal_view(db: Session, goal: ExecutiveGoal) -> dict:
    rows = (db.query(Approval).filter(Approval.organization_id == goal.organization_id,
                                      Approval.policy_key == policy_key(goal.id)).order_by(Approval.id.desc()).all())
    plan_task = planning_task(db, goal.id)
    kids = (db.query(Task).filter(Task.goal_id == goal.id, Task.parent_task_id == plan_task.id).order_by(Task.id).all()
            if plan_task else [])
    names = {m.id: m.name for m in db.query(Member).filter(Member.organization_id == goal.organization_id)}
    depts = {}
    if goal.company_id:
        depts = {d.id: d.name for d in db.query(Department).filter(Department.company_id == goal.company_id)}
    env = _goal_budget(db, goal)
    return {
        "goal": {"id": goal.id, "title": goal.title, "objective": goal.objective, "status": goal.status,
                 "company_id": goal.company_id, "deadline": goal.deadline,
                 "budget_usd": float(env.amount_limit) if env else None},
        "planning_task": {"id": plan_task.id, "status": plan_task.status,
                          "assignee": names.get(plan_task.assignee_member_id)} if plan_task else None,
        "plans": [{"approval_id": a.id, "status": a.status, "revision": a.revision, "note": a.resolution_note,
                   "approver": names.get(a.approver_member_id), "approver_member_id": a.approver_member_id,
                   "expires_at": a.expires_at.isoformat() + "Z" if a.expires_at else None,
                   "summary": (a.payload or {}).get("summary", ""), "tasks": (a.payload or {}).get("tasks", []),
                   "history": (a.payload or {}).get("history", []), "applied": (a.payload or {}).get("applied")}
                  for a in rows],
        "tasks": [{"id": t.id, "title": t.title, "status": t.status, "assignee": names.get(t.assignee_member_id),
                   "department": depts.get(t.assignee_department_id), "acceptance_criteria": t.acceptance_criteria}
                  for t in kids],
    }
