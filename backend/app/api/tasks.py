from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.models import Artifact, ExecutiveGoal, Member, Task, TaskRun, Project, Company
from app.schemas import TaskCreate, TaskOut
from app.services.tasks import dispatch_task
from app.services import agent_dispatch, handoff_dispatch, task_graph, task_journal, work_context
from app.services import task_lifecycle
from app.services import cost_ledger
from app.runtime.factory import get_runtime
from app.services.artifacts import handoff_artifact, register_artifact
from app.core.authz import Principal, get_principal, require_role, require_human
from app.core.tenancy import active_org, ensure_project, ensure_member, ensure_task

router = APIRouter(prefix="/tasks", tags=["tasks"])

@router.get("", response_model=list[TaskOut])
def list_tasks(project_id: int | None = None, goal_id: int | None = None, principal: Principal = Depends(require_human()), db: Session = Depends(get_db)):
    org_id = active_org(principal)
    q = db.query(Task).join(Project, Project.id == Task.project_id).join(Company, Company.id == Project.company_id).filter(Company.organization_id == org_id)
    if project_id is not None:
        ensure_project(db, project_id, principal); q = q.filter(Task.project_id == project_id)
    if goal_id is not None:
        q = q.filter(Task.goal_id == goal_id)
    return q.order_by(Task.id.desc()).all()

@router.post("", response_model=TaskOut)
def create_task(payload: TaskCreate, principal: Principal = Depends(require_role("member")), db: Session = Depends(get_db)):
    ensure_project(db, payload.project_id, principal)
    if payload.assignee_member_id is not None: ensure_member(db, payload.assignee_member_id, principal)
    if payload.status not in task_lifecycle.TASK_STATUSES:
        raise HTTPException(400, f"status must be one of: {', '.join(task_lifecycle.TASK_STATUSES)}")
    obj = Task(**payload.model_dump())
    db.add(obj); db.commit(); db.refresh(obj)
    return obj

@router.get("/cost-reconciliation")
async def cost_reconciliation(task_id: int | None = None, limit: int = 20,
                              principal: Principal = Depends(require_role("admin")),
                              db: Session = Depends(get_db)):
    """D1.2: so ``usage_events`` (model_usage) của từng phiên task với ``sessions.usage`` của gateway."""
    org_id = active_org(principal)
    if task_id is not None:
        ensure_task(db, task_id, principal)
    return await cost_ledger.reconcile(db, get_runtime(), organization_id=org_id,
                                       task_ids=[task_id] if task_id else None, limit=limit)


@router.post("/{task_id}/dispatch", response_model=TaskOut)
async def dispatch(task_id: int, principal: Principal = Depends(require_role("member")), db: Session = Depends(get_db)):
    task = ensure_task(db, task_id, principal)
    try:
        return await agent_dispatch.dispatch_task(db, task)
    except agent_dispatch.DispatchConflict as exc:
        raise HTTPException(409, str(exc))
    except agent_dispatch.DispatchError as exc:
        raise HTTPException(400, str(exc))


# ------------------------------------------------------------------ WP-4.3 UI
#
# Ba endpoint cho màn hình chi tiết task. Đặt ở router `tasks` vì chúng nói về
# task, không mở router mới (luật số 4 của BUILD_PLAN).


@router.get("/{task_id}/journal")
def task_journal_read(task_id: int, principal: Principal = Depends(require_human()),
                      db: Session = Depends(get_db)):
    """Sổ ghi của task theo thời gian, kèm tên người thay vì chỉ id.

    `digest` nói rõ `success_rate` là `null` khi chưa có mục nào đo được kết quả
    — khác với 0%, cùng lý lẽ với v36.
    """
    task = ensure_task(db, task_id, principal)
    entries = task_journal.read(db, task.id, limit=200)
    actor_ids = {e.actor_member_id for e in entries if e.actor_member_id}
    names = {m.id: m.name for m in db.execute(
        select(Member).where(Member.id.in_(actor_ids))
    ).scalars().all()} if actor_ids else {}
    return {
        "task_id": task.id,
        "digest": task_journal.digest(db, task.id),
        "entries": [{
            "seq": e.seq, "kind": e.kind, "summary": e.summary, "detail": e.detail,
            "outcome": e.outcome, "cost_usd": e.cost_usd,
            "actor_member_id": e.actor_member_id,
            "actor_name": names.get(e.actor_member_id or 0, "hệ thống"),
            "runtime_run_id": e.runtime_run_id,
            "runtime_session_key": e.runtime_session_key,
            "created_at": e.created_at.isoformat(),
        } for e in entries],
        "kinds": list(task_journal.KINDS),
    }


