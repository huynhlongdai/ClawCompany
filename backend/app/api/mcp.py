"""D1.5 — máy chủ MCP của ClawCompany (streamable-http, chỉ trả JSON).

Gateway OpenClaw khai báo:

    { mcp: { servers: { "clawcompany": {
        url: "https://<api>/api/mcp", transport: "streamable-http",
        headers: { "X-API-Key": "${CLAWCOMPANY_SEAT_KEY}" },
        toolFilter: { include: ["company_*"] }, enabled: true } } } }

Mỗi seat dùng API key gắn ``member_id`` của chính nó (``POST /api/auth/api-keys``
với ``member_id``), nên máy chủ biết ai đang gọi mà không tin tham số nào do
model điền. Key không gắn seat thì phải gửi ``X-ClawCompany-Seat`` (agentId)
và chỉ dùng được trong tổ chức của key.

Theo spec streamable-http, máy chủ được phép trả ``application/json`` cho mỗi
POST thay vì mở SSE; GET trả 405 vì máy chủ không chủ động đẩy thông điệp.
"""
from __future__ import annotations

import json
import re
import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.authz import Principal, enforce_org, get_principal
from app.db.session import get_db
from app.models import Agent, Member, TaskRun
from app.services import company_mcp, tool_permissions

router = APIRouter(tags=["mcp"])

PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
SERVER_INFO = {"name": "clawcompany", "version": "d1.5"}
TASK_SESSION = re.compile(r"company-task-(\d+)$")


def _seat(db: Session, principal: Principal, seat_header: str | None) -> tuple[Member, Agent | None]:
    if principal.auth_type != "api_key":
        raise HTTPException(403, "MCP chỉ nhận API key của seat (X-API-Key)")
    if principal.member_id:
        member = db.get(Member, principal.member_id)
        agent = db.execute(select(Agent).where(Agent.member_id == principal.member_id)).scalars().first()
        if member is None:
            raise HTTPException(403, "API key trỏ tới thành viên không còn tồn tại")
        if seat_header and (agent is None or agent.runtime_agent_id != seat_header):
            raise HTTPException(403, "X-ClawCompany-Seat không khớp seat của API key")
    else:
        if not seat_header:
            raise HTTPException(403, "API key không gắn seat: gửi X-ClawCompany-Seat")
        agent = db.execute(select(Agent).where(Agent.runtime_agent_id == seat_header)).scalars().first()
        member = db.get(Member, agent.member_id) if agent else None
        if member is None:
            raise HTTPException(404, "Không thấy seat")
    enforce_org(member.organization_id, principal)
    if member.member_type != "agent":
        raise HTTPException(403, "MCP dành cho seat agent")
    if member.status not in ("active", "onboarding"):
        raise HTTPException(403, f"Seat đang ở trạng thái {member.status}")
    return member, agent


def _run_for_session(db: Session, member: Member, session_key: str) -> TaskRun | None:
    """Lượt chạy hiện tại suy từ session key ``…:company-task-<id>``."""
    m = TASK_SESSION.search(session_key or "")
    if not m:
        return None
    return db.execute(select(TaskRun).where(
        TaskRun.task_id == int(m.group(1)), TaskRun.member_id == member.id,
        TaskRun.status.in_(("queued", "dispatched", "running")))
        .order_by(TaskRun.id.desc())).scalars().first()


def _allowed(ctx: company_mcp.ToolContext, spec: company_mcp.Tool) -> bool:
    scopes = set(ctx.scopes or [])
    return "*" in scopes or spec.scope in scopes


def _error(id_, code: int, message: str, data: dict | None = None) -> dict:
    err = {"code": code, "message": message}
    if data:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": id_, "error": err}


class Denied(Exception):
    """D1.6: tool ở mức ``off`` cho seat này → HTTP 403, kể cả khi gateway đã
    cho lời gọi đi qua (lớp chặn thứ hai không tin lớp thứ nhất)."""

    def __init__(self, reply: dict):
        self.reply = reply


def _deny_event(ctx, name: str, reason: str, **extra) -> None:
    company_mcp.emit_event(
        ctx.db, organization_id=ctx.org, event_type="mcp.tool.denied",
        source=company_mcp.SOURCE, company_id=ctx.member.company_id,
        aggregate_type="member", aggregate_id=str(ctx.member.id),
        actor_member_id=ctx.member.id, payload={"tool": name, "reason": reason, **extra})


