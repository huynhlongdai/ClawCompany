"""v36: chuỗi thời gian chỉ số, lịch, và số theo ngày của agent.

Nguyên tắc của module này: **không tự sinh số**. Mỗi hàm chỉ đọc từ nguồn đã
có rồi tổng hợp lại, và nói rõ nguồn nào trong mỗi phản hồi. Nếu nguồn trống
thì kết quả trống — không nội suy, không điền mặc định.

Ba nguồn:

* ``metric_samples`` — lịch sử chỉ số. Ghi bằng ``snapshot_metrics()``, tức
  chốt số hiện tại của ``analytics_metrics`` vào kỳ đang xét.
* ``calendar_events`` — do người/agent tạo qua API.
* ``usage_events`` + ``company_events`` — nguồn để dẫn xuất
  ``agent_daily_stats``; không có endpoint nào cho người gõ số vào bảng đó.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.entities import Agent, Company, Member, Project
from app.models.extended import AnalyticsMetric
from app.models.v7 import UsageEvent
from app.models.v10 import CompanyEvent
from app.models.v36 import AgentDailyStat, CalendarEvent, MetricSample

# Quét có trần: một tổ chức nhiều năm dữ liệu không được làm sập một request.
MAX_SAMPLES = 500
MAX_EVENTS = 200
MAX_DERIVE_DAYS = 90


def _period_of(moment: datetime, grain: str) -> str:
    return moment.strftime("%Y-%m") if grain == "month" else moment.strftime("%Y-%m-%d")


# ---------------------------------------------------------------- chỉ số

def metric_history(db: Session, organization_id: int, *, metric_key: str | None = None,
                   limit: int = MAX_SAMPLES) -> dict:
    """Lịch sử chỉ số, nhóm theo ``metric_key``.

    ``points_are_measurements`` nói thẳng một điều dễ bị hiểu sai: những mẫu
    có ``source='analytics_backfill'`` là hai mốc mà bảng cũ vốn đã biết, chứ
    không phải chuỗi đo liên tục. Ai vẽ biểu đồ từ đây phải biết điều đó.
    """
    stmt = select(MetricSample).where(MetricSample.organization_id == organization_id)
    if metric_key:
        stmt = stmt.where(MetricSample.metric_key == metric_key)
    rows = list(db.execute(
        stmt.order_by(MetricSample.metric_key, MetricSample.period)
        .limit(max(1, min(limit, MAX_SAMPLES)))
    ).scalars().all())

    series: dict[str, list[dict]] = defaultdict(list)
    sources: set[str] = set()
    for row in rows:
        series[row.metric_key].append({
            "period": row.period, "value": row.value, "unit": row.unit,
            "source": row.source, "recorded_at": row.recorded_at.isoformat(),
        })
        sources.add(row.source)

    return {
        "organization_id": organization_id,
        "series": [{"metric_key": key, "points": points} for key, points in series.items()],
        "sample_count": len(rows),
        "sources": sorted(sources),
        # Chuỗi chỉ có hai điểm thì gọi là "chuỗi" là quá lời.
        "points_are_measurements": all(s != "analytics_backfill" for s in sources) if sources else True,
        "truncated": len(rows) >= MAX_SAMPLES,
    }


def snapshot_metrics(db: Session, organization_id: int, *, grain: str = "month",
                     source: str = "analytics_snapshot") -> dict:
    """Chốt trị hiện tại của mọi chỉ số vào kỳ đang xét.

    Chạy lại trong cùng kỳ thì ghi đè đúng hàng đó (ràng buộc unique lo phần
    đó), nên một cron gọi mỗi ngày không nhân bản điểm.
    """
    now = datetime.utcnow()
    period = _period_of(now, grain)
    metrics = list(db.execute(
        select(AnalyticsMetric).where(AnalyticsMetric.organization_id == organization_id)
    ).scalars().all())

    written, updated = 0, 0
    for metric in metrics:
        existing = db.execute(
            select(MetricSample).where(
                MetricSample.organization_id == organization_id,
                MetricSample.metric_key == metric.metric_key,
                MetricSample.scope_type == (metric.scope_type or "organization"),
                MetricSample.scope_id == (metric.scope_id or ""),
                MetricSample.period == period,
            )
        ).scalars().first()
        if existing:
            existing.value = metric.current_value
            existing.unit = metric.unit or ""
            existing.source = source
            existing.recorded_at = now
            updated += 1
        else:
            db.add(MetricSample(
                organization_id=organization_id, metric_key=metric.metric_key,
                scope_type=metric.scope_type or "organization",
                scope_id=metric.scope_id or "", period=period,
                value=metric.current_value, unit=metric.unit or "",
                source=source, recorded_at=now,
            ))
            written += 1
    db.commit()
    return {"period": period, "grain": grain, "metrics_seen": len(metrics),
            "written": written, "updated": updated, "source": source}


# ---------------------------------------------------------------- lịch

def calendar(db: Session, organization_id: int, *, day: date | None = None,
             days: int = 1, limit: int = MAX_EVENTS) -> dict:
    """Lịch trong một khoảng ngày.

    Không có tích hợp Google/Outlook nào, nên ``synced_from_provider`` luôn là
    ``false``. Lịch trống nghĩa là chưa ai tạo mục nào — đó là sự thật, không
    phải lỗi tải dữ liệu.
    """
    start_day = day or datetime.utcnow().date()
    span = max(1, min(int(days or 1), 31))
    start = datetime.combine(start_day, datetime.min.time())
    end = start + timedelta(days=span)

    rows = list(db.execute(
        select(CalendarEvent).where(
            CalendarEvent.organization_id == organization_id,
            CalendarEvent.starts_at >= start,
            CalendarEvent.starts_at < end,
        ).order_by(CalendarEvent.starts_at).limit(max(1, min(limit, MAX_EVENTS)))
    ).scalars().all())

    owners = {
        m.id: m.name for m in db.execute(
            select(Member).where(Member.id.in_([r.owner_member_id for r in rows if r.owner_member_id]))
        ).scalars().all()
    } if rows else {}

    return {
        "organization_id": organization_id,
        "from": start.isoformat(), "to": end.isoformat(), "days": span,
        "events": [{
            "id": r.id, "title": r.title, "description": r.description,
            "starts_at": r.starts_at.isoformat(),
            "ends_at": r.ends_at.isoformat() if r.ends_at else None,
            "location": r.location, "event_type": r.event_type,
            "status": r.status, "project_id": r.project_id,
            "owner_member_id": r.owner_member_id,
            "owner_name": owners.get(r.owner_member_id or 0, ""),
        } for r in rows],
        "count": len(rows),
        "synced_from_provider": False,
    }


def create_calendar_event(db: Session, organization_id: int, *, title: str,
                          starts_at: datetime, ends_at: datetime | None = None,
                          event_type: str = "meeting", description: str = "",
                          location: str = "", company_id: int | None = None,
                          project_id: int | None = None,
                          owner_member_id: int | None = None) -> CalendarEvent:
    if ends_at and ends_at < starts_at:
        raise ValueError("ends_at sớm hơn starts_at")
    event = CalendarEvent(
        organization_id=organization_id, title=title.strip(), description=description,
        starts_at=starts_at, ends_at=ends_at, location=location,
        event_type=event_type, company_id=company_id, project_id=project_id,
        owner_member_id=owner_member_id,
    )
    db.add(event); db.commit(); db.refresh(event)
    return event


# ------------------------------------------------- số theo ngày của agent

# Event nào tính là việc xong / việc lỗi. Lấy từ vốn từ của company_event_bus,
# không thêm tên mới.
DONE_EVENTS = ("task.completed", "task.done", "openclaw.task.completed")
FAILED_EVENTS = ("task.failed", "task.blocked", "openclaw.task.error")


def derive_agent_stats(db: Session, organization_id: int, *, days: int = 30) -> dict:
    """Tính ``agent_daily_stats`` từ usage_events và company_events.

    Vì sao không nhận số do người gõ: con số này là *dẫn xuất*. Cho phép ghi
    tay thì hai nguồn sẽ lệch nhau và không ai biết nguồn nào đúng.

    ``runs`` và ``cost`` lấy từ ``usage_events`` (có agent_id, có amount).
    ``tasks_completed`` / ``tasks_failed`` lấy từ ``company_events`` theo
    ``aggregate_type='task'`` — và đây là chỗ yếu phải nói ra: bảng event
    không mang ``agent_id``, nên chỉ quy được về agent khi payload có
    ``runtime_agent_id``. Event không có thông tin đó thì không tính cho ai.
    """
    span = max(1, min(int(days or 30), MAX_DERIVE_DAYS))
    since = datetime.utcnow() - timedelta(days=span)

    agents = {
        a.id: a for a in db.execute(
            select(Agent).join(Member, Agent.member_id == Member.id)
            .join(Company, Member.company_id == Company.id)
            .where(Company.organization_id == organization_id)
        ).scalars().all()
    }
    if not agents:
        return {"organization_id": organization_id, "days": span, "agents": 0,
                "rows_written": 0, "note": "tổ chức chưa có agent nào"}

    # runs + cost theo ngày, từ usage_events
    usage_rows = db.execute(
        select(
            UsageEvent.agent_id,
            func.date(UsageEvent.created_at).label("day"),
            func.count(UsageEvent.id),
            func.coalesce(func.sum(UsageEvent.amount), 0.0),
        ).where(
            UsageEvent.organization_id == organization_id,
            UsageEvent.agent_id.isnot(None),
            UsageEvent.created_at >= since,
        ).group_by(UsageEvent.agent_id, func.date(UsageEvent.created_at))
    ).all()

    buckets: dict[tuple[int, date], dict] = {}
    for agent_id, day, runs, cost in usage_rows:
        day_value = day if isinstance(day, date) else datetime.fromisoformat(str(day)).date()
        buckets[(agent_id, day_value)] = {
            "runs": int(runs or 0), "cost": float(cost or 0),
            "done": 0, "failed": 0,
        }

    # việc xong / việc lỗi, quy về agent qua runtime_agent_id trong payload
    by_runtime_id = {a.runtime_agent_id: a.id for a in agents.values() if a.runtime_agent_id}
    unattributed = 0
    if by_runtime_id:
        events = db.execute(
            select(CompanyEvent).where(
                CompanyEvent.organization_id == organization_id,
                CompanyEvent.occurred_at >= since,
                CompanyEvent.event_type.in_(DONE_EVENTS + FAILED_EVENTS),
            ).limit(2000)
        ).scalars().all()
        for event in events:
            payload = event.payload_json or ""
            agent_id = next(
                (aid for rid, aid in by_runtime_id.items() if rid and f'"{rid}"' in payload),
                None,
            )
            if agent_id is None:
                unattributed += 1
                continue
            day_value = event.occurred_at.date()
            slot = buckets.setdefault((agent_id, day_value),
                                     {"runs": 0, "cost": 0.0, "done": 0, "failed": 0})
            if event.event_type in DONE_EVENTS:
                slot["done"] += 1
            else:
                slot["failed"] += 1

    now = datetime.utcnow()
    written = 0
    for (agent_id, day_value), slot in buckets.items():
        finished = slot["done"] + slot["failed"]
        rate = (slot["done"] / finished * 100.0) if finished else None
        existing = db.execute(
            select(AgentDailyStat).where(
                AgentDailyStat.agent_id == agent_id, AgentDailyStat.day == day_value)
        ).scalars().first()
        if existing:
            existing.runs = slot["runs"]; existing.cost = slot["cost"]
            existing.tasks_completed = slot["done"]; existing.tasks_failed = slot["failed"]
            existing.success_rate = rate; existing.derived_at = now
        else:
            db.add(AgentDailyStat(
                organization_id=organization_id, agent_id=agent_id, day=day_value,
                runs=slot["runs"], tasks_completed=slot["done"],
                tasks_failed=slot["failed"], cost=slot["cost"],
                success_rate=rate, derived_at=now,
            ))
        written += 1
    db.commit()

    return {
        "organization_id": organization_id, "days": span,
        "agents": len(agents), "rows_written": written,
        "events_unattributed": unattributed,
        "attribution": {
            # Bốn lời thừa nhận, đi kèm mọi phản hồi — cùng lối viết của v35.
            "usage_rows_carry_agent_id": True,
            "company_events_carry_agent_id": False,
            "task_outcome_matched_by_runtime_agent_id_in_payload": True,
            "success_rate_null_when_nothing_finished": True,
        },
    }


def agent_series(db: Session, organization_id: int, *, agent_id: int | None = None,
                 days: int = 30) -> dict:
    """Đọc lại ``agent_daily_stats`` để vẽ đường theo ngày."""
    span = max(1, min(int(days or 30), MAX_DERIVE_DAYS))
    since = (datetime.utcnow() - timedelta(days=span)).date()
    stmt = select(AgentDailyStat).where(
        AgentDailyStat.organization_id == organization_id,
        AgentDailyStat.day >= since,
    )
    if agent_id:
        stmt = stmt.where(AgentDailyStat.agent_id == agent_id)
    rows = list(db.execute(stmt.order_by(AgentDailyStat.agent_id, AgentDailyStat.day)).scalars().all())

    series: dict[int, list[dict]] = defaultdict(list)
    for row in rows:
        series[row.agent_id].append({
            "day": row.day.isoformat(), "runs": row.runs, "cost": row.cost,
            "tasks_completed": row.tasks_completed, "tasks_failed": row.tasks_failed,
            "success_rate": row.success_rate,
        })
    return {
        "organization_id": organization_id, "days": span,
        "series": [{"agent_id": aid, "points": pts} for aid, pts in series.items()],
        "row_count": len(rows),
        "derived": True,
        "note": "Số này do derive_agent_stats() tính từ usage_events và company_events; "
                "gọi POST /api/v36/agent-stats/derive để cập nhật.",
    }


# ---------------------------------------------------------------- hạn chót

def set_project_due_date(db: Session, project: Project, due: date | None) -> Project:
    project.due_date = due
    db.add(project); db.commit(); db.refresh(project)
    return project


def upcoming_deadlines(db: Session, organization_id: int, *, days: int = 30) -> dict:
    """Dự án có hạn trong khoảng tới, cộng dự án đã quá hạn."""
    span = max(1, min(int(days or 30), 365))
    today = datetime.utcnow().date()
    horizon = today + timedelta(days=span)

    rows = list(db.execute(
        select(Project, Company.name)
        .join(Company, Project.company_id == Company.id)
        .where(Company.organization_id == organization_id,
               Project.due_date.isnot(None),
               Project.due_date <= horizon)
        .order_by(Project.due_date)
        .limit(MAX_EVENTS)
    ).all())

    return {
        "organization_id": organization_id, "days": span,
        "projects": [{
            "id": p.id, "name": p.name, "company_name": company_name,
            "status": p.status, "progress": p.progress,
            "due_date": p.due_date.isoformat() if p.due_date else None,
            "overdue": bool(p.due_date and p.due_date < today),
            "days_left": (p.due_date - today).days if p.due_date else None,
        } for p, company_name in rows],
        "count": len(rows),
        # Dự án chưa đặt hạn thì không xuất hiện ở đây, và đó không phải "không có hạn nào".
        "projects_without_due_date_excluded": True,
    }


# ---------------------------------------------------------------- hỏi Nina

async def ask_nina(db: Session, organization_id: int, *, message: str,
                   timeout_seconds: int = 60) -> dict:
    """Gửi một câu hỏi tới agent Nina qua gateway OpenClaw và chờ trả lời.

    Vì sao cần endpoint này: ``/api/nina/command`` là bộ phân tích ý định theo
    luật — nó trả lời đúng cho vài câu hỏi đã lập trình sẵn và im lặng với mọi
    câu khác. Sau khi gateway có credential model, đường đi thật là:
    ClawCompany -> chat.send -> gateway -> nhà cung cấp model -> trả lời.

    Cách chờ: gửi rồi đọc ``chat.history``, lấy tin nhắn assistant mới hơn mốc
    trước khi gửi. Không dùng subscribe vì một câu hỏi lẻ không đáng mở thêm
    một follower có lease.

    Nói rõ trong phản hồi: model nào trả lời, và mất bao lâu — để không ai
    tưởng đây là câu trả lời tức thời từ database.
    """
    import asyncio as _asyncio
    import time as _time

    from app.models.entities import Agent, Company, Member
    from app.runtime.factory import get_runtime
    from app.runtime.openclaw_native import NativeOpenClawRuntime
    from app.runtime import openclaw_protocol as ocp

    runtime = get_runtime()
    if not isinstance(runtime, NativeOpenClawRuntime):
        return {"answered": False,
                "reason": "OPENCLAW_MODE không phải native, nên không có gateway để hỏi",
                "mode": type(runtime).__name__}

    # Scope theo ``members.organization_id``, KHÔNG join qua companies.
    # Nina là Chief of Staff cấp holding nên ``company_id`` là NULL; một inner
    # join qua companies lặng lẽ loại đúng cái ghế quan trọng nhất, và thông
    # báo lỗi hoá ra vô nghĩa ("không ghế nào khớp roster" trong khi ghế có
    # thật và đã bind đúng). Cùng lớp lỗi với live_channel/progress_autosync,
    # chỉ khác chiều: ở đó thiếu join, ở đây join quá nhiều.
    seats = list(db.execute(
        select(Agent, Member.name)
        .join(Member, Agent.member_id == Member.id)
        .where(Member.organization_id == organization_id,
               Agent.runtime_agent_id.isnot(None),
               Agent.runtime_agent_id != "")
    ).all())
    if not seats:
        return {"answered": False,
                "reason": "Chưa có ghế agent nào bind vào gateway. Bind ở /app/openclaw trước."}

    # HỎI GATEWAY xem agent nào thật sự tồn tại, thay vì tin cột lifecycle
    # trong database. Bản đầu sắp xếp theo ``lifecycle.desc()`` và trúng ngay
    # cái bẫy: chuỗi "detached" lớn hơn "active" theo thứ tự chữ, nên nó chọn
    # đúng cái ghế mồ côi và gateway trả 'Unknown agent id "sophia-cmo"'.
    # Trạng thái ghế trong database là ảnh chụp cũ; gateway mới là sự thật.
    known: set[str] = set()
    try:
        roster = await runtime.list_agents()
        known = {str(row.get("id") or row.get("agentId") or "") for row in roster}
    except Exception:
        known = set()

    usable = [(a, n) for a, n in seats if a.runtime_agent_id in known] if known else []
    if not usable:
        return {
            "answered": False,
            "reason": "Không ghế nào khớp roster của gateway."
                      + (f" Gateway đang biết: {sorted(known)}." if known else
                         " Và không đọc được roster từ gateway."),
            "company_seats": sorted({a.runtime_agent_id for a, _ in seats}),
            "hint": "Chạy reconcile ở /app/openclaw rồi bind lại ghế.",
        }

    # Trong số ghế gateway biết, ưu tiên ghế database cũng cho là active.
    usable.sort(key=lambda pair: 0 if pair[0].lifecycle == "active" else 1)
    agent, agent_name = usable[0]
    session_key = ocp.main_session_key(agent.runtime_agent_id)

    started = _time.monotonic()
    before = 0
    try:
        history = await runtime.history(session_key, limit=50)
        before = len(history.get("messages") or [])
    except Exception:
        before = 0

    try:
        await runtime.run_agent(agent.runtime_agent_id, message, metadata={}, session_key=session_key)
    except Exception as exc:  # noqa: BLE001 - lỗi gateway phải nói ra, không nuốt
        return {"answered": False, "reason": f"gateway từ chối: {exc}"[:400],
                "agent": agent_name, "session_key": session_key}

    # Chờ có thêm tin nhắn assistant. Bước ngắn để trả lời nhanh khi model nhanh.
    deadline = _time.monotonic() + max(5, min(timeout_seconds, 120))
    reply = ""
    while _time.monotonic() < deadline:
        await _asyncio.sleep(2)
        try:
            history = await runtime.history(session_key, limit=50)
        except Exception:
            continue
        messages = history.get("messages") or []
        fresh = messages[before:]
        for item in reversed(fresh):
            if (item.get("role") or "") != "assistant":
                continue
            content = item.get("content") or item.get("text") or ""
            if isinstance(content, list):
                content = " ".join(str(part.get("text", part)) for part in content)
            text = str(content).strip()
            # NO_REPLY là tín hiệu nội bộ của OpenClaw, không phải câu trả lời.
            if text and text != "NO_REPLY":
                reply = text
                break
        if reply:
            break

    return {
        "answered": bool(reply),
        "reply": reply,
        "agent": agent_name,
        "runtime_agent_id": agent.runtime_agent_id,
        "session_key": session_key,
        "elapsed_seconds": round(_time.monotonic() - started, 1),
        "timed_out": not reply,
        "note": "Câu trả lời do model sau gateway sinh ra, không phải đọc từ database. "
                "Hết thời gian chờ không có nghĩa là thất bại — lượt chạy vẫn tiếp tục "
                "trong phiên, xem ở /app/live-runs.",
    }