@router.get("/{task_id}/context-pack")
def task_context_pack(task_id: int, principal: Principal = Depends(require_human()),
                      db: Session = Depends(get_db)):
    """Xem trước **đúng** gói ngữ cảnh mà agent sẽ nhận khi được giao task này.

    Không phải bản mô phỏng: gọi cùng hàm `work_context.build_pack` mà
    `agent_dispatch` gọi. Nếu UI hiện một thứ và agent nhận một thứ khác thì
    màn hình xem trước là vô dụng — tệ hơn là gây tin sai.
    """
    task = ensure_task(db, task_id, principal)
    return work_context.build_pack(db, task, organization_id=active_org(principal))


class TaskHandoffIn(BaseModel):
    to_member_id: int
    instructions: str = Field(default="", max_length=30000)
    purpose: str = Field(default="continue_work", max_length=80)
    # None = theo cấu hình `openclaw_auto_dispatch`; True/False = nói rõ.
    dispatch: bool | None = None


@router.post("/{task_id}/handoff")
async def task_handoff(task_id: int, payload: TaskHandoffIn,
                       principal: Principal = Depends(require_role("member")),
                       db: Session = Depends(get_db)):
    """Bàn giao một task cho người khác, kèm hướng dẫn.

    Bàn giao trong hệ thống này luôn gắn với một **artifact** (`artifact_handoffs`
    từ v10), vì bàn giao mà không có sản phẩm nào đi kèm thì không truy lại được.
    Nhưng một task đang làm có thể chưa có artifact nào, và bắt người dùng tạo
    artifact trước khi bàn giao là bắt họ làm việc của hệ thống.

    Nên: dùng artifact mới nhất của task nếu có; nếu chưa có thì tạo một
    **phiếu bàn giao** (artifact loại `handoff_note`) mang chính nội dung hướng
    dẫn. Không sinh ra đường bàn giao thứ hai — vẫn đi qua `handoff_artifact`
    rồi `dispatch_on_handoff` của WP-4.3.
    """
    task = ensure_task(db, task_id, principal)
    target = ensure_member(db, payload.to_member_id, principal)
    organization_id = active_org(principal)
    project = db.get(Project, task.project_id)

    artifact = db.execute(
        select(Artifact).where(Artifact.task_id == task.id)
        .order_by(Artifact.id.desc()).limit(1)
    ).scalars().first()
    created_note = False
    if artifact is None:
        artifact = register_artifact(
            db, organization_id=organization_id,
            company_id=project.company_id if project else None,
            project_id=task.project_id, task_id=task.id,
            created_by_member_id=principal.member_id,
            name=f"Phiếu bàn giao task #{task.id}",
            logical_path=f"handoffs/task-{task.id}.md",
            artifact_type="handoff_note", mime_type="text/markdown",
            bundle_key=f"handoff-task-{task.id}",
            content_text=(payload.instructions or "").strip()
                         or f"Bàn giao task #{task.id}: {task.title}",
        )
        created_note = True

    try:
        handoff = handoff_artifact(
            db, artifact, to_member_id=payload.to_member_id,
            from_member_id=principal.member_id, task_id=task.id,
            purpose=payload.purpose, instructions=payload.instructions)
    except ValueError as exc:
        raise HTTPException(400, str(exc))

    outcome = await handoff_dispatch.dispatch_on_handoff(db, handoff,
                                                        dispatch=payload.dispatch)
    return {
        "task_id": task.id,
        "to_member_id": payload.to_member_id,
        "to_member_name": target.name,
        "artifact_id": artifact.id,
        "created_handoff_note": created_note,
        "handoff_id": handoff.id,
        "dispatch": outcome,
    }


# ------------------------------------------------------------------ D1.3 đồ thị
#
# Task cha, mục tiêu, hạn, tiêu chí nghiệm thu và các task đang chặn. Ghi cạnh
# đi qua task_graph (chặn vòng), không có endpoint nào ở đây ghi task.status.

class DependencyIn(BaseModel):
    blocked_by_task_id: int


class TaskLinksIn(BaseModel):
    parent_task_id: int | None = None
    goal_id: int | None = None
    due_at: datetime | None = None
    acceptance_criteria: str | None = Field(default=None, max_length=20000)


