"""Phase B việc 7 — bộ nhớ chung theo phạm vi (tổ chức/công ty/phòng/dự án/ghế)."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.authz import Principal, require_role
from app.core.tenancy import active_org
from app.db.session import get_db
from app.services import agent_memory

router = APIRouter(prefix="/shared-memory", tags=["shared-memory"])


class SharedMemoryIn(BaseModel):
    scope: str = "org"
    scope_id: int | None = None
    kind: str = "fact"
    content: str = Field(max_length=2000)
    importance: int = Field(default=3, ge=1, le=5)
    tags: list[str] = Field(default_factory=list)


class SharedMemoryPatch(BaseModel):
    scope: str | None = None
    scope_id: int | None = None
    kind: str | None = None
    content: str | None = Field(default=None, max_length=2000)
    importance: int | None = Field(default=None, ge=1, le=5)


@router.get("")
def shared_list(scope: str | None = None, scope_id: int | None = None, q: str = "",
                principal: Principal = Depends(require_role("member")), db: Session = Depends(get_db)):
    return {"items": agent_memory.list_shared(db, active_org(principal), scope=scope, scope_id=scope_id, q=q)}


@router.get("/options")
def shared_options(principal: Principal = Depends(require_role("member")), db: Session = Depends(get_db)):
    return agent_memory.options(db, active_org(principal))


@router.post("")
def shared_create(payload: SharedMemoryIn, principal: Principal = Depends(require_role("manager")),
                  db: Session = Depends(get_db)):
    return agent_memory.create_shared(db, principal, active_org(principal), payload.model_dump())


@router.patch("/{memory_id}")
def shared_update(memory_id: int, payload: SharedMemoryPatch, principal: Principal = Depends(require_role("manager")),
                  db: Session = Depends(get_db)):
    return agent_memory.update_shared(db, principal, active_org(principal), memory_id,
                                      payload.model_dump(exclude_unset=True))


@router.delete("/{memory_id}")
def shared_forget(memory_id: int, principal: Principal = Depends(require_role("manager")),
                  db: Session = Depends(get_db)):
    return agent_memory.forget_shared(db, principal, active_org(principal), memory_id)
