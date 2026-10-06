"""D3.4 API: routines (cron theo múi giờ / webhook) — xem app/services/routines.py."""
from fastapi import APIRouter, Body, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.authz import Principal, require_role, require_scope
from app.core.tenancy import active_org
from app.db.session import get_db
from app.models.routines import Routine, RoutineRun
from app.services import routines as svc

router = APIRouter(prefix="/routines", tags=["d34-routines"])
READ = "company.context:read"
HTTP = {"invalid_argument": 422, "not_found": 404, "forbidden": 403, "conflict": 409}


def _err(exc: svc.RoutineError) -> HTTPException:
    return HTTPException(HTTP.get(exc.code, 400), {"error": exc.code, "message": exc.message})


class RoutineIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    runbook: str = ""
    assignee_member_id: int | None = None
    department_id: int | None = None
    project_id: int | None = None
    mode: str = "create_task"
    timezone: str = "Asia/Ho_Chi_Minh"
    catch_up: str = "skip_missed"
    cron: str = ""
    webhook: bool = False
    max_consecutive_failures: int = 3


class FromTemplateIn(BaseModel):
    key: str
    assignee_member_id: int | None = None
    department_id: int | None = None
    cron: str | None = None


class RoutinePatch(BaseModel):
    enabled: bool


def _get(db: Session, principal: Principal, routine_id: int) -> Routine:
    r = db.get(Routine, routine_id)
    if r is None or r.organization_id != active_org(principal):
        raise HTTPException(404, "Không thấy routine")
    return r


@router.get("/templates")
def list_templates(principal: Principal = Depends(require_scope(READ))):
    return {"templates": svc.templates()}


@router.get("")
def list_routines(principal: Principal = Depends(require_scope(READ)), db: Session = Depends(get_db)):
    rows = db.query(Routine).filter(Routine.organization_id == active_org(principal)).order_by(Routine.id).all()
    return {"routines": [svc.public(db, r) for r in rows]}


@router.post("")
def create(payload: RoutineIn, principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    try:
        r = svc.create_routine(db, active_org(principal), name=payload.name, runbook=payload.runbook,
                               assignee_member_id=payload.assignee_member_id, department_id=payload.department_id,
                               project_id=payload.project_id, mode=payload.mode, timezone_name=payload.timezone,
                               catch_up=payload.catch_up, cron=payload.cron, webhook=payload.webhook,
                               max_consecutive_failures=payload.max_consecutive_failures,
                               owner_member_id=principal.member_id)
    except svc.RoutineError as exc:
        raise _err(exc)
    return svc.public(db, r, with_secret=True)


@router.post("/from-template")
def create_from_template(payload: FromTemplateIn, principal: Principal = Depends(require_role("manager")),
                         db: Session = Depends(get_db)):
    try:
        r = svc.from_template(db, active_org(principal), payload.key, assignee_member_id=payload.assignee_member_id,
                              department_id=payload.department_id, owner_member_id=principal.member_id,
                              cron=payload.cron)
    except svc.RoutineError as exc:
        raise _err(exc)
    return svc.public(db, r, with_secret=True)


@router.post("/tick")
def tick_now(principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    """Chạy một nhịp beat ngay cho tổ chức của mình (dev/kiểm thử)."""
    return {"fired": svc.tick(db, organization_id=active_org(principal))}


@router.get("/{routine_id}")
def get_routine(routine_id: int, principal: Principal = Depends(require_role("manager")),
                db: Session = Depends(get_db)):
    return svc.public(db, _get(db, principal, routine_id), with_secret=True)


@router.patch("/{routine_id}")
def patch(routine_id: int, payload: RoutinePatch, principal: Principal = Depends(require_role("manager")),
          db: Session = Depends(get_db)):
    r = svc.set_enabled(db, _get(db, principal, routine_id), payload.enabled, actor_member_id=principal.member_id)
    return svc.public(db, r)


@router.post("/{routine_id}/run")
def run(routine_id: int, principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    r = _get(db, principal, routine_id)
    if not r.enabled:
        raise HTTPException(409, f"Routine đang dừng: {r.paused_reason or 'tắt tay'}")
    return svc.public_run(svc.run_now(db, r))


@router.get("/{routine_id}/runs")
def runs(routine_id: int, limit: int = 50, principal: Principal = Depends(require_scope(READ)),
         db: Session = Depends(get_db)):
    r = _get(db, principal, routine_id)
    svc.reconcile_open(db, routine_id=r.id)
    rows = (db.query(RoutineRun).filter(RoutineRun.routine_id == r.id).order_by(RoutineRun.id.desc())
            .limit(max(1, min(limit, 200))).all())
    return {"routine": svc.public(db, r), "runs": [svc.public_run(x) for x in rows]}


@router.post("/hooks/{trigger_id}")
def hook(trigger_id: int, payload: dict | None = Body(default=None),
         x_routine_secret: str = Header(default=""), idempotency_key: str = Header(default=""),
         db: Session = Depends(get_db)):
    """Webhook công khai: xác thực bằng ``X-Routine-Secret``; ``Idempotency-Key`` bắt buộc —
    gửi lại cùng key trả lần chạy cũ, không tạo việc mới."""
    try:
        return svc.webhook(db, trigger_id, secret=x_routine_secret, idempotency_key=idempotency_key,
                           payload=payload)
    except svc.RoutineError as exc:
        raise _err(exc) if exc.code != "invalid_argument" else HTTPException(400, exc.message)
