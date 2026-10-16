"""M2c — vận hành công ty dưới tiền tố /api/team (cùng chỗ với M2b): bản đồ quy trình (D4).
Spec: docs/m2c-company-operations.md."""
from fastapi import HTTPException, APIRouter, BackgroundTasks, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.authz import Principal, require_role
from app.core.tenancy import active_org
from app.db.session import get_db
from app.services import process_map as pm

router = APIRouter(prefix="/team", tags=["company-ops"])


# ------------------------------------------------------------------ D4 quy trình

class StepIn(BaseModel):
    id: int | None = None
    name: str = Field(min_length=1, max_length=200)
    instructions: str = Field(default="", max_length=4000)
    position_id: int | None = None
    sop_id: int | None = None
    expected_minutes: int | None = None
    action_type: str = Field(default="", max_length=40)
    risk: str = Field(default="", max_length=16)
    depends_on: list[int] | None = None      # v2: seq các bước đứng trước; vắng = nối tiếp bước trước
    condition: dict | None = None             # v2: {field, op, value}
    branch: str = Field(default="", max_length=60)
    contract_id: int | None = None            # M2e.3: hợp đồng dữ liệu của bước


class OutcomeIn(BaseModel):
    outcome: str = Field(default="", max_length=200)


class ProcessIn(BaseModel):
    company_id: int | None = None
    name: str | None = Field(default=None, max_length=200)
    category: str | None = Field(default=None, max_length=8)
    description: str | None = Field(default=None, max_length=4000)
    owner_position_id: int | None = None
    steps: list[StepIn] | None = None


class StartIn(BaseModel):
    title: str = Field(default="", max_length=220)
    amount_usd: float | None = None
    input: dict | None = None


class SeedProcIn(BaseModel):
    company_id: int | None = None
    template: str = Field(pattern="^(shop|agency|ketoan)$")


def _dump(payload: BaseModel) -> tuple[dict, set[str]]:
    data = payload.model_dump(exclude_unset=True)
    if "steps" in data and data["steps"] is not None:
        data["steps"] = [s for s in data["steps"]]
    return data, set(data)


@router.get("/processes")
def list_processes(company_id: int | None = None, include_archived: bool = False,
                   principal: Principal = Depends(require_role("member")), db: Session = Depends(get_db)):
    return pm.list_processes(db, active_org(principal), company_id, include_archived=include_archived)


