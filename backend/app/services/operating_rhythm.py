"""M2c D6 — Nhịp vận hành: giao ban sáng (24 giờ qua) và báo cáo tuần (7 ngày qua) cho từng phòng ban
và cả công ty, gửi vào Hộp việc của người phụ trách.

Số liệu lấy thẳng từ dữ liệu đang có: việc (xong / đang làm / bị chặn / trễ hạn / mới), quy trình D4
(lần chạy xong, chu trình TB, bước trễ), KPI D5 cần chú ý, phê duyệt đang chờ, chi phí lượt chạy (USD),
ngoại lệ (lượt chạy lỗi). ``summarize`` dựng bản tóm tắt **xác định** (không cần model). Khi bật
``agent_author`` và trưởng phòng (với cấp công ty: trưởng Ban điều hành) là seat agent trên gateway thật,
agent đó viết lại bản giao ban từ đúng số liệu ấy (phiên ``agent:<rid>:rhythm-<scope>-<kỳ>``); agent lỗi /
không có gateway → dùng bản xác định, ghi lý do. Bản tóm tắt xác định luôn được lưu kèm (``fallback``).

Không có động cơ lịch riêng: Celery beat ``rhythm.tick`` (300 s) xét giờ địa phương của từng công ty;
UNIQUE(công ty, phạm vi, loại, kỳ) nên beat chạy lại / nút "Gửi ngay" không sinh bản trùng.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Agent, Approval, Company, Department, Member, Project, Task
from app.models.company_ops import (KpiDefinition, ProcessInstance, ProcessStepRun, RhythmConfig,
                                    RhythmReport)
from app.models.extended import InboxItem

KINDS = ("standup", "weekly")
INBOX_KIND = {"standup": "standup", "weekly": "weekly_report"}
OPEN = ("backlog", "todo", "in_progress", "review", "blocked")
WINDOW_HOURS = 2      # beat chỉ gửi trong 2 giờ kể từ giờ hẹn (khởi động muộn không gửi bù lúc nửa đêm)


def _err(status: int, msg: str) -> HTTPException:
    return HTTPException(status, msg)


def _local(now: datetime, tz: str) -> datetime:
    return now.replace(tzinfo=ZoneInfo("UTC")).astimezone(ZoneInfo(tz))


def period_key(kind: str, now: datetime, tz: str) -> str:
    loc = _local(now, tz)
    if kind == "weekly":
        y, w, _ = loc.isocalendar()
        return f"{y}-W{w:02d}"
    return loc.strftime("%Y-%m-%d")


# ------------------------------------------------------------------ cấu hình

def config(db: Session, org_id: int, company_id: int, *, create: bool = False) -> RhythmConfig | None:
    c = db.query(RhythmConfig).filter(RhythmConfig.company_id == company_id).first()
    if c is None and create:
        c = RhythmConfig(organization_id=org_id, company_id=company_id)
        db.add(c); db.commit(); db.refresh(c)
    return c


def public_config(c: RhythmConfig | None) -> dict:
    if c is None:
        return {"enabled": False, "standup_enabled": False, "standup_hour": 8, "weekly_enabled": False, "weekly_dow": 4,
                "weekly_hour": 17, "timezone": "Asia/Ho_Chi_Minh", "per_department": True, "agent_author": True}
    return {"enabled": True, "standup_enabled": c.standup_enabled, "standup_hour": c.standup_hour,
            "weekly_enabled": c.weekly_enabled, "weekly_dow": c.weekly_dow, "weekly_hour": c.weekly_hour,
            "timezone": c.timezone, "per_department": c.per_department, "agent_author": c.agent_author}


def save_config(db: Session, org_id: int, company_id: int | None, data: dict) -> dict:
    """Kiểm hết rồi mới ghi: yêu cầu sai không được để lại cấu hình (bật giao ban) nửa vời."""
    from app.services.company_foundation import _company
    co = _company(db, org_id, company_id)
    clean: dict = {}
    for f, lo, hi, msg in (("standup_hour", 0, 23, "Giờ giao ban phải từ 0 tới 23."),
                           ("weekly_hour", 0, 23, "Giờ báo cáo tuần phải từ 0 tới 23."),
                           ("weekly_dow", 0, 6, "Ngày báo cáo tuần: 0 = thứ Hai … 6 = Chủ nhật.")):
        if data.get(f) is not None:
            if not (lo <= int(data[f]) <= hi):
                raise _err(422, msg)
            clean[f] = int(data[f])
    if data.get("timezone"):
        try:
            ZoneInfo(data["timezone"])
        except Exception:  # noqa: BLE001
            raise _err(422, "Múi giờ không hợp lệ — dùng tên IANA, ví dụ Asia/Ho_Chi_Minh.")
        clean["timezone"] = data["timezone"]
    for f in ("standup_enabled", "weekly_enabled", "per_department", "agent_author"):
        if data.get(f) is not None:
            clean[f] = bool(data[f])
    c = config(db, org_id, co.id, create=True)
    for f, v in clean.items():
        setattr(c, f, v)
    db.commit()
    return public_config(c)


# ------------------------------------------------------------------ số liệu

def _scope_members(db: Session, company_id: int, department_id: int | None) -> list[int]:
    q = db.query(Member).filter(Member.company_id == company_id, Member.status != "archived")
    if department_id:
        q = q.filter(Member.department_id == department_id)
    return [m.id for m in q.all()]


def collect(db: Session, company_id: int, department_id: int | None, kind: str, now: datetime) -> dict:
    from app.models.work_graph import TaskRun
    from app.services import kpi_cascade
    hours = 24 if kind == "standup" else 24 * 7
    since = now - timedelta(hours=hours)
    members = _scope_members(db, company_id, department_id)
    names = {m.id: m.name for m in db.query(Member).filter(Member.company_id == company_id).all()}
    base = db.query(Task).join(Project, Project.id == Task.project_id).filter(Project.company_id == company_id)
    if department_id:
        base = base.filter((Task.assignee_member_id.in_(members or [-1])) | (Task.assignee_department_id == department_id))
    done = base.filter(Task.status == "done", Task.updated_at >= since).order_by(Task.updated_at.desc()).all()
    doing = base.filter(Task.status.in_(("in_progress", "review"))).all()
    blocked = base.filter(Task.status == "blocked").all()
    overdue = base.filter(Task.status.in_(OPEN), Task.due_at.isnot(None), Task.due_at < now).all()
    created = base.filter(Task.created_at >= since).count()
    task_ids = [t.id for t in base.with_entities(Task.id).all()]
    runs = db.query(TaskRun).filter(TaskRun.task_id.in_(task_ids or [-1]), TaskRun.created_at >= since).all()
    failed = [r for r in runs if (r.error_reason or "").strip() or r.status in ("failed", "error")]
    cost = round(sum(r.cost_usd or 0 for r in runs), 4)
    # quy trình D4
    pq = db.query(ProcessInstance).filter(ProcessInstance.company_id == company_id)
    inst_done = pq.filter(ProcessInstance.status == "done", ProcessInstance.finished_at >= since).all()
    running = pq.filter(ProcessInstance.status == "running").all()
    late = []
    for i in running:
        for r in db.query(ProcessStepRun).filter(ProcessStepRun.instance_id == i.id, ProcessStepRun.status == "active").all():
            if (department_id is None or r.assignee_member_id in members) and r.expected_minutes and r.activated_at \
                    and (now - r.activated_at).total_seconds() > r.expected_minutes * 60:
                late.append({"instance": i.title, "step": r.name, "assignee": names.get(r.assignee_member_id),
                             "over_minutes": round((now - r.activated_at).total_seconds() / 60 - r.expected_minutes)})
    cyc = [i.cycle_seconds for i in inst_done if i.cycle_seconds is not None]
    # KPI D5 cần chú ý
    kq = db.query(KpiDefinition).filter(KpiDefinition.company_id == company_id, KpiDefinition.status == "active")
    if department_id:
        kq = kq.filter(KpiDefinition.department_id == department_id)
    else:
        kq = kq.filter(KpiDefinition.level.in_(("company", "department")))
    kpis = [kpi_cascade.evaluate(db, k, now) for k in kq.all()]
    watch = [k for k in kpis if k["health"] in ("off_track", "at_risk")]
    # phê duyệt
    req = members if department_id else _scope_members(db, company_id, None)
    pend = db.query(Approval).filter(Approval.requester_member_id.in_(req or [-1]), Approval.status == "pending").all()
    oldest = max(((now - a.created_at).total_seconds() / 3600 for a in pend if a.created_at), default=None)
    return {"window_hours": hours, "since": since.isoformat(), "members": len(members),
            "tasks": {"done": len(done), "done_titles": [t.title for t in done[:5]], "doing": len(doing),
                      "blocked": len(blocked), "blocked_titles": [t.title for t in blocked[:5]],
                      "overdue": len(overdue), "overdue_titles": [t.title for t in overdue[:5]], "created": created},
            "processes": {"done": len(inst_done), "running": len(running),
                          "avg_cycle_minutes": round(sum(cyc) / len(cyc) / 60, 1) if cyc else None, "late_steps": late[:5]},
            "kpis": {"total": len(kpis), "watch": [{"name": k["name"], "owner": k["owner"], "value": k["value"],
                                                     "target": k["target"], "unit": k["unit"], "progress": k["progress"],
                                                     "health": k["health"]} for k in watch[:6]]},
            "approvals": {"pending": len(pend), "oldest_hours": round(oldest, 1) if oldest is not None else None},
            "costs": {"usd": cost, "runs": len(runs)},
            "exceptions": {"failed_runs": len(failed)}}


def _list(items: list[str]) -> str:
    return "; ".join(f"“{x[:80]}”" for x in items)


def summarize(title: str, d: dict) -> str:
    t, p, k, a = d["tasks"], d["processes"], d["kpis"], d["approvals"]
    span = "24 giờ qua" if d["window_hours"] == 24 else "7 ngày qua"
    lines = [f"## {title}", "",
             f"**Đã xong ({span}):** {t['done']} việc" + (f" — {_list(t['done_titles'])}" if t["done_titles"] else ""),
             f"**Đang làm / chờ duyệt kết quả:** {t['doing']} việc · việc mới: {t['created']}"]
    if t["blocked"] or t["overdue"]:
        lines.append(f"**Bị chặn:** {t['blocked']}" + (f" ({_list(t['blocked_titles'])})" if t["blocked_titles"] else "")
                     + f" · **Trễ hạn:** {t['overdue']}" + (f" ({_list(t['overdue_titles'])})" if t["overdue_titles"] else ""))
    else:
        lines.append("**Bị chặn / trễ hạn:** không có")
    proc = f"**Quy trình:** {p['done']} lần chạy xong, {p['running']} đang chạy"
    if p["avg_cycle_minutes"] is not None:
        proc += f", chu trình TB {p['avg_cycle_minutes']} phút"
    lines.append(proc)
    for s in p["late_steps"]:
        lines.append(f"  - Bước trễ: {s['step']} ({s['instance']}) — {s['assignee'] or 'chưa giao'}, quá {s['over_minutes']} phút")
    if k["watch"]:
        lines.append(f"**KPI cần chú ý ({len(k['watch'])}/{k['total']}):**")
        for x in k["watch"]:
            val = "chưa có số" if x["value"] is None else f"{x['value']}{(' ' + x['unit']) if x['unit'] else ''}"
            lines.append(f"  - {x['name']} ({x['owner']}): {val} / mục tiêu {x['target']} → {x['progress']}%")
    else:
        lines.append(f"**KPI:** {k['total']} KPI, không có KPI chậm" if k["total"] else "**KPI:** chưa đặt KPI cho phạm vi này")
    lines.append(f"**Chờ duyệt:** {a['pending']}" + (f" (lâu nhất {a['oldest_hours']} giờ)" if a["oldest_hours"] else ""))
    lines.append(f"**Chi phí AI ({span}):** ${d['costs']['usd']:.2f} cho {d['costs']['runs']} lượt chạy")
    lines.append(f"**Ngoại lệ:** {d['exceptions']['failed_runs']} lượt chạy lỗi" if d["exceptions"]["failed_runs"] else "**Ngoại lệ:** không có")
    return "\n".join(lines)


# ------------------------------------------------------------------ người viết + người nhận

def author_seat(db: Session, company_id: int, department_id: int | None) -> tuple[Member | None, Agent | None]:
    from app.services.team_templates import EXEC
    dept = db.get(Department, department_id) if department_id else (
        db.query(Department).filter(Department.company_id == company_id, Department.name == EXEC).first())
    head = db.get(Member, dept.head_member_id) if dept and dept.head_member_id else None
    if head is None or head.member_type != "agent":
        return head, None
    ag = db.query(Agent).filter(Agent.member_id == head.id).first()
    if ag is None or ag.lifecycle in ("paused", "retired", "runtime_missing"):
        return head, None
    return head, ag


def recipients(db: Session, org_id: int, company_id: int, department_id: int | None) -> list[int]:
    from app.services import authority, inbox
    out: list[int] = []
    if department_id:
        dept = db.get(Department, department_id)
        if dept and dept.head_member_id:
            out += inbox.human_recipients(db, dept.head_member_id)
    owner = authority.owner_member(db, org_id, company_id)
    if owner and (not department_id or not out):
        out.append(owner)
    return list(dict.fromkeys(x for x in out if x))


async def _agent_text(runtime: Any, ag: Agent, head: Member, title: str, fallback: str, key: str) -> str:
    from app.services.courses import _ask
    prompt = (f"Bạn là {head.name}, phụ trách viết \"{title}\". Viết bản giao ban ngắn (tối đa 180 chữ, gạch đầu dòng) "
              "cho người quản lý từ ĐÚNG số liệu dưới đây: nêu 3 điều quan trọng nhất, việc cần người quyết, và rủi ro. "
              "Không bịa thêm số, không gọi công cụ, trả lời bằng tiếng Việt.\n\n" + fallback)
    return (await _ask(runtime, ag.runtime_agent_id, prompt, key, timeout=75)).strip()


# ------------------------------------------------------------------ sinh + gửi

def _title(db: Session, co: Company, department_id: int | None, kind: str, now: datetime, tz: str) -> str:
    loc = _local(now, tz)
    scope = db.get(Department, department_id).name if department_id else co.name
    if kind == "weekly":
        y, w, _ = loc.isocalendar()
        return f"Báo cáo tuần {w}/{y} — {scope}"
    return f"Giao ban sáng {loc:%d/%m} — {scope}"


def _prepare(db: Session, org_id: int, company_id: int, kind: str, department_id: int | None, now: datetime,
             runtime: Any, use_agent: bool | None) -> dict:
    """Bước 1 (đồng bộ): kỳ đã có bản → trả bản cũ; chưa có → số liệu + bản xác định + ai sẽ viết."""
    from app.services.company_foundation import _company
    if kind not in KINDS:
        raise _err(422, "Loại báo cáo phải là standup (giao ban ngày) hoặc weekly (báo cáo tuần).")
    co = _company(db, org_id, company_id)
    if department_id is not None:
        dept = db.get(Department, department_id)
        if dept is None or dept.company_id != co.id:
            raise _err(422, f"Phòng ban #{department_id} không thuộc công ty {co.name}.")
    cfg = config(db, org_id, co.id)
    tz = cfg.timezone if cfg else "Asia/Ho_Chi_Minh"
    scope_key = f"d{department_id}" if department_id else f"c{co.id}"
    pk = period_key(kind, now, tz)
    old = (db.query(RhythmReport).filter(RhythmReport.company_id == co.id, RhythmReport.scope_key == scope_key,
                                         RhythmReport.kind == kind, RhythmReport.period_key == pk).first())
    if old is not None:
        return {"existing": old}
    title = _title(db, co, department_id, kind, now, tz)
    data = collect(db, co.id, department_id, kind, now)
    ctx = {"existing": None, "co": co, "kind": kind, "department_id": department_id, "scope_key": scope_key, "pk": pk,
           "title": title, "data": data, "fallback": summarize(title, data), "note": "", "agent": None, "head": None}
    agent_on = (cfg.agent_author if cfg else True) if use_agent is None else use_agent
    head, ag = author_seat(db, co.id, department_id)
    if agent_on and ag is not None and runtime is not None and hasattr(runtime, "chat_stream"):
        ctx.update(agent=ag, head=head, rid=ag.runtime_agent_id, head_name=head.name)
    elif agent_on and head is not None and ag is None:
        ctx["note"] = (f"{head.name} là người (không phải agent) → bản tự động" if head.member_type != "agent"
                       else "Seat agent không sẵn sàng → bản tự động")
    elif agent_on and ag is not None:
        ctx["note"] = "Chưa nối gateway thật → bản tự động"
    return ctx


async def _write(ctx: dict, runtime: Any) -> None:
    """Bước 2 (bất đồng bộ, chạy song song giữa các phạm vi): agent trưởng phòng viết lại."""
    ctx["content"], ctx["author"] = ctx.get("fallback", ""), "system"
    if ctx.get("existing") is not None or ctx.get("agent") is None:
        return
    try:
        text = await _agent_text(runtime, ctx["agent"], ctx["head"], ctx["title"], ctx["fallback"],
                                 f"agent:{ctx['rid']}:rhythm-{ctx['scope_key']}-{ctx['kind']}-{ctx['pk']}")
        if text and not text.startswith("[lỗi"):
            ctx["content"], ctx["author"] = f"## {ctx['title']}\n\n{text}", f"agent:{ctx['rid']}"
            ctx["note"] = f"Viết bởi {ctx['head_name']} (agent) từ số liệu hệ thống"
        else:
            ctx["note"] = "Agent trả lời rỗng → dùng bản tự động"
    except Exception as exc:  # noqa: BLE001 — agent lỗi không được chặn giao ban
        ctx["note"] = f"Agent {ctx['head_name']} không viết được ({str(getattr(exc, 'detail', exc))[:200]}) → dùng bản tự động"


def _finalize(db: Session, org_id: int, ctx: dict) -> dict:
    """Bước 3: lưu (UNIQUE theo kỳ) + gửi Hộp việc."""
    if ctx.get("existing") is not None:
        return {**public_report(db, ctx["existing"]), "created": False}
    co, department_id, kind = ctx["co"], ctx["department_id"], ctx["kind"]
    to = recipients(db, org_id, co.id, department_id)
    rep = RhythmReport(organization_id=org_id, company_id=co.id, department_id=department_id, scope_key=ctx["scope_key"],
                       kind=kind, period_key=ctx["pk"], title=ctx["title"][:220], content=ctx["content"],
                       fallback=ctx["fallback"], data_json=ctx["data"], author=ctx["author"],
                       author_note=(ctx["note"] or "")[:400], recipients=to)
    db.add(rep)
    try:
        db.commit()
    except IntegrityError:          # tiến trình khác vừa gửi đúng kỳ này
        db.rollback()
        old = (db.query(RhythmReport).filter(RhythmReport.company_id == co.id, RhythmReport.scope_key == ctx["scope_key"],
                                             RhythmReport.kind == kind, RhythmReport.period_key == ctx["pk"]).first())
        return {**public_report(db, old), "created": False}
    db.refresh(rep)
    body = rep.content + (f"\n\n_{rep.author_note}_" if rep.author_note else "")
    for rid in to:
        db.add(InboxItem(organization_id=org_id, recipient_member_id=rid, source="rhythm", title=rep.title,
                         item_type=INBOX_KIND[kind], priority="normal", status="unread", related_type="rhythm_report",
                         related_id=str(rep.id), group_key=f"rhythm:{rep.id}", kinds=INBOX_KIND[kind], count=1, body=body))
    db.commit()
    from app.services.company_event_bus import emit_event
    emit_event(db, organization_id=org_id, company_id=co.id, event_type=f"rhythm.{kind}.delivered", source="operating_rhythm",
               aggregate_type="rhythm_report", aggregate_id=str(rep.id),
               payload={"report_id": rep.id, "scope": rep.scope_key, "period": rep.period_key, "author": rep.author,
                        "recipients": to})
    return {**public_report(db, rep), "created": True}


async def generate(db: Session, org_id: int, company_id: int, kind: str, *, department_id: int | None = None,
                   now: datetime | None = None, runtime: Any = None, use_agent: bool | None = None) -> dict:
    ctx = _prepare(db, org_id, company_id, kind, department_id, now or datetime.utcnow(), runtime, use_agent)
    await _write(ctx, runtime)
    return _finalize(db, org_id, ctx)


async def generate_all(db: Session, org_id: int, company_id: int, kind: str, *, now: datetime | None = None,
                       runtime: Any = None) -> list[dict]:
    """Công ty + từng phòng ban; các agent viết song song (một lượt chờ, không cộng dồn thời gian)."""
    import asyncio
    now = now or datetime.utcnow()
    cfg = config(db, org_id, company_id)
    scopes: list[int | None] = [None]
    if cfg is None or cfg.per_department:
        scopes += [d.id for d in db.query(Department).filter(Department.company_id == company_id).order_by(Department.id).all()
                   if (getattr(d, "status", "active") or "active") != "archived"]
    ctxs = [_prepare(db, org_id, company_id, kind, s, now, runtime, None) for s in scopes]
    await asyncio.gather(*(_write(c, runtime) for c in ctxs))
    return [_finalize(db, org_id, c) for c in ctxs]


def due(cfg: RhythmConfig, now: datetime) -> list[str]:
    loc = _local(now, cfg.timezone)
    kinds = []
    if cfg.standup_enabled and cfg.standup_hour <= loc.hour < cfg.standup_hour + WINDOW_HOURS:
        kinds.append("standup")
    if cfg.weekly_enabled and loc.weekday() == cfg.weekly_dow and cfg.weekly_hour <= loc.hour < cfg.weekly_hour + WINDOW_HOURS:
        kinds.append("weekly")
    return kinds


async def tick(db: Session, *, now: datetime | None = None, runtime: Any = None) -> list[dict]:
    now = now or datetime.utcnow()
    out = []
    for cfg in db.query(RhythmConfig).all():
        for kind in due(cfg, now):
            try:
                rows = await generate_all(db, cfg.organization_id, cfg.company_id, kind, now=now, runtime=runtime)
                out.append({"company_id": cfg.company_id, "kind": kind, "created": sum(1 for r in rows if r["created"])})
            except Exception as exc:  # noqa: BLE001
                db.rollback()
                out.append({"company_id": cfg.company_id, "kind": kind, "error": str(exc)[:300]})
    return out


def public_report(db: Session, r: RhythmReport, *, full: bool = True) -> dict:
    names = {m.id: m.name for m in db.query(Member).filter(Member.id.in_(r.recipients or [-1])).all()}
    dept = db.get(Department, r.department_id) if r.department_id else None
    out = {"id": r.id, "company_id": r.company_id, "department_id": r.department_id,
           "scope": dept.name if dept else "company", "kind": r.kind, "period_key": r.period_key, "title": r.title,
           "author": r.author, "author_note": r.author_note, "by_agent": r.author.startswith("agent:"),
           "recipients": [names.get(x, f"#{x}") for x in (r.recipients or [])],
           "created_at": r.created_at.isoformat() if r.created_at else None}
    if full:
        out.update(content=r.content, fallback=r.fallback, data=r.data_json)
    return out


def overview(db: Session, org_id: int, company_id: int | None, *, limit: int = 20) -> dict:
    from app.services.company_foundation import _company
    co = _company(db, org_id, company_id)
    rows = (db.query(RhythmReport).filter(RhythmReport.company_id == co.id).order_by(RhythmReport.id.desc()).limit(limit).all())
    return {"company_id": co.id, "company_name": co.name, "config": public_config(config(db, org_id, co.id)),
            "departments": [{"id": d.id, "name": d.name} for d in db.query(Department).filter(Department.company_id == co.id).all()],
            "reports": [public_report(db, r) for r in rows]}


def get_report(db: Session, org_id: int, report_id: int) -> dict:
    r = db.get(RhythmReport, report_id)
    if r is None or r.organization_id != org_id:
        raise _err(404, "Không thấy bản giao ban này.")
    return public_report(db, r)
