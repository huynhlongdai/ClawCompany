"""D3.3 API: kế hoạch mục tiêu của Nina — xem, yêu cầu sửa. Duyệt/Từ chối đi qua
``POST /api/approvals/{id}/resolve`` (Hộp việc) như mọi phê duyệt khác."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.authz import Principal, require_human, require_role
from app.core.tenancy import active_org
from app.db.session import get_db
from app.models import Approval, ExecutiveGoal
from app.services import strategy as svc

router = APIRouter(prefix="/strategy", tags=["d33-strategy"])
HTTP = {"invalid_argument": 422, "not_found": 404, "forbidden": 403, "conflict": 409}


class RevisionIn(BaseModel):
    note: str


@router.get("/goals")
def goals(principal: Principal = Depends(require_human()), db: Session = Depends(get_db)):
    rows = (db.query(ExecutiveGoal).filter(ExecutiveGoal.organization_id == active_org(principal))
            .order_by(ExecutiveGoal.id.desc()).limit(100).all())
    return {"goals": [svc.goal_view(db, g) for g in rows]}


@router.get("/goals/{goal_id}")
def goal(goal_id: int, principal: Principal = Depends(require_human()), db: Session = Depends(get_db)):
    g = db.get(ExecutiveGoal, goal_id)
    if g is None or g.organization_id != active_org(principal):
        raise HTTPException(404, "Không thấy mục tiêu")
    return svc.goal_view(db, g)


@router.post("/plans/{approval_id}/request-revision")
def request_revision(approval_id: int, payload: RevisionIn, principal: Principal = Depends(require_role("manager")),
                     db: Session = Depends(get_db)):
    a = db.get(Approval, approval_id)
    if a is None or a.organization_id != active_org(principal):
        raise HTTPException(404, "Không thấy kế hoạch")
    if a.approver_member_id and principal.member_id != a.approver_member_id:
        raise HTTPException(403, {"error": "not_the_approver", "approver_member_id": a.approver_member_id})
    try:
        return svc.request_revision(db, a, note=payload.note, actor_member_id=principal.member_id)
    except svc.StrategyError as exc:
        raise HTTPException(HTTP.get(exc.code, 400), exc.message)
