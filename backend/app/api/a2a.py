"""A2A — thuê agent ngoài + mở seat cho bên ngoài (xem app/services/a2a.py)."""
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.authz import Principal, require_human, require_role
from app.core.tenancy import active_org
from app.db.session import get_db
from app.runtime.factory import get_runtime
from app.services import a2a

router = APIRouter(prefix="/a2a", tags=["a2a"])


def _base(request: Request) -> str:
    proto = request.headers.get("x-forwarded-proto") or request.url.scheme
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
    return f"{proto}://{host}"


class ExternalIn(BaseModel):
    card_url: str = Field(default="", max_length=1000)
    endpoint_url: str = Field(default="", max_length=1000)
    name: str = Field(default="", max_length=160)
    description: str = Field(default="", max_length=2000)
    auth_header: str = Field(default="", max_length=2000)


class ExternalPatch(BaseModel):
    enabled: bool | None = None
    auth_header: str | None = Field(default=None, max_length=2000)
    name: str | None = Field(default=None, max_length=160)


class SendIn(BaseModel):
    text: str = Field(min_length=1, max_length=12000)
    context_id: str | None = Field(default=None, max_length=120)


@router.get("/external")
def list_external(principal: Principal = Depends(require_human()), db: Session = Depends(get_db)):
    return {"items": a2a.list_ext(db, active_org(principal))}


@router.post("/external")
def add_external(payload: ExternalIn, principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    """Dán URL Agent Card (…/.well-known/agent-card.json) — tự đọc tên, mô tả, kỹ năng, endpoint."""
    return a2a.register(db, active_org(principal), payload.model_dump())


@router.patch("/external/{ext_id}")
def patch_external(ext_id: int, payload: ExternalPatch, principal: Principal = Depends(require_role("manager")),
                   db: Session = Depends(get_db)):
    return a2a.update_ext(db, active_org(principal), ext_id, payload.model_dump(exclude_unset=True))


@router.delete("/external/{ext_id}")
def delete_external(ext_id: int, principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    return a2a.delete_ext(db, active_org(principal), ext_id)


@router.post("/external/{ext_id}/send")
def send_external(ext_id: int, payload: SendIn, principal: Principal = Depends(require_role("manager")),
                  db: Session = Depends(get_db)):
    """Gửi thử một tin cho agent ngoài (người quản lý)."""
    return a2a.send(db, active_org(principal), ext_id, payload.text, context_id=payload.context_id)


class ExposeIn(BaseModel):
    enabled: bool = True
    rotate: bool = False


@router.get("/expose/{agent_id}")
def get_expose(agent_id: int, request: Request, principal: Principal = Depends(require_human()), db: Session = Depends(get_db)):
    return a2a.exposure_status(db, active_org(principal), agent_id, _base(request))


@router.post("/expose/{agent_id}")
def set_expose(agent_id: int, payload: ExposeIn, request: Request, principal: Principal = Depends(require_role("manager")),
               db: Session = Depends(get_db)):
    """Bật/tắt mở seat này cho bên ngoài qua A2A; lần đầu (hoặc rotate) trả khoá — chỉ hiện 1 lần."""
    return a2a.expose(db, active_org(principal), agent_id, enabled=payload.enabled, rotate=payload.rotate,
                      base_url=_base(request))


# --- công khai cho bên ngoài (xác thực bằng khoá A2A, không JWT)

@router.get("/agents/{rid}/.well-known/agent-card.json")
def public_card(rid: str, request: Request, db: Session = Depends(get_db)):
    return a2a.agent_card(db, rid, _base(request))


@router.post("/agents/{rid}")
async def public_rpc(rid: str, request: Request, db: Session = Depends(get_db)):
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = None
    return await a2a.handle_rpc(db, get_runtime(), rid, body, request.headers.get("authorization", ""))
