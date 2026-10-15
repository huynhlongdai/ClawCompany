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
