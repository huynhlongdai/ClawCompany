"""D2.1 — hàng đợi wakeup: lý do nào thì đánh thức seat nào, và vì sao không.

Trước D2.1 mỗi nguồn tự gọi ``agent_dispatch.dispatch_task`` (bàn giao) hoặc
không ai gọi cả (giao việc, comment @, approval có kết quả, blocker đóng) — seat
chỉ chạy khi người bấm nút. Ở đây mọi nguồn chỉ làm một việc: ``enqueue``.
``drain`` là đường duy nhất biến lý do thành lượt chạy:

- gộp các lý do của cùng seat trong cửa sổ ``wakeup_window_seconds`` (10 giây)
  thành **một** run; lý do khác cùng task thành ``coalesced``;
- bỏ qua, có ``skip_reason``, khi seat không ``active``, seat đang có run (hàng
  đợi ``steer`` của OpenClaw sẽ chèn tin thứ hai vào lượt đang chạy), ngoài
  ``heartbeat.activeHours`` của seat, hoặc ``budget.can_reserve`` trả false;
- lý do bị bỏ vì seat bận được xếp lại khi lượt đang chạy kết thúc
  (``requeue_deferred``), nên giao việc lúc seat bận không bị mất.

Mọi quyết định ghi ``company_events`` kèm ``reason``.
"""
from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import Agent, BudgetEnvelope, Member, Task, TaskRun, Wakeup
from app.models.work_graph import OPEN_RUN_STATUSES, WAKEUP_REASONS
from app.services import budget as budget_svc
from app.services.company_event_bus import emit_event

SOURCE = "wakeup"
DISPATCHABLE = ("backlog", "todo", "in_progress")  # như dispatch tay của v19/WP-4.3
STALE_RUN_MINUTES = 30  # lượt "đang chạy" quá lâu không có tin = follower đã lỡ frame cuối


# ------------------------------------------------------------------ enqueue


def _emit(db: Session, wk: Wakeup, event_type: str, reason: str, **extra) -> None:
    emit_event(db, organization_id=wk.organization_id, event_type=event_type, source=SOURCE,
               aggregate_type="wakeup", aggregate_id=str(wk.id),
               payload={"reason": reason, "wakeup_id": wk.id, "wake_reason": wk.reason,
                        "member_id": wk.member_id, "task_id": wk.task_id, **extra})


def enqueue(db: Session, *, organization_id: int, member_id: int, reason: str,
            dedupe_key: str, task_id: int | None = None,
            payload: dict | None = None) -> tuple[Wakeup, bool]:
    """Xếp một lý do. Cùng ``dedupe_key`` → trả hàng cũ, ``created=False``."""
    if reason not in WAKEUP_REASONS:
        raise ValueError(f"reason phải là một trong {', '.join(WAKEUP_REASONS)}")
    dedupe_key = dedupe_key[:200]
    existing = db.query(Wakeup).filter(Wakeup.dedupe_key == dedupe_key).first()
    if existing is not None:
        return existing, False
    wk = Wakeup(organization_id=organization_id, member_id=member_id, reason=reason, task_id=task_id,
                payload=json.dumps(payload or {}, ensure_ascii=False, default=str),
                dedupe_key=dedupe_key, status="queued")
    db.add(wk)
    try:
        db.commit()
    except IntegrityError:  # hai tiến trình cùng xếp một lý do: UNIQUE quyết
        db.rollback()
        return db.query(Wakeup).filter(Wakeup.dedupe_key == dedupe_key).one(), False
    db.refresh(wk)
    _emit(db, wk, "wakeup.enqueued", f"{reason}: xếp đánh thức seat #{member_id}"
          + (f" cho task #{task_id}" if task_id else ""), dedupe_key=dedupe_key)
    return wk, True


def agent_member(db: Session, member_id: int | None) -> Member | None:
    if not member_id:
        return None
    m = db.get(Member, member_id)
    return m if m is not None and m.member_type == "agent" else None


