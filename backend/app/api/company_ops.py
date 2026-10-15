"""M2c — vận hành công ty dưới tiền tố /api/team (cùng chỗ với M2b): bản đồ quy trình (D4).
Spec: docs/m2c-company-operations.md."""
from fastapi import APIRouter, Depends
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
def update_process(process_id: int, payload: ProcessIn, principal: Principal = Depends(require_role("manager")),
                   db: Session = Depends(get_db)):
    data, fields = _dump(payload)
    p = pm.update_process(db, active_org(principal), process_id, data, fields)
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


@router.post("/process-instances/{instance_id}/cancel")
def cancel_instance(instance_id: int, principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    return pm.cancel(db, active_org(principal), instance_id)


# ------------------------------------------------------------------ D5 KPI chia tầng

from app.services import kpi_cascade as kc  # noqa: E402


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
    co = _company(db, org, payload.company_id)
    if payload.all_departments:
        items = await rh.generate_all(db, org, co.id, payload.kind, runtime=_runtime())
        return {"items": items}
    return await rh.generate(db, org, co.id, payload.kind, department_id=payload.department_id, runtime=_runtime(),
                             use_agent=payload.use_agent)


@router.get("/rhythm/reports/{report_id}")
def rhythm_report(report_id: int, principal: Principal = Depends(require_role("member")), db: Session = Depends(get_db)):
    return rh.get_report(db, active_org(principal), report_id)
