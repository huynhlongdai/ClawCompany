"""M2 — Đội ngũ: quyền theo vai, lời mời, sơ đồ tổ chức theo quản lý, trưởng phòng.

Luật quyền (một chỗ, dùng chung cho /api/team và /api/auth/organization-access):
  * owner cấp được mọi vai; admin cấp tới admin (không cấp owner);
    manager chỉ mời member/guest; member/guest không cấp gì.
  * không tự đổi/thu quyền của mình; không đụng người cao quyền hơn mình;
    vai owner chỉ owner mới đổi; không hạ/thu owner cuối cùng của tổ chức.
"""
from __future__ import annotations

import hashlib
import re
import secrets
import unicodedata
from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.authz import ROLE_ORDER, Principal
from app.core.security import create_access_token, hash_password, verify_password
from app.models import (Agent, Company, Department, Invitation, Member, Organization, User,
                        UserOrganizationAccess)
from app.services import row_revision as rev
from app.services.audit import log_event

INVITE_DAYS = 7
ROLES = ("guest", "member", "manager", "admin", "owner")
ROLE_VI = {"guest": "Khách", "member": "Thành viên", "manager": "Quản lý", "admin": "Quản trị", "owner": "Chủ sở hữu"}


# --------------------------------------------------------------------- tiện ích

def slug_ascii(value: str, limit: int = 40) -> str:
    """'Giám đốc' → 'giam-doc' (id agent trên gateway phải ASCII, không dấu)."""
    v = (value or "").replace("đ", "d").replace("Đ", "D")
    v = unicodedata.normalize("NFKD", v).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", v.lower()).strip("-")[:limit] or "agent"


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _bump(entity) -> None:
    if hasattr(entity, "row_revision"):
        entity.row_revision = rev.next_counter(entity)


def _norm_email(email: str) -> str:
    email = (email or "").strip().lower()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise HTTPException(422, "Email không hợp lệ")
    return email


# --------------------------------------------------------------------- quyền

def assignable_roles(actor_role: str) -> list[str]:
    if actor_role == "owner":
        return list(ROLES)
    if actor_role == "admin":
        return ["guest", "member", "manager", "admin"]
    if actor_role == "manager":
        return ["guest", "member"]
    return []


def capabilities(role: str) -> dict:
    r = ROLE_ORDER.get(role, -1)
    return {
        "view_team": r >= ROLE_ORDER["guest"],
        "invite": r >= ROLE_ORDER["manager"],
        "edit_org_chart": r >= ROLE_ORDER["manager"],
        "manage_roles": r >= ROLE_ORDER["admin"],
        "create_company": r >= ROLE_ORDER["admin"],
        "import_csv": r >= ROLE_ORDER["admin"],
    }


def _active_owner_count(db: Session, org_id: int, exclude_user_id: int | None = None) -> int:
    q = db.query(UserOrganizationAccess).filter(
        UserOrganizationAccess.organization_id == org_id, UserOrganizationAccess.role == "owner",
        UserOrganizationAccess.status == "active")
    if exclude_user_id is not None:
        q = q.filter(UserOrganizationAccess.user_id != exclude_user_id)
    return q.count()


def check_role_change(db: Session, principal: Principal, *, target_user_id: int,
                      current: UserOrganizationAccess | None, new_role: str | None) -> None:
    """new_role=None nghĩa là thu hồi quyền. Ném HTTPException nếu không được phép."""
    actor = principal.role
    if principal.user_id is not None and principal.user_id == target_user_id:
        raise HTTPException(403, "Không tự đổi hoặc thu quyền của chính mình")
    if new_role is not None and new_role not in assignable_roles(actor):
        raise HTTPException(403, f"Vai {ROLE_VI.get(actor, actor)} không cấp được vai {ROLE_VI.get(new_role, new_role)}")
    if current is not None and (current.status or "active") == "active":
        if current.role == "owner" and actor != "owner":
            raise HTTPException(403, "Chỉ Chủ sở hữu mới đổi được quyền của Chủ sở hữu khác")
        if ROLE_ORDER.get(current.role, 0) > ROLE_ORDER.get(actor, -1):
            raise HTTPException(403, "Không đổi được quyền của người cao quyền hơn mình")
        if current.role == "owner" and new_role != "owner" and \
                _active_owner_count(db, current.organization_id, exclude_user_id=target_user_id) == 0:
            raise HTTPException(409, "Tổ chức phải còn ít nhất một Chủ sở hữu")


