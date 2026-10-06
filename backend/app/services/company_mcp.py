"""D1.5 — các tool ``company_*`` mà agent gọi qua MCP (``POST /api/mcp``).

Trước gói này Nina trả lời "công ty có mấy dự án đang chạy" bằng kiến thức
chung, vì không có tool nào đọc dữ liệu ClawCompany (ARCHITECTURE_TREE L2.5).

Quy ước:
* Mỗi tool là một hàm ``(ctx, args) -> dict``. Đọc thì lọc theo tổ chức + công
  ty + phạm vi phòng ban của seat (``visible_task``). Ghi trạng thái task thì
  đi qua ``task_lifecycle`` — không tool nào tự gán ``task.status``.
* Lỗi trả về ``ToolError(code, message)``; tầng MCP biến nó thành
  ``isError: true`` để model đọc được lý do, thay vì một lỗi giao thức.
* Bảng L2.5 kê 22 tool trong 6 nhóm (tiêu đề ghi "24" nhưng bảng chỉ có 22);
  kế hoạch D1.5 thêm ``company_task_checkout`` → 23 tool.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models import (Agent, Approval, Company, Department, KnowledgeDocument, Member,
                        PermissionPolicy, Project, Task, TaskRun)
from app.models.extended import SOP, Decision, Report
from app.models.v10 import Artifact
from app.models.v36 import CalendarEvent, MetricSample
from app.models.v9 import BudgetEnvelope
from app.services import task_graph, task_journal
from app.services import task_lifecycle as lifecycle
from app.services.company_event_bus import emit_event

SOURCE = "company_mcp"
RUNNING_PROJECT_STATUSES = ("active", "running", "in_progress")
MAX_LIST = 50


class ToolError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class ToolContext:
    db: Session
    member: Member
    agent: Agent | None
    scopes: list[str] = field(default_factory=list)
    session_key: str = ""
    run: TaskRun | None = None

    @property
    def org(self) -> int:
        return self.member.organization_id


@dataclass
class Tool:
    name: str
    group: str
    description: str
    scope: str
    schema: dict
    handler: Callable[[ToolContext, dict], dict]
    writes: bool = False


TOOLS: dict[str, Tool] = {}


def tool(name: str, group: str, description: str, scope: str, props: dict | None = None,
         required: tuple[str, ...] = (), writes: bool = False):
    schema = {"type": "object", "properties": props or {}, "additionalProperties": False}
    if required:
        schema["required"] = list(required)

    def wrap(fn):
        TOOLS[name] = Tool(name, group, description, scope, schema, fn, writes)
        return fn
    return wrap


# ------------------------------------------------------------------ phạm vi

def _int(args: dict, key: str, *, required: bool = True, default: int | None = None) -> int | None:
    value = args.get(key, default)
    if value is None:
        if required:
            raise ToolError("invalid_argument", f"{key} là bắt buộc")
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ToolError("invalid_argument", f"{key} phải là số nguyên") from None


def _str(args: dict, key: str, *, required: bool = True, limit: int = 20000, default: str = "") -> str:
    value = str(args.get(key, default) or "").strip()
    if required and not value:
        raise ToolError("invalid_argument", f"{key} là bắt buộc")
    return value[:limit]


def _limit(args: dict, default: int = 20) -> int:
    return max(1, min(_int(args, "limit", required=False, default=default) or default, MAX_LIST))


def _company_project_ids(ctx: ToolContext) -> list[int]:
    q = select(Project.id).join(Company, Company.id == Project.company_id).where(
        Company.organization_id == ctx.org)
    if ctx.member.company_id:
        q = q.where(Project.company_id == ctx.member.company_id)
    return list(ctx.db.execute(q).scalars())


def _department_member_ids(ctx: ToolContext) -> set[int]:
    if not ctx.member.department_id:
        return set()
    return set(ctx.db.execute(select(Member.id).where(
        Member.department_id == ctx.member.department_id)).scalars())


def task_scope(ctx: ToolContext) -> str:
    """``company`` cho seat không thuộc phòng nào (Nina, CEO); ``department``
    cho seat có phòng. D1.6: phòng A không đọc được task phòng B."""
    return "department" if ctx.member.department_id else "company"


def visible_task(ctx: ToolContext, task: Task | None) -> bool:
    if task is None or task.project_id not in _company_project_ids(ctx):
        return False
    if task.assignee_member_id == ctx.member.id:
        return True
    # D3.1: việc phòng đang giữ — người trong phòng thấy được.
    if task.assignee_department_id and task.assignee_department_id == ctx.member.department_id:
        return True
    if task_scope(ctx) == "company":
        return True
    if task.assignee_member_id is None:
        return False
    return task.assignee_member_id in _department_member_ids(ctx)


def _task_or_404(ctx: ToolContext, task_id: int) -> Task:
    task = ctx.db.get(Task, task_id)
    if not visible_task(ctx, task):
        # Không phân biệt "không tồn tại" và "không được xem": cả hai là 404.
        raise ToolError("not_found", f"Không thấy task #{task_id}")
    return task


def _brief(t: Task) -> dict:
    return {"id": t.id, "title": t.title, "status": t.status, "priority": t.priority,
            "project_id": t.project_id, "assignee_member_id": t.assignee_member_id,
            "due_at": t.due_at.isoformat() if t.due_at else None}


def _member_brief(db: Session, m: Member | None) -> dict | None:
    if m is None:
        return None
    dept = db.get(Department, m.department_id) if m.department_id else None
    return {"id": m.id, "name": m.name, "role": m.role, "type": m.member_type,
            "status": m.status, "department": dept.name if dept else None,
            "manager_id": m.manager_id}


# ------------------------------------------------------------------ Bối cảnh

@tool("company_context", "context", "Tôi là ai trong công ty: seat, phòng ban, người quản lý, "
      "số việc đang mở của tôi và ngày hôm nay.", "company.context:read")
def _context(ctx: ToolContext, args: dict) -> dict:
    m, db = ctx.member, ctx.db
    company = db.get(Company, m.company_id) if m.company_id else None
    open_mine = db.execute(select(func.count(Task.id)).where(
        Task.assignee_member_id == m.id, Task.status.in_(lifecycle.OPEN_TASK_STATUSES))).scalar()
    return {
        "me": _member_brief(db, m),
        "runtime_agent_id": ctx.agent.runtime_agent_id if ctx.agent else None,
        "company": {"id": company.id, "name": company.name} if company else None,
        "manager": _member_brief(db, db.get(Member, m.manager_id) if m.manager_id else None),
        "task_scope": task_scope(ctx),
        "open_tasks_assigned_to_me": open_mine,
        "current_run_id": ctx.run.id if ctx.run else None,
        "today_utc": datetime.utcnow().date().isoformat(),
    }


@tool("company_org_lookup", "context", "Tra người trong công ty theo tên/vai trò, hoặc theo "
      "member_id / department_id.", "company.org:read",
      {"query": {"type": "string"}, "member_id": {"type": "integer"},
       "department_id": {"type": "integer"}, "limit": {"type": "integer"}})
def _org_lookup(ctx: ToolContext, args: dict) -> dict:
    q = select(Member).where(Member.organization_id == ctx.org)
    if ctx.member.company_id:
        q = q.where(Member.company_id == ctx.member.company_id)
    if args.get("member_id") is not None:
        q = q.where(Member.id == _int(args, "member_id"))
    if args.get("department_id") is not None:
        q = q.where(Member.department_id == _int(args, "department_id"))
    text = _str(args, "query", required=False, limit=120)
    if text:
        like = f"%{text}%"
        q = q.where(or_(Member.name.ilike(like), Member.role.ilike(like)))
    rows = ctx.db.execute(q.order_by(Member.id).limit(_limit(args))).scalars().all()
    return {"members": [_member_brief(ctx.db, m) for m in rows]}


@tool("company_calendar", "context", "Lịch của công ty trong N ngày tới (mặc định 7).",
      "company.calendar:read", {"days": {"type": "integer"}})
def _calendar(ctx: ToolContext, args: dict) -> dict:
    days = max(1, min(_int(args, "days", required=False, default=7) or 7, 90))
    now = datetime.utcnow()
    q = select(CalendarEvent).where(CalendarEvent.organization_id == ctx.org,
                                    CalendarEvent.starts_at >= now - timedelta(hours=12),
                                    CalendarEvent.starts_at <= now + timedelta(days=days))
    if ctx.member.company_id:
        q = q.where(or_(CalendarEvent.company_id.is_(None),
                        CalendarEvent.company_id == ctx.member.company_id))
    rows = ctx.db.execute(q.order_by(CalendarEvent.starts_at).limit(MAX_LIST)).scalars().all()
    return {"days": days, "events": [{"id": e.id, "title": e.title,
                                      "starts_at": e.starts_at.isoformat(),
                                      "ends_at": e.ends_at.isoformat() if e.ends_at else None,
                                      "location": e.location} for e in rows]}


# ------------------------------------------------------------------ Công việc

@tool("company_tasks_list", "work", "Danh sách việc. scope=mine (mặc định) chỉ việc của tôi; "
      "scope=team là mọi việc tôi được xem (phòng tôi, hoặc cả công ty nếu tôi không thuộc phòng).",
      "company.tasks:read",
      {"status": {"type": "string"}, "scope": {"type": "string", "enum": ["mine", "team"]},
       "limit": {"type": "integer"}})
def _tasks_list(ctx: ToolContext, args: dict) -> dict:
    scope = _str(args, "scope", required=False, default="mine")
    q = select(Task).where(Task.project_id.in_(_company_project_ids(ctx)))
    if scope == "mine":
        q = q.where(Task.assignee_member_id == ctx.member.id)
    elif task_scope(ctx) == "department":
        q = q.where(Task.assignee_member_id.in_(_department_member_ids(ctx) | {ctx.member.id}))
    status = _str(args, "status", required=False, limit=32)
    if status:
        q = q.where(Task.status == status)
    rows = ctx.db.execute(q.order_by(Task.id.desc()).limit(_limit(args))).scalars().all()
    return {"scope": scope, "tasks": [_brief(t) for t in rows]}


@tool("company_task_get", "work", "Chi tiết một việc: mô tả, tiêu chí nghiệm thu, chuỗi mục "
      "tiêu, việc đang chặn, 5 mục sổ ghi gần nhất.", "company.tasks:read",
      {"task_id": {"type": "integer"}}, ("task_id",))
def _task_get(ctx: ToolContext, args: dict) -> dict:
    task = _task_or_404(ctx, _int(args, "task_id"))
    entries = task_journal.read(ctx.db, task.id, limit=100)[-5:]
    return {**_brief(task), "description": task.description,
            "acceptance_criteria": task.acceptance_criteria or "",
            "goal_line": task_graph.goal_line(ctx.db, task),
            "open_blockers": [_brief(t) for t in task_graph.open_blockers(ctx.db, task.id)],
            "checked_out_by_run": task.checkout_run_id,
            "journal": [{"seq": e.seq, "kind": e.kind, "summary": e.summary,
                         "created_at": e.created_at.isoformat() if e.created_at else None}
                        for e in entries]}


@tool("company_task_status", "work", "Chuyển trạng thái việc của tôi theo đúng bảng chuyển "
      "(backlog→todo→in_progress→review→done…). Bắt buộc nêu lý do.", "company.tasks:write",
      {"task_id": {"type": "integer"}, "status": {"type": "string",
                                                  "enum": list(lifecycle.TASK_STATUSES)},
       "reason": {"type": "string"}}, ("task_id", "status", "reason"), writes=True)
def _task_status(ctx: ToolContext, args: dict) -> dict:
    task = _task_or_404(ctx, _int(args, "task_id"))
    if task.assignee_member_id != ctx.member.id:
        raise ToolError("forbidden", "Chỉ người nhận việc mới đổi được trạng thái")
    before = task.status
    try:
        lifecycle.transition(ctx.db, task, _str(args, "status", limit=32), via="mcp",
                             reason=_str(args, "reason", limit=500),
                             actor_member_id=ctx.member.id)
    except HTTPException as exc:
        detail = exc.detail.get("message") if isinstance(exc.detail, dict) else exc.detail
        raise ToolError("conflict" if exc.status_code == 409 else "invalid_argument",
                        str(detail)) from exc
    return {"task_id": task.id, "from": before, "to": task.status}


@tool("company_task_comment", "work", "Ghi một dòng vào sổ của việc (tiến độ, kết quả, vướng). "
      "Mỗi lượt làm việc phải kết thúc bằng một comment.", "company.tasks:write",
      {"task_id": {"type": "integer"}, "body": {"type": "string"},
       "kind": {"type": "string", "enum": ["note", "result", "blocker", "decision"]},
       "detail": {"type": "string"}}, ("task_id", "body"), writes=True)
def _task_comment(ctx: ToolContext, args: dict) -> dict:
    task = _task_or_404(ctx, _int(args, "task_id"))
    kind = _str(args, "kind", required=False, default="note", limit=16)
    if kind not in ("note", "result", "blocker", "decision"):
        raise ToolError("invalid_argument", "kind phải là note|result|blocker|decision")
    try:
        entry = task_journal.append(
            ctx.db, task, kind=kind, summary=_str(args, "body", limit=400),
            detail=_str(args, "detail", required=False), actor_member_id=ctx.member.id,
            runtime_run_id=ctx.run.runtime_run_id if ctx.run else "",
            runtime_session_key=ctx.session_key)
    except task_journal.JournalError as exc:
        raise ToolError("invalid_argument", str(exc)) from exc
    return {"task_id": task.id, "journal_seq": entry.seq}


@tool("company_task_assign", "work", "Trưởng phòng giao việc của phòng cho một người trong phòng "
      "(hoặc seat điều hành giao cho bất kỳ ai). Bắt buộc nêu lý do. Bỏ member_id để hệ thống "
      "chọn theo tải. Giao xong thì dừng lượt định tuyến.", "company.tasks:write",
      {"task_id": {"type": "integer"}, "member_id": {"type": "integer"}, "reason": {"type": "string"}},
      ("task_id", "reason"), writes=True)
def _task_assign(ctx: ToolContext, args: dict) -> dict:
    from app.services import routing
    task = _task_or_404(ctx, _int(args, "task_id"))
    try:
        return routing.assign(ctx.db, task, actor=ctx.member,
                              member_id=_int(args, "member_id", required=False),
                              reason=_str(args, "reason", limit=1000), run=ctx.run)
    except routing.RoutingError as exc:
        raise ToolError(exc.code, exc.message) from exc


@tool("company_plan_submit", "work", "Seat chiến lược gửi kế hoạch phân rã một mục tiêu vào hàng duyệt. "
      "tasks: [{key, title, description, acceptance_criteria, department_id | member_id, budget_usd, "
      "depends_on: [key], priority}]. Bị yêu cầu sửa thì sửa theo ghi chú trong sổ việc rồi gửi lại.",
      "company.tasks:write",
      {"goal_id": {"type": "integer"}, "summary": {"type": "string"},
       "tasks": {"type": "array", "items": {"type": "object"}}},
      ("goal_id", "summary", "tasks"), writes=True)
def _plan_submit(ctx: ToolContext, args: dict) -> dict:
    from app.services import strategy
    try:
        return strategy.submit(ctx.db, actor=ctx.member, goal_id=_int(args, "goal_id"),
                               summary=_str(args, "summary", limit=4000), tasks=args.get("tasks"),
                               run_task_id=ctx.run.task_id if ctx.run else None)
    except strategy.StrategyError as exc:
        raise ToolError(exc.code, exc.message) from exc


@tool("company_task_checkout", "work", "Nhận giữ một việc của tôi cho lượt chạy hiện tại trước "
      "khi bắt tay làm. Thua (đã có lượt khác giữ) thì dừng, không thử lại.",
      "company.tasks:write", {"task_id": {"type": "integer"}}, ("task_id",), writes=True)
def _task_checkout(ctx: ToolContext, args: dict) -> dict:
    task = _task_or_404(ctx, _int(args, "task_id"))
    if task.assignee_member_id != ctx.member.id:
        raise ToolError("forbidden", "Chỉ người nhận việc mới giữ được việc")
    waiting = task_graph.open_blockers(ctx.db, task.id)
    if waiting:
        raise ToolError("conflict", "Việc còn bị chặn bởi "
                        + ", ".join(f"#{t.id}" for t in waiting))
    run = ctx.run if ctx.run is not None and ctx.run.task_id == task.id else None
    if run is None:
        run = lifecycle.open_run(ctx.db, task, organization_id=ctx.org,
                                 member_id=ctx.member.id, trigger_kind="mcp_checkout")
    try:
        lifecycle.checkout(ctx.db, task, run.id, expected_statuses=("todo", "in_progress", "blocked"))
    except lifecycle.CheckoutConflict as exc:
        if run is not ctx.run:
            lifecycle.finish_run(ctx.db, run, "skipped",
                                 error_reason=f"checkout lost to run #{exc.holder}")
        raise ToolError("conflict", exc.detail["message"]) from exc
    return {"task_id": task.id, "run_id": run.id, "checked_out": True}


@tool("company_project_get", "work", "Không truyền project_id: danh sách dự án của công ty kèm "
      "số đếm theo trạng thái (running_count = active|running|in_progress). Có project_id: chi "
      "tiết dự án và số việc theo trạng thái.", "company.projects:read",
      {"project_id": {"type": "integer"}, "status": {"type": "string"}})
def _project_get(ctx: ToolContext, args: dict) -> dict:
    ids = _company_project_ids(ctx)
    if args.get("project_id") is None:
        q = select(Project).where(Project.id.in_(ids))
        status = _str(args, "status", required=False, limit=32)
        rows = ctx.db.execute(q.order_by(Project.id)).scalars().all()
        by_status: dict[str, int] = {}
        for p in rows:
            by_status[p.status] = by_status.get(p.status, 0) + 1
        shown = [p for p in rows if not status or p.status == status]
        return {"total": len(rows), "by_status": by_status,
                "running_count": sum(by_status.get(s, 0) for s in RUNNING_PROJECT_STATUSES),
                "running_statuses": list(RUNNING_PROJECT_STATUSES),
                "projects": [{"id": p.id, "name": p.name, "status": p.status,
                              "progress": p.progress,
                              "due_date": p.due_date.isoformat() if p.due_date else None}
                             for p in shown[:MAX_LIST]]}
    pid = _int(args, "project_id")
    if pid not in ids:
        raise ToolError("not_found", f"Không thấy dự án #{pid}")
    p = ctx.db.get(Project, pid)
    counts = dict(ctx.db.execute(select(Task.status, func.count(Task.id))
                                 .where(Task.project_id == pid).group_by(Task.status)).all())
    return {"id": p.id, "name": p.name, "status": p.status, "progress": p.progress,
            "description": p.description,
            "due_date": p.due_date.isoformat() if p.due_date else None,
            "owner": _member_brief(ctx.db, ctx.db.get(Member, p.owner_member_id)
                                   if p.owner_member_id else None),
            "tasks_by_status": counts}


# ------------------------------------------------------------------ Tri thức

def _doc_visible(ctx: ToolContext, doc: KnowledgeDocument | None) -> bool:
    if doc is None or doc.organization_id != ctx.org:
        return False
    if doc.company_id and ctx.member.company_id and doc.company_id != ctx.member.company_id:
        return False
    if doc.access_level == "org_public":
        return True
    return doc.department_id is None or doc.department_id == ctx.member.department_id


@tool("company_knowledge_search", "knowledge", "Tìm trong kho tri thức công ty.",
      "company.knowledge:read", {"query": {"type": "string"}, "limit": {"type": "integer"}},
      ("query",))
def _knowledge_search(ctx: ToolContext, args: dict) -> dict:
    from app.services.vector_search import search_vectors
    hits = search_vectors(ctx.db, ctx.org, _str(args, "query", limit=500),
                          company_id=ctx.member.company_id,
                          department_id=ctx.member.department_id, limit=_limit(args, 8))
    return {"hits": hits}


@tool("company_knowledge_get", "knowledge", "Đọc nguyên văn một tài liệu tri thức.",
      "company.knowledge:read", {"document_id": {"type": "integer"}}, ("document_id",))
def _knowledge_get(ctx: ToolContext, args: dict) -> dict:
    doc = ctx.db.get(KnowledgeDocument, _int(args, "document_id"))
    if not _doc_visible(ctx, doc):
        raise ToolError("not_found", "Không thấy tài liệu")
    return {"id": doc.id, "title": doc.title, "access_level": doc.access_level,
            "content": (doc.content or "")[:20000]}


@tool("company_sop_get", "knowledge", "Lấy SOP theo sop_id, hoặc tìm theo tên.",
      "company.knowledge:read", {"sop_id": {"type": "integer"}, "query": {"type": "string"}})
def _sop_get(ctx: ToolContext, args: dict) -> dict:
    q = select(SOP).where(SOP.organization_id == ctx.org,
                          or_(SOP.department_id.is_(None),
                              SOP.department_id == ctx.member.department_id))
    if args.get("sop_id") is not None:
        sop = ctx.db.execute(q.where(SOP.id == _int(args, "sop_id"))).scalar_one_or_none()
        if sop is None:
            raise ToolError("not_found", "Không thấy SOP")
        return {"id": sop.id, "title": sop.title, "version": sop.version, "status": sop.status,
                "content": (sop.content or "")[:20000]}
    text = _str(args, "query", required=False, limit=120)
    if text:
        q = q.where(SOP.title.ilike(f"%{text}%"))
    rows = ctx.db.execute(q.order_by(SOP.id).limit(MAX_LIST)).scalars().all()
    return {"sops": [{"id": s.id, "title": s.title, "version": s.version, "status": s.status}
                     for s in rows]}


@tool("company_decision_log", "knowledge", "Các quyết định đã ghi của công ty (mới nhất trước).",
      "company.knowledge:read", {"query": {"type": "string"}, "limit": {"type": "integer"}})
def _decision_log(ctx: ToolContext, args: dict) -> dict:
    q = select(Decision).where(Decision.organization_id == ctx.org)
    if ctx.member.company_id:
        q = q.where(or_(Decision.company_id.is_(None), Decision.company_id == ctx.member.company_id))
    text = _str(args, "query", required=False, limit=120)
    if text:
        q = q.where(or_(Decision.title.ilike(f"%{text}%"), Decision.context.ilike(f"%{text}%")))
    rows = ctx.db.execute(q.order_by(Decision.id.desc()).limit(_limit(args))).scalars().all()
    return {"decisions": [{"id": d.id, "title": d.title, "status": d.status,
                           "recommendation": d.recommendation, "impact": d.impact}
                          for d in rows]}


# ------------------------------------------------------------------ Phối hợp

def _same_company_member(ctx: ToolContext, member_id: int) -> Member:
    m = ctx.db.get(Member, member_id)
    if m is None or m.organization_id != ctx.org or (
            ctx.member.company_id and m.company_id and m.company_id != ctx.member.company_id):
        raise ToolError("not_found", f"Không thấy thành viên #{member_id}")
    return m


@tool("company_message_send", "collab", "Gửi tin cho một thành viên (người hoặc agent).",
      "company.messages:write",
      {"to_member_id": {"type": "integer"}, "content": {"type": "string"},
       "subject": {"type": "string"}, "task_id": {"type": "integer"}},
      ("to_member_id", "content"), writes=True)
def _message_send(ctx: ToolContext, args: dict) -> dict:
    from app.services.agent_messaging import send_message
    to = _same_company_member(ctx, _int(args, "to_member_id"))
    task_id = _int(args, "task_id", required=False)
    if task_id is not None:
        _task_or_404(ctx, task_id)
    item = send_message(ctx.db, organization_id=ctx.org, content=_str(args, "content"),
                        sender_member_id=ctx.member.id, recipient_member_id=to.id,
                        company_id=ctx.member.company_id,
                        subject=_str(args, "subject", required=False, limit=200),
                        task_id=task_id)
    return {"message_id": item.id, "to_member_id": to.id}


@tool("company_handoff_create", "collab", "Bàn giao một sản phẩm (artifact) cho người khác kèm "
      "hướng dẫn.", "company.artifacts:write",
      {"artifact_id": {"type": "integer"}, "to_member_id": {"type": "integer"},
       "instructions": {"type": "string"}, "purpose": {"type": "string"}},
      ("artifact_id", "to_member_id"), writes=True)
def _handoff_create(ctx: ToolContext, args: dict) -> dict:
    from app.services.artifacts import handoff_artifact
    art = ctx.db.get(Artifact, _int(args, "artifact_id"))
    if art is None or art.organization_id != ctx.org:
        raise ToolError("not_found", "Không thấy artifact")
    to = _same_company_member(ctx, _int(args, "to_member_id"))
    item = handoff_artifact(ctx.db, art, to_member_id=to.id, from_member_id=ctx.member.id,
                            purpose=_str(args, "purpose", required=False, default="continue_work",
                                         limit=80),
                            instructions=_str(args, "instructions", required=False))
    return {"handoff_id": item.id, "status": item.status}


@tool("company_artifact_create", "collab", "Nộp một sản phẩm dạng văn bản, gắn với việc.",
      "company.artifacts:write",
      {"name": {"type": "string"}, "content_text": {"type": "string"},
       "task_id": {"type": "integer"}, "artifact_type": {"type": "string"}},
      ("name", "content_text"), writes=True)
def _artifact_create(ctx: ToolContext, args: dict) -> dict:
    from app.services.artifacts import register_artifact
    task_id = _int(args, "task_id", required=False)
    task = _task_or_404(ctx, task_id) if task_id is not None else None
    art = register_artifact(ctx.db, organization_id=ctx.org, name=_str(args, "name", limit=200),
                            content_text=_str(args, "content_text", limit=200000),
                            company_id=ctx.member.company_id,
                            project_id=task.project_id if task else None,
                            task_id=task.id if task else None,
                            created_by_member_id=ctx.member.id,
                            created_by_agent_id=ctx.agent.id if ctx.agent else None,
                            runtime_run_id=ctx.run.runtime_run_id if ctx.run else "",
                            artifact_type=_str(args, "artifact_type", required=False,
                                               default="deliverable", limit=40))
    return {"artifact_id": art.id, "version": art.version}


@tool("company_artifact_get", "collab", "Đọc một artifact.", "company.artifacts:read",
      {"artifact_id": {"type": "integer"}}, ("artifact_id",))
def _artifact_get(ctx: ToolContext, args: dict) -> dict:
    art = ctx.db.get(Artifact, _int(args, "artifact_id"))
    if art is None or art.organization_id != ctx.org or (
            art.task_id and not visible_task(ctx, ctx.db.get(Task, art.task_id))):
        raise ToolError("not_found", "Không thấy artifact")
    return {"id": art.id, "name": art.name, "type": art.artifact_type, "task_id": art.task_id,
            "version": art.version, "content_text": (art.content_text or "")[:20000]}


# ------------------------------------------------------------------ Kiểm soát

@tool("company_approval_request", "control", "Xin phép trước khi làm một hành động rủi ro. "
      "Trả allow / deny / approval_required (kèm approval_id).", "company.approvals:write",
      {"action": {"type": "string"}, "evidence": {"type": "string"}}, ("action",), writes=True)
def _approval_request(ctx: ToolContext, args: dict) -> dict:
    from app.services.policy import authorize
    d = authorize(ctx.db, ctx.org, _str(args, "action", limit=120), actor_member_id=ctx.member.id,
                  fallback_role="member", company_id=ctx.member.company_id,
                  evidence=_str(args, "evidence", required=False, limit=4000))
    return {"decision": d.decision, "reason": d.reason, "policy_key": d.policy_key,
            "approval_id": d.approval_id}


@tool("company_policy_check", "control", "Hỏi trước (không tạo yêu cầu duyệt) một hành động có "
      "cần duyệt hay bị cấm không.", "company.policy:read",
      {"action": {"type": "string"}}, ("action",))
def _policy_check(ctx: ToolContext, args: dict) -> dict:
    action = _str(args, "action", limit=120)
    policy = ctx.db.execute(select(PermissionPolicy).where(
        PermissionPolicy.organization_id == ctx.org, PermissionPolicy.action == action,
        PermissionPolicy.enabled == True)).scalars().first()  # noqa: E712
    if policy is None:
        return {"action": action, "policy": None, "requires_approval": False,
                "note": "Không có policy riêng cho hành động này"}
    return {"action": action, "policy": policy.key, "minimum_role": policy.minimum_role,
            "requires_approval": bool(policy.requires_approval)}


@tool("company_budget_check", "control", "Ngân sách còn lại của công ty; truyền amount để hỏi "
      "có giữ chỗ được khoản đó không.", "company.budget:read", {"amount": {"type": "number"}})
def _budget_check(ctx: ToolContext, args: dict) -> dict:
    from app.services.budget import can_reserve, remaining
    q = select(BudgetEnvelope).where(BudgetEnvelope.organization_id == ctx.org)
    if ctx.member.company_id:
        q = q.where(or_(BudgetEnvelope.company_id.is_(None),
                        BudgetEnvelope.company_id == ctx.member.company_id))
    rows = ctx.db.execute(q.order_by(BudgetEnvelope.id)).scalars().all()
    amount = args.get("amount")
    out = []
    for b in rows:
        item = {"id": b.id, "name": b.name, "currency": b.currency, "limit": b.amount_limit,
                "reserved": b.amount_reserved, "spent": b.amount_spent,
                "remaining": remaining(b), "status": b.status}
        if amount is not None:
            ok, why = can_reserve(b, float(amount))
            item.update({"can_reserve": ok, "reason": why})
        out.append(item)
    return {"envelopes": out}


# ------------------------------------------------------------------ Báo cáo

@tool("company_metric_read", "report", "Đọc chuỗi số đo (metric_samples).", "company.metrics:read",
      {"metric_key": {"type": "string"}, "scope_type": {"type": "string"},
       "scope_id": {"type": "string"}, "limit": {"type": "integer"}}, ("metric_key",))
def _metric_read(ctx: ToolContext, args: dict) -> dict:
    q = select(MetricSample).where(MetricSample.organization_id == ctx.org,
                                   MetricSample.metric_key == _str(args, "metric_key", limit=120))
    if args.get("scope_type"):
        q = q.where(MetricSample.scope_type == _str(args, "scope_type", limit=40))
    if args.get("scope_id"):
        q = q.where(MetricSample.scope_id == _str(args, "scope_id", limit=80))
    rows = ctx.db.execute(q.order_by(MetricSample.recorded_at.desc())
                          .limit(_limit(args))).scalars().all()
    return {"samples": [{"period": s.period, "value": s.value, "unit": s.unit,
                         "scope_type": s.scope_type, "scope_id": s.scope_id, "source": s.source,
                         "recorded_at": s.recorded_at.isoformat() if s.recorded_at else None}
                        for s in rows]}


@tool("company_report_submit", "report", "Nộp một báo cáo (tiến độ, tuần, sự cố…).",
      "company.reports:write",
      {"title": {"type": "string"}, "content": {"type": "string"},
       "report_type": {"type": "string"}, "period": {"type": "string"}},
      ("title", "content"), writes=True)
def _report_submit(ctx: ToolContext, args: dict) -> dict:
    r = Report(organization_id=ctx.org, company_id=ctx.member.company_id,
               report_type=_str(args, "report_type", required=False, default="progress", limit=40),
               title=_str(args, "title", limit=200), period=_str(args, "period", required=False,
                                                                 limit=40),
               owner_member_id=ctx.member.id, content=_str(args, "content", limit=100000),
               audience="management", status="submitted")
    ctx.db.add(r); ctx.db.commit(); ctx.db.refresh(r)
    return {"report_id": r.id}


EVENT_NAME = re.compile(r"^[a-z][a-z0-9_.]{2,80}$")


@tool("company_event_emit", "report", "Phát một sự kiện nghiệp vụ. Tên luôn được đặt dưới "
      "tiền tố agent. để agent không giả được sự kiện của hệ thống.", "company.events:write",
      {"event_type": {"type": "string"}, "payload": {"type": "object"}}, ("event_type",),
      writes=True)
def _event_emit(ctx: ToolContext, args: dict) -> dict:
    name = _str(args, "event_type", limit=80)
    if not EVENT_NAME.match(name):
        raise ToolError("invalid_argument", "event_type chỉ gồm a-z, 0-9, _ và .")
    payload = args.get("payload") or {}
    if not isinstance(payload, dict) or len(json.dumps(payload, default=str)) > 8000:
        raise ToolError("invalid_argument", "payload phải là object ≤ 8000 ký tự")
    ev = emit_event(ctx.db, organization_id=ctx.org, event_type=f"agent.{name}", payload=payload,
                    company_id=ctx.member.company_id, source=SOURCE, aggregate_type="member",
                    aggregate_id=str(ctx.member.id), actor_member_id=ctx.member.id)
    return {"event_id": ev.id, "event_type": ev.event_type}


# ------------------------------------------------------------------ gọi tool

def call(ctx: ToolContext, name: str, args: dict | None) -> tuple[bool, dict]:
    """Chạy tool và ghi ``mcp.tool.called``. Trả (ok, kết quả hoặc lỗi)."""
    started = datetime.utcnow()
    spec = TOOLS.get(name)
    args = args or {}
    if spec is None:
        ok, result = False, {"error": "unknown_tool", "message": f"Không có tool {name}"}
    else:
        unknown = set(args) - set(spec.schema["properties"])
        try:
            if unknown:
                raise ToolError("invalid_argument", "Tham số lạ: " + ", ".join(sorted(unknown)))
            ok, result = True, spec.handler(ctx, args)
        except ToolError as exc:
            ctx.db.rollback()
            ok, result = False, {"error": exc.code, "message": exc.message}
    ms = int((datetime.utcnow() - started).total_seconds() * 1000)
    emit_event(ctx.db, organization_id=ctx.org, event_type="mcp.tool.called", source=SOURCE,
               company_id=ctx.member.company_id, aggregate_type="member",
               aggregate_id=str(ctx.member.id), actor_member_id=ctx.member.id,
               payload={"tool": name, "ok": ok, "error": None if ok else result.get("error"),
                        "ms": ms, "arg_keys": sorted(args), "session_key": ctx.session_key,
                        "run_id": ctx.run.id if ctx.run else None,
                        "writes": bool(spec and spec.writes)})
    return ok, result
