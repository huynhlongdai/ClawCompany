"""M2 — /api/team: Đội ngũ (sơ đồ tổ chức, người & quyền, lời mời, trưởng phòng,
mẫu công ty, nhập CSV). Luật quyền ở app/services/team.py."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.authz import Principal, require_role
from app.core.tenancy import active_org, ensure_department, ensure_member
from app.db.session import get_db
from app.models import Organization, User
from app.services import team as svc
from app.services import team_templates as tpl

router = APIRouter(prefix="/team", tags=["team"])
ROLE_PATTERN = "^(guest|member|manager|admin|owner)$"


class InviteIn(BaseModel):
    email: str = Field(min_length=3, max_length=240)
    role: str = Field(default="member", pattern=ROLE_PATTERN)
    display_name: str = Field(default="", max_length=160)
    job_title: str = Field(default="", max_length=160)
    company_id: int | None = None
    department_id: int | None = None
    manager_member_id: int | None = None
    member_id: int | None = None


class AcceptIn(BaseModel):
    token: str = Field(min_length=8, max_length=200)
    password: str = Field(min_length=1, max_length=200)
    display_name: str = Field(default="", max_length=160)


class RoleIn(BaseModel):
    role: str = Field(pattern=ROLE_PATTERN)


class HeadIn(BaseModel):
    member_id: int | None = None


class ManagerIn(BaseModel):
    manager_id: int | None = None


class TemplateIn(BaseModel):
    template_key: str = Field(pattern="^(shop|agency|ketoan)$")
    company_name: str = Field(default="", max_length=160)
    model: str = Field(default="", max_length=120)


class CsvIn(BaseModel):
    company_id: int
    csv_text: str = Field(max_length=500_000)
    dry_run: bool = True


def _actor(p: Principal) -> str:
    return f"user:{p.user_id}"


@router.get("/me")
def me(principal: Principal = Depends(require_role("guest")), db: Session = Depends(get_db)):
    org_id = active_org(principal)
    user = db.get(User, principal.user_id) if principal.user_id else None
    org = db.get(Organization, org_id)
    return {"user_id": principal.user_id, "email": user.email if user else None,
            "display_name": user.display_name if user else None, "member_id": principal.member_id,
            "organization_id": org_id, "organization": org.name if org else None,
            "role": principal.role, "role_label": svc.ROLE_VI.get(principal.role, principal.role),
            "capabilities": svc.capabilities(principal.role), "assignable_roles": svc.assignable_roles(principal.role)}


@router.get("/people")
def people(principal: Principal = Depends(require_role("member")), db: Session = Depends(get_db)):
    return svc.people(db, principal, active_org(principal))


@router.post("/invitations")
def invite(payload: InviteIn, principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    inv, raw = svc.create_invitation(db, principal, active_org(principal), **payload.model_dump())
    return {**svc.describe_invitation(db, inv), "token": raw, "invite_path": f"/invite/{raw}"}


@router.delete("/invitations/{invitation_id}")
def revoke_invite(invitation_id: int, principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    return svc.revoke_invitation(db, principal, active_org(principal), invitation_id)


@router.get("/invitations/lookup")
def lookup(token: str, db: Session = Depends(get_db)):
    return svc.describe_invitation(db, svc.find_invitation(db, token))


@router.post("/invitations/accept")
def accept(payload: AcceptIn, db: Session = Depends(get_db)):
    return svc.accept_invitation(db, payload.token, password=payload.password, display_name=payload.display_name)


@router.patch("/access/{user_id}")
def change_role(user_id: int, payload: RoleIn, principal: Principal = Depends(require_role("admin")), db: Session = Depends(get_db)):
    return svc.set_access_role(db, principal, active_org(principal), user_id, payload.role)


@router.delete("/access/{user_id}")
def remove_access(user_id: int, principal: Principal = Depends(require_role("admin")), db: Session = Depends(get_db)):
    return svc.revoke_access(db, principal, active_org(principal), user_id)


@router.get("/org-chart")
def org_chart(company_id: int | None = None, principal: Principal = Depends(require_role("guest")), db: Session = Depends(get_db)):
    return svc.org_chart(db, active_org(principal), company_id)


@router.put("/departments/{department_id}/head")
def department_head(department_id: int, payload: HeadIn, principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    dept = ensure_department(db, department_id, principal)
    return svc.set_department_head(db, active_org(principal), dept, payload.member_id, actor=_actor(principal))


@router.put("/members/{member_id}/manager")
def member_manager(member_id: int, payload: ManagerIn, principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    member = ensure_member(db, member_id, principal)
    return svc.set_manager(db, active_org(principal), member, payload.manager_id, actor=_actor(principal))


@router.get("/templates")
def templates(principal: Principal = Depends(require_role("guest"))):
    return tpl.list_templates()


@router.post("/companies/from-template")
async def from_template(payload: TemplateIn, principal: Principal = Depends(require_role("admin")), db: Session = Depends(get_db)):
    return await tpl.create_from_template(db, principal, active_org(principal), payload.template_key,
                                          payload.company_name, payload.model)


@router.post("/import-csv")
async def import_csv(payload: CsvIn, principal: Principal = Depends(require_role("admin")), db: Session = Depends(get_db)):
    return await tpl.import_csv(db, principal, active_org(principal), payload.company_id, payload.csv_text, payload.dry_run)
