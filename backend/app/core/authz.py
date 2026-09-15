from dataclasses import dataclass
from datetime import datetime
from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.models import User, APIKey
from app.core.security import decode_access_token, pwd_context

bearer = HTTPBearer(auto_error=False)
ROLE_ORDER = {"guest":0,"member":1,"manager":2,"admin":3,"owner":4}

@dataclass
class Principal:
    user_id: int | None
    organization_id: int | None
    role: str
    auth_type: str
    scopes: list[str]
    member_id: int | None = None


def get_principal(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    db: Session = Depends(get_db),
) -> Principal:
    if x_api_key:
        prefix = x_api_key[:12]
        candidates = db.query(APIKey).filter(APIKey.key_prefix == prefix, APIKey.is_active == True).all()  # noqa: E712
        for item in candidates:
            if pwd_context.verify(x_api_key, item.key_hash):
                item.last_used_at = datetime.utcnow(); db.add(item); db.commit()
                import json
                try: scopes = json.loads(item.scopes or "[]")
                except Exception: scopes = []
                return Principal(None, item.organization_id, "api", "api_key", scopes, item.member_id)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")
    if not credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    try:
        claims = decode_access_token(credentials.credentials)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
    user = db.get(User, int(claims["sub"]))
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Inactive user")
    return Principal(user.id, claims.get("org_id"), claims.get("role", "member"), "jwt", [], user.member_id)



def require_human():
    def dep(principal: Principal = Depends(get_principal)):
        if principal.auth_type != "jwt":
            raise HTTPException(status_code=403, detail="Human user credential required")
        return principal
    return dep

def require_role(minimum_role: str):
    def dep(principal: Principal = Depends(get_principal)):
        if principal.auth_type == "api_key":
            # API keys do not inherit human roles. Endpoints that support API keys
            # should require an explicit scope via require_scope().
            raise HTTPException(status_code=403, detail="Human role required")
        if ROLE_ORDER.get(principal.role, -1) < ROLE_ORDER.get(minimum_role, 999):
            raise HTTPException(status_code=403, detail=f"{minimum_role} role required")
        return principal
    return dep


def require_scope(required_scope: str):
    def dep(principal: Principal = Depends(get_principal)):
        if principal.auth_type != "api_key":
            return principal
        scopes = set(principal.scopes or [])
        if "*" not in scopes and required_scope not in scopes:
            raise HTTPException(status_code=403, detail=f"API key scope required: {required_scope}")
        return principal
    return dep


def enforce_org(requested_org_id: int, principal: Principal):
    if principal.organization_id is None:
        raise HTTPException(status_code=403, detail="No organization is bound to this credential")
    if int(requested_org_id) != int(principal.organization_id):
        raise HTTPException(status_code=403, detail="Cross-tenant access denied")
