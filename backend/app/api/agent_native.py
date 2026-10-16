"""M2e — công ty agent-native: luật cứng (M2e.2), hợp đồng dữ liệu (M2e.3) … Spec docs/m2e-agent-native-company.md."""
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


# ------------------------------------------------------------------ M2e.3 hợp đồng dữ liệu

class ContractIn(BaseModel):
    company_id: int | None = None
    template: str | None = None
    name: str | None = None
    description: str | None = None
    input_schema: dict | str | None = None
    output_schema: dict | str | None = None
    acceptance: list | None = None
    max_attempts: int | None = None
    outcome_field: str | None = None
    position_id: int | None = None
    status: str | None = None


class OutputIn(BaseModel):
    output: dict | str | None = None


class AttachIn(BaseModel):
    contract_id: int
    input: dict | None = None


def _task_in_org(db: Session, org: int, task_id: int):
    from app.models import Company, Project, Task
    t = db.get(Task, task_id)
    pr = db.get(Project, t.project_id) if t is not None and t.project_id else None
    co = db.get(Company, pr.company_id) if pr else None
    if t is None or co is None or co.organization_id != org:
        raise HTTPException(404, "Không thấy việc này.")
    return t


@router.get("/contracts")
def contracts(company_id: int | None = None, include_archived: bool = False,
              principal: Principal = Depends(require_role("member")), db: Session = Depends(get_db)):
    from app.services import io_contracts as ioc
    return ioc.list_contracts(db, active_org(principal), company_id, include_archived=include_archived)


@router.post("/contracts")
def create_contract(payload: ContractIn, background: BackgroundTasks,
                    principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    from app.services import io_contracts as ioc
    org = active_org(principal)
    c = ioc.create_contract(db, org, payload.model_dump(exclude_unset=True))
    resync_agents_later(background, principal, org)
    return ioc.public_contract(db, c)


@router.patch("/contracts/{contract_id}")
def update_contract(contract_id: int, payload: ContractIn, background: BackgroundTasks,
                    principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    from app.services import io_contracts as ioc
    org = active_org(principal)
    data = payload.model_dump(exclude_unset=True); data.pop("company_id", None); data.pop("template", None)
    c = ioc.update_contract(db, org, contract_id, data)
    resync_agents_later(background, principal, org)
    return ioc.public_contract(db, c)


@router.delete("/contracts/{contract_id}")
def archive_contract(contract_id: int, background: BackgroundTasks,
                     principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    from app.services import io_contracts as ioc
    org = active_org(principal)
    out = ioc.archive_contract(db, org, contract_id)
    resync_agents_later(background, principal, org)
    return out


@router.post("/contracts/{contract_id}/validate")
def validate_output(contract_id: int, payload: OutputIn, principal: Principal = Depends(require_role("member")),
                    db: Session = Depends(get_db)):
    """Thử một kết quả với hợp đồng — đúng hàm kiểm của company_task_submit_output, không ghi gì."""
    import json as _json
    from app.services import io_contracts as ioc
    out = payload.output
    if isinstance(out, str):
        try:
            out = _json.loads(out)
        except ValueError:
            return {"valid": False, "errors": [{"path": "(gốc)", "message": "không phải JSON hợp lệ"}]}
    return ioc.try_output(db, active_org(principal), contract_id, out)


@router.get("/tasks/{task_id}/contract")
def task_contract(task_id: int, principal: Principal = Depends(require_role("member")), db: Session = Depends(get_db)):
    from app.services import io_contracts as ioc
    t = _task_in_org(db, active_org(principal), task_id)
    return {"task_id": t.id, "contract": ioc.public_task_contract(db, ioc.task_contract(db, t.id))}


@router.post("/tasks/{task_id}/contract")
def attach_contract(task_id: int, payload: AttachIn, principal: Principal = Depends(require_role("manager")),
                    db: Session = Depends(get_db)):
    from app.services import io_contracts as ioc
    org = active_org(principal)
    t = _task_in_org(db, org, task_id)
    return ioc.attach_by_id(db, org, t, payload.contract_id, payload.input)


@router.post("/tasks/{task_id}/output")
def submit_output(task_id: int, payload: OutputIn, principal: Principal = Depends(require_role("member")),
                  db: Session = Depends(get_db)):
    """Người nộp (hoặc nộp thay) kết quả theo hợp đồng — cùng đường kiểm với agent."""
    from app.models import Member
    from app.services import io_contracts as ioc
    org = active_org(principal)
    t = _task_in_org(db, org, task_id)
    member = db.get(Member, principal.member_id) if getattr(principal, "member_id", None) else None
    try:
        return ioc.submit(db, t, member, payload.output, via="api")
    except ioc.SubmitError as exc:
        raise HTTPException(exc.status, exc.message) from exc
