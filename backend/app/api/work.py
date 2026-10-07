"""M4a — /api/work: Công việc & lượt chạy (danh sách, bảng, side-peek, review chéo).

Gom các đường cũ mà màn hình việc phải ghép: ``/v17/workspace/tasks`` (thẻ),
``/v27/tasks/{id}/move`` (kéo thẻ), ``/tasks/{id}/runs|journal|execution-policy|review``.
Các đường cũ vẫn chạy, có header ``Deprecation`` trỏ về đây. Luật ở
``services/work_board.py`` (đọc gộp) — trạng thái vẫn chỉ ghi qua ``task_lifecycle``.
"""
import functools
import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.authz import ROLE_ORDER, Principal, require_human, require_role
from app.core.tenancy import active_org, ensure_task
from app.db.session import get_db
from app.models import Agent, Company, Department, Member, Project
from app.services import work_board as svc

router = APIRouter(prefix="/work", tags=["work"])


def _stale(fn):
    """409 revision cũ của board_truth → câu tiếng Việt + revision hiện tại để tải lại."""
    @functools.wraps(fn)
    def wrap(*a, **kw):
        try:
            return fn(*a, **kw)
        except HTTPException as exc:
            d = exc.detail
            if exc.status_code == 409 and isinstance(d, dict) and "current_revision" in d:
                raise svc.WorkError(409, "stale_revision",
                                    "Việc vừa được người khác sửa — đã tải bản mới, xem lại rồi thao tác lần nữa",
                                    current_revision=d["current_revision"]) from exc
            raise
    return wrap


# Các đường cũ mà /api/work thay thế: vẫn chạy, nhưng trả header Deprecation + Link.
DEPRECATED = [
    (re.compile(r"^/api/v17/workspace/tasks$"), "/api/work/tasks"),
    (re.compile(r"^/api/v27/tasks/(\d+)/move$"), "/api/work/tasks/{0}/move"),
    (re.compile(r"^/api/v18/workspace/tasks/(\d+)/move$"), "/api/work/tasks/{0}/move"),
    (re.compile(r"^/api/tasks/(\d+)/runs$"), "/api/work/tasks/{0}"),
    (re.compile(r"^/api/tasks/(\d+)/execution-policy$"), "/api/work/tasks/{0}/reviewers"),
    (re.compile(r"^/api/tasks/(\d+)/review$"), "/api/work/tasks/{0}/review"),
]


def successor(path: str) -> str | None:
    for rx, target in DEPRECATED:
        m = rx.match(path)
        if m:
            return target.format(*m.groups())
    return None


def _is_manager(p: Principal) -> bool:
    return ROLE_ORDER.get(p.role, -1) >= ROLE_ORDER["manager"]


class CreateIn(BaseModel):
    title: str = Field(min_length=1, max_length=220)
    project_id: int
    description: str = Field(default="", max_length=20000)
    acceptance_criteria: str = Field(default="", max_length=4000)
    priority: str = "medium"
    assignee_member_id: int | None = None
    department_id: int | None = None
    reviewer_member_ids: list[int] = []
    due_at: str | None = None
    start: bool = True


class UpdateIn(BaseModel):
    expected_revision: str | None = None
    title: str | None = Field(default=None, max_length=220)
    description: str | None = Field(default=None, max_length=20000)
    acceptance_criteria: str | None = Field(default=None, max_length=4000)
    priority: str | None = None
    assignee_member_id: int | None = None
    department_id: int | None = None
    due_at: str | None = None


class MoveIn(BaseModel):
    status: str
    expected_revision: str | None = None


class ReviewersIn(BaseModel):
    reviewer_member_ids: list[int] = []


class DecisionIn(BaseModel):
    decision: str = Field(pattern="^(approve|revise)$")
    note: str = Field(default="", max_length=2000)