def enqueue_for_task(db: Session, task: Task, reason: str, *, dedupe_key: str,
                     member_id: int | None = None, payload: dict | None = None) -> Wakeup | None:
    """Đánh thức người nhận việc (hoặc ``member_id``) nếu đó là seat agent. Không bao giờ ném."""
    try:
        member = agent_member(db, member_id or task.assignee_member_id)
        if member is None:
            return None
        wk, _ = enqueue(db, organization_id=member.organization_id, member_id=member.id,
                        reason=reason, task_id=task.id, dedupe_key=dedupe_key, payload=payload)
        return wk
    except Exception as exc:  # noqa: BLE001 — một nguồn phát không được làm hỏng thao tác gốc
        db.rollback()
        print(f"[D2.1] enqueue {reason} for task #{task.id} failed: {exc}")
        return None


# ------------------------------------------------------------------ skip rules


def within_active_hours(spec: dict | None, now_utc: datetime) -> bool:
    """``heartbeat.activeHours`` {start, end, timezone} kiểu OpenClaw; qua đêm được."""
    if not spec or not spec.get("start") or not spec.get("end"):
        return True
    try:
        tz = ZoneInfo(str(spec.get("timezone") or "UTC"))
    except Exception:  # noqa: BLE001
        tz = ZoneInfo("UTC")
    local = now_utc.replace(tzinfo=ZoneInfo("UTC")).astimezone(tz)
    minute = local.hour * 60 + local.minute

    def parse(v: str) -> int:
        h, m = str(v).split(":")[:2]
        return int(h) * 60 + int(m)

    start, end = parse(spec["start"]), parse(spec["end"])
    if start == end:
        return True
    return start <= minute < end if start < end else (minute >= start or minute < end)


_HOURS_CACHE: dict[str, tuple[float, dict | None]] = {}


async def _gateway_active_hours(agent: Agent) -> dict | None:
    """Đọc ``agents.entries.<id>.heartbeat.activeHours`` (cache 60 giây)."""
    key = agent.runtime_agent_id or ""
    hit = _HOURS_CACHE.get(key)
    if hit and time.monotonic() - hit[0] < 60:
        return hit[1]
    spec = None
    if settings.openclaw_mode == "native" and key:
        try:
            from app.runtime.factory import get_runtime
            from app.services.openclaw_config import ConfigRegistry
            entry = await asyncio.wait_for(ConfigRegistry(get_runtime()).agent_entry(key), timeout=5)
            hb = (entry.get("effective") or {}).get("heartbeat") or {}
            spec = hb.get("activeHours") if isinstance(hb.get("activeHours"), dict) else None
        except Exception:  # noqa: BLE001 — không đọc được thì không chặn, nhưng ghi lại
            spec = None
    _HOURS_CACHE[key] = (time.monotonic(), spec)
    return spec


ACTIVE_HOURS_LOOKUP = _gateway_active_hours


def open_run_for(db: Session, member_id: int, now: datetime) -> TaskRun | None:
    stale = now - timedelta(minutes=STALE_RUN_MINUTES)
    for run in (db.query(TaskRun).filter(TaskRun.member_id == member_id,
                                         TaskRun.status.in_(OPEN_RUN_STATUSES))
                .order_by(TaskRun.id.desc()).all()):
        if (run.started_at or run.created_at or now) >= stale:
            return run
    return None


def budget_block(db: Session, member: Member) -> str:
    q = db.query(BudgetEnvelope).filter(BudgetEnvelope.organization_id == member.organization_id,
                                        BudgetEnvelope.status != "archived")
    for env in q.all():
        if env.company_id not in (None, member.company_id) or env.goal_id is not None:
            continue
        ok, msg = budget_svc.can_reserve(env, settings.wakeup_run_estimate_usd)
        if not ok:
            return f"budget: {env.name}: {msg}"
    return ""


async def skip_reason(db: Session, member: Member | None, agent: Agent | None, now: datetime) -> str:
    if member is None or member.member_type != "agent":
        return "not_an_agent_seat"
    if member.status != "active" or agent is None or (agent.lifecycle or "active") != "active":
        return "seat_inactive"
    busy = open_run_for(db, member.id, now)
    if busy is not None:
        return f"seat_busy: run #{busy.id} (task #{busy.task_id})"
    if not within_active_hours(await ACTIVE_HOURS_LOOKUP(agent), now):
        return "outside_active_hours"
    return budget_block(db, member)


# ------------------------------------------------------------------ drain


def _close(wk: Wakeup, status: str, *, skip: str = "", run_id: int | None = None,
           into: int | None = None, now: datetime) -> None:
    wk.status, wk.skip_reason, wk.processed_at = status, skip[:200], now
    if run_id is not None:
        wk.run_id = run_id
    if into is not None:
        wk.coalesced_into_id = into



