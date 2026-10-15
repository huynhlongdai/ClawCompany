"""M5b việc 8 — bài học có kiểm soát: đề xuất → Hộp việc duyệt → MEMORY.md.

Agent không tự ghi bài học vào ký ức dài hạn. Mọi bài học đi qua một yêu cầu
duyệt (``policy_key = lesson:a<agent_id>:<sha>``) để người quản lý đọc rồi quyết:

* Nguồn ``review``: reviewer bấm "Sửa"/từ chối kèm góp ý → góp ý đó thành bài học.
* Nguồn ``self``: agent tự đề xuất qua MCP ``company_lesson_propose``.
* Nguồn ``extract``: người quản lý bấm "Rút bài học" → agent đọc nhật ký các việc
  gần đây (kết quả, lỗi, góp ý) trong một phiên riêng và đề xuất tối đa 3 bài học.

Duyệt → thêm một mục ``[Bài học] …`` vào MEMORY.md qua ``agent_memory`` (cùng cơ
chế khoá hash như sửa tay). Từ chối → không ghi gì; cùng nội dung sẽ không được
đề xuất lại (khoá trùng theo sha của nội dung đã chuẩn hoá).
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models import Agent, Approval, Member, Task

SOURCES_VI = {"review": "Góp ý của người duyệt", "self": "Agent tự đề xuất", "extract": "Rút từ nhật ký làm việc"}
MAX_LESSON = 600
PREFIX = "[Bài học]"


class LessonError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def key_for(agent_id: int, text: str) -> str:
    return f"lesson:a{agent_id}:{hashlib.sha256(_norm(text).encode()).hexdigest()[:16]}"


def agent_of(a: Approval) -> int | None:
    m = re.match(r"lesson:a(\d+):", a.policy_key or "")
    return int(m.group(1)) if m else None


def evidence(a: Approval) -> dict:
    try:
        ev = json.loads(a.evidence or "{}")
        return ev if isinstance(ev, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def propose(db: Session, *, agent: Agent, member: Member, text: str, source: str,
            task_id: int | None = None, reason: str = "", requester_member_id: int | None = None,
            commit: bool = True) -> dict:
    """Tạo yêu cầu duyệt bài học. Trùng nội dung (kể cả đã bị từ chối) → không tạo lại."""
    text = re.sub(r"\s+", " ", (text or "").strip())
    if text.startswith(PREFIX):
        text = text[len(PREFIX):].strip()
    if len(text) < 12:
        raise LessonError(422, "Bài học quá ngắn — viết rõ khi nào áp dụng và làm gì")
    if len(text) > MAX_LESSON:
        raise LessonError(422, f"Bài học tối đa {MAX_LESSON} ký tự — tách thành nhiều bài nếu cần")
    if source not in SOURCES_VI:
        raise LessonError(422, "Nguồn bài học không hợp lệ")
    key = key_for(agent.id, text)
    old = (db.query(Approval).filter(Approval.organization_id == member.organization_id,
                                     Approval.policy_key == key).order_by(Approval.id.desc()).first())
    if old is not None:
        return {"approval_id": old.id, "status": old.status, "duplicate": True}
    task = db.get(Task, task_id) if task_id else None
    ev = {"lesson": text, "source": source, "source_vi": SOURCES_VI[source], "reason": (reason or "")[:1500],
          "agent_id": agent.id, "agent_name": member.name, "task_id": task.id if task else None,
          "task_title": task.title if task else None}
    from app.services import inbox
    boss = (inbox.human_recipients(db, member.manager_id) or [None])[0] if member.manager_id else None
    a = Approval(organization_id=member.organization_id, company_id=member.company_id,
                 requester_member_id=requester_member_id or member.id, approver_member_id=boss,
                 action=f"Bài học cho {member.name}: {text}"[:220], risk="low", policy_key=key,
                 status="pending", evidence=json.dumps(ev, ensure_ascii=False),
                 payload={"lesson": text, "agent_id": agent.id, "source": source})
    db.add(a)
    if commit:
        db.commit(); db.refresh(a)
    else:
        db.flush()
    return {"approval_id": a.id, "status": a.status, "duplicate": False}


def _seat_by_member(db: Session, member_id: int | None) -> tuple[Agent, Member] | None:
    if not member_id:
        return None
    m = db.get(Member, member_id)
    ag = db.query(Agent).filter(Agent.member_id == member_id).first() if m else None
    return (ag, m) if ag and m and m.member_type == "agent" else None


def from_review(db: Session, task: Task, *, doer_member_id: int | None, reviewer_member_id: int | None,
                note: str) -> dict | None:
    """Reviewer yêu cầu sửa kèm góp ý → đề xuất bài học cho agent làm việc đó."""
    note = (note or "").strip()
    seat = _seat_by_member(db, doer_member_id)
    if seat is None or len(note) < 12:
        return None
    agent, member = seat
    text = f"Khi làm việc kiểu \"{task.title[:80]}\": {note[:480]}"
    try:
        return propose(db, agent=agent, member=member, text=text, source="review", task_id=task.id,
                       reason="Người duyệt yêu cầu sửa với góp ý này", requester_member_id=reviewer_member_id,
                       commit=False)
    except LessonError:
        return None


async def apply(db: Session, a: Approval, principal, runtime: Any, *, edited_text: str = "") -> dict:
    """Bài học đã duyệt → thêm vào MEMORY.md. Không ghi được thì giữ quyết định, báo lỗi rõ."""
    from fastapi import HTTPException
    from app.services import agent_memory
    agent_id = agent_of(a)
    text = re.sub(r"\s+", " ", (edited_text or "").strip()) or (a.payload or {}).get("lesson") or evidence(a).get("lesson") or ""
    if not agent_id or not text:
        return {"applied": False, "apply_error": "Không đọc được nội dung bài học"}
    try:
        out = await agent_memory.change_personal(db, principal, a.organization_id, runtime, agent_id,
                                                 op="add", text=f"{PREFIX} {text[:MAX_LESSON]}")
        a.payload = {**(a.payload or {}), "applied": True, "applied_text": text[:MAX_LESSON],
                     "applied_at": datetime.utcnow().isoformat(), "memory_hash": out.get("hash")}
        db.add(a); db.commit()
        return {"applied": True, "memory_hash": out.get("hash")}
    except HTTPException as exc:
        msg = str(exc.detail)
    except Exception as exc:  # noqa: BLE001
        msg = str(exc)[:300]
    a.payload = {**(a.payload or {}), "applied": False, "apply_error": msg}
    db.add(a); db.commit()
    return {"applied": False, "apply_error": msg}


# ------------------------------------------------------------------ rút bài học từ nhật ký

EXTRACT_PROMPT = """Em là {name}. Dưới đây là nhật ký các việc gần đây của em (kết quả, lỗi, góp ý của người duyệt).
Hãy rút ra TỐI ĐA 3 bài học thật sự hữu ích cho lần làm sau. Mỗi bài học:
- Một câu, cụ thể: khi nào áp dụng và cần làm gì (không chung chung kiểu "cẩn thận hơn").
- Dựa trên điều đã xảy ra trong nhật ký, không bịa thêm.
Nếu không có bài học nào đáng ghi, trả về mảng rỗng.
Chỉ trả lời bằng JSON đúng dạng: {{"lessons": [{{"lesson": "...", "reason": "dựa trên việc #..."}}]}}