def _access(db: Session, user_id: int, org_id: int) -> UserOrganizationAccess | None:
    return db.query(UserOrganizationAccess).filter(
        UserOrganizationAccess.user_id == user_id, UserOrganizationAccess.organization_id == org_id).first()


def set_access_role(db: Session, principal: Principal, org_id: int, user_id: int, role: str) -> dict:
    if principal.user_id is not None and principal.user_id == user_id:
        raise HTTPException(403, "Không tự đổi hoặc thu quyền của chính mình")
    if role not in ROLES:
        raise HTTPException(422, "Vai không hợp lệ")
    item = _access(db, user_id, org_id)
    if item is None or item.status != "active":
        raise HTTPException(404, "Người này chưa có quyền trong tổ chức")
    check_role_change(db, principal, target_user_id=user_id, current=item, new_role=role)
    old = item.role
    item.role = role
    db.add(item); db.commit()
    log_event(db, org_id, "team.role_changed", "users", user_id, actor_name=f"user:{principal.user_id}",
              payload={"from": old, "to": role})
    return {"user_id": user_id, "role": role, "previous": old}


def revoke_access(db: Session, principal: Principal, org_id: int, user_id: int) -> dict:
    if principal.user_id is not None and principal.user_id == user_id:
        raise HTTPException(403, "Không tự đổi hoặc thu quyền của chính mình")
    item = _access(db, user_id, org_id)
    if item is None or item.status != "active":
        raise HTTPException(404, "Người này chưa có quyền trong tổ chức")
    if ROLE_ORDER.get(principal.role, -1) < ROLE_ORDER["admin"]:
        raise HTTPException(403, "admin role required")
    check_role_change(db, principal, target_user_id=user_id, current=item, new_role=None)
    item.status = "revoked"; item.is_default = False
    db.add(item); db.commit()
    log_event(db, org_id, "team.access_revoked", "users", user_id, actor_name=f"user:{principal.user_id}",
              payload={"role": item.role})
    return {"user_id": user_id, "status": "revoked"}


# --------------------------------------------------------------------- lời mời

def _check_placement(db: Session, org_id: int, company_id: int | None, department_id: int | None,
                     manager_member_id: int | None) -> tuple[int | None, int | None, int | None]:
    company = db.get(Company, company_id) if company_id else None
    if company_id and (not company or company.organization_id != org_id):
        raise HTTPException(404, "Không thấy công ty trong tổ chức")
    if department_id:
        dept = db.get(Department, department_id)
        if not dept or (company and dept.company_id != company.id):
            raise HTTPException(422, "Phòng ban không thuộc công ty đã chọn")
        dc = db.get(Company, dept.company_id)
        if not dc or dc.organization_id != org_id:
            raise HTTPException(404, "Không thấy phòng ban trong tổ chức")
        company_id = dc.id
    if manager_member_id:
        m = db.get(Member, manager_member_id)
        if not m or m.organization_id != org_id:
            raise HTTPException(422, "Người quản lý không thuộc tổ chức")
        if company_id and m.company_id not in (None, company_id):
            raise HTTPException(422, "Người quản lý phải cùng công ty")
    return company_id, department_id, manager_member_id


