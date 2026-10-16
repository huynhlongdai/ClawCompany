"""R1 — quản lý vai trò theo công ty + liên kết user ↔ nhiều ghế. Spec: docs/r-rental-and-multi-company.md §R1."""
from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core import company_scope
from app.core.authz import ROLE_ORDER, Principal
from app.models import Company, Member, User, UserOrganizationAccess
from app.models.company_access import COMPANY_ROLES, CompanyAccess, UserSeat


def _co(db: Session, org: int, company_id: int) -> Company:
    co = db.get(Company, company_id)
    if co is None or co.organization_id != org:
        raise HTTPException(404, "Không thấy công ty này trong tổ chức.")
    return co


def can_manage(principal: Principal, company_id: int) -> bool:
    """owner/admin của org, hoặc owner CỦA công ty (vai trò công ty)."""
    if principal.company_roles is None:
        return ROLE_ORDER.get(principal.role, -1) >= ROLE_ORDER["admin"]
    return principal.company_roles.get(company_id) == "owner"


def public(db: Session, a: CompanyAccess) -> dict:
    u = db.get(User, a.user_id)
    seat = db.query(UserSeat).filter(UserSeat.user_id == a.user_id, UserSeat.company_id == a.company_id).first()
    m = db.get(Member, seat.member_id) if seat else None
    return {"id": a.id, "user_id": a.user_id, "email": u.email if u else "", "display_name": (u.display_name if u else "") or "",
            "company_id": a.company_id, "role": a.role, "status": a.status,
            "seat": {"member_id": m.id, "name": m.name} if m else None}


def list_access(db: Session, org: int, company_id: int) -> dict:
    _co(db, org, company_id)
    company_scope.check(company_id, min_role="member")
    rows = db.query(CompanyAccess).filter(CompanyAccess.company_id == company_id).order_by(CompanyAccess.id).all()
    return {"company_id": company_id, "roles": list(COMPANY_ROLES), "items": [public(db, a) for a in rows]}


def set_access(db: Session, org: int, principal: Principal, *, company_id: int, role: str,
               user_id: int | None = None, email: str | None = None) -> dict:
    _co(db, org, company_id)
    if role not in COMPANY_ROLES:
        raise HTTPException(422, f"Vai trò công ty phải là một trong: {', '.join(COMPANY_ROLES)}")
    if not can_manage(principal, company_id):
        raise HTTPException(403, "Chỉ owner/admin của tổ chức hoặc chủ công ty này được đổi vai trò công ty.")
    u = db.get(User, user_id) if user_id else (db.query(User).filter(User.email == (email or "").strip().lower()).first()
                                                if email else None)
    if u is None:
        raise HTTPException(404, "Không thấy người dùng này.")
    acc = db.query(UserOrganizationAccess).filter(UserOrganizationAccess.user_id == u.id,
                                                  UserOrganizationAccess.organization_id == org,
                                                  UserOrganizationAccess.status == "active").first()
    if acc is None:
        raise HTTPException(422, "Người này chưa thuộc tổ chức — mời vào tổ chức trước (Đội ngũ → Mời).")
    row = db.query(CompanyAccess).filter(CompanyAccess.user_id == u.id, CompanyAccess.company_id == company_id).first()
    if row is None:
        row = CompanyAccess(user_id=u.id, organization_id=org, company_id=company_id)
    row.role, row.status = role, "active"
    db.add(row); db.commit(); db.refresh(row)
    return public(db, row)


def remove_access(db: Session, org: int, principal: Principal, access_id: int) -> dict:
    row = db.get(CompanyAccess, access_id)
    if row is None or row.organization_id != org:
        raise HTTPException(404, "Không thấy vai trò này.")
    if not can_manage(principal, row.company_id):
        raise HTTPException(403, "Chỉ owner/admin của tổ chức hoặc chủ công ty này được gỡ vai trò công ty.")
    row.status = "revoked"; db.add(row); db.commit()
    return {"ok": True, "id": row.id}


def link_seat(db: Session, org: int, principal: Principal, *, user_id: int, member_id: int) -> dict:
    """Gắn một ghế (người) cho user. Mỗi công ty tối đa một ghế / user; ghế chỉ thuộc một user."""
    m = db.get(Member, member_id)
    u = db.get(User, user_id)
    if m is None or m.organization_id != org or u is None:
        raise HTTPException(404, "Không thấy người dùng hoặc ghế này.")
    if m.member_type != "human":
        raise HTTPException(422, "Chỉ ghế người mới gắn được với tài khoản đăng nhập.")
    if not can_manage(principal, m.company_id):
        raise HTTPException(403, "Chỉ owner/admin của tổ chức hoặc chủ công ty của ghế được gắn ghế.")
    other = db.query(UserSeat).filter(UserSeat.member_id == m.id).first()
    if other is not None and other.user_id != u.id:
        raise HTTPException(409, "Ghế này đã gắn với tài khoản khác.")
    same = db.query(UserSeat).filter(UserSeat.user_id == u.id, UserSeat.company_id == m.company_id).first()
    if same is not None and same.member_id != m.id:
        raise HTTPException(409, "Người này đã có một ghế ở công ty này — mỗi công ty một ghế.")
    row = other or same or UserSeat(user_id=u.id, member_id=m.id, organization_id=org, company_id=m.company_id)
    db.add(row)
    if u.member_id is None:
        u.member_id = m.id; db.add(u)
    db.commit(); db.refresh(row)
    return {"id": row.id, "user_id": u.id, "member_id": m.id, "company_id": m.company_id}


def unlink_seat(db: Session, org: int, principal: Principal, seat_id: int) -> dict:
    row = db.get(UserSeat, seat_id)
    if row is None or row.organization_id != org:
        raise HTTPException(404, "Không thấy liên kết ghế này.")
    if not can_manage(principal, row.company_id):
        raise HTTPException(403, "Không đủ quyền gỡ ghế này.")
    u = db.get(User, row.user_id)
    if u is not None and u.member_id == row.member_id:
        nxt = db.query(UserSeat).filter(UserSeat.user_id == u.id, UserSeat.id != row.id).first()
        u.member_id = nxt.member_id if nxt else None; db.add(u)
    db.delete(row); db.commit()
    return {"ok": True}


def my_companies(db: Session, org: int, principal: Principal) -> dict:
    q = db.query(Company).filter(Company.organization_id == org, Company.status != "archived").order_by(Company.id)
    ids = company_scope.allowed_company_ids(principal)
    rows = [c for c in q.all() if ids is None or c.id in ids]
    seats = principal.seats or {}
    by_co = {cid: mid for mid, cid in seats.items()}
    return {"restricted": ids is not None, "org_role": principal.role,
            "items": [{"id": c.id, "name": c.name, "status": c.status,
                       "role": (principal.company_roles or {}).get(c.id) if ids is not None else principal.role,
                       "seat_member_id": by_co.get(c.id)} for c in rows]}
