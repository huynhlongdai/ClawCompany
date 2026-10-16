"""M3i — họp & quyết định. Spec: docs/company-knowledge-library-and-gaps.md §C M3i.

* Cuộc họp: ``draft`` (sửa tự do) → gửi duyệt biên bản ``in_review`` → người duyệt (chủ toạ là người, không thì chủ công ty;
  người soạn không tự duyệt trừ khi chính là người duyệt) → ``approved``: KHOÁ sửa (409 ``minutes_locked``) và lưu thành hồ sơ
  ``meeting_minutes`` (record M3a, có hash) — Luật DN 2020 Đ11 k1 điểm d.
* Biên bản nháp từ ghi chú: ``draft_minutes`` dựng TẤT ĐỊNH từ chương trình + người dự + ghi chú + quyết định + việc sau họp (không
  gọi model). Agent thư ký soạn bằng model là bước sau, cần CometAPI.
* Việc sau họp: mỗi dòng → một task thật (dự án "Họp & quyết định") cho đúng người, có hạn, + thẻ Hộp việc ``meeting_action``.
* Quyết định (bảng ``decisions`` mở rộng): ai quyết, căn cứ thẩm quyền — hoặc loại việc trong ma trận (người quyết phải là người
  có quyền: không thì 409 ``decider_lacks_authority``) hoặc căn cứ ghi tay (điều lệ, nghị quyết…); hiệu lực từ/đến; thay thế
  quyết định cũ (cũ → ``superseded``); liên kết tài liệu / việc / hợp đồng; tài liệu liên kết nhận cờ "cũ" để chủ tài liệu cập nhật.
* Agent đọc qua MCP ``company_decision_log`` (tool_only — không vào AGENTS.md): chỉ quyết định ``decided`` đang hiệu lực, agent_visible."""
from __future__ import annotations

from datetime import date, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import Decision, KnowledgeDocument, Member, Task
from app.models.meetings import MEETING_KINDS, Meeting, MeetingAction


def _err(status, code, message, **extra):
    return HTTPException(status, {"error": code, "message": message, **extra})


def _company(db, org_id, company_id, *, write=False):
    from app.services.company_foundation import _company as c
    return c(db, org_id, company_id, write=write)


def _seat(principal, company_id):
    from app.services.doc_library import _seat as s
    return s(None, principal, company_id)


def _name(db, mid):
    m = db.get(Member, mid) if mid else None
    return m.name if m else None


def today_vn() -> date:
    return (datetime.utcnow() + timedelta(hours=7)).date()


def _dt(v):
    if v in (None, ""):
        return None
    try:
        return datetime.fromisoformat(str(v).replace("Z", ""))
    except ValueError:
        raise _err(422, "invalid_date", f"Ngày giờ không hợp lệ: {v}") from None


def _d(v):
    if v in (None, ""):
        return None
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        raise _err(422, "invalid_date", f"Ngày không hợp lệ: {v}") from None


def _event(db, company_id, org_id, kind, agg, aid, actor, payload):
    from app.services.company_event_bus import emit_event
    emit_event(db, organization_id=org_id, company_id=company_id, event_type=kind, source="meetings", aggregate_type=agg,
               aggregate_id=str(aid), actor_member_id=actor, payload=payload)


def _member_in(db, mid, company_id) -> Member:
    m = db.get(Member, int(mid))
    if m is None or m.company_id != company_id:
        raise _err(404, "not_found", "Thành viên không thuộc công ty này")
    return m


# ------------------------------------------------------------------ biểu diễn

def public_action(db, a: MeetingAction) -> dict:
    t = db.get(Task, a.task_id) if a.task_id else None
    return {"id": a.id, "title": a.title, "assignee": _name(db, a.assignee_member_id), "assignee_member_id": a.assignee_member_id,
            "due_date": a.due_date.isoformat() if a.due_date else None, "task_id": a.task_id,
            "task_status": t.status if t else None, "decision_id": a.decision_id}


