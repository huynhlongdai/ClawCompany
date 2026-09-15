from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.models import Organization, UserOrganizationAccess
from app.schemas import OrganizationCreate, OrganizationOut
from app.core.authz import Principal, get_principal, require_role, require_human

router = APIRouter(prefix="/organizations", tags=["organizations"])

@router.get("", response_model=list[OrganizationOut])
def list_organizations(principal: Principal = Depends(require_human()), db: Session = Depends(get_db)):
    if principal.organization_id is None:
        return []
    item = db.get(Organization, principal.organization_id)
    return [item] if item else []

@router.post("", response_model=OrganizationOut)
def create_organization(payload: OrganizationCreate, principal: Principal = Depends(require_role("owner")), db: Session = Depends(get_db)):
    if db.query(Organization).filter((Organization.slug == payload.slug) | (Organization.name == payload.name)).first():
        raise HTTPException(409, "Organization name or slug already exists")
    obj = Organization(**payload.model_dump())
    db.add(obj); db.commit(); db.refresh(obj)
    if principal.user_id is not None:
        db.add(UserOrganizationAccess(user_id=principal.user_id, organization_id=obj.id, role="owner", is_default=False))
        db.commit()
    return obj
