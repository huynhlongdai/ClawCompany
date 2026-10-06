"""D1.3 — đồ thị công việc: task cha, mục tiêu, và các task đang chặn.

Phần thuần (không chạm DB) đứng riêng để test được bằng dữ liệu tay:
``would_create_cycle``, ``chain_line``. Phần còn lại đọc DB nhưng không ghi
``task.status`` — chuyện đó thuộc về ``task_lifecycle``.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Iterable

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ExecutiveGoal, Project, Task, TaskDependency

CLOSED_STATUSES = ("done", "cancelled")
GOAL_LINE_LIMIT = 240
MAX_DEPTH = 50  # chặn vòng lặp vô hạn nếu DB đã lỡ có vòng cha


# ------------------------------------------------------------------ phần thuần

def would_create_cycle(edges: Iterable[tuple[int, int]], task_id: int, blocked_by: int) -> bool:
    """Thêm cạnh ``task_id`` bị chặn bởi ``blocked_by`` có tạo vòng không.

    ``edges`` là các cặp (task, blocked_by) đang có. Vòng xuất hiện khi từ
    ``blocked_by`` đi theo chiều "bị chặn bởi" tới được ``task_id``.
    """
    if task_id == blocked_by:
        return True
    graph: dict[int, list[int]] = defaultdict(list)
    for a, b in edges:
        graph[a].append(b)
    stack, seen = [blocked_by], set()
    while stack:
        node = stack.pop()
        if node == task_id:
            return True
        if node in seen:
            continue
        seen.add(node)
        stack.extend(graph.get(node, ()))
    return False


def chain_line(goal: str | None, project: str | None, parents: list[str], task: str,
               limit: int = GOAL_LINE_LIMIT) -> str:
    """"Mục tiêu → Dự án → Task cha → Task này", không dài quá ``limit``.

    Khi quá dài thì rút các task cha ở giữa trước (giữ cha gần nhất), rồi mới
    cắt chữ — vì mục tiêu và task này là hai đầu agent cần nhất.
    """
    def build(mid: list[str]) -> str:
        parts = [p for p in [goal, project, *mid, task] if p]
        return " → ".join(parts)

    real = list(parents)
    line = build(real)
    while len(line) > limit and len(real) > 1:
        real.pop(0)  # bỏ cha xa nhất trước
        line = build(["…", *real])
    if len(line) > limit:
        line = line[: limit - 1].rstrip() + "…"
    return line


# ------------------------------------------------------------------ đọc DB

def ancestry(db: Session, task: Task) -> list[Task]:
    """Các task cha từ gần tới xa (không gồm chính task)."""
    out: list[Task] = []
    seen = {task.id}
    current = task
    while current.parent_task_id and len(out) < MAX_DEPTH:
        parent = db.get(Task, current.parent_task_id)
        if parent is None or parent.id in seen:
            break
        out.append(parent)
        seen.add(parent.id)
        current = parent
    return out


def blockers(db: Session, task_id: int) -> list[Task]:
    rows = db.execute(
        select(Task).join(TaskDependency, TaskDependency.blocked_by_task_id == Task.id)
        .where(TaskDependency.task_id == task_id).order_by(Task.id)
    ).scalars().all()
    return list(rows)


def open_blockers(db: Session, task_id: int) -> list[Task]:
    return [t for t in blockers(db, task_id) if t.status not in CLOSED_STATUSES]


def blocking(db: Session, task_id: int) -> list[Task]:
    """Các task đang chờ ``task_id``."""
    return list(db.execute(
        select(Task).join(TaskDependency, TaskDependency.task_id == Task.id)
        .where(TaskDependency.blocked_by_task_id == task_id).order_by(Task.id)
    ).scalars().all())


def children(db: Session, task_id: int) -> list[Task]:
    return list(db.execute(select(Task).where(Task.parent_task_id == task_id)
                           .order_by(Task.id)).scalars().all())


def goal_of(db: Session, task: Task) -> ExecutiveGoal | None:
    """Mục tiêu của task, hoặc của task cha gần nhất có mục tiêu."""
    for node in [task, *ancestry(db, task)]:
        if node.goal_id:
            return db.get(ExecutiveGoal, node.goal_id)
    return None


def goal_line(db: Session, task: Task) -> str:
    goal = goal_of(db, task)
    project = db.get(Project, task.project_id) if task.project_id else None
    parents = [f"#{p.id} {p.title}" for p in reversed(ancestry(db, task))]
    return chain_line(goal.title if goal else None, project.name if project else None,
                      parents, f"#{task.id} {task.title}")


def _brief(t: Task) -> dict:
    return {"id": t.id, "title": t.title, "status": t.status, "project_id": t.project_id}


def graph(db: Session, task: Task) -> dict:
    goal = goal_of(db, task)
    return {
        "task_id": task.id,
        "goal": ({"id": goal.id, "title": goal.title, "status": goal.status,
                  "inherited": goal.id != task.goal_id} if goal else None),
        "parents": [_brief(t) for t in ancestry(db, task)],
        "children": [_brief(t) for t in children(db, task.id)],
        "blocked_by": [_brief(t) for t in blockers(db, task.id)],
        "blocking": [_brief(t) for t in blocking(db, task.id)],
        "open_blocker_ids": [t.id for t in open_blockers(db, task.id)],
        "goal_line": goal_line(db, task),
        "due_at": task.due_at.isoformat() if task.due_at else None,
        "acceptance_criteria": task.acceptance_criteria or "",
    }


# ------------------------------------------------------------------ ghi cạnh

def _org_of(db: Session, task: Task) -> int | None:
    from app.models import Company
    project = db.get(Project, task.project_id) if task.project_id else None
    company = db.get(Company, project.company_id) if project else None
    return company.organization_id if company else None


def same_tenant(db: Session, a: Task, b: Task) -> bool:
    return _org_of(db, a) is not None and _org_of(db, a) == _org_of(db, b)


def add_dependency(db: Session, task: Task, blocked_by: Task, *,
                   actor_member_id: int | None = None) -> TaskDependency:
    if not same_tenant(db, task, blocked_by):
        raise HTTPException(404, "Task not found")
    existing = db.execute(select(TaskDependency).where(
        TaskDependency.task_id == task.id,
        TaskDependency.blocked_by_task_id == blocked_by.id)).scalar_one_or_none()
    if existing:
        return existing
    edges = db.execute(select(TaskDependency.task_id, TaskDependency.blocked_by_task_id)).all()
    if would_create_cycle([tuple(e) for e in edges], task.id, blocked_by.id):
        raise HTTPException(422, f"Thêm phụ thuộc này sẽ tạo vòng: task #{blocked_by.id} "
                                 f"đã (trực tiếp hoặc gián tiếp) chờ task #{task.id}")
    dep = TaskDependency(task_id=task.id, blocked_by_task_id=blocked_by.id,
                         created_by_member_id=actor_member_id)
    db.add(dep); db.commit(); db.refresh(dep)
    return dep


def remove_dependency(db: Session, task: Task, blocked_by_id: int) -> bool:
    dep = db.execute(select(TaskDependency).where(
        TaskDependency.task_id == task.id,
        TaskDependency.blocked_by_task_id == blocked_by_id)).scalar_one_or_none()
    if not dep:
        return False
    db.delete(dep); db.commit()
    return True


def set_parent(db: Session, task: Task, parent: Task | None) -> None:
    """Đặt task cha; từ chối nếu tạo vòng (cha là chính nó hoặc là con cháu)."""
    if parent is None:
        task.parent_task_id = None
        return
    if not same_tenant(db, task, parent):
        raise HTTPException(404, "Parent task not found")
    if parent.id == task.id or task.id in {p.id for p in [parent, *ancestry(db, parent)]}:
        raise HTTPException(422, f"Task #{parent.id} là con cháu của task #{task.id}; "
                                 "đặt làm cha sẽ tạo vòng")
    task.parent_task_id = parent.id