def _same_tenant_or_404(db: Session, task_id: int, principal: Principal) -> Task:
    """Task của tenant khác trả 404, không 403: không xác nhận nó tồn tại."""
    try:
        return ensure_task(db, task_id, principal)
    except HTTPException as exc:
        if exc.status_code == 403:
            raise HTTPException(404, "Task not found") from exc
        raise


@router.get("/{task_id}/graph")
def task_graph_read(task_id: int, principal: Principal = Depends(require_human()),
                    db: Session = Depends(get_db)):
    task = ensure_task(db, task_id, principal)
    return task_graph.graph(db, task)


@router.post("/{task_id}/dependencies", status_code=201)
def task_dependency_add(task_id: int, payload: DependencyIn,
                        principal: Principal = Depends(require_role("member")),
                        db: Session = Depends(get_db)):
    task = ensure_task(db, task_id, principal)
    other = db.get(Task, payload.blocked_by_task_id)
    if other is None:
        raise HTTPException(404, "Task not found")
    _same_tenant_or_404(db, other.id, principal)
    dep = task_graph.add_dependency(db, task, other, actor_member_id=principal.member_id)
    return {"id": dep.id, "task_id": dep.task_id, "blocked_by_task_id": dep.blocked_by_task_id,
            "graph": task_graph.graph(db, task)}


@router.delete("/{task_id}/dependencies/{blocked_by_task_id}")
def task_dependency_remove(task_id: int, blocked_by_task_id: int,
                           principal: Principal = Depends(require_role("member")),
                           db: Session = Depends(get_db)):
    task = ensure_task(db, task_id, principal)
    if not task_graph.remove_dependency(db, task, blocked_by_task_id):
        raise HTTPException(404, "Dependency not found")
    return {"removed": True, "graph": task_graph.graph(db, task)}


@router.patch("/{task_id}/links")
def task_links_update(task_id: int, payload: TaskLinksIn,
                      principal: Principal = Depends(require_role("member")),
                      db: Session = Depends(get_db)):
    """Chỉ đổi những trường có mặt trong body; gửi ``null`` để gỡ liên kết."""
    task = ensure_task(db, task_id, principal)
    sent = payload.model_fields_set
    if "parent_task_id" in sent:
        parent = None
        if payload.parent_task_id is not None:
            parent = db.get(Task, payload.parent_task_id)
            if parent is None:
                raise HTTPException(404, "Parent task not found")
            _same_tenant_or_404(db, parent.id, principal)
        task_graph.set_parent(db, task, parent)
    if "goal_id" in sent:
        if payload.goal_id is not None:
            goal = db.get(ExecutiveGoal, payload.goal_id)
            if goal is None or goal.organization_id != active_org(principal):
                raise HTTPException(404, "Goal not found")
        task.goal_id = payload.goal_id
    if "due_at" in sent:
        task.due_at = payload.due_at
    if "acceptance_criteria" in sent:
        task.acceptance_criteria = payload.acceptance_criteria or ""
    db.add(task); db.commit(); db.refresh(task)
    return task_graph.graph(db, task)


# ------------------------------------------------------------------ D1.4 lượt chạy

@router.get("/{task_id}/runs")
def task_runs_read(task_id: int, limit: int = 50, principal: Principal = Depends(require_human()),
                   db: Session = Depends(get_db)):
    task = ensure_task(db, task_id, principal)
    rows = db.execute(select(TaskRun).where(TaskRun.task_id == task.id)
                      .order_by(TaskRun.id.desc()).limit(max(1, min(limit, 200)))).scalars().all()
    members = {m.id: m.name for m in db.query(Member).filter(
        Member.id.in_({r.member_id for r in rows if r.member_id})).all()} if rows else {}
    return {
        "task_id": task.id,
        "checkout_run_id": task.checkout_run_id,
        "runs": [{
            "id": r.id, "status": r.status, "trigger_kind": r.trigger_kind,
            "member_id": r.member_id, "member_name": members.get(r.member_id),
            "session_key": r.session_key, "runtime_run_id": r.runtime_run_id,
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "ended_at": r.ended_at.isoformat() if r.ended_at else None,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "cost_usd": r.cost_usd, "tokens_in": r.tokens_in, "tokens_out": r.tokens_out,
            "error_reason": r.error_reason, "holds_task": r.id == task.checkout_run_id,
        } for r in rows],
    }
