from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.models import Company
from app.schemas import CompanyCreate, CompanyOut
from app.core.authz import Principal, get_principal, require_role, enforce_org, require_human
from app.core.tenancy import active_org

router = APIRouter(prefix="/companies", tags=["companies"])

@router.get("", response_model=list[CompanyOut])
def list_companies(organization_id: int | None = None, principal: Principal = Depends(require_human()), db: Session = Depends(get_db)):
    org_id = active_org(principal)
    if organization_id is not None:
        enforce_org(organization_id, principal)
    from app.core import company_scope  # P0
    ids = company_scope.allowed_company_ids(principal)
    q = db.query(Company).filter(Company.organization_id == org_id)
    if ids is not None:
        q = q.filter(Company.id.in_(ids or [-1]))
    return q.order_by(Company.id).all()

@router.post("", response_model=CompanyOut)
def create_company(payload: CompanyCreate, principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    enforce_org(payload.organization_id, principal)
    obj = Company(**payload.model_dump())
    db.add(obj); db.commit(); db.refresh(obj)
    from app.services.provisioning import seed_authority
    seed_authority(db, obj)
    return obj