def create_invitation(db: Session, principal: Principal, org_id: int, *, email: str, role: str = "member",
                      display_name: str = "", job_title: str = "", company_id: int | None = None,
                      department_id: int | None = None, manager_member_id: int | None = None,
                      member_id: int | None = None) -> tuple[Invitation, str]:
    email = _norm_email(email)
    if role not in assignable_roles(principal.role):
        raise HTTPException(403, f"Vai {ROLE_VI.get(principal.role, principal.role)} không mời được vai {ROLE_VI.get(role, role)}")
    company_id, department_id, manager_member_id = _check_placement(db, org_id, company_id, department_id, manager_member_id)
    if member_id:
        seat = db.get(Member, member_id)
        if not seat or seat.organization_id != org_id or seat.member_type != "human":
            raise HTTPException(422, "Ghế được gắn phải là thành viên người trong tổ chức")
        if db.query(User).filter(User.member_id == member_id).first():
            raise HTTPException(409, "Ghế này đã gắn với một tài khoản")
    user = db.query(User).filter(User.email == email).first()
    if user:
        acc = _access(db, user.id, org_id)
        if acc and acc.status == "active":
            raise HTTPException(409, "Người này đã ở trong tổ chức — đổi vai ở mục Người & quyền")
    # mời lại cùng email thì thu hồi link cũ
    for old in db.query(Invitation).filter(Invitation.organization_id == org_id, Invitation.email == email,
                                           Invitation.status == "pending").all():
        old.status = "revoked"; db.add(old)
    raw = "inv_" + secrets.token_urlsafe(24)
    inv = Invitation(organization_id=org_id, company_id=company_id, department_id=department_id,
                     manager_member_id=manager_member_id, member_id=member_id, email=email,
                     display_name=(display_name or "").strip(), role=role, job_title=(job_title or "").strip(),
                     token_hash=_hash(raw), status="pending", invited_by_user_id=principal.user_id,
                     expires_at=datetime.utcnow() + timedelta(days=INVITE_DAYS))
    db.add(inv); db.commit(); db.refresh(inv)
    log_event(db, org_id, "team.invited", "invitations", inv.id, actor_name=f"user:{principal.user_id}",
              payload={"email": email, "role": role})
    return inv, raw


def invitation_state(inv: Invitation, now: datetime | None = None) -> str:
    if inv.status == "pending" and inv.expires_at < (now or datetime.utcnow()):
        return "expired"
    return inv.status


def find_invitation(db: Session, token: str) -> Invitation:
    inv = db.query(Invitation).filter(Invitation.token_hash == _hash(token or "")).first()
    if not inv:
        raise HTTPException(404, "Link mời không đúng")
    state = invitation_state(inv)
    if state != "pending":
        msg = {"expired": "Link mời đã hết hạn — nhờ người mời gửi link mới",
               "revoked": "Link mời đã bị thu hồi", "accepted": "Link mời này đã được dùng"}[state]
        raise HTTPException(410, msg)
    return inv


def describe_invitation(db: Session, inv: Invitation) -> dict:
    org = db.get(Organization, inv.organization_id)
    company = db.get(Company, inv.company_id) if inv.company_id else None
    dept = db.get(Department, inv.department_id) if inv.department_id else None
    manager = db.get(Member, inv.manager_member_id) if inv.manager_member_id else None
    inviter = db.get(User, inv.invited_by_user_id) if inv.invited_by_user_id else None
    return {
        "id": inv.id, "email": inv.email, "display_name": inv.display_name, "role": inv.role,
        "role_label": ROLE_VI.get(inv.role, inv.role), "job_title": inv.job_title,
        "organization": org.name if org else "", "company": company.name if company else None,
        "department": dept.name if dept else None, "manager": manager.name if manager else None,
        "invited_by": (inviter.display_name or inviter.email) if inviter else None,
        "expires_at": inv.expires_at.isoformat(), "status": invitation_state(inv),
        "account_exists": db.query(User).filter(User.email == inv.email).first() is not None,
    }


