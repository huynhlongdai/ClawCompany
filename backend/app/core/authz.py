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
    # R1: None = phạm vi cả tổ chức theo ``role``; dict = CHỈ các công ty này với vai trò công ty
    company_roles: dict | None = None
    # R1: mọi ghế của user trong org: member_id → company_id (một người nhiều ghế, mỗi công ty một ghế)
    seats: dict | None = None

    @property
    def member_ids(self) -> list[int]:
        ids = list((self.seats or {}).keys())
        if self.member_id and self.member_id not in ids:
            ids.insert(0, self.member_id)
        return ids

    def seat_in(self, company_id: int | None) -> int | None:
        for mid, cid in (self.seats or {}).items():
            if cid == company_id:
                return mid
        return self.member_id


# bcrypt cố ý chậm (~0,1–0,3 s). Mỗi lượt gọi tool MCP của agent đều mang key,
# nên một agent gọi 10 tool trả 1–3 giây chỉ để xác thực. Nhớ trong tiến trình
# rằng "băm SHA-256 của key này đã khớp key #id" trong 5 phút; vẫn đọc hàng
# APIKey mỗi lần nên key bị thu hồi (is_active=False) mất hiệu lực ngay.
_KEY_CACHE: dict[str, tuple[int, float]] = {}
_KEY_CACHE_TTL = 300.0


def _key_digest(raw: str) -> str:
    import hashlib
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _verified_key_id(raw: str) -> int | None:
    import time
    hit = _KEY_CACHE.get(_key_digest(raw))
    if hit and hit[1] > time.monotonic():
        return hit[0]
    return None


def _remember_key(raw: str, key_id: int) -> None:
    import time
    if len(_KEY_CACHE) > 2048:
        _KEY_CACHE.clear()
    _KEY_CACHE[_key_digest(raw)] = (key_id, time.monotonic() + _KEY_CACHE_TTL)


def get_principal(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    db: Session = Depends(get_db),
) -> Principal:
    if x_api_key:
        prefix = x_api_key[:12]
        candidates = db.query(APIKey).filter(APIKey.key_prefix == prefix, APIKey.is_active == True).all()  # noqa: E712
        cached = _verified_key_id(x_api_key)
        for item in candidates:
            if item.id == cached or pwd_context.verify(x_api_key, item.key_hash):
                _remember_key(x_api_key, item.id)
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
    org_id = claims.get("org_id")
    role = claims.get("role", "member")
    # M2: quyền là dữ liệu sống. Có dòng UserOrganizationAccess thì role lấy từ
    # DB mỗi request — đổi/thu quyền có hiệu lực ngay, không đợi token hết hạn.
    # Không có dòng (token phát hành trực tiếp, superuser) thì giữ role trong JWT.
    if org_id is not None and not user.is_superuser:
        from app.models import UserOrganizationAccess
        access = db.query(UserOrganizationAccess).filter(
            UserOrganizationAccess.user_id == user.id,
            UserOrganizationAccess.organization_id == int(org_id),
        ).first()
        if access is not None:
            if (access.status or "active") != "active":
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                                    detail="Quyền truy cập tổ chức này đã bị thu hồi")
            role = access.role
    p = Principal(user.id, org_id, role, "jwt", [], user.member_id)
    if org_id is not None:
        _load_company_scope(db, p, user)
    from app.core import company_scope
    company_scope.remember(p)
    return p


def _load_company_scope(db: Session, p: Principal, user: User) -> None:
    from app.models import Member
    from app.models.company_access import CompanyAccess, UserSeat
    org = int(p.organization_id)
    seats = {s.member_id: s.company_id for s in db.query(UserSeat).filter(
        UserSeat.user_id == user.id, UserSeat.organization_id == org).all()}
    if user.member_id and user.member_id not in seats:
        m = db.get(Member, user.member_id)
        if m is not None and m.organization_id == org:
            seats[m.id] = m.company_id
    p.seats = seats
    if p.member_id is None or p.member_id not in seats:
        p.member_id = next(iter(seats), None)
    if user.is_superuser or ROLE_ORDER.get(p.role, 0) >= ROLE_ORDER["admin"]:
        return
    rows = db.query(CompanyAccess).filter(CompanyAccess.user_id == user.id, CompanyAccess.organization_id == org,
                                          CompanyAccess.status == "active").all()
    if rows:
        p.company_roles = {r.company_id: r.role for r in rows}



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


def require_company_role(minimum_role: str):
    """R1: như require_role cho route thuộc phạm vi công ty. Người bị giới hạn công ty qua cổng nếu vai trò công ty
    CAO NHẤT đủ; service kiểm lại đúng công ty của thao tác qua company_scope.check (dùng ``minimum_role`` này)."""
    def dep(principal: Principal = Depends(get_principal)):
        from app.core import company_scope
        if principal.auth_type == "api_key":
            raise HTTPException(status_code=403, detail="Human role required")
        need = ROLE_ORDER.get(minimum_role, 999)
        if principal.company_roles is not None:
            best = max((company_scope.COMPANY_LEVEL.get(r, 0) for r in principal.company_roles.values()), default=-1)
            if best < need:
                raise HTTPException(status_code=403, detail=f"{minimum_role} role required")
        elif ROLE_ORDER.get(principal.role, -1) < need:
            raise HTTPException(status_code=403, detail=f"{minimum_role} role required")
        company_scope.remember(principal, minimum_role)
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
