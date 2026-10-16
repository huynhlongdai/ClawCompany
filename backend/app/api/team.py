"""M2 — /api/team: Đội ngũ (sơ đồ tổ chức, người & quyền, lời mời, trưởng phòng,
mẫu công ty, nhập CSV). Luật quyền ở app/services/team.py."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.authz import Principal, require_company_role, require_role
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
def org_chart(company_id: int | None = None, principal: Principal = Depends(require_company_role("guest")), db: Session = Depends(get_db)):
    return svc.org_chart(db, active_org(principal), company_id)


@router.put("/departments/{department_id}/head")
def department_head(department_id: int, payload: HeadIn, principal: Principal = Depends(require_company_role("manager")), db: Session = Depends(get_db)):
    dept = ensure_department(db, department_id, principal)
    return svc.set_department_head(db, active_org(principal), dept, payload.member_id, actor=_actor(principal))


@router.put("/members/{member_id}/manager")
def member_manager(member_id: int, payload: ManagerIn, principal: Principal = Depends(require_company_role("manager")), db: Session = Depends(get_db)):
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


# ===================================================================== M2b nền công ty
# Hồ sơ pháp nhân + hiến chương · chức danh · ma trận phân quyền. Spec: docs/m2b-company-foundation.md

from datetime import date as _date  # noqa: E402

from fastapi import BackgroundTasks  # noqa: E402

from app.services import authority as auth_svc  # noqa: E402
from app.services import company_foundation as cf  # noqa: E402


def _resync(background: BackgroundTasks, principal: Principal, org_id: int, agent_ids: list[int] | None) -> None:
    """Sinh lại AGENTS.md sau khi trả lời (phiên DB riêng). None = mọi seat (cùng đường với tri thức cốt lõi)."""
    async def run():
        from app.db.session import SessionLocal
        from app.runtime.factory import get_runtime
        from app.services import agent_hr, knowledge_hub
        db = SessionLocal()
        try:
            if agent_ids is None:
                await knowledge_hub.sync_core(db, principal, org_id, get_runtime())
            else:
                for aid in agent_ids:
                    try:
                        await agent_hr.update_hr(db, principal, org_id, get_runtime(), aid,
                                                 {"regenerate_files": ["AGENTS.md"]}, set())
                    except Exception as exc:  # noqa: BLE001
                        print(f"[m2b] resync agent {aid}: {exc}")
        except Exception as exc:  # noqa: BLE001
            print(f"[m2b] resync failed: {exc}")
        finally:
            db.close()
    background.add_task(run)


class ProfileIn(BaseModel):
    company_id: int | None = None
    legal_name: str | None = Field(default=None, max_length=240)
    entity_type: str | None = Field(default=None, max_length=32)
    tax_code: str | None = Field(default=None, max_length=20)
    legal_representative: str | None = Field(default=None, max_length=160)
    representative_title: str | None = Field(default=None, max_length=120)
    registered_address: str | None = Field(default=None, max_length=400)
    charter_capital_usd: float | None = None
    charter_capital_note: str | None = Field(default=None, max_length=200)
    business_lines: list[str] | None = None
    founded_on: _date | None = None
    mission: str | None = Field(default=None, max_length=2000)
    values: list[str] | None = None
    brand_voice: str | None = Field(default=None, max_length=2000)
    prohibitions: list[str] | None = None
    customer_promises: list[str] | None = None


@router.get("/company-profile")
def company_profile(company_id: int | None = None, principal: Principal = Depends(require_company_role("member")),
                    db: Session = Depends(get_db)):
    return cf.get_profile(db, active_org(principal), company_id)


@router.put("/company-profile")
def save_company_profile(payload: ProfileIn, background: BackgroundTasks,
                         principal: Principal = Depends(require_company_role("admin")), db: Session = Depends(get_db)):
    org_id = active_org(principal)
    data = payload.model_dump(exclude_unset=True)
    out, changed = cf.save_profile(db, org_id, data.pop("company_id", None), data, user_id=principal.user_id)
    if changed:
        _resync(background, principal, org_id, None)
    return {**out, "core_sync": changed}


class KpiIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    target: float | None = None
    unit: str = Field(default="", max_length=40)
    period: str = Field(default="month", pattern="^(day|week|month|quarter|year)$")


class PositionIn(BaseModel):
    company_id: int | None = None
    department_id: int | None = None
    title: str | None = Field(default=None, max_length=160)
    job_description: str | None = Field(default=None, max_length=4000)
    responsibilities: list[str] | None = None
    kpis: list[KpiIn] | None = None
    allowed_tools: list[str] | None = None
    allowed_skills: list[str] | None = None
    headcount: int | None = Field(default=None, ge=0, le=500)
    reports_to_position_id: int | None = None


class SeatIn(BaseModel):
    member_id: int


@router.get("/positions")
def positions(company_id: int | None = None, principal: Principal = Depends(require_company_role("member")),
              db: Session = Depends(get_db)):
    return cf.list_positions(db, active_org(principal), company_id)


@router.post("/positions")
def create_position(payload: PositionIn, principal: Principal = Depends(require_company_role("manager")),
                    db: Session = Depends(get_db)):
    data = payload.model_dump(exclude_unset=True)
    p = cf.create_position(db, active_org(principal), data)
    return cf.public_position(db, p)


@router.post("/positions/from-members")
def positions_from_members(company_id: int | None = None, principal: Principal = Depends(require_company_role("manager")),
                           db: Session = Depends(get_db)):
    org_id = active_org(principal)
    co = cf._company(db, org_id, company_id, write=True)
    return cf.positions_from_members(db, org_id, co.id)


@router.patch("/positions/{position_id}")
def update_position(position_id: int, payload: PositionIn, background: BackgroundTasks,
                    principal: Principal = Depends(require_company_role("manager")), db: Session = Depends(get_db)):
    org_id = active_org(principal)
    data = payload.model_dump(exclude_unset=True)
    data.pop("company_id", None)
    p, affects = cf.update_position(db, org_id, position_id, data, set(data))
    agents = cf.seated_agent_ids(db, p.id) if affects else []
    if agents:
        _resync(background, principal, org_id, agents)
    return {**cf.public_position(db, p), "resync_agents": agents}


@router.delete("/positions/{position_id}")
def archive_position(position_id: int, principal: Principal = Depends(require_company_role("manager")),
                     db: Session = Depends(get_db)):
    return cf.archive_position(db, active_org(principal), position_id)


@router.post("/positions/{position_id}/seats")
def assign_seat(position_id: int, payload: SeatIn, background: BackgroundTasks,
                principal: Principal = Depends(require_company_role("manager")), db: Session = Depends(get_db)):
    org_id = active_org(principal)
    out = cf.assign_seat(db, org_id, position_id, payload.member_id)
    agents = [s["agent_id"] for s in out["seats"] if s["member_id"] == payload.member_id and s["agent_id"]]
    if agents:
        _resync(background, principal, org_id, agents)
    return {**out, "resync_agents": agents}


@router.delete("/positions/{position_id}/seats/{member_id}")
def unassign_seat(position_id: int, member_id: int, background: BackgroundTasks,
                  principal: Principal = Depends(require_company_role("manager")), db: Session = Depends(get_db)):
    from app.models import Agent
    org_id = active_org(principal)
    out = cf.unassign_seat(db, org_id, position_id, member_id)
    ag = db.query(Agent).filter(Agent.member_id == member_id).first()
    if ag is not None:
        _resync(background, principal, org_id, [ag.id])
    return out


class RuleIn(BaseModel):
    company_id: int | None = None
    action_type: str | None = Field(default=None, max_length=40)
    min_amount_usd: float | None = Field(default=None, ge=0)
    max_amount_usd: float | None = Field(default=None, ge=0)
    min_risk: str | None = Field(default=None, max_length=16)
    approver_kind: str | None = Field(default=None, max_length=24)
    approver_position_id: int | None = None
    agent_alone_level: str | None = Field(default=None, max_length=16)
    note: str | None = Field(default=None, max_length=400)
    enabled: bool | None = None


class SeedIn(BaseModel):
    company_id: int | None = None
    template: str | None = Field(default=None, pattern="^(shop|agency|ketoan)$")
    replace: bool = False


class EvaluateIn(BaseModel):
    member_id: int
    action_type: str = Field(min_length=1, max_length=60)
    amount_usd: float | None = Field(default=None, ge=0)
    risk: str | None = Field(default=None, max_length=16)


@router.get("/authority")
def authority_matrix(company_id: int | None = None, principal: Principal = Depends(require_company_role("member")),
                     db: Session = Depends(get_db)):
    return auth_svc.list_rules(db, active_org(principal), company_id)


@router.post("/authority/rules")
def create_rule(payload: RuleIn, principal: Principal = Depends(require_company_role("admin")), db: Session = Depends(get_db)):
    r = auth_svc.create_rule(db, active_org(principal), payload.model_dump(exclude_unset=True))
    return auth_svc.public_rule(db, r)


@router.patch("/authority/rules/{rule_id}")
def update_rule(rule_id: int, payload: RuleIn, principal: Principal = Depends(require_company_role("admin")),
                db: Session = Depends(get_db)):
    data = payload.model_dump(exclude_unset=True)
    data.pop("company_id", None)
    r = auth_svc.update_rule(db, active_org(principal), rule_id, data, set(data))
    return auth_svc.public_rule(db, r)


@router.delete("/authority/rules/{rule_id}")
def delete_rule(rule_id: int, principal: Principal = Depends(require_company_role("admin")), db: Session = Depends(get_db)):
    return auth_svc.delete_rule(db, active_org(principal), rule_id)


@router.post("/authority/seed-defaults")
def seed_authority(payload: SeedIn, principal: Principal = Depends(require_company_role("admin")), db: Session = Depends(get_db)):
    org_id = active_org(principal)
    co = cf._company(db, org_id, payload.company_id, write=True)
    out = auth_svc.seed_defaults(db, org_id, co.id, template=payload.template, replace=payload.replace)
    if out["seeded"] == 0 and out["kept"]:
        raise HTTPException(409, f"Công ty đã có {out['kept']} luật. Chọn \"Thay bằng mặc định\" nếu muốn xoá và gieo lại.")
    return {**out, **auth_svc.list_rules(db, org_id, co.id)}


@router.post("/authority/evaluate")
def evaluate(payload: EvaluateIn, principal: Principal = Depends(require_company_role("member")), db: Session = Depends(get_db)):
    """Thử luật: người/agent này làm việc này với số tiền này thì ai duyệt? Không tạo phê duyệt."""
    from app.models import Member
    m = ensure_member(db, payload.member_id, principal)
    if not isinstance(m, Member):
        raise HTTPException(404, "Không thấy người/agent này")
    d = auth_svc.decide(db, m, payload.action_type, amount_usd=payload.amount_usd, risk=payload.risk)
    if d is None:
        return {"matched": False, "message": "Không có luật nào khớp → hệ thống dùng hành vi cũ "
                                              "(lưới quyền công cụ / chính sách hiện có)."}
    return {"matched": True, **d.as_dict()}


# ------------------------------------------------------------------ R1 vai trò theo công ty + nhiều ghế

class CompanyAccessIn(BaseModel):
    company_id: int
    role: str
    user_id: int | None = None
    email: str | None = None


class SeatLinkIn(BaseModel):
    user_id: int
    member_id: int


@router.get("/my-companies")
def my_companies(principal: Principal = Depends(require_role("guest")), db: Session = Depends(get_db)):
    from app.services import company_roles
    return company_roles.my_companies(db, active_org(principal), principal)


@router.get("/company-access")
def company_access(company_id: int, principal: Principal = Depends(require_company_role("member")),
                   db: Session = Depends(get_db)):
    from app.services import company_roles
    return company_roles.list_access(db, active_org(principal), company_id)


@router.put("/company-access")
def set_company_access(payload: CompanyAccessIn, principal: Principal = Depends(require_company_role("member")),
                       db: Session = Depends(get_db)):
    from app.services import company_roles
    return company_roles.set_access(db, active_org(principal), principal, company_id=payload.company_id,
                                    role=payload.role, user_id=payload.user_id, email=payload.email)


@router.delete("/company-access/{access_id}")
def remove_company_access(access_id: int, principal: Principal = Depends(require_company_role("member")),
                          db: Session = Depends(get_db)):
    from app.services import company_roles
    return company_roles.remove_access(db, active_org(principal), principal, access_id)


@router.post("/user-seats")
def link_user_seat(payload: SeatLinkIn, principal: Principal = Depends(require_company_role("member")),
                   db: Session = Depends(get_db)):
    from app.services import company_roles
    return company_roles.link_seat(db, active_org(principal), principal, user_id=payload.user_id,
                                   member_id=payload.member_id)


@router.delete("/user-seats/{seat_id}")
def unlink_user_seat(seat_id: int, principal: Principal = Depends(require_company_role("member")),
                     db: Session = Depends(get_db)):
    from app.services import company_roles
    return company_roles.unlink_seat(db, active_org(principal), principal, seat_id)
