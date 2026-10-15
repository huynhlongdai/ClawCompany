"""M4b — /api/inbox (Hộp việc, phê duyệt) và /api/costs (Chi phí, ngân sách ba nấc).

Gom các đường cũ: ``/v9/inbox/mine``, ``/v9/inbox/{id}/status``, ``/v9/approvals/quick``,
``/v9/approvals/escalate-overdue``, ``/approvals/{id}/resolve``, ``/v21/approvals/{id}/decide``,
``GET /inbox`` + ``/inbox/{id}/read`` (extended), ``/v9/budgets*``. Các đường cũ vẫn chạy và trả
``Deprecation: true`` + ``Link: <…>; rel="successor-version"`` (bảng ``DEPRECATED``).
Luật nằm ở ``services/inbox_hub.py``, ``services/cost_board.py``, ``services/budget_scope.py``.
"""
import re

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.authz import Principal, require_human, require_role
from app.core.tenancy import active_org
from app.db.session import get_db
from app.models import BudgetEnvelope, Member
from app.services import budget_scope, cost_board, inbox_hub
from app.services.work_board import WorkError

router = APIRouter(prefix="/inbox", tags=["inbox"])
costs_router = APIRouter(prefix="/costs", tags=["costs"])

# (method | None, đường cũ, đường mới)
DEPRECATED = [
    ("GET", re.compile(r"^/api/inbox$"), "/api/inbox/items"),
    (None, re.compile(r"^/api/inbox/(\d+)/read$"), "/api/inbox/items/{0}/status"),
    (None, re.compile(r"^/api/v9/inbox/mine$"), "/api/inbox/items"),
    (None, re.compile(r"^/api/v9/inbox/(\d+)/status$"), "/api/inbox/items/{0}/status"),
    (None, re.compile(r"^/api/v9/approvals/quick$"), "/api/inbox/items?group=approvals"),
    (None, re.compile(r"^/api/v9/approvals/escalate-overdue$"), "/api/inbox/escalate"),
    (None, re.compile(r"^/api/approvals/(\d+)/resolve$"), "/api/inbox/approvals/{0}/decide"),
    (None, re.compile(r"^/api/v21/approvals/(\d+)/decide$"), "/api/inbox/approvals/{0}/decide"),
    (None, re.compile(r"^/api/v9/budgets$"), "/api/costs/budgets"),
    (None, re.compile(r"^/api/v9/budgets-overview$"), "/api/costs/overview"),
    ("GET", re.compile(r"^/api/v9/budgets/(\d+)$"), "/api/costs/budgets/{0}"),
    (None, re.compile(r"^/api/v9/budgets/(\d+)/override$"), "/api/costs/budgets/{0}/override"),
]


def successor(path: str, method: str = "GET") -> str | None:
    for meth, rx, target in DEPRECATED:
        if meth and meth != method:
            continue
        m = rx.match(path)
        if m:
            return target.format(*m.groups())
    return None


# ------------------------------------------------------------------ Hộp việc


class StatusIn(BaseModel):
    status: str


class DecideIn(BaseModel):
    decision: str = Field(pattern="^(approve|reject)$")
    note: str = Field(default="", max_length=2000)
    expected_revision: int | None = None
    grant_scope: str | None = None   # chi tiếp ngân sách: task | seat | department
    edited_text: str = Field(default="", max_length=600)   # bài học: người duyệt sửa câu chữ trước khi ghi


@router.get("/items")
def items(status: str = "open", group: str | None = None, member_id: int | None = None,
          department_id: int | None = None, company_id: int | None = None,
          principal: Principal = Depends(require_human()), db: Session = Depends(get_db)):
    if group is not None and group not in inbox_hub.GROUP_VI:
        raise WorkError(422, "bad_group", "Nhóm chỉ được là approvals, review, budget, lessons hoặc updates")
    return inbox_hub.feed(db, active_org(principal), principal, status=status, group=group,
                          member_id=member_id, department_id=department_id, company_id=company_id)


@router.get("/summary")
def summary(principal: Principal = Depends(require_human()), db: Session = Depends(get_db)):
    """Số đếm cho chuông / menu (không trả danh sách)."""
    return inbox_hub.feed(db, active_org(principal), principal)["counts"]


@router.post("/items/{item_id}/status")
def item_status(item_id: int, payload: StatusIn, principal: Principal = Depends(require_human()),
                db: Session = Depends(get_db)):
    return inbox_hub.set_status(db, active_org(principal), principal, item_id, payload.status)


@router.post("/items/read-all")
def read_all(principal: Principal = Depends(require_human()), db: Session = Depends(get_db)):
    return {"updated": inbox_hub.mark_all_read(db, active_org(principal), principal)}


@router.get("/items/{item_id}")
def item_detail(item_id: int, principal: Principal = Depends(require_human()), db: Session = Depends(get_db)):
    """Chi tiết một mục hộp việc; mở ra thì tính là đã đọc."""
    return inbox_hub.item_detail(db, active_org(principal), principal, item_id)


@router.get("/approvals/{approval_id}")
def approval_detail(approval_id: int, principal: Principal = Depends(require_human()), db: Session = Depends(get_db)):
    """Chi tiết một yêu cầu duyệt: ai xin, xin làm gì (lệnh/nội dung/số tiền), việc liên quan, hạn."""
    return inbox_hub.approval_detail(db, active_org(principal), principal, approval_id)


@router.post("/approvals/{approval_id}/decide")
async def decide(approval_id: int, payload: DecideIn, principal: Principal = Depends(require_human()),
                 db: Session = Depends(get_db)):
    """Duyệt một chạm. Từ chối phải có lý do. 409 khi đã có người quyết / nội dung vừa đổi."""
    return await inbox_hub.decide(db, active_org(principal), principal, approval_id, decision=payload.decision,
                                  note=payload.note, expected_revision=payload.expected_revision,
                                  grant_scope=payload.grant_scope, edited_text=payload.edited_text)


