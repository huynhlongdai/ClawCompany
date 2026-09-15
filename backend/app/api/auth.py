import json, secrets
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.models import User, UserOrganizationAccess, APIKey, Member
from app.schemas.auth import RegisterRequest, LoginRequest, TokenResponse, UserOut, APIKeyCreate, APIKeyCreated, OrganizationAccessGrant
from app.core.security import hash_password, verify_password, create_access_token, pwd_context
from app.core.authz import get_principal, Principal, require_role, enforce_org

router = APIRouter(prefix="/auth", tags=["auth"])

@router.post("/register", response_model=UserOut)
def register(payload: RegisterRequest, db: Session = Depends(get_db)):
    """Public registration creates an identity only.

    Organization membership and role are granted separately by an organization admin.
    This prevents self-registration from becoming a tenant/role escalation path.
    """
    if db.query(User).filter(User.email == payload.email).first():
        raise HTTPException(409, "Email already exists")
    user = User(email=payload.email, password_hash=hash_password(payload.password), display_name=payload.display_name)
    db.add(user); db.commit(); db.refresh(user)
    return user

@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email).first()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(401, "Invalid credentials")
    accesses = db.query(UserOrganizationAccess).filter(UserOrganizationAccess.user_id == user.id).all()
    access = None
    if payload.organization_id:
        access = next((x for x in accesses if x.organization_id == payload.organization_id), None)
        if not access and not user.is_superuser:
            raise HTTPException(403, "No access to organization")
    else:
        access = next((x for x in accesses if x.is_default), None) or (accesses[0] if accesses else None)
    org_id = access.organization_id if access else None
    role = "owner" if user.is_superuser else (access.role if access else "member")
    return TokenResponse(access_token=create_access_token(user.id, org_id, role), organization_id=org_id, role=role)

@router.get("/me", response_model=UserOut)
def me(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    if principal.user_id is None:
        raise HTTPException(400, "API key has no user profile")
    return db.get(User, principal.user_id)

@router.post("/organization-access")
def grant_organization_access(payload: OrganizationAccessGrant, principal: Principal = Depends(require_role("admin")), db: Session = Depends(get_db)):
    enforce_org(payload.organization_id, principal)
    user = db.get(User, payload.user_id)
    if not user:
        raise HTTPException(404, "User not found")
    item = db.query(UserOrganizationAccess).filter(
        UserOrganizationAccess.user_id == payload.user_id,
        UserOrganizationAccess.organization_id == payload.organization_id,
    ).first()
    if item:
        item.role = payload.role
        item.is_default = payload.is_default
    else:
        item = UserOrganizationAccess(**payload.model_dump())
    if payload.is_default:
        db.query(UserOrganizationAccess).filter(UserOrganizationAccess.user_id == payload.user_id).update({UserOrganizationAccess.is_default: False})
        item.is_default = True
    db.add(item); db.commit(); db.refresh(item)
    return {"id": item.id, "user_id": item.user_id, "organization_id": item.organization_id, "role": item.role, "is_default": item.is_default}

@router.post("/api-keys", response_model=APIKeyCreated)
def create_api_key(payload: APIKeyCreate, principal: Principal = Depends(require_role("admin")), db: Session = Depends(get_db)):
    enforce_org(payload.organization_id, principal)
    if payload.member_id is not None:
        member = db.get(Member, payload.member_id)
        if not member or member.organization_id != payload.organization_id:
            raise HTTPException(400, "member_id must belong to organization")
    raw = "cc_" + secrets.token_urlsafe(32)
    item = APIKey(
        organization_id=payload.organization_id,
        member_id=payload.member_id,
        name=payload.name,
        key_prefix=raw[:12],
        key_hash=pwd_context.hash(raw),
        scopes=json.dumps(payload.scopes),
        created_by_user_id=principal.user_id,
    )
    db.add(item); db.commit(); db.refresh(item)
    return APIKeyCreated(id=item.id, name=item.name, key=raw, key_prefix=item.key_prefix)
