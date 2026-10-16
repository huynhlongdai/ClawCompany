"""R1 — phạm vi công ty theo người gọi (vai trò theo công ty).

Mỗi request HTTP có một dict ngữ cảnh (đặt bởi ``CompanyScopeMiddleware`` ở main.py). ``get_principal`` ghi người
gọi vào đó; cổng ``require_company_role(min)`` ghi vai trò tối thiểu của route. Service gọi ``check(company_id)``
ở chỗ nó xác định công ty (``company_foundation._company``, các hàm lấy theo id) → 403 nếu người gọi bị giới hạn
công ty và không có vai trò đủ ở công ty đó. Ngoài request (beat, worker, test gọi service trực tiếp) không có
ngữ cảnh → không giới hạn (hệ thống)."""
from __future__ import annotations

from contextvars import ContextVar

from fastapi import HTTPException

REQ: ContextVar[dict | None] = ContextVar("cc_company_scope", default=None)

# vai trò công ty → mức của ROLE_ORDER (core/authz) khi so với yêu cầu của route
COMPANY_LEVEL = {"viewer": 1, "approver": 1, "manager": 2, "owner": 4}
COMPANY_ROLE_RANK = {"viewer": 0, "approver": 1, "manager": 2, "owner": 3}


class CompanyScopeMiddleware:
    """ASGI thuần: dict mới cho mỗi request; dependency sync (threadpool) sửa dict này, endpoint đọc được."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            return await self.app(scope, receive, send)
        token = REQ.set({})
        try:
            return await self.app(scope, receive, send)
        finally:
            REQ.reset(token)


def _ctx() -> dict | None:
    return REQ.get()


def remember(principal, min_role: str | None = None) -> None:
    c = _ctx()
    if c is None:
        return
    c["principal"] = principal
    if min_role is not None:
        c["min_role"] = min_role


def current_principal():
    c = _ctx()
    return c.get("principal") if c else None


def restricted(principal=None) -> bool:
    p = principal or current_principal()
    return bool(p is not None and getattr(p, "company_roles", None) is not None)


def allowed_company_ids(principal=None) -> list[int] | None:
    """None = không giới hạn (owner/admin org, người dùng cũ chưa có vai trò công ty, hệ thống)."""
    p = principal or current_principal()
    if not restricted(p):
        return None
    return sorted(p.company_roles)


def role_in(company_id: int | None, principal=None) -> str | None:
    p = principal or current_principal()
    if not restricted(p) or company_id is None:
        return None
    return p.company_roles.get(int(company_id))


def check(company_id: int | None, *, min_role: str | None = None, principal=None) -> None:
    """403 nếu người gọi bị giới hạn và không có vai trò đủ ở ``company_id``. company_id None (dữ liệu cấp org)
    → chỉ cho đọc khi route yêu cầu ≤ member."""
    from app.core.authz import ROLE_ORDER
    p = principal or current_principal()
    if not restricted(p):
        return
    c = _ctx() or {}
    need = min_role or c.get("min_role") or "member"
    if company_id is None:
        if ROLE_ORDER.get(need, 1) > 1:
            raise HTTPException(403, "Vai trò của anh chỉ ở cấp công ty; thao tác này thuộc cấp tổ chức.")
        return
    role = p.company_roles.get(int(company_id))
    if role is None:
        raise HTTPException(403, "Anh không có quyền ở công ty này.")
    if COMPANY_LEVEL.get(role, 0) < ROLE_ORDER.get(need, 999):
        raise HTTPException(403, f"Vai trò '{role}' ở công ty này chưa đủ cho thao tác (cần {need}).")


def default_company_id(principal=None) -> int | None:
    ids = allowed_company_ids(principal)
    return ids[0] if ids and len(ids) == 1 else None


def scope_filter(q, col, company_id: int | None = None, *, include_null: bool = True):
    """Lọc một query theo công ty: ``company_id`` cho trước → chỉ công ty đó (kiểm quyền); người bị giới hạn →
    chỉ các công ty của họ. ``include_null``: giữ dòng cấp tổ chức (company_id NULL)."""
    from sqlalchemy import or_
    if company_id:
        check(company_id)
        return q.filter(or_(col == company_id, col.is_(None)) if include_null else col == company_id)
    ids = allowed_company_ids()
    if ids is not None:
        return q.filter(or_(col.in_(ids or [-1]), col.is_(None)) if include_null else col.in_(ids or [-1]))
    return q