@router.post("/escalate")
def escalate(principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    """Chạy ngay vòng leo thang (bình thường Celery beat / vòng trong tiến trình chạy mỗi phút)."""
    return inbox_hub.escalate(db, active_org(principal))


# ------------------------------------------------------------------ Chi phí


class BudgetIn(BaseModel):
    name: str = Field(default="", max_length=180)
    scope_type: str
    scope_id: int | None = None
    amount_limit: float = Field(gt=0)
    warn_pct: int | None = 80
    soft_stop_pct: int | None = None


class BudgetPatch(BaseModel):
    name: str | None = Field(default=None, max_length=180)
    amount_limit: float | None = None
    warn_pct: int | None = None
    soft_stop_pct: int | None = None


class OverrideIn(BaseModel):
    reason: str = Field(default="", max_length=500)
    amount_limit: float | None = Field(default=None, gt=0)
    add_usd: float | None = Field(default=None, gt=0)


def _budget(db: Session, budget_id: int, principal: Principal) -> BudgetEnvelope:
    env = db.get(BudgetEnvelope, budget_id)
    if env is None or env.organization_id != active_org(principal):
        raise WorkError(404, "not_found", "Không tìm thấy ngân sách này")
    return env


@costs_router.get("/overview")
def costs_overview(days: int = 30, principal: Principal = Depends(require_human()), db: Session = Depends(get_db)):
    return cost_board.overview(db, active_org(principal), days=days)


@costs_router.get("/budgets")
def budgets(include_archived: bool = False, principal: Principal = Depends(require_human()),
            db: Session = Depends(get_db)):
    from app.models import Company, Department
    from app.models.v16 import AgentTeam
    org = active_org(principal)
    cids = [c.id for c in db.query(Company).filter(Company.organization_id == org).all()]
    return {"budgets": cost_board.list_budgets(db, org, include_archived),
            "caps": {"manage": inbox_hub.is_manager(principal)},
            "scopes": {
                "company": [{"id": c.id, "name": c.name} for c in
                            db.query(Company).filter(Company.organization_id == org).order_by(Company.id)],
                "department": [{"id": d.id, "name": d.name, "company_id": d.company_id} for d in
                               (db.query(Department).filter(Department.company_id.in_(cids)).order_by(Department.id)
                                if cids else [])],
                "team": [{"id": t.id, "name": t.name} for t in
                         db.query(AgentTeam).filter(AgentTeam.organization_id == org).order_by(AgentTeam.id)],
                "member": [{"id": m.id, "name": m.name} for m in
                           db.query(Member).filter(Member.organization_id == org, Member.member_type == "agent",
                                                   Member.status != "retired").order_by(Member.name)]}}


@costs_router.post("/budgets", status_code=201)
def create_budget(payload: BudgetIn, principal: Principal = Depends(require_role("manager")),
                  db: Session = Depends(get_db)):
    env = cost_board.create(db, active_org(principal), payload.model_dump())
    return cost_board.budget_row(db, env)


@costs_router.get("/budgets/{budget_id}")
def budget_detail(budget_id: int, principal: Principal = Depends(require_human()), db: Session = Depends(get_db)):
    return cost_board.detail(db, _budget(db, budget_id, principal))


@costs_router.patch("/budgets/{budget_id}")
def patch_budget(budget_id: int, payload: BudgetPatch, principal: Principal = Depends(require_role("manager")),
                 db: Session = Depends(get_db)):
    env = _budget(db, budget_id, principal)
    out = cost_board.update(db, env, payload.model_dump(exclude_unset=True))
    db.refresh(env)
    return {"budget": cost_board.budget_row(db, env), "threshold": out}


@costs_router.post("/budgets/{budget_id}/override")
def override_budget(budget_id: int, payload: OverrideIn, principal: Principal = Depends(require_role("manager")),
                    db: Session = Depends(get_db)):
    """Nâng hạn mức (đường duy nhất mở lại ngân sách đã dừng cứng): cần lý do, ghi audit."""
    env = _budget(db, budget_id, principal)
    if not payload.reason.strip() or len(payload.reason.strip()) < 3:
        raise WorkError(422, "reason_required", "Ghi lý do nâng hạn mức (ít nhất 3 ký tự) — lý do được lưu vào nhật ký")
    if payload.amount_limit is None and payload.add_usd is None:
        raise WorkError(422, "amount_required", "Nhập hạn mức mới hoặc số tiền cộng thêm")
    member = db.get(Member, principal.member_id) if principal.member_id else None
    out = budget_scope.override(db, env, actor_member_id=member.id if member else None,
                                actor_name=member.name if member else f"user#{principal.user_id}",
                                reason=payload.reason.strip(), new_limit=payload.amount_limit, add_usd=payload.add_usd)
    db.refresh(env)
    return {"budget": cost_board.budget_row(db, env), **out}


@costs_router.delete("/budgets/{budget_id}")
def archive_budget(budget_id: int, principal: Principal = Depends(require_role("manager")),
                   db: Session = Depends(get_db)):
    env = _budget(db, budget_id, principal)
    if (env.threshold_state or "ok") == "exhausted":
        raise WorkError(409, "exhausted",
                        "Ngân sách đang dừng cứng — nâng hạn mức để mở lại seat/việc trước khi lưu trữ")
    env.status = "archived"
    db.add(env); db.commit()
    budget_scope.expire_soft_grants(db, env, "ngân sách đã lưu trữ")
    return {"archived": env.id}
