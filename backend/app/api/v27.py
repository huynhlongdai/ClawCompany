"""v27: the write half of the cockpit, finished.

These endpoints close the three debts v18 declared in its own "giới hạn cố ý"
section: a hand-typed progress number, no optimistic concurrency, and no
archive path because the cascade needed designing.
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.authz import Principal, require_role, require_scope
from app.core.tenancy import active_org, ensure_project, ensure_task
from app.db.session import get_db
from app.services import board_truth

router = APIRouter(prefix="/v27", tags=["v27-board-truth"])

READ = "company.context:read"
WRITE = "company.workspace:write"  # same scope as v18: this is cockpit writing


def writer(minimum_role: str = "member"):
    def dep(principal: Principal = Depends(require_scope(WRITE))) -> Principal:
        if principal.auth_type != "api_key":
            return require_role(minimum_role)(principal)
        return principal
    return dep


class RevisionIn(BaseModel):
    expected_revision: str | None = Field(default=None, max_length=200)


class ArchiveIn(RevisionIn):
    force: bool = False


@router.get("/projects/{project_id}/truth")
def project_truth(project_id: int, principal: Principal = Depends(require_scope(READ)),
                  db: Session = Depends(get_db)):
    """What the board says, what the column says, and the gap between them."""
    project = ensure_project(db, project_id, principal)
    return board_truth.derive(db, project)


@router.post("/projects/{project_id}/progress/sync")
def sync_progress(project_id: int, payload: ArchiveIn | None = None,
                  principal: Principal = Depends(writer("member")),
                  db: Session = Depends(get_db)):
    """Apply the derived number. Explicit, because the column is read widely."""
    project = ensure_project(db, project_id, principal)
    return board_truth.sync_progress(
        db, project, active_org(principal),
        expected_revision=(payload.expected_revision if payload else None),
        actor_member_id=principal.member_id,
    )


@router.get("/projects/{project_id}/archive/preview")
def archive_preview(project_id: int, principal: Principal = Depends(require_scope(READ)),
                    db: Session = Depends(get_db)):
    """Exactly what archiving would cancel, and what would block it."""
    project = ensure_project(db, project_id, principal)
    return board_truth.archive_preview(db, project)


@router.post("/projects/{project_id}/archive")
def archive(project_id: int, payload: ArchiveIn | None = None,
            principal: Principal = Depends(writer("manager")),
            db: Session = Depends(get_db)):
    """Archive by cancelling what is still owed. Nothing is deleted."""
    project = ensure_project(db, project_id, principal)
    return board_truth.archive_project(
        db, project, active_org(principal),
        force=(payload.force if payload else False),
        expected_revision=(payload.expected_revision if payload else None),
        actor_member_id=principal.member_id,
    )


@router.get("/revisions/project/{project_id}")
def project_revision(project_id: int, principal: Principal = Depends(require_scope(READ)),
                     db: Session = Depends(get_db)):
    """Read a revision token before a guarded write."""
    project = ensure_project(db, project_id, principal)
    return {"kind": "project", "id": project.id, "revision": board_truth.revision(project),
            "updated_at": project.updated_at.isoformat() if project.updated_at else None}


@router.get("/revisions/task/{task_id}")
def task_revision(task_id: int, principal: Principal = Depends(require_scope(READ)),
                  db: Session = Depends(get_db)):
    task = ensure_task(db, task_id, principal)
    return {"kind": "task", "id": task.id, "revision": board_truth.revision(task),
            "updated_at": task.updated_at.isoformat() if task.updated_at else None}


class TaskMoveIn(RevisionIn):
    status: str = Field(min_length=1, max_length=32)


@router.post("/tasks/{task_id}/move")
def guarded_move(task_id: int, payload: TaskMoveIn,
                 principal: Principal = Depends(writer("member")),
                 db: Session = Depends(get_db)):
    """v18's task move, but refusing a write built on a stale read.

    The v18 endpoint stays exactly as it was -- requiring revisions there
    would break every existing client. Opting in is what buys the guarantee.
    """
    from app.services import workspace_ops as ops

    task = ensure_task(db, task_id, principal)
    board_truth.check_revision(db, task, payload.expected_revision,
                               organization_id=active_org(principal))
    project = ensure_project(db, task.project_id, principal)
    task = ops.move_task(db, task, project, active_org(principal), status=payload.status,
                         actor_member_id=principal.member_id)
    return {"task_id": task.id, "status": task.status,
            "revision": board_truth.revision(task),
            "project_truth": board_truth.derive(db, project)}