def public_decision(db, d: Decision) -> dict:
    today = today_vn()
    live = d.status == "decided" and (d.effective_from is None or d.effective_from <= today) and (d.effective_to is None or d.effective_to > today)
    return {"id": d.id, "number": d.number, "title": d.title, "body": d.body or d.recommendation or "", "status": d.status,
            "in_effect": live, "meeting_id": d.meeting_id, "decided_by": _name(db, d.decided_by_member_id),
            "decided_by_member_id": d.decided_by_member_id, "decided_at": d.decided_at.isoformat() if d.decided_at else None,
            "authority_basis": d.authority_basis or "", "authority_rule_id": d.authority_rule_id,
            "effective_from": d.effective_from.isoformat() if d.effective_from else None,
            "effective_to": d.effective_to.isoformat() if d.effective_to else None, "supersedes_id": d.supersedes_id,
            "superseded_by": (lambda x: x.id if x else None)(db.query(Decision).filter(Decision.supersedes_id == d.id).first()),
            "linked": d.linked or {}, "agent_visible": d.agent_visible is not False, "impact": d.impact}


def public_meeting(db, m: Meeting, *, detail=False) -> dict:
    out = {"id": m.id, "company_id": m.company_id, "kind": m.kind, "title": m.title, "held_at": m.held_at.isoformat(),
           "location": m.location, "chair": _name(db, m.chair_member_id), "chair_member_id": m.chair_member_id,
           "secretary": _name(db, m.secretary_member_id), "secretary_member_id": m.secretary_member_id,
           "attendees": [{"id": i, "name": _name(db, i)} for i in (m.attendee_ids or [])], "guests": m.guests,
           "status": m.status, "locked": m.status == "approved", "approver": _name(db, m.approver_member_id),
           "approver_member_id": m.approver_member_id, "approved_by": _name(db, m.approved_by_member_id),
           "approved_at": m.approved_at.isoformat() if m.approved_at else None, "rhythm_report_id": m.rhythm_report_id,
           "minutes_document": None, "n_actions": db.query(MeetingAction.id).filter(MeetingAction.meeting_id == m.id).count(),
           "n_decisions": db.query(Decision.id).filter(Decision.meeting_id == m.id).count()}
    doc = db.get(KnowledgeDocument, m.minutes_document_id) if m.minutes_document_id else None
    if doc is not None:
        out["minutes_document"] = {"id": doc.id, "doc_code": doc.doc_code, "status": doc.status, "content_hash": doc.content_hash}
    if detail:
        out.update(agenda=m.agenda, notes=m.notes, minutes=m.minutes,
                   actions=[public_action(db, a) for a in db.query(MeetingAction).filter(MeetingAction.meeting_id == m.id).order_by(MeetingAction.id)],
                   decisions=[public_decision(db, d) for d in db.query(Decision).filter(Decision.meeting_id == m.id).order_by(Decision.id)])
        if m.rhythm_report_id:
            from app.models.company_ops import RhythmReport
            r = db.get(RhythmReport, m.rhythm_report_id)
            out["rhythm_report"] = {"id": r.id, "kind": r.kind, "period_key": r.period_key, "title": r.title} if r else None
    return out


def listing(db, org_id, company_id) -> dict:
    co = _company(db, org_id, company_id)
    ms = db.query(Meeting).filter(Meeting.company_id == co.id).order_by(Meeting.held_at.desc()).limit(200).all()
    ds = db.query(Decision).filter(Decision.company_id == co.id, Decision.status.in_(("decided", "superseded", "revoked"))) \
        .order_by(Decision.id.desc()).limit(300).all()
    from app.models.company_ops import RhythmReport
    reports = [{"id": r.id, "kind": r.kind, "period_key": r.period_key, "title": r.title}
               for r in db.query(RhythmReport).filter(RhythmReport.company_id == co.id).order_by(RhythmReport.id.desc()).limit(20)]
    from app.services import authority
    open_actions = [a for a in db.query(MeetingAction).filter(MeetingAction.company_id == co.id).all()
                    if not a.task_id or (db.get(Task, a.task_id) and db.get(Task, a.task_id).status != "done")]
    return {"company_id": co.id, "meetings": [public_meeting(db, m) for m in ms], "decisions": [public_decision(db, d) for d in ds],
            "kinds": list(MEETING_KINDS), "rhythm_reports": reports, "action_types": list(authority.ACTION_TYPES),
            "members": [{"id": x.id, "name": x.name, "type": x.member_type} for x in
                        db.query(Member).filter(Member.company_id == co.id, Member.status != "archived").order_by(Member.name)],
            "counts": {"meetings": len(ms), "decisions_in_effect": sum(1 for d in ds if public_decision(db, d)["in_effect"]),
                       "open_actions": len(open_actions), "pending_minutes": sum(1 for m in ms if m.status == "in_review")}}


