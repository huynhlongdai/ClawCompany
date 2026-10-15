"""Approval listener thường trực (gate M4b trên gateway thật).

Một tiến trình API giữ một socket khai ``exec-approvals`` (lease ``approval-listener``), nhận
``exec.approval.requested/resolved`` của MỌI phiên và ghi vào hàng ``approvals`` như follower vẫn làm —
cùng ``policy_key`` nên follower đến sau không tạo hàng trùng. Không có socket này, lệnh cần duyệt trong
vài giây đầu lượt chạy bị gateway từ chối ngay vì không có nơi nhận thẻ.
"""
from __future__ import annotations

import asyncio

from app.db.session import SessionLocal
from app.models import Agent, Member, TaskRun
from app.runtime import openclaw_protocol as ocp
from app.runtime.factory import get_runtime
from app.services.runtime_leases import store as lease_store

LEASE = "approval-listener"
STATUS: dict = {"connected": False, "events": 0, "approvals": 0, "error": "", "holder": False}


def _session_of(event: dict) -> str:
    raw = event.get("raw") if isinstance(event.get("raw"), dict) else {}
    req = raw.get("request") if isinstance(raw.get("request"), dict) else {}
    rec = raw.get("record") if isinstance(raw.get("record"), dict) else {}
    rreq = rec.get("request") if isinstance(rec.get("request"), dict) else {}
    return str(req.get("sessionKey") or rreq.get("sessionKey") or raw.get("sessionKey") or event.get("sessionKey") or "")


def record(db, event: dict) -> bool:
    """Ghi một sự kiện duyệt của gateway; trả True nếu thuộc một agent của ClawCompany."""
    from app.services.runtime_stream import ConsumerState, record_approval
    key = _session_of(event)
    if not key.startswith("agent:"):
        return False
    rid = key.split(":", 2)[1]
    agent = db.query(Agent).filter(Agent.runtime_agent_id == rid).first()
    member = db.get(Member, agent.member_id) if agent and agent.member_id else None
    run = db.query(TaskRun).filter(TaskRun.session_key == key).order_by(TaskRun.id.desc()).first()
    org = member.organization_id if member else None
    if org is None:
        return False
    state = ConsumerState(session_key=key, task_id=run.task_id if run else None, organization_id=org)
    record_approval(db, state, event, member=member)
    return True


async def listen_forever(retry_seconds: float = 5.0) -> None:
    rt = get_runtime()
    if not callable(getattr(rt, "listen_approvals", None)):
        return
    while True:
        if lease_store.acquire(LEASE) is None:
            STATUS["holder"] = False
            await asyncio.sleep(30)
            continue
        STATUS["holder"] = True
        try:
            async for event in rt.listen_approvals():
                STATUS["connected"] = True
                if not lease_store.renew(LEASE):
                    break
                if event.get("family") == "_idle":
                    continue
                STATUS["events"] += 1
                if str(event.get("family") or "") in ocp.APPROVAL_EVENTS:
                    db = SessionLocal()
                    try:
                        if record(db, event):
                            STATUS["approvals"] += 1
                    except Exception as exc:  # noqa: BLE001
                        STATUS["error"] = f"record: {exc}"[:300]
                        db.rollback()
                    finally:
                        db.close()
        except asyncio.CancelledError:
            lease_store.release(LEASE)
            raise
        except Exception as exc:  # noqa: BLE001
            STATUS["error"] = f"{type(exc).__name__}: {exc}"[:300]
        STATUS["connected"] = False
        await asyncio.sleep(retry_seconds)
