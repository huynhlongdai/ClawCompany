"""D1.2 — sổ chi phí model và đối chiếu với gateway OpenClaw.

Trước D1.2 ClawCompany có hai "nguồn tiền" nhưng không nguồn nào chứa tiền
model: ``usage_events`` chỉ ghi ``task_dispatch`` (đơn giá 0) và các dòng theo
``usage_meter_rules`` (đơn giá đặt tay); ``task_runs.cost_usd/tokens_*`` luôn 0.
Tiền thật nằm ở gateway: mỗi ``session.message`` của assistant mang
``message.usage`` (token + ``cost.total`` tính theo bảng giá model của gateway),
và ``sessions.usage`` / ``usage.cost`` cộng lại từ transcript.

Module này làm hai việc, đúng một đường code cho mỗi việc:

1. ``record_message_usage`` — khi follower nhận ``session.message`` có usage,
   ghi một dòng ``usage_events`` loại ``model_usage`` (idempotent theo
   ``messageId``) và cộng vào ``task_runs`` đang chạy.
2. ``reconcile`` — so tổng ``usage_events`` của từng phiên task với
   ``sessions.usage`` của gateway, ra câu kết luận "nguồn sự thật là X, độ lệch
   Y%". D2.3 quyết toán ngân sách bằng nguồn được chọn ở đây.

Gateway là nguồn sự thật: nó tính từ transcript nên không phụ thuộc việc
ClawCompany có đang nghe stream hay không. ``usage_events`` là bản sao để gắn
chi phí vào task/seat/khách hàng; nó thiếu khi follower không nghe kịp.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Company, Project, Task, UsageEvent
from app.runtime import openclaw_protocol as ocp
from app.services.company_event_bus import emit_event
from app.services.metering import record_usage

EVENT_TYPE = "model_usage"
SOURCE_OF_TRUTH = "gateway sessions.usage"
# Kế hoạch: D2.3 cần khớp gateway ±5%; lệch > 10% thì usage_events chỉ là số tham khảo.
TOLERANCE_PCT = 5.0
REFERENCE_ONLY_PCT = 10.0


def _int(v) -> int:
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


def _float(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def message_usage(raw: dict) -> dict | None:
    """Đọc usage của một ``session.message`` (assistant) thật từ gateway 2026.9.8.

    Khung: ``{messageId, runId?, sessionKey, message: {role, model, provider,
    usage: {input, output, cacheRead, cacheWrite, totalTokens, cost: {total}}}}``.
    """
    msg = raw.get("message") if isinstance(raw.get("message"), dict) else None
    if not msg or msg.get("role") != "assistant":
        return None
    usage = msg.get("usage") if isinstance(msg.get("usage"), dict) else None
    if not usage:
        return None
    cost = usage.get("cost") if isinstance(usage.get("cost"), dict) else {}
    message_id = str(raw.get("messageId") or msg.get("responseId") or "")
    inp, out = _int(usage.get("input")), _int(usage.get("output"))
    cr, cw = _int(usage.get("cacheRead")), _int(usage.get("cacheWrite"))
    return {
        "message_id": message_id,
        "run_id": str(raw.get("runId") or ""),
        "input": inp, "output": out, "cache_read": cr, "cache_write": cw,
        "total_tokens": _int(usage.get("totalTokens")) or inp + out + cr + cw,
        "cost_usd": _float(cost.get("total")),
        "model": str(msg.get("model") or ""), "provider": str(msg.get("provider") or ""),
    }


def record_message_usage(db: Session, *, organization_id: int, task: Task | None,
                         agent_id: int | None, session_key: str, raw: dict,
                         run=None) -> UsageEvent | None:
    """Ghi một lượt model vào ``usage_events`` + ``task_runs``. Không ghi hai lần."""
    u = message_usage(raw)
    if u is None or not u["message_id"]:
        return None
    marker = f'"message_id": "{u["message_id"]}"'
    exists = (db.query(UsageEvent.id)
              .filter(UsageEvent.organization_id == organization_id,
                      UsageEvent.event_type == EVENT_TYPE,
                      UsageEvent.metadata_json.contains(marker))
              .first())
    if exists:
        return None
    if run is None and task is not None:  # D3.1: lượt định tuyến truyền run của nó
        from app.services import task_lifecycle as lifecycle
        run = lifecycle.current_run(db, task)
    item = record_usage(
        db, organization_id=organization_id, agent_id=agent_id,
        task_id=task.id if task is not None else None,
        runtime_run_id=(task.runtime_run_id if task is not None and task.runtime_run_id else u["run_id"]),
        event_type=EVENT_TYPE, quantity=1, unit="model_call", unit_cost=u["cost_usd"],
        metadata={**u, "session_key": session_key, "task_run_id": run.id if run else None,
                  "source": "gateway.session.message"},
    )
    if run is not None:
        run.tokens_in = (run.tokens_in or 0) + u["input"] + u["cache_read"] + u["cache_write"]
        run.tokens_out = (run.tokens_out or 0) + u["output"]
        run.cost_usd = round((run.cost_usd or 0.0) + u["cost_usd"], 10)
        db.add(run); db.commit()
    return item


# ------------------------------------------------------------------ gateway


def gateway_session_usage(result: dict, session_key: str) -> dict | None:
    """Rút usage của một phiên từ kết quả ``sessions.usage``."""
    for s in result.get("sessions") or []:
        if s.get("key") != session_key:
            continue
        u = s.get("usage") if isinstance(s.get("usage"), dict) else None
        if u is None:
            return None
        counts = u.get("messageCounts") if isinstance(u.get("messageCounts"), dict) else {}
        return {
            "input": _int(u.get("input")), "output": _int(u.get("output")),
            "cache_read": _int(u.get("cacheRead")), "cache_write": _int(u.get("cacheWrite")),
            "total_tokens": _int(u.get("totalTokens")),
            "cost_usd": _float(u.get("totalCost")),
            "missing_cost_entries": _int(u.get("missingCostEntries")),
            "assistant_messages": _int(counts.get("assistant")),
        }
    return None


async def fetch_gateway_usage(runtime, session_key: str, *, attempts: int = 6,
                              wait_seconds: float = 1.0) -> dict:
    """``sessions.usage`` tính lại cache theo transcript; chờ tới khi ``fresh``."""
    last: dict = {}
    for i in range(max(1, attempts)):
        last = await runtime.rpc(ocp.M_SESSIONS_USAGE, {"key": session_key})
        cache = last.get("cacheStatus") if isinstance(last.get("cacheStatus"), dict) else {}
        usage = gateway_session_usage(last, session_key)
        if usage is not None and cache.get("status", "fresh") == "fresh":
            return {"usage": usage, "cache": cache.get("status", "fresh")}
        if i + 1 < attempts:
            await asyncio.sleep(wait_seconds)
    cache = last.get("cacheStatus") if isinstance(last.get("cacheStatus"), dict) else {}
    return {"usage": gateway_session_usage(last, session_key), "cache": cache.get("status", "unknown")}


# ------------------------------------------------------------------ phía ClawCompany


def local_usage(db: Session, organization_id: int, task_id: int) -> dict:
    rows = (db.query(UsageEvent)
            .filter(UsageEvent.organization_id == organization_id,
                    UsageEvent.task_id == task_id).all())
    out = {"cost_usd": 0.0, "total_tokens": 0, "model_calls": 0, "other_events": 0, "other_amount_usd": 0.0}
    for r in rows:
        if r.event_type == EVENT_TYPE:
            meta = json.loads(r.metadata_json or "{}")
            out["cost_usd"] += float(r.amount or 0)
            out["total_tokens"] += _int(meta.get("total_tokens"))
            out["model_calls"] += 1
        else:
            out["other_events"] += 1
            out["other_amount_usd"] += float(r.amount or 0)
    out["cost_usd"] = round(out["cost_usd"], 10)
    return out


def _pct(local: float, gateway: float) -> float:
    if gateway == 0:
        return 0.0 if local == 0 else 100.0
    return round(abs(local - gateway) / gateway * 100.0, 2)


def compare(local: dict, gateway: dict | None) -> dict:
    """So một phiên. Thuần, để test không cần gateway."""
    if gateway is None:
        return {"status": "gateway_missing", "cost_delta_pct": None, "token_delta_pct": None}
    cost_pct = _pct(local["cost_usd"], gateway["cost_usd"])
    token_pct = _pct(local["total_tokens"], gateway["total_tokens"])
    worst = max(cost_pct, token_pct)
    status = "match" if worst == 0 else ("within_tolerance" if worst <= TOLERANCE_PCT else "drift")
    return {"status": status, "cost_delta_usd": round(local["cost_usd"] - gateway["cost_usd"], 10),
            "cost_delta_pct": cost_pct, "token_delta_pct": token_pct,
            "missing_model_calls": max(0, gateway.get("assistant_messages", 0) - local["model_calls"])}


def summarize(rows: list[dict]) -> dict:
    compared = [r for r in rows if r["gateway"] is not None]
    gw = round(sum(r["gateway"]["cost_usd"] for r in compared), 10)
    lc = round(sum(r["local"]["cost_usd"] for r in compared), 10)
    gw_tok = sum(r["gateway"]["total_tokens"] for r in compared)
    lc_tok = sum(r["local"]["total_tokens"] for r in compared)
    pct = _pct(lc, gw) if gw else _pct(lc_tok, gw_tok)
    sentence = (f"Nguồn sự thật là {SOURCE_OF_TRUTH} (gateway OpenClaw), "
                f"độ lệch {pct:.2f}% so với usage_events ({len(compared)} phiên).")
    if pct > REFERENCE_ONLY_PCT:
        sentence += " Lệch > 10%: chặn ngân sách theo số gateway, usage_events chỉ là số tham khảo."
    return {"sessions": len(rows), "compared": len(compared),
            "gateway_cost_usd": gw, "local_cost_usd": lc,
            "gateway_tokens": gw_tok, "local_tokens": lc_tok,
            "delta_pct": pct, "source_of_truth": SOURCE_OF_TRUTH,
            "tolerance_pct": TOLERANCE_PCT, "conclusion": sentence}


async def reconcile(db: Session, runtime, *, organization_id: int,
                    task_ids: list[int] | None = None, limit: int = 20) -> dict:
    q = (db.query(Task).join(Project, Project.id == Task.project_id)
         .join(Company, Company.id == Project.company_id)
         .filter(Company.organization_id == organization_id,
                 Task.runtime_session_key.is_not(None), Task.runtime_session_key != ""))
    if task_ids:
        q = q.filter(Task.id.in_(task_ids))
    tasks = q.order_by(Task.id.desc()).limit(max(1, min(limit, 200))).all()
    rows = []
    for t in tasks:
        local = local_usage(db, organization_id, t.id)
        try:
            gw = await fetch_gateway_usage(runtime, t.runtime_session_key)
            gateway, cache, error = gw["usage"], gw["cache"], ""
        except Exception as exc:  # noqa: BLE001 — báo lỗi theo phiên, không làm hỏng cả báo cáo
            gateway, cache, error = None, "error", str(exc)[:300]
        rows.append({"task_id": t.id, "session_key": t.runtime_session_key, "local": local,
                     "gateway": gateway, "gateway_cache": cache, "error": error,
                     **compare(local, gateway)})
    summary = summarize(rows)
    emit_event(db, organization_id=organization_id, event_type="cost.reconciled", source="cost_ledger",
               aggregate_type="organization", aggregate_id=str(organization_id),
               payload={"reason": summary["conclusion"], **{k: v for k, v in summary.items() if k != "conclusion"},
                        "task_ids": [r["task_id"] for r in rows]})
    return {"generated_at": datetime.utcnow().isoformat(), "summary": summary, "rows": rows}


def org_totals(db: Session, organization_id: int, since: datetime) -> dict:
    cost, n = (db.query(func.coalesce(func.sum(UsageEvent.amount), 0.0), func.count(UsageEvent.id))
               .filter(UsageEvent.organization_id == organization_id, UsageEvent.event_type == EVENT_TYPE,
                       UsageEvent.created_at >= since).one())
    return {"cost_usd": float(cost or 0), "model_calls": int(n or 0)}