# ------------------------------------------------------------------ cuộc họp

def _meeting(db, org_id, mid, *, write=False) -> Meeting:
    m = db.get(Meeting, mid)
    if m is None or m.organization_id != org_id:
        raise _err(404, "not_found", "Không thấy cuộc họp")
    from app.core import company_scope
    company_scope.check(m.company_id, min_role="manager" if write else None)
    return m


def _apply(db, m: Meeting, data: dict) -> None:
    for k, lim in (("title", 220), ("location", 200), ("guests", 2000), ("agenda", 8000), ("notes", 20000), ("minutes", 40000)):
        if data.get(k) is not None:
            setattr(m, k, str(data[k])[:lim])
    if data.get("kind") is not None:
        if data["kind"] not in MEETING_KINDS:
            raise _err(422, "invalid_kind", "Loại cuộc họp không hợp lệ", allowed=list(MEETING_KINDS))
        m.kind = data["kind"]
    if data.get("held_at") is not None:
        m.held_at = _dt(data["held_at"]) or m.held_at
    for k in ("chair_member_id", "secretary_member_id"):
        if k in data:
            setattr(m, k, _member_in(db, data[k], m.company_id).id if data[k] else None)
    if data.get("attendee_ids") is not None:
        m.attendee_ids = sorted({_member_in(db, i, m.company_id).id for i in data["attendee_ids"]}) or None
    if "rhythm_report_id" in data:
        rid = data["rhythm_report_id"]
        if rid:
            from app.models.company_ops import RhythmReport
            r = db.get(RhythmReport, int(rid))
            if r is None or r.company_id != m.company_id:
                raise _err(404, "not_found", "Không thấy bản giao ban / báo cáo tuần trong công ty này")
        m.rhythm_report_id = int(rid) if rid else None
    if not (m.title or "").strip():
        raise _err(422, "title_required", "Thiếu tên cuộc họp")
    m.updated_at = datetime.utcnow()


def create(db, org_id, principal, data):
    co = _company(db, org_id, data.get("company_id"), write=True)
    from app.core import company_scope
    company_scope.check(co.id, min_role="manager")
    seat = _seat(principal, co.id)
    m = Meeting(organization_id=org_id, company_id=co.id, title="", held_at=datetime.utcnow(), status="draft",
                created_by_member_id=seat, chair_member_id=seat)
    _apply(db, m, data)
    db.add(m); db.flush()
    _event(db, co.id, org_id, "meeting.created", "meeting", m.id, seat, {"kind": m.kind})
    db.commit(); db.refresh(m)
    return public_meeting(db, m, detail=True)


def update(db, org_id, principal, mid, data):
    m = _meeting(db, org_id, mid, write=True)
    if m.status == "approved":
        raise _err(409, "minutes_locked", "Biên bản đã duyệt — khoá sửa (lập biên bản bổ sung nếu cần)")
    if m.status == "in_review" and any(k in data for k in ("minutes", "notes", "agenda", "attendee_ids")):
        raise _err(409, "minutes_in_review", "Biên bản đang chờ duyệt — rút về nháp rồi sửa")
    _apply(db, m, {k: v for k, v in data.items() if k != "company_id"})
    db.add(m); db.commit(); db.refresh(m)
    return public_meeting(db, m, detail=True)


def get(db, org_id, mid):
    return public_meeting(db, _meeting(db, org_id, mid), detail=True)


KIND_VI = {"members_council": "Họp Hội đồng thành viên", "shareholders": "Đại hội đồng cổ đông", "board": "Họp Hội đồng quản trị",
           "standup": "Giao ban", "weekly": "Họp tuần", "other": "Cuộc họp"}


