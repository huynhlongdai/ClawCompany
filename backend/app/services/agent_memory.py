"""Phase B việc 7 — xem/sửa/quên bộ nhớ, và bộ nhớ chung theo phạm vi.

Hai tầng, hai chủ sở hữu:

* **Ký ức riêng của ghế** nằm trong ``MEMORY.md`` trên gateway OpenClaw (agent tự
  đọc mỗi phiên, memory search index file này). ClawCompany không giữ bản sao
  riêng: đọc file, tách thành từng mục (mỗi gạch đầu dòng cấp 1 là một mục), sửa
  hoặc quên một mục rồi ghi lại cả file với ``expectedHash`` — agent ghi xen giữa
  thì trả 409 thay vì đè mất. Gateway 2026.9.8 chỉ cho đọc/ghi file gốc của
  workspace (``memory/YYYY-MM-DD.md`` trả "unsupported file"), nên nhật ký ngày
  chưa xem được ở đây.
* **Bộ nhớ chung** (bảng ``organization_memories``) do ClawCompany sở hữu: phạm
  vi tổ chức / công ty / phòng ban / dự án / riêng một ghế. Agent đọc qua tool
  MCP ``company_memory_search``, chỉ thấy phần thuộc phạm vi của mình.

"Quên" là xoá thật: không giữ nội dung trong nhật ký, chỉ ghi dấu vân tay
(sha256) để biết có một mục đã bị quên, ai quên và lúc nào.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models import Agent, Department, Member, OrganizationMemory, Project, Task

MEMORY_FILE = "MEMORY.md"
MAX_ENTRY = 2000
KINDS = ("fact", "decision", "policy", "principle", "glossary", "lesson", "outcome", "preference")
KIND_VI = {"fact": "Sự thật", "decision": "Quyết định", "policy": "Chính sách", "glossary": "Thuật ngữ",
           "lesson": "Bài học", "preference": "Sở thích/thói quen",
           "principle": "Nguyên tắc", "outcome": "Kết quả"}
SCOPES = ("org", "company", "department", "project", "agent")
SCOPE_VI = {"org": "Toàn tổ chức", "company": "Công ty", "department": "Phòng ban", "project": "Dự án",
            "agent": "Riêng một ghế"}
_DATE = re.compile(r"^(\d{4}-\d{2}-\d{2}):\s*")


def _audit(db: Session, principal, org_id: int, action: str, obj_type: str, obj_id: str, payload: dict) -> None:
    from app.services.audit import log_event
    log_event(db, org_id, action, obj_type, obj_id, actor_member_id=getattr(principal, "member_id", None),
              actor_name=f"user:{getattr(principal, 'user_id', '')}", payload=payload)


def _fp(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ------------------------------------------------------------------ ký ức riêng (MEMORY.md)

def parse(content: str) -> tuple[list[str], list[dict]]:
    """(phần đầu không phải mục, các mục). Mục = dòng ``- ``/``* `` cấp 1 + các dòng thụt vào sau nó."""
    head: list[str] = []
    entries: list[dict] = []
    for line in (content or "").splitlines():
        if re.match(r"^[-*] ", line):
            entries.append({"lines": [line]})
        elif entries and (line.startswith((" ", "\t")) and line.strip()):
            entries[-1]["lines"].append(line)
        elif not entries:
            head.append(line)
        else:
            entries[-1].setdefault("after", []).append(line)   # dòng trống/tiêu đề giữa các mục
    out = []
    seen: dict[str, int] = {}
    for e in entries:
        raw = "\n".join(e["lines"])
        text = re.sub(r"^[-*] ", "", raw, count=1)
        base = _fp(raw)[:12]
        seen[base] = seen.get(base, 0) + 1
        eid = base if seen[base] == 1 else f"{base}-{seen[base]}"
        m = _DATE.match(text)
        out.append({"id": eid, "raw": raw, "text": text, "date": m.group(1) if m else None,
                    "body": _DATE.sub("", text, count=1), "after": e.get("after", [])})
    return head, out


def render(head: list[str], entries: list[dict]) -> str:
    lines = list(head)
    for e in entries:
        lines.append(e["raw"])
        lines.extend(e.get("after", []))
    return "\n".join(lines).rstrip("\n") + "\n"


def _entry_raw(text: str, date: str | None) -> str:
    text = text.strip()
    if not text:
        raise HTTPException(422, "Nội dung ký ức không được trống")
    if len(text) > MAX_ENTRY:
        raise HTTPException(422, f"Một mục ký ức tối đa {MAX_ENTRY} ký tự")
    first, *rest = text.splitlines()
    first = f"- {date}: {first.strip()}" if date else f"- {first.strip()}"
    return "\n".join([first] + [f"  {r.strip()}" for r in rest if r.strip()])


async def _load(db: Session, org_id: int, runtime: Any, agent_id: int):
    from app.services import agent_hr
    agent, member = agent_hr.seat(db, org_id, agent_id)
    if not agent_hr._has_rpc(runtime) or agent.lifecycle == "runtime_missing":
        raise HTTPException(409, "Agent chưa có trên gateway — chưa đọc được ký ức")
    f = await agent_hr._get_file(runtime, agent.runtime_agent_id, MEMORY_FILE)
    return agent, member, f


def _public(agent: Agent, f: dict, entries: list[dict]) -> dict:
    return {"agent_id": agent.id, "file": MEMORY_FILE, "hash": f["hash"], "missing": f["missing"],
            "chars": len(f["content"]),
            "entries": [{k: e[k] for k in ("id", "text", "date", "body")} for e in entries]}


async def personal(db: Session, org_id: int, runtime: Any, agent_id: int) -> dict:
    agent, _, f = await _load(db, org_id, runtime, agent_id)
    _, entries = parse(f["content"])
    return _public(agent, f, entries)


async def change_personal(db: Session, principal, org_id: int, runtime: Any, agent_id: int, *,
                          op: str, entry_id: str | None = None, text: str = "",
                          expected_hash: str | None = None) -> dict:
    """``op``: ``add`` | ``edit`` | ``forget``. ``expected_hash`` = hash file lúc người dùng xem."""
    from app.services import agent_hr
    agent, member, f = await _load(db, org_id, runtime, agent_id)
    if agent.lifecycle == "retired":
        raise HTTPException(409, "Nhân sự đã nghỉ việc — không sửa ký ức được")
    if expected_hash and f["hash"] and expected_hash != f["hash"]:
        raise HTTPException(409, "Ký ức vừa thay đổi (agent hoặc người khác vừa ghi) — tải lại rồi thử lại")
    head, entries = parse(f["content"])
    if not head and not entries:
        head = ["# MEMORY.md — Ký ức đã hợp nhất", ""]
    today = datetime.utcnow().date().isoformat()
    detail: dict[str, Any] = {"op": op}
    if op == "add":
        raw = _entry_raw(text, today)
        entries.append({"raw": raw, "after": []})
        detail["fingerprint"] = _fp(raw)
    else:
        idx = next((i for i, e in enumerate(entries) if e["id"] == entry_id), None)
        if idx is None:
            raise HTTPException(404, "Không thấy mục ký ức này (có thể vừa bị sửa) — tải lại")
        old = entries[idx]
        detail["fingerprint"] = _fp(old["raw"])
        if op == "edit":
            entries[idx] = {**old, "raw": _entry_raw(text, old["date"])}
        elif op == "forget":
            after = old.get("after", [])
            entries.pop(idx)
            if after and idx > 0:   # giữ tiêu đề/dòng trống đứng sau mục bị xoá
                entries[idx - 1]["after"] = entries[idx - 1].get("after", []) + after
            elif after and idx == 0:
                head += after
        else:
            raise HTTPException(422, "op phải là add, edit hoặc forget")
    content = render(head, entries)
    try:
        new_hash = await agent_hr._set_file(runtime, agent.runtime_agent_id, MEMORY_FILE, content,
                                            expected_hash=f["hash"] or None)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(409, f"Gateway từ chối ghi ký ức: {exc}") from exc
    agent_hr.put_snapshot(db, agent.id, MEMORY_FILE, content, user_id=principal.user_id, hash_=new_hash)
    _audit(db, principal, org_id, f"agent.memory.{op}", "agent", str(agent.id), detail)
    _, now = parse(content)
    return _public(agent, {"hash": new_hash, "missing": False, "content": content}, now)


# ------------------------------------------------------------------ bộ nhớ chung theo phạm vi

def scope_of(m: OrganizationMemory) -> tuple[str, int | None]:
    if m.agent_id:
        return "agent", m.agent_id
    if m.project_id:
        return "project", m.project_id
    if m.department_id:
        return "department", m.department_id
    if m.company_id:
        return "company", m.company_id
    return "org", None


def _scope_name(db: Session, scope: str, sid: int | None) -> str:
    if scope == "org" or sid is None:
        return SCOPE_VI["org"]
    if scope == "agent":
        a = db.get(Agent, sid)
        mem = db.get(Member, a.member_id) if a else None
        return mem.name if mem else f"Ghế #{sid}"
    model = {"company": __import__("app.models", fromlist=["Company"]).Company,
             "department": Department, "project": Project}[scope]
    row = db.get(model, sid)
    return getattr(row, "name", None) or f"#{sid}"


def item(db: Session, m: OrganizationMemory) -> dict:
    scope, sid = scope_of(m)
    try:
        tags = json.loads(m.tags_json or "[]")
    except Exception:  # noqa: BLE001
        tags = []
    return {"id": m.id, "scope": scope, "scope_id": sid, "scope_label": SCOPE_VI[scope],
            "scope_name": _scope_name(db, scope, sid), "kind": m.memory_type,
            "kind_label": KIND_VI.get(m.memory_type, m.memory_type), "content": m.content,
            "importance": m.importance, "source_type": m.source_type, "tags": tags,
            "created_at": m.created_at.isoformat() if m.created_at else None,
            "updated_at": m.updated_at.isoformat() if m.updated_at else None}


def _check_scope(db: Session, org_id: int, scope: str, sid: int | None) -> dict:
    """Trả các cột phạm vi đã kiểm tra thuộc đúng tổ chức."""
    from app.models import Company
    cols = {"company_id": None, "department_id": None, "project_id": None, "agent_id": None}
    if scope not in SCOPES:
        raise HTTPException(422, f"Phạm vi phải là một trong: {', '.join(SCOPES)}")
    if scope == "org":
        return cols
    if not sid:
        raise HTTPException(422, "Thiếu scope_id")
    if scope == "company":
        row = db.get(Company, sid); ok = row and row.organization_id == org_id
        cols["company_id"] = sid
    elif scope == "department":
        row = db.get(Department, sid); co = db.get(Company, row.company_id) if row else None
        ok = co and co.organization_id == org_id
        cols.update(department_id=sid, company_id=row.company_id if row else None)
    elif scope == "project":
        row = db.get(Project, sid); co = db.get(Company, row.company_id) if row else None
        ok = co and co.organization_id == org_id
        cols.update(project_id=sid, company_id=row.company_id if row else None)
    else:
        row = db.get(Agent, sid); mem = db.get(Member, row.member_id) if row else None
        ok = mem and mem.organization_id == org_id
        cols.update(agent_id=sid, company_id=mem.company_id if mem else None)
    if not ok:
        raise HTTPException(404, "Không thấy phạm vi này trong tổ chức")
    return cols


def _clean(content: str, kind: str, importance: int) -> tuple[str, str, int]:
    content = (content or "").strip()
    if not content:
        raise HTTPException(422, "Nội dung không được trống")
    if len(content) > MAX_ENTRY:
        raise HTTPException(422, f"Tối đa {MAX_ENTRY} ký tự")
    if kind not in KINDS:
        raise HTTPException(422, f"Loại phải là một trong: {', '.join(KINDS)}")
    return content, kind, max(1, min(5, int(importance or 3)))


def list_shared(db: Session, org_id: int, *, scope: str | None = None, scope_id: int | None = None,
                q: str = "", limit: int = 200) -> list[dict]:
    rows = (db.query(OrganizationMemory)
            .filter(OrganizationMemory.organization_id == org_id, OrganizationMemory.status == "active")
            .order_by(OrganizationMemory.importance.desc(), OrganizationMemory.id.desc()).all())
    out = []
    tokens = [t.lower() for t in q.split() if len(t) > 1][:8]
    for m in rows:
        s, sid = scope_of(m)
        if scope and (s != scope or (scope_id and sid != scope_id)):
            continue
        if tokens and not all(t in (m.content or "").lower() for t in tokens):
            continue
        out.append(item(db, m))
        if len(out) >= limit:
            break
    return out


def create_shared(db: Session, principal, org_id: int, data: dict) -> dict:
    cols = _check_scope(db, org_id, data.get("scope") or "org", data.get("scope_id"))
    content, kind, imp = _clean(data.get("content"), data.get("kind") or "fact", data.get("importance") or 3)
    m = OrganizationMemory(organization_id=org_id, **cols, memory_type=kind, content=content,
                           source_type="manual", source_id=f"user:{principal.user_id}", importance=imp,
                           tags_json=json.dumps(data.get("tags") or [], ensure_ascii=False), status="active")
    db.add(m); db.commit(); db.refresh(m)
    _audit(db, principal, org_id, "memory.shared.created", "memory", str(m.id), {"scope": scope_of(m)[0], "kind": kind})
    return item(db, m)


def _get(db: Session, org_id: int, mid: int) -> OrganizationMemory:
    m = db.get(OrganizationMemory, mid)
    if m is None or m.organization_id != org_id or m.status != "active":
        raise HTTPException(404, "Không thấy mục bộ nhớ")
    return m


def update_shared(db: Session, principal, org_id: int, mid: int, data: dict) -> dict:
    m = _get(db, org_id, mid)
    if "scope" in data and data["scope"]:
        for k, v in _check_scope(db, org_id, data["scope"], data.get("scope_id")).items():
            setattr(m, k, v)
    content, kind, imp = _clean(data.get("content", m.content), data.get("kind") or m.memory_type,
                                data.get("importance") or m.importance)
    m.content, m.memory_type, m.importance = content, kind, imp
    db.add(m); db.commit(); db.refresh(m)
    _audit(db, principal, org_id, "memory.shared.updated", "memory", str(m.id), {"scope": scope_of(m)[0]})
    return item(db, m)


def forget_shared(db: Session, principal, org_id: int, mid: int) -> dict:
    m = _get(db, org_id, mid)
    fp = _fp(m.content or "")
    scope = scope_of(m)[0]
    db.delete(m); db.commit()
    _audit(db, principal, org_id, "memory.shared.forgotten", "memory", str(mid), {"scope": scope, "fingerprint": fp})
    return {"id": mid, "forgotten": True}


def visible_for(db: Session, member: Member, agent: Agent | None) -> list[OrganizationMemory]:
    """Bộ nhớ chung một ghế được thấy: toàn tổ chức, công ty mình, phòng mình,
    dự án mình đang có việc, và mục ghi riêng cho ghế mình."""
    projects = {pid for (pid,) in db.query(Task.project_id).filter(
        Task.assignee_member_id == member.id).distinct().all() if pid}
    conds = [
        (OrganizationMemory.company_id.is_(None)) & (OrganizationMemory.department_id.is_(None))
        & (OrganizationMemory.project_id.is_(None)) & (OrganizationMemory.agent_id.is_(None)),
    ]
    if member.company_id:
        conds.append((OrganizationMemory.company_id == member.company_id)
                     & OrganizationMemory.department_id.is_(None) & OrganizationMemory.project_id.is_(None)
                     & OrganizationMemory.agent_id.is_(None))
    if member.department_id:
        conds.append((OrganizationMemory.department_id == member.department_id)
                     & OrganizationMemory.project_id.is_(None) & OrganizationMemory.agent_id.is_(None))
    if projects:
        conds.append(OrganizationMemory.project_id.in_(projects) & OrganizationMemory.agent_id.is_(None))
    if agent is not None:
        conds.append(OrganizationMemory.agent_id == agent.id)
    return (db.query(OrganizationMemory)
            .filter(OrganizationMemory.organization_id == member.organization_id,
                    OrganizationMemory.status == "active", or_(*conds))
            .order_by(OrganizationMemory.importance.desc(), OrganizationMemory.id.desc()).all())


def options(db: Session, org_id: int) -> dict:
    from app.models import Company
    cos = db.query(Company).filter(Company.organization_id == org_id).all()
    co_ids = [c.id for c in cos]
    deps = db.query(Department).filter(Department.company_id.in_(co_ids)).all() if co_ids else []
    projs = db.query(Project).filter(Project.company_id.in_(co_ids)).all() if co_ids else []
    seats = (db.query(Agent, Member).join(Member, Member.id == Agent.member_id)
             .filter(Member.organization_id == org_id).all())
    return {"kinds": [{"key": k, "label": KIND_VI[k]} for k in KINDS],
            "scopes": [{"key": k, "label": SCOPE_VI[k]} for k in SCOPES],
            "companies": [{"id": c.id, "name": c.name} for c in cos],
            "departments": [{"id": d.id, "name": d.name} for d in deps],
            "projects": [{"id": p.id, "name": p.name} for p in projs],
            "agents": [{"id": a.id, "name": m.name} for a, m in seats]}
