from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.models import Department, Company
from app.schemas import DepartmentCreate, DepartmentOut
from app.core.authz import Principal, get_principal, require_role, require_human
from app.core.tenancy import active_org, ensure_company

router = APIRouter(prefix="/departments", tags=["departments"])

@router.get("", response_model=list[DepartmentOut])
def list_departments(company_id: int | None = None, principal: Principal = Depends(require_human()), db: Session = Depends(get_db)):
    org_id = active_org(principal)
    q = db.query(Department).join(Company, Company.id == Department.company_id).filter(Company.organization_id == org_id)
    if company_id is not None:
        ensure_company(db, company_id, principal)
        q = q.filter(Department.company_id == company_id)
    return q.order_by(Department.id).all()

@router.post("", response_model=DepartmentOut)
def create_department(payload: DepartmentCreate, principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    ensure_company(db, payload.company_id, principal)
    obj = Department(**payload.model_dump())
    db.add(obj); db.commit(); db.refresh(obj)
    return obj