def draft_minutes(db, org_id, principal, mid):
    """Biên bản nháp TẤT ĐỊNH từ dữ liệu cuộc họp (không model). Ghi đè ô biên bản khi còn nháp."""
    m = _meeting(db, org_id, mid, write=True)
    if m.status != "draft":
        raise _err(409, "minutes_locked" if m.status == "approved" else "minutes_in_review", "Chỉ soạn lại khi biên bản còn nháp")
    from app.models import Company
    co = db.get(Company, m.company_id)
    t = m.held_at + timedelta(hours=7)
    lines = [f"# BIÊN BẢN — {KIND_VI.get(m.kind, 'Cuộc họp').upper()}", f"**{co.name if co else ''}** — {m.title}", "",
             f"- Thời gian: {t:%H:%M ngày %d/%m/%Y} (giờ Việt Nam)", f"- Địa điểm: {m.location or '—'}",
             f"- Chủ toạ: {_name(db, m.chair_member_id) or '—'}" + (f" · Thư ký: {_name(db, m.secretary_member_id)}" if m.secretary_member_id else ""),
             f"- Thành phần: {', '.join(filter(None, (_name(db, i) for i in (m.attendee_ids or [])))) or '—'}"
             + (f"; khách mời: {m.guests}" if m.guests else ""), ""]
    if m.agenda.strip():
        lines += ["## Chương trình", m.agenda.strip(), ""]
    if m.notes.strip():
        lines += ["## Diễn biến (từ ghi chú)", m.notes.strip(), ""]
    ds = db.query(Decision).filter(Decision.meeting_id == m.id).order_by(Decision.id).all()
    if ds:
        lines += ["## Quyết định"] + [f"{i}. {(d.number + ' — ') if d.number else ''}{d.title}: {d.body or ''} "
                                      f"(người quyết: {_name(db, d.decided_by_member_id) or '—'}; căn cứ: {d.authority_basis or '—'}; "
                                      f"hiệu lực từ {d.effective_from:%d/%m/%Y})" if d.effective_from else f"{i}. {d.title}"
                                      for i, d in enumerate(ds, 1)] + [""]
    acts = db.query(MeetingAction).filter(MeetingAction.meeting_id == m.id).order_by(MeetingAction.id).all()
    if acts:
        lines += ["## Việc sau họp"] + [f"- {a.title} — {_name(db, a.assignee_member_id) or '—'}"
                                         + (f", hạn {a.due_date:%d/%m/%Y}" if a.due_date else "") for a in acts] + [""]
    lines += ["Biên bản được lập lúc kết thúc cuộc họp và được các thành viên dự họp thông qua.", "",
              "_Bản nháp dựng tự động từ dữ liệu cuộc họp — người duyệt kiểm tra trước khi ký._"]
    m.minutes = "\n".join(lines)
    db.add(m); db.commit(); db.refresh(m)
    return public_meeting(db, m, detail=True)


def submit_minutes(db, org_id, principal, mid):
    m = _meeting(db, org_id, mid, write=True)
    if m.status != "draft":
        raise _err(409, "not_draft", "Biên bản không ở trạng thái nháp")
    if len((m.minutes or "").strip()) < 40:
        raise _err(422, "minutes_empty", "Biên bản trống — soạn từ ghi chú hoặc viết trước khi gửi duyệt")
    from app.services import authority
    chair = db.get(Member, m.chair_member_id) if m.chair_member_id else None
    m.approver_member_id = chair.id if chair is not None and chair.member_type == "human" else authority.owner_member(db, org_id, m.company_id)
    m.status = "in_review"
    seat = _seat(principal, m.company_id)
    from app.services import inbox
    inbox.notify(db, organization_id=org_id, recipients=[m.approver_member_id], kind="meeting_action", company_id=m.company_id,
                 title=f"Duyệt biên bản: {m.title} ({(m.held_at + timedelta(hours=7)):%d/%m/%Y})", related_type="meeting",
                 related_id=str(m.id), commit=False)
    _event(db, m.company_id, org_id, "meeting.minutes_submitted", "meeting", m.id, seat, {"approver_member_id": m.approver_member_id})
    db.add(m); db.commit(); db.refresh(m)
    return public_meeting(db, m, detail=True)


