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
from app.runtime.factory import resolve_mode
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
    if resolve_mode(settings.openclaw_mode) == "native" and key:
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


def budget_block(db: Session, member: Member, task: Task | None = None) -> str:
    """D2.3: cổng ngân sách theo phạm vi (company/department/member/project/goal)."""
    from app.services import budget_scope
    return budget_scope.gate(db, member, task)[0]


async def skip_reason(db: Session, member: Member | None, agent: Agent | None, now: datetime) -> str:
    if member is None or member.member_type != "agent":
        return "not_an_agent_seat"
    if member.status == "paused":
        from app.services import budget_scope
        spent = [e for e in budget_scope.applicable(db, member) if (e.threshold_state or "") == "exhausted"]
        if spent:
            return f"budget: {spent[0].name}: đã hết hạn mức — seat tạm dừng"
    if member.status != "active" or agent is None or (agent.lifecycle or "active") != "active":
        return "seat_inactive"
    busy = open_run_for(db, member.id, now)
    if busy is not None:
        return f"seat_busy: run #{busy.id} (task #{busy.task_id})"
    if not within_active_hours(await ACTIVE_HOURS_LOOKUP(agent), now):
        return "outside_active_hours"
    return ""


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

async def _review(db: Session, member: Member, primary: Wakeup, task: Task, items: list[Wakeup],
                  now: datetime) -> dict:
    """D2.2: reviewer là agent → phòng review 2 người thay cho một run thường."""
    from app.runtime.factory import get_runtime
    from app.services import execution_policy
    same = [w for w in items if w is not primary and w.status == "queued" and w.task_id == task.id]
    try:
        out = await execution_policy.run_agent_review(db, task, member, get_runtime())
    except Exception as exc:  # noqa: BLE001
        why = f"review_error: {exc}"[:200]
        for wk in [primary, *same]:
            _close(wk, "failed", skip=why, now=now)
        db.commit(); _emit(db, primary, "wakeup.failed", why)
        return {"member_id": member.id, "decision": "failed", "reason": why, "wakeups": [primary.id]}
    _close(primary, "dispatched", now=now)
    for wk in same:
        _close(wk, "coalesced", into=primary.id, now=now)
    db.commit()
    _emit(db, primary, "wakeup.dispatched", f"review_requested: phòng #{out.get('room_id')} → {out.get('decision')}")
    return {"member_id": member.id, "decision": "reviewed", "task_id": task.id, "review": out,
            "wakeups": [primary.id]}