@router.get("/meta")
def meta(principal: Principal = Depends(require_human()), db: Session = Depends(get_db)):
    """Bộ chọn cho bộ lọc / tạo việc: dự án, người & agent đang làm, phòng ban, trạng thái."""
    org = active_org(principal)
    companies = db.query(Company).filter(Company.organization_id == org).order_by(Company.id).all()
    cids = [c.id for c in companies]
    projects = db.query(Project).filter(Project.company_id.in_(cids)).order_by(Project.id.desc()).all() if cids else []
    members = (db.query(Member).filter(Member.organization_id == org, Member.status.in_(("active", "onboarding")))
               .order_by(Member.member_type, Member.name).all())
    agents = {a.member_id: a for a in db.query(Agent).filter(Agent.member_id.in_([m.id for m in members])).all()}
    depts = db.query(Department).filter(Department.company_id.in_(cids)).order_by(Department.id).all() if cids else []
    return {
        "companies": [{"id": c.id, "name": c.name} for c in companies],
        "projects": [{"id": p.id, "name": p.name, "company_id": p.company_id, "status": p.status} for p in projects
                     if p.status != "cancelled"],
        "members": [{"id": m.id, "name": m.name, "type": m.member_type, "role": m.role or "",
                     "company_id": m.company_id, "department_id": m.department_id,
                     "lifecycle": (agents[m.id].lifecycle or "active") if m.id in agents else None,
                     "assignable": m.id not in agents or (agents[m.id].lifecycle or "active") == "active"}
                    for m in members],
        "departments": [{"id": d.id, "name": d.name, "company_id": d.company_id, "head_member_id": d.head_member_id}
                        for d in depts if (d.status or "active") == "active"],
        "statuses": svc.statuses(),
        "priorities": [{"key": k, "label": v} for k, v in svc.PRIORITY_VI.items()],
        "me": principal.member_id,
        "caps": {"create": ROLE_ORDER.get(principal.role, -1) >= ROLE_ORDER["member"],
                 "set_reviewers": _is_manager(principal)},
    }


@router.get("/tasks")
def list_tasks(status: str | None = None, assignee: str | None = None, department_id: int | None = None,
               project_id: int | None = None, company_id: int | None = None, priority: str | None = None,
               q: str | None = None, include_closed: bool = True, limit: int = 500,
               principal: Principal = Depends(require_human()), db: Session = Depends(get_db)):
    return svc.list_items(db, active_org(principal), status=status, assignee=assignee, department_id=department_id,
                          project_id=project_id, company_id=company_id, priority=priority, q=q,
                          me=principal.member_id, include_closed=include_closed, limit=limit)


@router.post("/tasks", status_code=201)
def create_task(payload: CreateIn, principal: Principal = Depends(require_role("member")),
                db: Session = Depends(get_db)):
    if payload.reviewer_member_ids and not _is_manager(principal):
        raise svc.WorkError(403, "manager_required", "Chỉ quản lý trở lên được chọn người review")
    org = active_org(principal)
    task = svc.create(db, org, principal, payload.model_dump())
    return svc.detail(db, org, task)


@router.get("/tasks/{task_id}")
def read_task(task_id: int, principal: Principal = Depends(require_human()), db: Session = Depends(get_db)):
    task = ensure_task(db, task_id, principal)
    out = svc.detail(db, active_org(principal), task)
    out["suggested_reviewer"] = svc._who(svc.suggest_reviewer(db, active_org(principal), task.assignee_member_id))
    return out


@router.patch("/tasks/{task_id}")
@_stale
def update_task(task_id: int, payload: UpdateIn, principal: Principal = Depends(require_role("member")),
                db: Session = Depends(get_db)):
    task = ensure_task(db, task_id, principal)
    org = active_org(principal)
    svc.update(db, org, principal, task, payload.model_dump(exclude_unset=True))
    return svc.detail(db, org, task)


@router.post("/tasks/{task_id}/move")
@_stale
def move_task(task_id: int, payload: MoveIn, principal: Principal = Depends(require_role("member")),
              db: Session = Depends(get_db)):
    task = ensure_task(db, task_id, principal)
    org = active_org(principal)
    svc.move(db, org, principal, task, payload.status, payload.expected_revision)
    return svc.detail(db, org, task)


@router.put("/tasks/{task_id}/reviewers")
def set_reviewers(task_id: int, payload: ReviewersIn, principal: Principal = Depends(require_role("manager")),
                  db: Session = Depends(get_db)):
    task = ensure_task(db, task_id, principal)
    org = active_org(principal)
    svc.set_review(db, org, task, payload.reviewer_member_ids)
    return svc.detail(db, org, task)


@router.post("/tasks/{task_id}/review")
def decide(task_id: int, payload: DecisionIn, principal: Principal = Depends(require_role("member")),
           db: Session = Depends(get_db)):
    """Reviewer là người quyết chặng hiện tại: duyệt → chặng kế/Xong; sửa → về Đang làm, agent được đánh thức."""
    from app.services import execution_policy as ep
    task = ensure_task(db, task_id, principal)
    ep.decide(db, task, member_id=principal.member_id, decision=payload.decision, note=payload.note, via="work")
    db.refresh(task)
    return svc.detail(db, active_org(principal), task)


@router.post("/tasks/{task_id}/run")
async def run_now(task_id: int, principal: Principal = Depends(require_role("member")),
                  db: Session = Depends(get_db)):
    task = ensure_task(db, task_id, principal)
    org = active_org(principal)
    out = await svc.run_now(db, org, task)
    db.refresh(task)
    return {**out, "task": svc.detail(db, org, task)}