def decide_minutes(db, org_id, principal, mid, decision: str, note: str = ""):
    m = _meeting(db, org_id, mid)
    if m.status != "in_review":
        raise _err(409, "not_in_review", "Biên bản không chờ duyệt")
    me = set(getattr(principal, "member_ids", []) or [])
    if m.approver_member_id not in me and getattr(principal, "role", "") != "owner":
        raise _err(403, "not_the_approver", "Không phải người duyệt biên bản", approver_member_id=m.approver_member_id)
    seat = m.approver_member_id if m.approver_member_id in me else _seat(principal, m.company_id)
    if decision == "rejected":
        if len((note or "").strip()) < 3:
            raise _err(422, "reason_required", "Ghi lý do trả lại")
        m.status = "draft"
        _event(db, m.company_id, org_id, "meeting.minutes_returned", "meeting", m.id, seat, {"note": note[:300]})
        db.add(m); db.commit()
        return public_meeting(db, m, detail=True)
    if decision != "approved":
        raise _err(422, "invalid_decision", "decision: approved | rejected")
    from app.services import doc_library
    doc = doc_library.create(db, org_id, principal, {"company_id": m.company_id, "doc_type": "meeting_minutes", "doc_class": "record",
                                                     "title": f"Biên bản: {m.title} {(m.held_at + timedelta(hours=7)):%d/%m/%Y}"[:220],
                                                     "content": m.minutes})
    m.minutes_document_id = doc.get("id") if isinstance(doc, dict) else getattr(doc, "id", None)
    m.status, m.approved_by_member_id, m.approved_at = "approved", seat, datetime.utcnow()
    _event(db, m.company_id, org_id, "meeting.minutes_approved", "meeting", m.id, seat, {"document_id": m.minutes_document_id})
    db.add(m); db.commit(); db.refresh(m)
    return public_meeting(db, m, detail=True)


def _project(db, company_id):
    from app.models import Project
    pr = db.query(Project).filter(Project.company_id == company_id, Project.name == "Họp & quyết định").first()
    if pr is None:
        pr = Project(company_id=company_id, name="Họp & quyết định", status="active", description="Việc sau họp (P1 M3i)")
        db.add(pr); db.commit(); db.refresh(pr)
    return pr


def add_actions(db, org_id, principal, mid, items: list[dict]):
    """Mỗi việc sau họp → MỘT task đúng người (+ hạn) + thẻ Hộp việc. Biên bản đã duyệt vẫn thêm được việc (việc không sửa biên bản)."""
    m = _meeting(db, org_id, mid, write=True)
    if not items:
        raise _err(422, "items_required", "Cần ít nhất một việc")
    from app.services import inbox
    from app.services import workspace_ops as ops
    seat = _seat(principal, m.company_id)
    out = []
    for it in items[:30]:
        title = str(it.get("title") or "").strip()[:200]
        if not title:
            raise _err(422, "title_required", "Việc thiếu tên")
        who = _member_in(db, it["assignee_member_id"], m.company_id).id if it.get("assignee_member_id") else None
        if who is None:
            raise _err(422, "assignee_required", "Việc sau họp phải có người nhận")
        due = _d(it.get("due_date"))
        did = it.get("decision_id")
        if did:
            dd = db.get(Decision, int(did))
            if dd is None or dd.company_id != m.company_id:
                raise _err(404, "not_found", "Không thấy quyết định")
        t = ops.create_task(db, _project(db, m.company_id), org_id, title=title,
                            description=f"Việc sau họp **{m.title}** ({(m.held_at + timedelta(hours=7)):%d/%m/%Y}).",
                            assignee_member_id=who, priority="medium", actor_member_id=seat)
        if due:
            t.due_at = datetime.combine(due, datetime.min.time()) + timedelta(hours=10)
            db.add(t)
        a = MeetingAction(organization_id=org_id, company_id=m.company_id, meeting_id=m.id, title=title, assignee_member_id=who,
                          due_date=due, task_id=t.id, decision_id=int(did) if did else None)
        db.add(a); db.flush()
        inbox.notify(db, organization_id=org_id, recipients=[who], kind="meeting_action", company_id=m.company_id, task_id=t.id,
                     title=f"Việc sau họp: {title}"[:220], related_type="meeting", related_id=str(m.id), commit=False)
        out.append(a)
    _event(db, m.company_id, org_id, "meeting.actions_created", "meeting", m.id, seat, {"n": len(out)})
    db.commit()
    return {"meeting_id": m.id, "actions": [public_action(db, a) for a in out]}


# ------------------------------------------------------------------ quyết định

