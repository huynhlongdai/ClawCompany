from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.models import Agent, Member
from app.schemas import AgentCreate, AgentOut
from app.runtime.factory import get_runtime
from app.core.authz import Principal, get_principal, require_role, require_human
from app.core.tenancy import active_org, ensure_member
from app.services.seat_profile import SeatError, SeatProfileService

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


# ---------------------------------------------------------------- WP-2.1/2.2
#
# Hồ sơ nhân sự AI. Đặt ở router `agents` thay vì mở một `/v37` mới: luật số 4
# của BUILD_PLAN — 45 router đã là quá nhiều, và những endpoint này nói đúng về
# agent nên chúng thuộc về đây.
#
# Cả ba endpoint đều `async def`. Bên trong có `await` gọi gateway, và một
# endpoint sync sẽ chạy trong threadpool không có event loop — đúng lỗi đã làm
# `POST /api/v20/tasks/{id}/follow` trả 500 suốt nhiều version.


class SeatFileIn(BaseModel):
    content: str = Field(max_length=200_000)
    # Hash của bản đang sửa. Thiếu nó thì từ chối, trừ khi force=true: ghi đè
    # vô điều kiện phải là lựa chọn nói ra, không phải mặc định.
    expected_hash: str | None = None
    force: bool = False


class SeatConfigIn(BaseModel):
    tab: str = Field(pattern="^(profile|capability|permission|budget)$")
    values: dict[str, object]
    base_hash: str | None = None
    allow_restart: bool = False
    dry_run: bool = False


def _seat_service(db: Session) -> SeatProfileService:
    return SeatProfileService(db, get_runtime())


@router.get("/{agent_id}/profile")
async def seat_profile(agent_id: int, principal: Principal = Depends(require_human()),
                       db: Session = Depends(get_db)):
    """Hồ sơ đầy đủ của một seat: database + roster + danh tính + config + 5 file.

    Mỗi trường mang theo nguồn (`sources`), và `warnings` nói thẳng cái gì không
    đọc được hoặc cái gì sắp bị cắt vì vượt hạn mức ký tự.
    """
    try:
        return await _seat_service(db).read(agent_id, active_org(principal))
    except SeatError as exc:
        raise HTTPException(404 if exc.reason == "not_found" else 400, exc.as_dict())


@router.put("/{agent_id}/files/{name}")
async def write_seat_file(agent_id: int, name: str, payload: SeatFileIn,
                          principal: Principal = Depends(require_role("manager")),
                          db: Session = Depends(get_db)):
    """Ghi một file bootstrap (tab Hồ sơ / Tính cách / Công việc).

    409 khi `expectedHash` đã cũ — nghĩa là có người khác vừa sửa. Phản hồi mang
    `current_hash` để client đọc lại và ghi trên bản mới.
    """
    try:
        return await _seat_service(db).write_file(
            agent_id, active_org(principal), name=name, content=payload.content,
            expected_hash=payload.expected_hash, force=payload.force)
    except SeatError as exc:
        status = {"not_found": 404, "file_conflict": 409}.get(exc.reason, 400)
        raise HTTPException(status, exc.as_dict())


@router.patch("/{agent_id}/config")
async def write_seat_config(agent_id: int, payload: SeatConfigIn,
                            principal: Principal = Depends(require_role("manager")),
                            db: Session = Depends(get_db)):
    """Ghi cấu hình seat (tab Năng lực / Quyền / Hạn mức) qua ConfigRegistry.

    Khoá được phép ghi bị giới hạn theo tab ở tầng server. `dry_run: true` trả
    về đúng frame sẽ gửi mà không ghi gì.
    """
    try:
        return await _seat_service(db).write_config(
            agent_id, active_org(principal), tab=payload.tab,
            values=dict(payload.values), base_hash=payload.base_hash,
            allow_restart=payload.allow_restart, dry_run=payload.dry_run)
    except SeatError as exc:
        status = {"not_found": 404, "restart_required": 409,
                  "rate_limited": 429}.get(exc.reason, 400)
        raise HTTPException(status, exc.as_dict())