def accept_invitation(db: Session, token: str, *, password: str, display_name: str = "") -> dict:
    inv = find_invitation(db, token)
    user = db.query(User).filter(User.email == inv.email).first()
    if user:
        if not verify_password(password, user.password_hash):
            raise HTTPException(401, "Email này đã có tài khoản — nhập đúng mật khẩu của tài khoản đó")
        if not user.is_active:
            raise HTTPException(403, "Tài khoản đã bị khoá")
    else:
        if len(password or "") < 8:
            raise HTTPException(422, "Mật khẩu cần ít nhất 8 ký tự")
        user = User(email=inv.email, password_hash=hash_password(password),
                    display_name=(display_name or inv.display_name or inv.email.split("@")[0]).strip())
        db.add(user); db.flush()
    # ghế người trên sơ đồ
    member = db.get(Member, inv.member_id) if inv.member_id else None
    if member is None and user.member_id:
        mine = db.get(Member, user.member_id)
        if mine and mine.organization_id == inv.organization_id:
            member = mine
    if member is None:
        # chưa chọn người quản lý → báo cáo trưởng phòng (nếu phòng có)
        manager_id = inv.manager_member_id
        if manager_id is None and inv.department_id:
            dept = db.get(Department, inv.department_id)
            manager_id = dept.head_member_id if dept else None
        member = Member(organization_id=inv.organization_id, company_id=inv.company_id,
                        department_id=inv.department_id, name=user.display_name or inv.email,
                        member_type="human", role=inv.job_title or ROLE_VI.get(inv.role, inv.role),
                        manager_id=manager_id, status="active")
        db.add(member); db.flush()
    if user.member_id is None:
        taken = db.query(User).filter(User.member_id == member.id, User.id != user.id).first()
        if not taken:
            user.member_id = member.id
    acc = _access(db, user.id, inv.organization_id)
    if acc is None:
        acc = UserOrganizationAccess(user_id=user.id, organization_id=inv.organization_id, role=inv.role,
                                     status="active")
    elif acc.status != "active" or ROLE_ORDER.get(inv.role, 0) > ROLE_ORDER.get(acc.role, 0):
        acc.role = inv.role
        acc.status = "active"
    has_default = db.query(UserOrganizationAccess).filter(
        UserOrganizationAccess.user_id == user.id, UserOrganizationAccess.is_default == True,  # noqa: E712
        UserOrganizationAccess.status == "active").first()
    if not has_default:
        acc.is_default = True
    inv.status = "accepted"; inv.accepted_user_id = user.id; inv.accepted_at = datetime.utcnow()
    db.add_all([user, member, acc, inv]); db.commit()
    log_event(db, inv.organization_id, "team.invite_accepted", "users", user.id, actor_name=inv.email,
              payload={"invitation_id": inv.id, "member_id": member.id, "role": acc.role})
    return {"access_token": create_access_token(user.id, inv.organization_id, acc.role), "token_type": "bearer",
            "organization_id": inv.organization_id, "role": acc.role, "user_id": user.id, "member_id": member.id}


def revoke_invitation(db: Session, principal: Principal, org_id: int, invitation_id: int) -> dict:
    inv = db.get(Invitation, invitation_id)
    if not inv or inv.organization_id != org_id:
        raise HTTPException(404, "Không thấy lời mời")
    if inv.status != "pending":
        raise HTTPException(409, "Lời mời không còn chờ")
    if inv.role not in assignable_roles(principal.role):
        raise HTTPException(403, "Không thu hồi được lời mời có vai cao hơn quyền mình")
    inv.status = "revoked"; db.add(inv); db.commit()
    return {"id": inv.id, "status": "revoked"}


# --------------------------------------------------------------------- người & quyền