def _follow(task, organization_id: int) -> str | None:
    """Theo dõi phiên vừa gửi; trả trạng thái follower (hoặc 'error: ...')."""
    if not task.runtime_session_key:
        return None
    try:
        from app.services.runtime_stream import supervisor
        state = supervisor.follow(session_key=task.runtime_session_key, organization_id=organization_id,
                                  task_id=task.id)
        return getattr(state, "status", "following")
    except Exception as exc:  # noqa: BLE001 - follow lỗi không được làm hỏng lượt đã gửi
        print(f"[D2.1] follow after wakeup failed: {exc}")
        return f"error: {exc}"

async def _process(db: Session, member_id: int, items: list[Wakeup], now: datetime,
                   follow: bool, prefer: int | None = None) -> dict:
    if prefer is not None:
        items = sorted(items, key=lambda w: (w.id != prefer, w.id))
    member = db.get(Member, member_id)
    agent = db.query(Agent).filter(Agent.member_id == member_id).first() if member else None
    why = await skip_reason(db, member, agent, now)
    if why:
        for wk in items:
            _close(wk, "skipped", skip=why, now=now)
        db.commit()
        for wk in items:
            _emit(db, wk, "wakeup.skipped", why)
        return {"member_id": member_id, "decision": "skipped", "reason": why, "wakeups": [w.id for w in items]}

    primary, task = None, None
    for wk in items:
        t = db.get(Task, wk.task_id) if wk.task_id else None
        if t is None:
            why_one = "no_task"
        elif t.assignee_member_id != member_id:
            why_one = "not_assignee"
        elif t.status not in DISPATCHABLE:
            why_one = f"task_status: {t.status}"
        else:
            primary, task = wk, t
            break
        _close(wk, "skipped", skip=why_one, now=now); db.commit()
        _emit(db, wk, "wakeup.skipped", why_one)
    if primary is None:
        return {"member_id": member_id, "decision": "skipped", "reason": "no_dispatchable_task",
                "wakeups": [w.id for w in items]}
    same = [w for w in items if w is not primary and w.status == "queued" and w.task_id == primary.task_id]

    from app.services import agent_dispatch
    from app.services import task_lifecycle as lifecycle
    try:
        task = await agent_dispatch.dispatch_task(db, task, trigger_kind=primary.reason, wakeup_id=primary.id)
    except agent_dispatch.DispatchError as exc:
        why = f"dispatch_error: {exc}"
        for wk in [primary, *same]:
            _close(wk, "skipped", skip=why, now=now)
        db.commit(); _emit(db, primary, "wakeup.skipped", why)
        return {"member_id": member_id, "decision": "skipped", "reason": why, "wakeups": [primary.id]}
    except Exception as exc:  # noqa: BLE001
        why = f"runtime_error: {exc}"
        for wk in [primary, *same]:
            _close(wk, "failed", skip=why, now=now)
        db.commit(); _emit(db, primary, "wakeup.failed", why)
        return {"member_id": member_id, "decision": "failed", "reason": why, "wakeups": [primary.id]}

    # Gắn follower NGAY sau chat.send, trước mọi ghi DB khác: gateway từ chối
    # exec cần duyệt nếu lúc agent xin lệnh chưa có client duyệt nào kết nối
    # (approval-e2e.md, giới hạn #5).
    followed = _follow(task, member.organization_id) if follow else None
    run = lifecycle.current_run(db, task)
    run_id = run.id if run else None
    _close(primary, "dispatched", run_id=run_id, now=now)
    for wk in same:
        _close(wk, "coalesced", run_id=run_id, into=primary.id, now=now)
    db.commit()
    _emit(db, primary, "wakeup.dispatched",
          f"{primary.reason}: lượt chạy #{run_id} cho task #{task.id}"
          + (f", gộp {len(same)} lý do khác" if same else ""),
          run_id=run_id, coalesced=[w.id for w in same], session_key=task.runtime_session_key)
    return {"member_id": member_id, "decision": "dispatched", "task_id": task.id, "run_id": run_id,
            "wakeups": [primary.id], "coalesced": [w.id for w in same], "followed": followed}