def _next_number(db, company_id) -> str:
    y = today_vn().year
    n = db.query(Decision.id).filter(Decision.company_id == company_id, Decision.number.like(f"QĐ-{y}-%")).count() + 1
    return f"QĐ-{y}-{n:03d}"


def record_decision(db, org_id, principal, data):
    co = _company(db, org_id, data.get("company_id"), write=True)
    from app.core import company_scope
    company_scope.check(co.id, min_role="manager")
    seat = _seat(principal, co.id)
    title = str(data.get("title") or "").strip()[:220]
    body = str(data.get("body") or "").strip()[:8000]
    if not title or len(body) < 5:
        raise _err(422, "decision_text_required", "Cần tên và nội dung quyết định")
    mid = data.get("meeting_id")
    m = _meeting(db, org_id, int(mid), write=True) if mid else None
    if m is not None and m.company_id != co.id:
        raise _err(404, "not_found", "Cuộc họp thuộc công ty khác")
    decider = _member_in(db, data.get("decided_by_member_id") or seat, co.id) if (data.get("decided_by_member_id") or seat) else None
    if decider is None or decider.member_type != "human":
        raise _err(422, "decider_must_be_human", "Người quyết định phải là người (agent không ra quyết định)")
    basis, rule_id = str(data.get("authority_basis") or "").strip()[:2000], None
    at = data.get("action_type")
    if at:
        from app.services import authority
        authority.ensure_action_defaults(db, org_id, co.id, authority.normalize_action(at) or at)
        d = authority.decide(db, decider, at, risk=data.get("risk"), company_id=co.id)
        if d is None:
            raise _err(422, "no_rule", "Ma trận chưa có luật cho loại việc này — ghi căn cứ bằng tay")
        owner = authority.owner_member(db, org_id, co.id)
        if d.requires_approval and decider.id != owner:
            raise _err(409, "decider_lacks_authority", "Người quyết không có thẩm quyền theo ma trận cho loại việc này",
                       needs=d.approver_name, rule=d.label)
        basis, rule_id = (f"Ma trận thẩm quyền: {d.label}" + (f" — {basis}" if basis else ""))[:2000], d.rule_id
    if len(basis) < 5:
        raise _err(422, "basis_required", "Ghi căn cứ thẩm quyền (điều lệ / nghị quyết / ma trận)")
    eff_from = _d(data.get("effective_from")) or today_vn()
    eff_to = _d(data.get("effective_to"))
    if eff_to and eff_to <= eff_from:
        raise _err(422, "end_before_start", "Hiệu lực đến phải sau hiệu lực từ")
    old = None
    if data.get("supersedes_id"):
        old = db.get(Decision, int(data["supersedes_id"]))
        if old is None or old.company_id != co.id:
            raise _err(404, "not_found", "Không thấy quyết định bị thay thế")
        if old.status != "decided":
            raise _err(409, "not_in_effect", "Quyết định cũ không còn hiệu lực")
    linked = {}
    for k, model in (("doc_ids", KnowledgeDocument), ("task_ids", Task)):
        ids = [int(x) for x in (data.get("linked") or {}).get(k, []) or []]
        for i in ids:
            o = db.get(model, i)
            cid = getattr(o, "company_id", None) if model is KnowledgeDocument else None
            if model is Task and o is not None:
                from app.models import Project
                pr = db.get(Project, o.project_id) if o.project_id else None
                cid = pr.company_id if pr else None
            if o is None or cid != co.id:
                raise _err(404, "not_found", f"{k}: {i} không thuộc công ty này")
        if ids:
            linked[k] = ids
    cids = [int(x) for x in (data.get("linked") or {}).get("contract_ids", []) or []]
    if cids:
        from app.models.contracts import BizContract
        for i in cids:
            o = db.get(BizContract, i)
            if o is None or o.company_id != co.id:
                raise _err(404, "not_found", f"contract_ids: {i} không thuộc công ty này")
        linked["contract_ids"] = cids
    d = Decision(organization_id=org_id, company_id=co.id, title=title, context=str(data.get("context") or "")[:4000],
                 recommendation="", owner_member_id=decider.id, status="decided", impact=str(data.get("impact") or "medium")[:32],
                 number=str(data.get("number") or "").strip()[:48] or _next_number(db, co.id), meeting_id=m.id if m else None,
                 body=body, decided_by_member_id=decider.id, decided_at=datetime.utcnow(), authority_basis=basis,
                 authority_rule_id=rule_id, effective_from=eff_from, effective_to=eff_to, supersedes_id=old.id if old else None,
                 linked=linked or None, agent_visible=bool(data.get("agent_visible", True)))
    db.add(d); db.flush()
    if old is not None:
        old.status = "superseded"
        if old.effective_to is None or old.effective_to > eff_from:
            old.effective_to = eff_from
        db.add(old)
    _event(db, co.id, org_id, "decision.recorded", "decision", d.id, seat, {"number": d.number, "supersedes_id": d.supersedes_id})
    db.commit(); db.refresh(d)
    # tài liệu liên kết → cờ "cũ" để chủ tài liệu cập nhật theo quyết định
    flagged = 0
    from app.services import doc_library
    for i in linked.get("doc_ids", []):
        doc = db.get(KnowledgeDocument, i)
        try:
            doc_library.flag(db, member=decider, doc=doc, reason="outdated",
                             note=f"Quyết định {d.number} ({d.title}) có hiệu lực từ {eff_from:%d/%m/%Y} — cần cập nhật theo quyết định")
            flagged += 1
        except Exception:  # noqa: BLE001 — cờ không được làm hỏng việc ghi quyết định
            db.rollback()
    return {**public_decision(db, d), "docs_flagged": flagged}


