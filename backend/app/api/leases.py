"""R2 — cho thuê agent (seat_leases). Spec: docs/r-rental-and-multi-company.md §R2.

Bên cho thuê (provider) và bên thuê (renter) là HAI tổ chức khác nhau; mỗi bên chỉ thấy phần của mình
(``seat_leases.view``): bên cho thuê thấy điều khoản + số đo đếm, không thấy ghế/việc/phiên của bên thuê."""
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.authz import Principal, require_company_role, require_role
from app.core.tenancy import active_org
from app.db.session import get_db
from app.runtime.factory import get_runtime
from app.services import seat_leases as svc

router = APIRouter(prefix="/leases", tags=["leases"])


class OfferIn(BaseModel):
    provider_agent_id: int | None = None
    name: str | None = None
    starts_at: str | None = None
    ends_at: str | None = None
    offer_expires_at: str | None = None
    price_per_task_usd: float | None = None
    price_per_hour_usd: float | None = None
    price_per_month_usd: float | None = None
    markup_pct: float | None = None
    monthly_cost_cap_usd: float | None = None
    allowed_tools: list[str] | None = None
    knowledge_doc_ids: list[int] | None = None
    data_handling: str | None = None
    approval_policy: dict | None = None


class AcceptIn(BaseModel):
    offer_code: str
    company_id: int
    position_id: int
    department_id: int | None = None
    name: str | None = None


class StatusIn(BaseModel):
    action: str
    reason: str = ""


class EndIn(BaseModel):
    reason: str = ""


class ChangeIn(BaseModel):
    changes: dict
    note: str = ""


class DecideIn(BaseModel):
    decision: str


class TickIn(BaseModel):
    now: str | None = None


@router.get("")
def list_leases(side: str = "provider", principal: Principal = Depends(require_company_role("member")),
                db: Session = Depends(get_db)):
    return svc.list_for(db, active_org(principal), side)


@router.post("")
def create_offer(payload: OfferIn, principal: Principal = Depends(require_company_role("admin")),
                 db: Session = Depends(get_db)):
    return svc.create_offer(db, active_org(principal), principal, payload.model_dump(exclude_unset=True))


@router.get("/offer/{code}")
def preview(code: str, principal: Principal = Depends(require_company_role("member")), db: Session = Depends(get_db)):
    return svc.preview_offer(db, code)


@router.post("/accept")
async def accept(payload: AcceptIn, principal: Principal = Depends(require_company_role("admin")),
                 db: Session = Depends(get_db)):
    return await svc.accept(db, active_org(principal), principal, get_runtime(), payload.model_dump())


@router.get("/{lease_id}")
def get_lease(lease_id: int, principal: Principal = Depends(require_company_role("member")), db: Session = Depends(get_db)):
    return svc.view(db, svc._get(db, lease_id), active_org(principal))


@router.get("/{lease_id}/policy")
def policy(lease_id: int, principal: Principal = Depends(require_company_role("member")), db: Session = Depends(get_db)):
    ls = svc._get(db, lease_id)
    svc.side_of(ls, active_org(principal))
    return {"lease_id": ls.id, "floor_section": svc.floor_section(db, ls), "scope_section": svc.scope_section(db, ls),
            "provider_rules": svc.provider_rules(db, ls), "allowed_tools": svc.provider_allowed_tools(db, ls),
            "approval_policy": svc._policy(ls)}


@router.patch("/{lease_id}")
def update_terms(lease_id: int, payload: OfferIn, principal: Principal = Depends(require_company_role("admin")),
                 db: Session = Depends(get_db)):
    return svc.update_terms(db, active_org(principal), lease_id, payload.model_dump(exclude_unset=True))


@router.post("/{lease_id}/status")
def set_status(lease_id: int, payload: StatusIn, principal: Principal = Depends(require_company_role("admin")),
               db: Session = Depends(get_db)):
    return svc.set_status(db, active_org(principal), lease_id, payload.action, payload.reason)


@router.post("/{lease_id}/end")
async def end(lease_id: int, payload: EndIn, principal: Principal = Depends(require_company_role("admin")),
              db: Session = Depends(get_db)):
    return await svc.end_by(db, active_org(principal), principal, get_runtime(), lease_id, payload.reason)


@router.post("/{lease_id}/change-requests")
def change_request(lease_id: int, payload: ChangeIn, principal: Principal = Depends(require_company_role("manager")),
                   db: Session = Depends(get_db)):
    return svc.request_change(db, active_org(principal), principal, lease_id, payload.model_dump())


@router.post("/{lease_id}/change-requests/{cr_id}/decide")
def decide_change(lease_id: int, cr_id: int, payload: DecideIn,
                  principal: Principal = Depends(require_company_role("admin")), db: Session = Depends(get_db)):
    return svc.decide_change(db, active_org(principal), lease_id, cr_id, payload.decision)


@router.post("/tick")
async def tick(payload: TickIn, principal: Principal = Depends(require_role("owner")), db: Session = Depends(get_db)):
    """Chạy tick hợp đồng ngay (beat chạy mỗi 5 phút). ``now`` (UTC ISO) để kiểm chứng tất định."""
    now = datetime.fromisoformat(payload.now.replace("Z", "")) if payload.now else None
    return {"results": await svc.tick(db, get_runtime(), now=now)}