def _handle(ctx: company_mcp.ToolContext, msg: dict) -> dict | None:
    if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0" or "method" not in msg:
        return _error(msg.get("id") if isinstance(msg, dict) else None, -32600, "Invalid Request")
    id_, method, params = msg.get("id"), msg["method"], msg.get("params") or {}
    if id_ is None:  # notification: không trả lời
        return None
    if method == "initialize":
        asked = str(params.get("protocolVersion") or "")
        return {"jsonrpc": "2.0", "id": id_, "result": {
            "protocolVersion": asked if asked in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0],
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": SERVER_INFO,
            "instructions": "Công cụ đọc/ghi dữ liệu công ty ClawCompany. Gọi company_context "
                            "trước; kết thúc mỗi lượt làm việc bằng company_task_comment.",
        }}
    if method == "ping":
        return {"jsonrpc": "2.0", "id": id_, "result": {}}
    if method == "tools/list":
        tools = [{"name": t.name, "description": t.description, "inputSchema": t.schema,
                  "annotations": {"readOnlyHint": not t.writes}}
                 for t in company_mcp.TOOLS.values()
                 if _allowed(ctx, t)
                 and tool_permissions.resolve(ctx.db, ctx.member, t.name)[0] != "off"]
        return {"jsonrpc": "2.0", "id": id_, "result": {"tools": tools}}
    if method == "tools/call":
        name = str(params.get("name") or "")
        spec = company_mcp.TOOLS.get(name)
        if spec is None:
            return _error(id_, -32602, f"Unknown tool: {name}")
        level, source = tool_permissions.resolve(ctx.db, ctx.member, name)
        if level == "off":
            _deny_event(ctx, name, "level_off", source=source)
            raise Denied(_error(id_, -32003, f"Seat không được dùng {name}",
                                {"error": "forbidden", "level": "off", "source": source}))
        args = params.get("arguments") or {}
        if not _allowed(ctx, spec):
            ok, result = False, {"error": "forbidden",
                                 "message": f"API key thiếu scope {spec.scope}"}
            _deny_event(ctx, name, "scope", scope=spec.scope)
        elif level == "ask":
            state, approval = tool_permissions.ask_approval(
                ctx.db, ctx.member, name, json.dumps(args, ensure_ascii=False, default=str))
            if state == "granted":
                ok, result = company_mcp.call(ctx, name, args)
            else:
                ok, result = True, {"pending_approval": True, "approval_id": approval.id,
                                    "message": f"{name} cần người duyệt; đã gửi yêu cầu "
                                               f"#{approval.id}. Dừng việc này và chờ kết quả."}
                _deny_event(ctx, name, "ask_pending", approval_id=approval.id)
        else:
            ok, result = company_mcp.call(ctx, name, args)
        return {"jsonrpc": "2.0", "id": id_, "result": {
            "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, default=str)}],
            "structuredContent": result, "isError": not ok}}
    return _error(id_, -32601, f"Method not found: {method}")


@router.post("/mcp")
async def mcp_post(request: Request, principal: Principal = Depends(get_principal),
                   db: Session = Depends(get_db),
                   seat: str | None = Header(default=None, alias="X-ClawCompany-Seat"),
                   session_key: str | None = Header(default=None, alias="X-OpenClaw-Session-Key"),
                   mcp_session: str | None = Header(default=None, alias="Mcp-Session-Id")):
    member, agent = _seat(db, principal, seat)
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        return JSONResponse(_error(None, -32700, "Parse error"), status_code=400)
    ctx = company_mcp.ToolContext(db=db, member=member, agent=agent, scopes=principal.scopes or [],
                                  session_key=session_key or "",
                                  run=_run_for_session(db, member, session_key or ""))
    batch = isinstance(body, list)
    replies = []
    for m in (body if batch else [body]):
        try:
            r = _handle(ctx, m)
        except Denied as exc:
            if not batch:
                return JSONResponse(exc.reply, status_code=403)
            r = exc.reply
        if r is not None:
            replies.append(r)
    headers = {}
    if any(isinstance(m, dict) and m.get("method") == "initialize" for m in (body if batch else [body])):
        headers["Mcp-Session-Id"] = mcp_session or uuid.uuid4().hex
    if not replies:
        return Response(status_code=202, headers=headers)
    return JSONResponse(replies if batch else replies[0], headers=headers)


@router.get("/mcp")
def mcp_get():
    return Response(status_code=405, headers={"Allow": "POST"})


@router.get("/mcp/tools")
def mcp_catalog(principal: Principal = Depends(get_principal)):
    """Danh mục tool: tên, nhóm, scope cần có (để cấp key và cấu hình toolFilter)."""
    return {"server": SERVER_INFO, "count": len(company_mcp.TOOLS),
            "tools": [{"name": t.name, "group": t.group, "scope": t.scope, "writes": t.writes,
                       "description": t.description} for t in company_mcp.TOOLS.values()]}


# ------------------------------------------------------------------ D1.6 quản trị quyền

from pydantic import BaseModel  # noqa: E402

from app.core.authz import require_role  # noqa: E402


class ToolPermissionIn(BaseModel):
    tool: str
    level: str  # allowed | ask | off | inherit
    role: str | None = None
    member_id: int | None = None


@router.get("/mcp/permissions")
def tool_permissions_read(principal: Principal = Depends(require_role("member")),
                          db: Session = Depends(get_db)):
    return tool_permissions.matrix(db, principal.organization_id)


@router.put("/mcp/permissions")
def tool_permissions_write(payload: ToolPermissionIn,
                           principal: Principal = Depends(require_role("admin")),
                           db: Session = Depends(get_db)):
    if payload.tool not in company_mcp.TOOLS:
        raise HTTPException(404, f"Không có tool {payload.tool}")
    if payload.member_id is not None:
        m = db.get(Member, payload.member_id)
        if m is None or m.organization_id != principal.organization_id:
            raise HTTPException(404, "Không thấy thành viên")
    try:
        tool_permissions.set_level(db, principal.organization_id, payload.tool, payload.level,
                                   role=payload.role, member_id=payload.member_id,
                                   actor_member_id=principal.member_id)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    company_mcp.emit_event(db, organization_id=principal.organization_id,
                           event_type="mcp.permission.changed", source=company_mcp.SOURCE,
                           aggregate_type="tool", aggregate_id=payload.tool,
                           actor_member_id=principal.member_id,
                           payload=payload.model_dump())
    return tool_permissions.matrix(db, principal.organization_id)