async def drain(db: Session, *, now: datetime | None = None, member_id: int | None = None,
                force: bool = False, follow: bool = False, window_seconds: float | None = None,
                prefer: int | None = None) -> list[dict]:
    """Biến lý do đang chờ thành lượt chạy. Một seat → tối đa một run mỗi lần drain."""
    now = now or datetime.utcnow()
    window = settings.wakeup_window_seconds if window_seconds is None else window_seconds
    await requeue_when_hours_open(db, now)
    q = db.query(Wakeup).filter(Wakeup.status == "queued")
    if member_id is not None:
        q = q.filter(Wakeup.member_id == member_id)
    groups: dict[int, list[Wakeup]] = {}
    for wk in q.order_by(Wakeup.id).all():
        groups.setdefault(wk.member_id, []).append(wk)
    out = []
    for mid, items in groups.items():
        oldest = min(w.created_at for w in items)
        if not force and oldest > now - timedelta(seconds=window):
            out.append({"member_id": mid, "decision": "waiting", "wakeups": [w.id for w in items]})
            continue
        out.append(await _process(db, mid, items, now, follow, prefer))
    return out


def requeue_deferred(db: Session, member_id: int, *, after_run_id: int) -> list[Wakeup]:
    """Lượt chạy vừa xong: xếp lại các lý do đã bị bỏ vì seat bận (mỗi task một lần)."""
    return _requeue(db, member_id, "seat_busy%", f"after-run-{after_run_id}")


async def requeue_when_hours_open(db: Session, now: datetime) -> list[Wakeup]:
    """Lý do bị bỏ vì ngoài giờ làm được xếp lại khi giờ làm của seat bắt đầu.

    Không có bước này, việc giao lúc 23h cho seat làm 8h–20h sẽ nằm im mãi:
    wakeup đã ``skipped`` và không sự kiện nào khác đánh thức lại."""
    out = []
    mids = {mid for (mid,) in db.query(Wakeup.member_id).filter(
        Wakeup.status == "skipped", Wakeup.skip_reason == "outside_active_hours").distinct()}
    for mid in sorted(mids):
        agent = db.query(Agent).filter(Agent.member_id == mid).first()
        if agent is None or not within_active_hours(await ACTIVE_HOURS_LOOKUP(agent), now):
            continue
        out += _requeue(db, mid, "outside_active_hours", f"hours-open-{now:%Y%m%d}")
    return out


def _requeue(db: Session, member_id: int, pattern: str, suffix: str) -> list[Wakeup]:
    out, seen = [], set()
    rows = (db.query(Wakeup).filter(Wakeup.member_id == member_id, Wakeup.status == "skipped",
                                    Wakeup.skip_reason.like(pattern))
            .order_by(Wakeup.id).all())
    for old in rows:
        meta = json.loads(old.payload or "{}")
        if meta.get("requeued_as") or old.task_id in seen:
            continue
        seen.add(old.task_id)
        new, _ = enqueue(db, organization_id=old.organization_id, member_id=member_id, reason=old.reason,
                         task_id=old.task_id, dedupe_key=f"{old.dedupe_key}:{suffix}",
                         payload={"requeued_from": old.id})
        meta["requeued_as"] = new.id
        old.payload = json.dumps(meta)
        db.commit()
        out.append(new)
    return out


async def drain_forever(interval_seconds: float) -> None:
    """Chạy drain trong tiến trình API (dev / không có Celery)."""
    from app.db.session import SessionLocal
    while True:
        db = SessionLocal()
        try:
            await drain(db, follow=settings.wakeup_follow)
        except Exception as exc:  # noqa: BLE001
            print(f"[D2.1] drain failed: {exc}")
        finally:
            db.close()
        await asyncio.sleep(interval_seconds)


def public(wk: Wakeup) -> dict:
    return {"id": wk.id, "member_id": wk.member_id, "reason": wk.reason, "task_id": wk.task_id,
            "status": wk.status, "skip_reason": wk.skip_reason, "run_id": wk.run_id,
            "coalesced_into_id": wk.coalesced_into_id, "dedupe_key": wk.dedupe_key,
            "payload": json.loads(wk.payload or "{}"),
            "created_at": wk.created_at.isoformat() if wk.created_at else None,
            "processed_at": wk.processed_at.isoformat() if wk.processed_at else None}
