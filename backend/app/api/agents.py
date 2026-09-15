from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.models import Agent, Member
from app.schemas import AgentCreate, AgentOut
from app.runtime.factory import get_runtime
from app.core.authz import Principal, get_principal, require_role, require_human
from app.core.tenancy import active_org, ensure_member

router = APIRouter(prefix="/agents", tags=["agents"])

@router.get("", response_model=list[AgentOut])
def list_agents(principal: Principal = Depends(require_human()), db: Session = Depends(get_db)):
    org_id = active_org(principal)
    return db.query(Agent).join(Member, Member.id == Agent.member_id).filter(Member.organization_id == org_id).order_by(Agent.id).all()

@router.post("", response_model=AgentOut)
async def create_agent(payload: AgentCreate, principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    member = ensure_member(db, payload.member_id, principal)
    if member.member_type != "agent":
        raise HTTPException(status_code=400, detail="member_id must reference an AI member")
    obj = Agent(**payload.model_dump())
    db.add(obj); db.commit(); db.refresh(obj)
    runtime = get_runtime()
    try:
        await runtime.create_agent(obj.runtime_agent_id, {"name": member.name, "role": member.role, "model": obj.model})
    except Exception as exc:
        obj.lifecycle = "runtime_error"; db.add(obj); db.commit()
        raise HTTPException(502, f"Runtime provisioning failed: {exc}")
    return obj

@router.get("/runtime/health")
async def runtime_health(principal: Principal = Depends(require_human())):
    return await get_runtime().health()
