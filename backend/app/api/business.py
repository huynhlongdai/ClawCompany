"""P1 — gói "Kinh doanh" của module Công ty: khách hàng & đồng ý DLCN (M3g), hợp đồng & đối tác (M3h), họp & quyết định (M3i),
tài chính kinh doanh (M3j). Spec: docs/company-knowledge-library-and-gaps.md §C. Mọi route thuộc phạm vi công ty
(R1: require_company_role ở cổng + company_scope.check ở service; khai trong company_guard.AWARE)."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.authz import Principal, require_company_role
from app.core.tenancy import active_org
from app.db.session import get_db

router = APIRouter(prefix="/team", tags=["business"])


# ------------------------------------------------------------------ M3g khách hàng & DLCN

@router.get("/crm/contacts")
def crm_list(company_id: int | None = None, q: str = "", segment: str = "", consent: str = "",
             principal: Principal = Depends(require_company_role("member")), db: Session = Depends(get_db)):
    from app.services import crm
    return crm.listing(db, active_org(principal), principal, company_id, q=q, segment=segment, consent=consent)


@router.post("/crm/contacts")
def crm_create(payload: dict, principal: Principal = Depends(require_company_role("manager")), db: Session = Depends(get_db)):
    from app.services import crm
    return crm.create_contact(db, active_org(principal), principal, payload)


@router.get("/crm/contacts/{contact_id}")
def crm_get(contact_id: int, principal: Principal = Depends(require_company_role("member")), db: Session = Depends(get_db)):
    from app.services import crm
    return crm.get_contact(db, active_org(principal), principal, contact_id)


@router.patch("/crm/contacts/{contact_id}")
def crm_patch(contact_id: int, payload: dict, principal: Principal = Depends(require_company_role("manager")),
              db: Session = Depends(get_db)):
    from app.services import crm
    return crm.update_contact(db, active_org(principal), principal, contact_id, payload)


@router.post("/crm/contacts/{contact_id}/consents")
def crm_consent(contact_id: int, payload: dict, principal: Principal = Depends(require_company_role("manager")),
                db: Session = Depends(get_db)):
    from app.services import crm
    return crm.grant_consent(db, active_org(principal), principal, contact_id, payload)


@router.post("/crm/consents/{consent_id}/withdraw")
def crm_withdraw(consent_id: int, payload: dict | None = None, principal: Principal = Depends(require_company_role("manager")),
                 db: Session = Depends(get_db)):
    from app.services import crm
    return crm.withdraw_consent(db, active_org(principal), principal, consent_id, (payload or {}).get("reason", ""))


@router.post("/crm/contacts/{contact_id}/interactions")
def crm_interaction(contact_id: int, payload: dict, principal: Principal = Depends(require_company_role("manager")),
                    db: Session = Depends(get_db)):
    from app.services import crm
    return crm.add_interaction(db, active_org(principal), principal, contact_id, payload)


@router.post("/crm/contacts/{contact_id}/outreach")
def crm_outreach(contact_id: int, payload: dict, principal: Principal = Depends(require_company_role("manager")),
                 db: Session = Depends(get_db)):
    from app.services import crm
    return crm.outreach(db, active_org(principal), principal, contact_id, payload)


@router.get("/crm/audience")
def crm_audience(company_id: int | None = None, channel: str = "other",
                 principal: Principal = Depends(require_company_role("manager")), db: Session = Depends(get_db)):
    from app.services import crm
    ids = crm.marketing_audience(db, active_org(principal), company_id, channel)
    return {"channel": channel, "contact_ids": ids, "count": len(ids)}


@router.post("/crm/contacts/{contact_id}/requests")
def crm_request_open(contact_id: int, payload: dict, principal: Principal = Depends(require_company_role("manager")),
                     db: Session = Depends(get_db)):
    from app.services import crm
    return crm.open_request(db, active_org(principal), principal, contact_id, payload)


@router.get("/crm/requests")
def crm_requests(company_id: int | None = None, status: str = "", principal: Principal = Depends(require_company_role("member")),
                 db: Session = Depends(get_db)):
    from app.services import crm
    return crm.requests_list(db, active_org(principal), company_id, status)


@router.post("/crm/requests/{request_id}/act")
def crm_request_act(request_id: int, payload: dict, principal: Principal = Depends(require_company_role("manager")),
                    db: Session = Depends(get_db)):
    from app.services import crm
    return crm.act_request(db, active_org(principal), principal, request_id, payload)


@router.post("/crm/lookup")
def crm_lookup_preview(payload: dict, principal: Principal = Depends(require_company_role("member")),
                       db: Session = Depends(get_db)):
    """Xem trước đúng thứ một agent của phòng ``department_id`` nhận từ MCP company_customer_lookup (đã che PII)."""
    from app.models import Member
    from app.services import crm
    from app.services.company_foundation import _company
    co = _company(db, active_org(principal), payload.get("company_id"))
    fake = Member(organization_id=co.organization_id, company_id=co.id, department_id=payload.get("department_id"),
                  name="preview", member_type="agent")
    return crm.agent_lookup(db, fake, query=str(payload.get("query") or "")[:200])
