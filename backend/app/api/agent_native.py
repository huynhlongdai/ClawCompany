"""M2e — công ty agent-native: luật cứng (M2e.2) … Spec docs/m2e-agent-native-company.md."""
import hmac

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.authz import Principal, require_role
from app.core.tenancy import active_org
from app.db.session import get_db
from app.services import runtime_rules as rr

router = APIRouter(prefix="/team", tags=["agent-native"])
guard_router = APIRouter(prefix="/guard", tags=["guard"])


def push_rules_later(background: BackgroundTasks) -> None:
    """Đẩy bộ luật lên gateway + sinh lại AGENTS.md (phần Luật cứng) sau khi trả lời."""
    async def run():
        from app.db.session import SessionLocal
        from app.runtime.factory import get_runtime
        db = SessionLocal()
        try:
            out = await rr.push(db, get_runtime())
            print(f"[m2e] rules push: {out}")
        except Exception as exc:  # noqa: BLE001
            print(f"[m2e] rules push failed: {exc}")
        finally:
            db.close()
    background.add_task(run)


def resync_agents_later(background: BackgroundTasks, principal: Principal, org_id: int) -> None:
    from app.api.team import _resync
    _resync(background, principal, org_id, None)


class RuleIn(BaseModel):
    company_id: int | None = None
    template: str | None = None
    name: str | None = None
    kind: str | None = None
    pattern: str | None = None
    action: str | None = None
    message: str | None = None
    external_only: bool | None = None
    position_id: int | None = None
    source_ref: str | None = None
    enabled: bool | None = None


class RuleTestIn(BaseModel):
    company_id: int | None = None
    position_id: int | None = None
    text: str = ""
    tool: str = ""
    external: bool = True


@router.get("/rules")
def rules(company_id: int | None = None, principal: Principal = Depends(require_role("member")),
          db: Session = Depends(get_db)):
    return rr.list_rules(db, active_org(principal), company_id)


@router.post("/rules")
def create_rule(payload: RuleIn, background: BackgroundTasks, principal: Principal = Depends(require_role("manager")),
                db: Session = Depends(get_db)):
    org = active_org(principal)
    r = rr.create_rule(db, org, payload.model_dump(exclude_unset=True))
    push_rules_later(background); resync_agents_later(background, principal, org)
    return rr.public_rule(db, r)


@router.patch("/rules/{rule_id}")
def update_rule(rule_id: int, payload: RuleIn, background: BackgroundTasks,
                principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    org = active_org(principal)
    data = payload.model_dump(exclude_unset=True); data.pop("company_id", None); data.pop("template", None)
    r = rr.update_rule(db, org, rule_id, data)
    push_rules_later(background); resync_agents_later(background, principal, org)
    return rr.public_rule(db, r)


@router.delete("/rules/{rule_id}")
def delete_rule(rule_id: int, background: BackgroundTasks, principal: Principal = Depends(require_role("manager")),
                db: Session = Depends(get_db)):
    org = active_org(principal)
    out = rr.delete_rule(db, org, rule_id)
    push_rules_later(background); resync_agents_later(background, principal, org)
    return out


@router.post("/rules/test")
def test_rules(payload: RuleTestIn, principal: Principal = Depends(require_role("member")), db: Session = Depends(get_db)):
    """Thử một câu / một tool với bộ luật của công ty (hoặc của một chức danh) — đúng hàm cổng MCP dùng."""
    from app.models.agent_native import CompanyRule
    from app.services.company_foundation import _company
    co = _company(db, active_org(principal), payload.company_id)
    rows = db.query(CompanyRule).filter(CompanyRule.company_id == co.id, CompanyRule.enabled.is_(True)).all()
    rules = [rr.as_dict(r) for r in rows if r.position_id in (None, payload.position_id)]
    hits = rr.check_text(rules, payload.text, external=payload.external) if payload.text else []
    return {"hits": hits, "scrubbed": rr.scrub(rules, payload.text, external=payload.external) if payload.text else "",
            "tool": rr.check_tool(rules, payload.tool) if payload.tool else None}


@router.post("/rules/sync")
async def sync_rules(principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    from app.runtime.factory import get_runtime
    return await rr.push(db, get_runtime())


@router.get("/rules/compiled")
def compiled_rules(principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    return rr.compile_all(db, active_org(principal))


class ViolationIn(BaseModel):
    agentId: str
    ruleId: int | str | None = None
    hook: str = ""
    action: str = ""
    excerpt: str = ""
    sessionKey: str = ""
    runId: str = ""


@guard_router.post("/violations")
def guard_violation(payload: ViolationIn, x_guard_token: str = Header(default=""), db: Session = Depends(get_db)):
    """Guard plugin trên gateway báo một vi phạm (mạng docker nội bộ, token HMAC từ JWT_SECRET)."""
    if not x_guard_token or not hmac.compare_digest(x_guard_token, rr.report_token()):
        raise HTTPException(401, "guard token sai")
    return rr.record_from_plugin(db, payload.model_dump())
