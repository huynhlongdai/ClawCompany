from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.models import Approval
from app.schemas import ApprovalCreate, ApprovalResolve, ApprovalOut
from app.core.authz import Principal, get_principal, require_role, enforce_org, require_human
from app.core.tenancy import active_org, ensure_company, ensure_member

router = APIRouter(prefix="/approvals", tags=["approvals"])

@router.get("", response_model=list[ApprovalOut])
def list_approvals(status: str | None = None, principal: Principal = Depends(require_human()), db: Session = Depends(get_db)):
    org_id = active_org(principal)
    q = db.query(Approval).filter(Approval.organization_id == org_id)
    if status: q = q.filter(Approval.status == status)
    return q.order_by(Approval.id.desc()).all()

@router.post("", response_model=ApprovalOut)
def create_approval(payload: ApprovalCreate, principal: Principal = Depends(require_role("member")), db: Session = Depends(get_db)):
    enforce_org(payload.organization_id, principal)
    if payload.company_id is not None: ensure_company(db, payload.company_id, principal)
    if payload.requester_member_id is not None: ensure_member(db, payload.requester_member_id, principal)
    if payload.approver_member_id is not None: ensure_member(db, payload.approver_member_id, principal)
    obj = Approval(**payload.model_dump())
    db.add(obj); db.commit(); db.refresh(obj)
    return obj

@router.post("/{approval_id}/resolve", response_model=ApprovalOut)
async def resolve_approval(approval_id: int, payload: ApprovalResolve, principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    """Nút Duyệt/Từ chối của Hộp việc.

    D1.1: hàng sinh từ gateway (``policy_key`` ``openclaw:...``) phải đi qua
    ``approval_bridge.decide`` để quyết định tới được ``exec.approval.resolve``.
    Bản trước chỉ đổi cột status, nên lệnh của agent treo tới khi hết hạn dù
    Hộp việc báo "đã duyệt" (đo trên gateway thật, xem _reports/approval-e2e.md).
    """
    from fastapi import HTTPException
    obj = db.get(Approval, approval_id)
    if not obj: raise HTTPException(404, "Approval not found")
    enforce_org(obj.organization_id, principal)
    if (obj.policy_key or "").startswith("openclaw:"):
        from app.services import approval_bridge
        if payload.status not in ("approved", "rejected", "denied"):
            raise HTTPException(422, "OpenClaw approvals take approved or rejected")
        try:
            await approval_bridge.decide(db, obj, decision="approved" if payload.status == "approved" else "denied",
                                         note=payload.resolution_note or "", actor_member_id=principal.member_id)
        except approval_bridge.ApprovalBridgeError as exc:
            raise HTTPException(409, str(exc))
        db.refresh(obj)
        return obj
    obj.status = payload.status; obj.resolution_note = payload.resolution_note
    db.add(obj); db.commit(); db.refresh(obj)
    from app.services.runtime_stream import _audit
    _audit(db, obj, "approval.decided", actor_member_id=principal.member_id, actor_name="human",
           result=payload.status, payload={"decision": payload.status, "policy_key": obj.policy_key})
    _wake_requester(db, obj)
    return obj


def _wake_requester(db: Session, obj: Approval) -> None:
    """D2.1: approval của seat agent có kết quả → đánh thức seat đó trên việc nó đang làm.

    Hàng ``openclaw:`` không đi qua đây: lượt chạy đang chờ tự chạy tiếp khi
    gateway nhận quyết định, đánh thức thêm chỉ sinh lượt thứ hai."""
    if obj.status not in ("approved", "rejected") or not obj.requester_member_id:
        return
    from app.models import Task, TaskRun
    from app.services import wakeup
    last = (db.query(TaskRun).filter(TaskRun.member_id == obj.requester_member_id)
            .order_by(TaskRun.id.desc()).first())
    task = db.get(Task, last.task_id) if last else None
    if task is not None:
        wakeup.enqueue_for_task(db, task, "approval_resolved", member_id=obj.requester_member_id,
                                dedupe_key=f"approval_resolved:a{obj.id}:{obj.status}",
                                payload={"approval_id": obj.id, "decision": obj.status})