@router.post("/processes")
def create_process(payload: ProcessIn, principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    data, _ = _dump(payload)
    p = pm.create_process(db, active_org(principal), data)
    return pm.public_process(db, p)


@router.patch("/processes/{process_id}")
def update_process(process_id: int, payload: ProcessIn, background: BackgroundTasks,
                   principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    data, fields = _dump(payload)
    p = pm.update_process(db, active_org(principal), process_id, data, fields)
    if any(s.get("contract_id") for s in data.get("steps") or []):   # M2e.3: hợp đồng của bước → AGENTS.md chức danh
        from app.api.team import _resync
        _resync(background, principal, active_org(principal), None)
    return pm.public_process(db, p)


@router.delete("/processes/{process_id}")
def archive_process(process_id: int, principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    return pm.archive_process(db, active_org(principal), process_id)


@router.post("/processes/seed")
def seed_processes(payload: SeedProcIn, principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    return pm.seed_templates(db, active_org(principal), payload.company_id, payload.template)


@router.post("/processes/{process_id}/start")
def start_process(process_id: int, payload: StartIn, principal: Principal = Depends(require_role("member")),
                  db: Session = Depends(get_db)):
    return pm.start(db, active_org(principal), process_id, title=payload.title, amount_usd=payload.amount_usd,
                    input_data=payload.input, actor_member_id=principal.member_id)


@router.get("/processes/{process_id}/instances")
def process_instances(process_id: int, principal: Principal = Depends(require_role("member")), db: Session = Depends(get_db)):
    return pm.instances(db, active_org(principal), process_id)


@router.get("/process-instances/{instance_id}")
def process_instance(instance_id: int, principal: Principal = Depends(require_role("member")), db: Session = Depends(get_db)):
    return pm.get_instance(db, active_org(principal), instance_id)


@router.post("/process-step-runs/{run_id}/outcome")
def step_outcome(run_id: int, payload: OutcomeIn, principal: Principal = Depends(require_role("member")),
                 db: Session = Depends(get_db)):
    return pm.set_outcome(db, active_org(principal), run_id, payload.outcome)


@router.post("/process-instances/{instance_id}/cancel")
def cancel_instance(instance_id: int, principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    return pm.cancel(db, active_org(principal), instance_id)


# ------------------------------------------------------------------ D5 KPI chia tầng

from app.services import kpi_cascade as kc  # noqa: E402


class KpiSnapIn(BaseModel):
    company_id: int | None = None
    backfill: int = Field(default=0, ge=0, le=12)


class KpiIn(BaseModel):
    company_id: int | None = None
    level: str | None = Field(default=None, max_length=16)
    name: str | None = Field(default=None, max_length=200)
    unit: str | None = Field(default=None, max_length=40)
    target: float | None = None
    direction: str | None = Field(default=None, max_length=8)
    period: str | None = Field(default=None, max_length=16)
    metric: str | None = Field(default=None, max_length=40)
    department_id: int | None = None
    position_id: int | None = None
    member_id: int | None = None
    parent_id: int | None = None
    goal_id: int | None = None
    objective_id: int | None = None
    process_id: int | None = None
    weight: float | None = None


class MeasureIn(BaseModel):
    value: float
    note: str = Field(default="", max_length=400)
    period_key: str | None = Field(default=None, max_length=16)


class CompanyIn(BaseModel):
    company_id: int | None = None


@router.get("/kpis")
def list_kpis(company_id: int | None = None, principal: Principal = Depends(require_role("member")), db: Session = Depends(get_db)):
    return kc.list_kpis(db, active_org(principal), company_id)


@router.post("/kpis")
def create_kpi(payload: KpiIn, principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    return kc.create_kpi(db, active_org(principal), payload.model_dump(exclude_unset=True))


@router.patch("/kpis/{kpi_id}")
def update_kpi(kpi_id: int, payload: KpiIn, principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    data = payload.model_dump(exclude_unset=True)
    return kc.update_kpi(db, active_org(principal), kpi_id, data, set(data))


@router.delete("/kpis/{kpi_id}")
def delete_kpi(kpi_id: int, principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    return kc.delete_kpi(db, active_org(principal), kpi_id)


@router.post("/kpis/{kpi_id}/measurements")
def record_kpi(kpi_id: int, payload: MeasureIn, principal: Principal = Depends(require_role("member")), db: Session = Depends(get_db)):
    return kc.record(db, active_org(principal), kpi_id, payload.value, note=payload.note, period_key=payload.period_key,
                     member_id=principal.member_id)


@router.post("/kpis/sync-positions")
def sync_position_kpis(payload: CompanyIn, principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    return kc.sync_positions(db, active_org(principal), payload.company_id)


@router.post("/kpis/snapshot")
def snapshot_kpis(payload: KpiSnapIn, principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    """M2d.2: chụp số KPI ngay (kỳ hiện tại) + tuỳ chọn tính lại ``backfill`` kỳ cũ từ dữ liệu hiện có."""
    from app.services.company_foundation import _company
    co = _company(db, active_org(principal), payload.company_id, write=True)
    return kc.snapshot_company(db, co.id, trigger="manual", backfill=payload.backfill)


# ------------------------------------------------------------------ D6 nhịp vận hành

from app.services import operating_rhythm as rh  # noqa: E402


class RhythmConfigIn(BaseModel):
    company_id: int | None = None
    standup_enabled: bool | None = None
    standup_hour: int | None = None
    weekly_enabled: bool | None = None
    weekly_dow: int | None = None
    weekly_hour: int | None = None
    timezone: str | None = Field(default=None, max_length=64)
    per_department: bool | None = None
    agent_author: bool | None = None


class RhythmRunIn(BaseModel):
    company_id: int | None = None
    kind: str = Field(default="standup", pattern="^(standup|weekly)$")
    department_id: int | None = None
    all_departments: bool = False
    use_agent: bool | None = None


def _runtime():
    from app.core.config import settings
    if (settings.openclaw_mode or "").lower() not in ("native", "gateway"):
        return None
    from app.runtime.factory import get_runtime
    return get_runtime()


@router.get("/rhythm")
def rhythm(company_id: int | None = None, principal: Principal = Depends(require_role("member")), db: Session = Depends(get_db)):
    return rh.overview(db, active_org(principal), company_id)


@router.put("/rhythm/config")
def rhythm_config(payload: RhythmConfigIn, principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    data = payload.model_dump(exclude_unset=True)
    return rh.save_config(db, active_org(principal), data.pop("company_id", None), data)


@router.post("/rhythm/run")
async def rhythm_run(payload: RhythmRunIn, principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    """Gửi ngay giao ban / báo cáo tuần của kỳ hiện tại (đã gửi kỳ này thì trả bản cũ, không gửi lại)."""
    from app.services.company_foundation import _company
    org = active_org(principal)
    co = _company(db, org, payload.company_id, write=True)
    if payload.all_departments:
        items = await rh.generate_all(db, org, co.id, payload.kind, runtime=_runtime())
        return {"items": items}
    return await rh.generate(db, org, co.id, payload.kind, department_id=payload.department_id, runtime=_runtime(),
                             use_agent=payload.use_agent)


@router.get("/rhythm/reports/{report_id}")
def rhythm_report(report_id: int, principal: Principal = Depends(require_role("member")), db: Session = Depends(get_db)):
    return rh.get_report(db, active_org(principal), report_id)


# ------------------------------------------------------------------ D7 lịch tuân thủ

from app.services import compliance_calendar as cc  # noqa: E402


class ComplianceSettingsIn(BaseModel):
    company_id: int | None = None
    vat_period: str | None = Field(default=None, max_length=16)
    pit_period: str | None = Field(default=None, max_length=16)
    has_employees: bool | None = None
    accounting_position_id: int | None = None


class ComplianceRuleIn(BaseModel):
    company_id: int | None = None
    name: str | None = Field(default=None, max_length=200)
    category: str | None = Field(default=None, max_length=16)
    frequency: str | None = Field(default=None, max_length=16)
    due_rule: dict | None = None
    legal_basis: str | None = Field(default=None, max_length=4000)
    note: str | None = Field(default=None, max_length=4000)
    remind_days: int | None = None
    enabled: bool | None = None
    needs_review: bool | None = None
    entity_types: list[str] | None = None
    condition: dict | None = None


class SeedComplianceIn(BaseModel):
    company_id: int | None = None
    replace: bool = False


@router.get("/compliance")
def compliance(company_id: int | None = None, principal: Principal = Depends(require_role("member")), db: Session = Depends(get_db)):
    return cc.overview(db, active_org(principal), company_id)


@router.put("/compliance/settings")
def compliance_settings(payload: ComplianceSettingsIn, principal: Principal = Depends(require_role("admin")), db: Session = Depends(get_db)):
    data = payload.model_dump(exclude_unset=True)
    org = active_org(principal)
    out = cc.save_settings(db, org, data.pop("company_id", None), data)
    return out


@router.post("/compliance/seed")
def compliance_seed(payload: SeedComplianceIn, principal: Principal = Depends(require_role("admin")), db: Session = Depends(get_db)):
    from app.services.company_foundation import _company
    org = active_org(principal)
    co = _company(db, org, payload.company_id, write=True)
    return cc.seed_defaults(db, org, co.id, replace=payload.replace)


@router.post("/compliance/rules")
def compliance_rule_create(payload: ComplianceRuleIn, principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    data = payload.model_dump(exclude_unset=True)
    return cc.create_rule(db, active_org(principal), data.pop("company_id", None), data)


@router.patch("/compliance/rules/{rule_id}")
def compliance_rule_update(rule_id: int, payload: ComplianceRuleIn, principal: Principal = Depends(require_role("admin")),
                           db: Session = Depends(get_db)):
    data = payload.model_dump(exclude_unset=True)
    data.pop("company_id", None)
    return cc.update_rule(db, active_org(principal), rule_id, data)


@router.delete("/compliance/rules/{rule_id}")
def compliance_rule_delete(rule_id: int, principal: Principal = Depends(require_role("admin")), db: Session = Depends(get_db)):
    return cc.delete_rule(db, active_org(principal), rule_id)


@router.post("/compliance/generate")
def compliance_generate(payload: CompanyIn, principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    """Sinh hạn 120 ngày tới + gửi nhắc tới hạn ngay (không chờ beat)."""
    org = active_org(principal)
    g = cc.generate(db, org, payload.company_id)
    m = cc.remind(db, org, payload.company_id)
    return {**g, "reminded": m["reminded"]}


# M2d.3: ngày nghỉ lễ — chỉ để tính hạn pháp lý (agent không có ngày nghỉ)
from app.services import holidays as hol  # noqa: E402


class HolidayIn(BaseModel):
    day: str | None = Field(default=None, max_length=10)
    name: str | None = Field(default=None, max_length=200)
    kind: str | None = Field(default=None, max_length=16)
    status: str | None = Field(default=None, max_length=24)
    source_url: str | None = Field(default=None, max_length=400)
    note: str | None = Field(default=None, max_length=400)


@router.get("/compliance/holidays")
def holidays_list(year: int, principal: Principal = Depends(require_role("member")), db: Session = Depends(get_db)):
    if year < 2000 or year > 2100:
        raise HTTPException(422, "Năm không hợp lệ.")
    return hol.list_year(db, active_org(principal), year)


@router.post("/compliance/holidays")
def holidays_create(payload: HolidayIn, principal: Principal = Depends(require_role("admin")), db: Session = Depends(get_db)):
    org = active_org(principal)
    out = hol.create(db, org, payload.model_dump(exclude_unset=True))
    out["legal_due_updated"] = cc.refresh_legal(db, org)
    return out


@router.patch("/compliance/holidays/{holiday_id}")
def holidays_update(holiday_id: int, payload: HolidayIn, principal: Principal = Depends(require_role("admin")),
                    db: Session = Depends(get_db)):
    org = active_org(principal)
    out = hol.update(db, org, holiday_id, payload.model_dump(exclude_unset=True))
    out["legal_due_updated"] = cc.refresh_legal(db, org)
    return out


@router.delete("/compliance/holidays/{holiday_id}")
def holidays_delete(holiday_id: int, principal: Principal = Depends(require_role("admin")), db: Session = Depends(get_db)):
    org = active_org(principal)
    out = hol.delete(db, org, holiday_id)
    out["legal_due_updated"] = cc.refresh_legal(db, org)
    return out


@router.post("/compliance/deadlines/{deadline_id}/done")
def compliance_done(deadline_id: int, principal: Principal = Depends(require_role("member")), db: Session = Depends(get_db)):
    return cc.mark_done(db, active_org(principal), deadline_id)


# ------------------------------------------------------------------ D8 chẩn đoán sẵn sàng agent

from app.services import agent_readiness as ar  # noqa: E402


class ReadinessIn(BaseModel):
    company_id: int | None = None
    answers: dict | None = None


@router.get("/readiness")
def readiness(company_id: int | None = None, principal: Principal = Depends(require_role("member")), db: Session = Depends(get_db)):
    return ar.latest(db, active_org(principal), company_id)


@router.post("/readiness")
def readiness_assess(payload: ReadinessIn, principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    return ar.assess(db, active_org(principal), payload.company_id, answers=payload.answers, member_id=principal.member_id)
