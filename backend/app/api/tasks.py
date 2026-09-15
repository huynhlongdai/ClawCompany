from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.models import Task, Project, Company
from app.schemas import TaskCreate, TaskOut
from app.services.tasks import dispatch_task
from app.core.authz import Principal, get_principal, require_role, require_human
from app.core.tenancy import active_org, ensure_project, ensure_member, ensure_task

router = APIRouter(prefix="/tasks", tags=["tasks"])

@router.get("", response_model=list[TaskOut])
def list_tasks(project_id: int | None = None, principal: Principal = Depends(require_human()), db: Session = Depends(get_db)):
    org_id = active_org(principal)
    q = db.query(Task).join(Project, Project.id == Task.project_id).join(Company, Company.id == Project.company_id).filter(Company.organization_id == org_id)
    if project_id is not None:
        ensure_project(db, project_id, principal); q = q.filter(Task.project_id == project_id)
    return q.order_by(Task.id.desc()).all()

@router.post("", response_model=TaskOut)
def create_task(payload: TaskCreate, principal: Principal = Depends(require_role("member")), db: Session = Depends(get_db)):
    ensure_project(db, payload.project_id, principal)
    if payload.assignee_member_id is not None: ensure_member(db, payload.assignee_member_id, principal)
    obj = Task(**payload.model_dump())
    db.add(obj); db.commit(); db.refresh(obj)
    return obj

@router.post("/{task_id}/dispatch", response_model=TaskOut)
async def dispatch(task_id: int, principal: Principal = Depends(require_role("member")), db: Session = Depends(get_db)):
    task = ensure_task(db, task_id, principal)
    return await dispatch_task(db, task)