async def _route(db: Session, member: Member, agent: Agent, primary: Wakeup, task: Task,
                 items: list[Wakeup], now: datetime, follow: bool) -> dict:
    """D3.1: lượt định tuyến của trưởng phòng — cổng ngân sách như lượt thường."""
    from app.services import budget_scope, routing
    same = [w for w in items if w is not primary and w.status == "queued" and w.task_id == task.id
            and w.reason == "routed"]
    why, envs, amount = budget_scope.gate(db, member, task)
    if why:
        for wk in [primary, *same]:
            _close(wk, "skipped", skip=why, now=now)
        db.commit()
        for wk in [primary, *same]:
            _emit(db, wk, "wakeup.skipped", why)
        return {"member_id": member.id, "decision": "skipped", "reason": why,
                "wakeups": [w.id for w in [primary, *same]]}
    hold_key = f"wakeup:{primary.id}"
    budget_scope.hold(db, envs, amount, hold_key,
                      memo=f"giữ chỗ lượt định tuyến wakeup #{primary.id} (task #{task.id})")
    try:
        run = await routing.dispatch_routing(db, task, member, agent, wakeup_id=primary.id)
    except Exception as exc:  # noqa: BLE001
        budget_scope.release_key(db, hold_key, "runtime lỗi — trả phần giữ")
        why = f"runtime_error: {exc}"[:200]
        for wk in [primary, *same]:
            _close(wk, "failed", skip=why, now=now)
        db.commit(); _emit(db, primary, "wakeup.failed", why)
        return {"member_id": member.id, "decision": "failed", "reason": why, "wakeups": [primary.id]}
    followed = None
    if follow:
        try:
            from app.services.runtime_stream import supervisor
            followed = getattr(supervisor.follow(session_key=run.session_key, organization_id=member.organization_id,
                                                 task_id=task.id), "status", "following")
        except Exception as exc:  # noqa: BLE001
            followed = f"error: {exc}"
    budget_scope.rekey(db, hold_key, budget_scope.run_key(run.id))
    _close(primary, "dispatched", run_id=run.id, now=now)
    for wk in same:
        _close(wk, "coalesced", run_id=run.id, into=primary.id, now=now)
    db.commit()
    _emit(db, primary, "wakeup.dispatched", f"routed: lượt định tuyến #{run.id} cho task #{task.id}",
          run_id=run.id, coalesced=[w.id for w in same], session_key=run.session_key)
    return {"member_id": member.id, "decision": "routed", "task_id": task.id, "run_id": run.id,
            "wakeups": [primary.id], "coalesced": [w.id for w in same], "followed": followed}


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
        if t is not None and wk.reason == "review_requested":
            from app.services import execution_policy
            if t.status == "review" and execution_policy.is_current_reviewer(t, member_id):
                return await _review(db, member, wk, t, items, now)
            why_one = "not_current_reviewer"
            _close(wk, "skipped", skip=why_one, now=now); db.commit()
            _emit(db, wk, "wakeup.skipped", why_one)
            continue
        if t is not None and wk.reason == "routed":
            # D3.1: trưởng phòng định tuyến việc của phòng — lượt riêng, không giữ task.
            from app.services import routing
            why_one = routing.routable(db, t, member_id)
            if not why_one:
                return await _route(db, member, agent, wk, t, items, now, follow)
            _close(wk, "skipped", skip=why_one, now=now); db.commit()
            _emit(db, wk, "wakeup.skipped", why_one)
            continue
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

    # D2.3: giữ chỗ TRƯỚC chat.send. Không giữ được → gateway không nhận gì.
    from app.services import budget_scope
    why, envs, amount = budget_scope.gate(db, member, task)
    if why:
        for wk in [primary, *same]:
            _close(wk, "skipped", skip=why, now=now)
        db.commit()
        for wk in [primary, *same]:
            _emit(db, wk, "wakeup.skipped", why)
        return {"member_id": member_id, "decision": "skipped", "reason": why,
                "wakeups": [w.id for w in [primary, *same]]}
    hold_key = f"wakeup:{primary.id}"
    budget_scope.hold(db, envs, amount, hold_key,
                      memo=f"giữ chỗ khi drain wakeup #{primary.id} (task #{task.id}, ước tính {amount:.4f})")

    from app.services import agent_dispatch
    from app.services import task_lifecycle as lifecycle
    try:
        task = await agent_dispatch.dispatch_task(db, task, trigger_kind=primary.reason, wakeup_id=primary.id)
    except agent_dispatch.DispatchError as exc:
        budget_scope.release_key(db, hold_key, "dispatch lỗi — trả phần giữ")
        why = f"dispatch_error: {exc}"
        for wk in [primary, *same]:
            _close(wk, "skipped", skip=why, now=now)
        db.commit(); _emit(db, primary, "wakeup.skipped", why)
        return {"member_id": member_id, "decision": "skipped", "reason": why, "wakeups": [primary.id]}
    except Exception as exc:  # noqa: BLE001
        budget_scope.release_key(db, hold_key, "runtime lỗi — trả phần giữ")
        why = f"runtime_error: {exc}"
        for wk in [primary, *same]:
            _close(wk, "failed", skip=why, now=now)
        db.commit(); _emit(db, primary, "wakeup.failed", why)
        from app.services import inbox
        inbox.run_failed(db, task, why, member_id=member_id)
        return {"member_id": member_id, "decision": "failed", "reason": why, "wakeups": [primary.id]}

    # Gắn follower NGAY sau chat.send, trước mọi ghi DB khác: gateway từ chối
    # exec cần duyệt nếu lúc agent xin lệnh chưa có client duyệt nào kết nối
    # (approval-e2e.md, giới hạn #5).
    followed = _follow(task, member.organization_id) if follow else None
    run = lifecycle.current_run(db, task)
    run_id = run.id if run else None
    if run_id is not None:
        budget_scope.rekey(db, hold_key, budget_scope.run_key(run_id))
    else:
        budget_scope.release_key(db, hold_key, "không có task_run — trả phần giữ")
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
    q = db.query(Wakeup).filter(Wakeup.status == "queued", _claimable(now))
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
        mine = _claim(db, items, now)
        if not mine:
            out.append({"member_id": mid, "decision": "claimed_elsewhere", "wakeups": [w.id for w in items]})
            continue
        try:
            out.append(await _process(db, mid, mine, now, follow, prefer))
        finally:
            _unclaim(db, mine)
    return out


# M4a — gate thật: Celery chạy 4 tiến trình, beat drain mỗi 5 giây. Một lượt review
# (phòng họp) mất ~40 giây, wakeup vẫn ``queued`` suốt lúc đó nên tiến trình khác bốc
# lại ĐÚNG wakeup ấy, chạy review lần hai (việc #26: hai drain cùng chốt, một cái 409,
# side-peek thiếu phòng review). Nay mỗi drain giành wakeup bằng một UPDATE có điều
# kiện (``processed_at`` làm dấu giữ chỗ); giữ chỗ quá hạn thì coi như tiến trình đã chết.
CLAIM_TTL_SECONDS = 900


def _claimable(now: datetime):
    from sqlalchemy import or_
    return or_(Wakeup.processed_at.is_(None), Wakeup.processed_at < now - timedelta(seconds=CLAIM_TTL_SECONDS))


def _claim(db: Session, items: list[Wakeup], now: datetime) -> list[Wakeup]:
    mine = []
    for wk in items:
        n = (db.query(Wakeup).filter(Wakeup.id == wk.id, Wakeup.status == "queued", _claimable(now))
             .update({Wakeup.processed_at: now}, synchronize_session=False))
        db.commit()
        if n:
            mine.append(wk)
    for wk in items:
        db.refresh(wk)
    return mine


def _unclaim(db: Session, items: list[Wakeup]) -> None:
    """Wakeup còn ``queued`` sau lượt này (seat chỉ chạy một việc mỗi drain) → trả chỗ."""
    ids = [w.id for w in items]
    for attempt in (1, 2):
        try:
            (db.query(Wakeup).filter(Wakeup.id.in_(ids), Wakeup.status == "queued")
             .update({Wakeup.processed_at: None}, synchronize_session=False))
            db.commit()
            for wk in items:
                db.refresh(wk)
            return
        except Exception as exc:  # noqa: BLE001 - trả chỗ hỏng thì hết hạn sau CLAIM_TTL_SECONDS
            db.rollback()
            if attempt == 2:
                print(f"[M4a] unclaim wakeups failed: {exc}")


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