def people(db: Session, principal: Principal, org_id: int) -> dict:
    rows = db.query(UserOrganizationAccess, User).join(User, User.id == UserOrganizationAccess.user_id).filter(
        UserOrganizationAccess.organization_id == org_id).all()
    members = {m.id: m for m in db.query(Member).filter(Member.organization_id == org_id).all()}
    linked = {u.member_id for _, u in rows if u.member_id}
    can = assignable_roles(principal.role)
    out_users = []
    for acc, user in sorted(rows, key=lambda r: (-ROLE_ORDER.get(r[0].role, 0), r[1].email)):
        m = members.get(user.member_id) if user.member_id else None
        editable = acc.status == "active" and user.id != principal.user_id and acc.role in can and \
            not (acc.role == "owner" and principal.role != "owner")
        out_users.append({
            "user_id": user.id, "email": user.email, "display_name": user.display_name, "role": acc.role,
            "role_label": ROLE_VI.get(acc.role, acc.role), "status": acc.status, "is_self": user.id == principal.user_id,
            "member_id": m.id if m else None, "member_name": m.name if m else None,
            "job_title": m.role if m else None, "department_id": m.department_id if m else None,
            "editable": editable and ROLE_ORDER.get(principal.role, -1) >= ROLE_ORDER["admin"],
        })
    now = datetime.utcnow()
    invites = [{
        "id": i.id, "email": i.email, "display_name": i.display_name, "role": i.role,
        "role_label": ROLE_VI.get(i.role, i.role), "job_title": i.job_title, "status": invitation_state(i, now),
        "department_id": i.department_id, "company_id": i.company_id, "expires_at": i.expires_at.isoformat(),
        "created_at": i.created_at.isoformat() if i.created_at else None,
    } for i in db.query(Invitation).filter(Invitation.organization_id == org_id).order_by(Invitation.id.desc()).limit(100)]
    seats = [{"member_id": m.id, "name": m.name, "role": m.role, "company_id": m.company_id,
              "department_id": m.department_id}
             for m in members.values() if m.member_type == "human" and m.id not in linked and m.status == "active"]
    return {"users": out_users, "invitations": invites, "unlinked_seats": seats,
            "assignable_roles": can, "role_labels": ROLE_VI}


# --------------------------------------------------------------------- sơ đồ tổ chức

def would_cycle(db: Session, member_id: int, manager_id: int | None) -> bool:
    seen = set()
    cur = manager_id
    while cur is not None:
        if cur == member_id:
            return True
        if cur in seen or len(seen) > 2000:
            return True
        seen.add(cur)
        m = db.get(Member, cur)
        cur = m.manager_id if m else None
    return False


def org_chart(db: Session, org_id: int, company_id: int | None = None) -> dict:
    companies = db.query(Company).filter(Company.organization_id == org_id, Company.status != "archived").order_by(Company.id).all()
    if not companies:
        return {"companies": [], "company": None, "departments": [], "tree": [], "stats": {}}
    company = next((c for c in companies if c.id == company_id), None) if company_id else companies[0]
    if company is None:
        raise HTTPException(404, "Không thấy công ty")
    depts = db.query(Department).filter(Department.company_id == company.id, Department.status != "archived").order_by(Department.id).all()
    dept_by = {d.id: d for d in depts}
    members = db.query(Member).filter(Member.company_id == company.id, Member.status != "archived").order_by(Member.id).all()
    ids = {m.id for m in members}
    users = {u.member_id: u for u in db.query(User).filter(User.member_id.in_(ids)).all()} if ids else {}
    access = {a.user_id: a for a in db.query(UserOrganizationAccess).filter(UserOrganizationAccess.organization_id == org_id).all()}
    agents = {a.member_id: a for a in db.query(Agent).filter(Agent.member_id.in_(ids)).all()} if ids else {}
    heads = {d.head_member_id: d.id for d in depts if d.head_member_id}
    nodes = {}
    for m in members:
        u = users.get(m.id); acc = access.get(u.id) if u else None; ag = agents.get(m.id)
        nodes[m.id] = {
            "id": m.id, "name": m.name, "type": m.member_type, "role": m.role, "status": m.status,
            "department_id": m.department_id, "department": dept_by[m.department_id].name if m.department_id in dept_by else None,
            "manager_id": m.manager_id, "is_head": m.id in heads, "head_of": heads.get(m.id),
            "email": u.email if u else None, "access_role": acc.role if acc and acc.status == "active" else None,
            "runtime_agent_id": ag.runtime_agent_id if ag else None, "lifecycle": ag.lifecycle if ag else None,
            "children": [],
        }
    roots = []
    for m in members:
        n = nodes[m.id]
        if m.manager_id in nodes and m.manager_id != m.id:
            nodes[m.manager_id]["children"].append(n)
        else:
            roots.append(n)
    # vòng lặp (dữ liệu cũ) → node không tới được từ gốc nào; đưa lên gốc kèm cờ
    reach = set()
    stack = list(roots)
    while stack:
        n = stack.pop()
        if n["id"] in reach:
            continue
        reach.add(n["id"]); stack.extend(n["children"])
    for mid, n in nodes.items():
        if mid not in reach:
            n["cycle"] = True
            roots.append(n)
            for parent in nodes.values():
                parent["children"] = [c for c in parent["children"] if c["id"] != mid]
    dept_out = []
    for d in depts:
        head = nodes.get(d.head_member_id) if d.head_member_id else None
        dm = [n for n in nodes.values() if n["department_id"] == d.id]
        dept_out.append({"id": d.id, "name": d.name, "head_member_id": d.head_member_id,
                         "head_name": head["name"] if head else None, "guide": d.guide or "",
                         "members": len(dm), "agents": sum(1 for n in dm if n["type"] == "agent"),
                         "humans": sum(1 for n in dm if n["type"] == "human")})
    return {
        "companies": [{"id": c.id, "name": c.name, "industry": c.industry} for c in companies],
        "company": {"id": company.id, "name": company.name, "industry": company.industry},
        "departments": dept_out, "tree": roots,
        "stats": {"members": len(members), "agents": sum(1 for m in members if m.member_type == "agent"),
                  "humans": sum(1 for m in members if m.member_type == "human"), "departments": len(depts),
                  "without_head": sum(1 for d in depts if not d.head_member_id)},
    }