def revoke_decision(db, org_id, principal, did, note=""):
    d = db.get(Decision, did)
    if d is None or d.organization_id != org_id:
        raise _err(404, "not_found", "Không thấy quyết định")
    from app.core import company_scope
    company_scope.check(d.company_id, min_role="manager")
    if d.status != "decided":
        raise _err(409, "not_in_effect", "Quyết định không còn hiệu lực")
    if len((note or "").strip()) < 5:
        raise _err(422, "reason_required", "Ghi lý do / căn cứ huỷ")
    d.status, d.effective_to = "revoked", today_vn()
    _event(db, d.company_id, org_id, "decision.revoked", "decision", d.id, _seat(principal, d.company_id), {"note": note[:300]})
    db.add(d); db.commit()
    return public_decision(db, d)


def agent_log(db, company_id: int | None, org_id: int, *, query: str = "", limit: int = 10, include_history: bool = False) -> dict:
    from sqlalchemy import or_
    q = db.query(Decision).filter(Decision.organization_id == org_id)
    # như bản cũ: quyết định cấp tổ chức (company_id NULL) vẫn thấy; công ty khác thì không
    q = q.filter(or_(Decision.company_id.is_(None), Decision.company_id == company_id)) if company_id else q.filter(Decision.company_id.is_(None))
    q = q.filter(or_(Decision.agent_visible.is_(None), Decision.agent_visible.is_(True)))
    if not include_history:
        # dòng sổ quyết định mới (có số): chỉ "decided"; dòng cũ trước M3i (number NULL) giữ hành vi cũ (trả kèm status)
        q = q.filter(or_(Decision.status == "decided", Decision.number.is_(None)))
    if query:
        q = q.filter(or_(Decision.title.ilike(f"%{query}%"), Decision.body.ilike(f"%{query}%"), Decision.context.ilike(f"%{query}%"),
                         Decision.number.ilike(f"%{query}%")))
    today = today_vn()
    out = []
    for d in q.order_by(Decision.id.desc()).limit(max(1, min(limit, 30))):
        if d.status == "decided" and not include_history and d.effective_from and d.effective_from > today:
            continue
        out.append({"id": d.id, "number": d.number, "title": d.title, "decision": d.body or d.recommendation or "",
                    "status": d.status, "decided_by": _name(db, d.decided_by_member_id),
                    "authority_basis": d.authority_basis or "", "effective_from": d.effective_from.isoformat() if d.effective_from else None,
                    "effective_to": d.effective_to.isoformat() if d.effective_to else None, "supersedes_id": d.supersedes_id,
                    "impact": d.impact, "cite": f"[QĐ:{d.number or d.id}]"})
    return {"decisions": out, "rule": "Chỉ quyết định đang hiệu lực (mới nhất trước). Quyết định bị thay thế/huỷ không áp dụng."}