NHẬT KÝ:
{journal}"""


def journal_digest(db: Session, member_id: int, *, limit_tasks: int = 8, max_chars: int = 9000) -> tuple[str, list[int]]:
    from app.models.v37 import TaskJournalEntry
    from app.models.work_graph import TaskRun
    tasks = (db.query(Task).filter(Task.assignee_member_id == member_id)
             .order_by(Task.updated_at.desc()).limit(limit_tasks).all())
    parts, ids = [], []
    for t in tasks:
        rows = (db.query(TaskJournalEntry).filter(TaskJournalEntry.task_id == t.id,
                                                   TaskJournalEntry.kind.in_(("result", "review", "blocker", "decision", "note")))
                .order_by(TaskJournalEntry.seq.desc()).limit(6).all())
        run = (db.query(TaskRun).filter(TaskRun.task_id == t.id, TaskRun.error_reason != "")
               .order_by(TaskRun.id.desc()).first())
        if not rows and run is None:
            continue
        ids.append(t.id)
        lines = [f"## Việc #{t.id}: {t.title} (trạng thái {t.status})"]
        for j in reversed(rows):
            lines.append(f"- [{j.kind}] {j.summary}" + (f" — {j.detail[:400]}" if j.detail and j.detail != j.summary else ""))
        if run is not None:
            lines.append(f"- [lỗi lần chạy] {run.error_reason[:300]}")
        parts.append("\n".join(lines))
    text = "\n\n".join(parts)
    return text[:max_chars], ids


def parse_lessons(reply: str) -> list[dict]:
    m = re.search(r"\{.*\}", reply or "", re.S)
    if not m:
        return []
    try:
        data = json.loads(m.group(0))
    except Exception:  # noqa: BLE001
        return []
    out = []
    for it in (data.get("lessons") or [])[:3] if isinstance(data, dict) else []:
        if isinstance(it, dict) and isinstance(it.get("lesson"), str):
            out.append({"lesson": it["lesson"].strip(), "reason": str(it.get("reason") or "")[:500]})
        elif isinstance(it, str):
            out.append({"lesson": it.strip(), "reason": ""})
    return [x for x in out if x["lesson"]]


async def extract(db: Session, org_id: int, runtime: Any, agent_id: int, *, timeout_seconds: int = 120) -> dict:
    from fastapi import HTTPException
    from app.services import agent_hr
    agent, member = agent_hr.seat(db, org_id, agent_id)
    if not agent_hr._has_rpc(runtime) or not hasattr(runtime, "chat_stream"):
        raise HTTPException(409, "Cần gateway OpenClaw thật để agent rút bài học")
    if agent.lifecycle in ("paused", "retired", "runtime_missing"):
        raise HTTPException(409, f"{member.name} đang ở trạng thái {agent.lifecycle}")
    journal, task_ids = journal_digest(db, member.id)
    if not journal:
        return {"agent_id": agent.id, "proposed": [], "message": f"{member.name} chưa có nhật ký việc nào để rút bài học"}
    key = f"agent:{agent.runtime_agent_id}:lessons-{int(time.time())}"
    text, err = "", ""
    try:
        async for ev in runtime.chat_stream(agent.runtime_agent_id, EXTRACT_PROMPT.format(name=member.name, journal=journal),
                                            session_key=key, timeout_seconds=timeout_seconds):
            if ev["kind"] == "delta":
                text = ev["text"]
            elif ev["kind"] == "final":
                text = ev.get("text") or text
                break
            elif ev["kind"] != "tool":
                err = str(ev.get("message") or "lỗi"); break
    except Exception as exc:  # noqa: BLE001
        err = f"gateway: {exc}"[:300]
    if err and not text:
        raise HTTPException(502, f"Agent không trả lời được: {err}")
    proposed = []
    for it in parse_lessons(text):
        try:
            r = propose(db, agent=agent, member=member, text=it["lesson"], source="extract",
                        reason=it["reason"] or f"Rút từ nhật ký các việc {', '.join('#' + str(i) for i in task_ids)}")
            proposed.append({**r, "lesson": it["lesson"]})
        except LessonError as exc:
            proposed.append({"lesson": it["lesson"], "error": exc.message})
    new = sum(1 for p in proposed if p.get("approval_id") and not p.get("duplicate"))
    msg = (f"{member.name} đề xuất {new} bài học mới — đang chờ duyệt trong Hộp việc" if new
           else f"{member.name} không có bài học mới nào đáng ghi")
    return {"agent_id": agent.id, "proposed": proposed, "reply": text[:2000], "message": msg}


def list_for(db: Session, org_id: int, agent_id: int, limit: int = 30) -> list[dict]:
    rows = (db.query(Approval).filter(Approval.organization_id == org_id,
                                      Approval.policy_key.like(f"lesson:a{agent_id}:%"))
            .order_by(Approval.id.desc()).limit(limit).all())
    out = []
    for a in rows:
        ev, pl = evidence(a), a.payload or {}
        out.append({"approval_id": a.id, "lesson": pl.get("applied_text") or pl.get("lesson") or ev.get("lesson"),
                    "source": ev.get("source"), "source_vi": ev.get("source_vi"), "status": a.status,
                    "applied": bool(pl.get("applied")), "apply_error": pl.get("apply_error"),
                    "task_id": ev.get("task_id"), "note": a.resolution_note or "",
                    "created_at": a.created_at.isoformat() if getattr(a, "created_at", None) else None})
    return out