def set_department_head(db: Session, org_id: int, department: Department, member_id: int | None,
                        *, actor: str = "system") -> dict:
    company = db.get(Company, department.company_id)
    if not company or company.organization_id != org_id:
        raise HTTPException(404, "Không thấy phòng ban")
    old = department.head_member_id
    head = None
    if member_id is not None:
        head = db.get(Member, member_id)
        if not head or head.organization_id != org_id or head.company_id != company.id:
            raise HTTPException(422, "Trưởng phòng phải là thành viên của cùng công ty")
        if head.status not in ("active", "pending_runtime"):
            raise HTTPException(422, "Trưởng phòng phải đang hoạt động")
        if head.department_id != department.id:
            head.department_id = department.id; _bump(head); db.add(head)
    department.head_member_id = member_id
    _bump(department); db.add(department)
    moved = 0
    if head is not None:
        for m in db.query(Member).filter(Member.department_id == department.id, Member.id != head.id).all():
            if m.manager_id is None or (old is not None and m.manager_id == old):
                if not would_cycle(db, m.id, head.id):
                    m.manager_id = head.id; _bump(m); db.add(m); moved += 1
    db.commit()
    log_event(db, org_id, "team.department_head", "departments", department.id, actor_name=actor,
              payload={"from": old, "to": member_id, "reassigned": moved})
    return {"department_id": department.id, "head_member_id": member_id, "reassigned": moved}


def set_manager(db: Session, org_id: int, member: Member, manager_id: int | None, *, actor: str = "system") -> dict:
    if member.organization_id != org_id:
        raise HTTPException(404, "Không thấy thành viên")
    if manager_id is not None:
        if manager_id == member.id:
            raise HTTPException(422, "Không thể tự quản lý chính mình")
        mgr = db.get(Member, manager_id)
        if not mgr or mgr.organization_id != org_id or mgr.company_id != member.company_id:
            raise HTTPException(422, "Người quản lý phải cùng công ty")
        if would_cycle(db, member.id, manager_id):
            raise HTTPException(422, f"Tạo vòng quản lý: {mgr.name} đang (gián tiếp) báo cáo cho {member.name}")
    old = member.manager_id
    member.manager_id = manager_id; _bump(member); db.add(member); db.commit()
    log_event(db, org_id, "team.manager_set", "members", member.id, actor_name=actor,
              payload={"from": old, "to": manager_id})
    return {"member_id": member.id, "manager_id": manager_id}
