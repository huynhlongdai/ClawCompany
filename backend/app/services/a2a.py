"""A2A (Agent2Agent) — hai chiều, theo giao thức mở: Agent Card + JSON-RPC 2.0 ``message/send``.

* **Thuê ngoài (outbound):** quản lý dán URL Agent Card của một agent bên ngoài → lưu tên, mô tả, kỹ năng,
  endpoint, header xác thực (không bao giờ trả ra). Nhân sự AI trong công ty giao việc cho nó qua tool MCP
  ``company_delegate_external``; mỗi lần gọi ghi sự kiện ``agent.a2a.outbound`` để kiểm toán.
* **Mở cho bên ngoài (inbound):** bật A2A cho một seat → sinh khoá riêng (chỉ hiện 1 lần, lưu hash). Bên ngoài
  đọc ``/api/a2a/agents/<rid>/.well-known/agent-card.json`` rồi gửi ``message/send`` kèm ``Authorization:
  Bearer <khoá>``; tin chạy trong phiên riêng ``agent:<rid>:a2a-<contextId>``, chịu trần chi của seat.
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import Agent, Member
from app.models.a2a import A2AExposure, ExternalAgent
from app.services.company_event_bus import emit_event

SOURCE = "a2a"
TIMEOUT = 120
PROTOCOL_VERSION = "0.3.0"


# ------------------------------------------------------------------ vận chuyển (thay được trong test)

def _http(method: str, url: str, body: dict | None = None, headers: dict | None = None, timeout: int = TIMEOUT) -> tuple[int, Any]:
    data = json.dumps(body).encode() if body is not None else None
    h = {"Accept": "application/json", **({"Content-Type": "application/json"} if data else {}), **(headers or {})}
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 — URL do quản lý nhập
            raw = r.read().decode("utf-8", "replace")
            return r.status, (json.loads(raw) if raw.strip() else None)
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, {"error": raw[:300]}


def _clean_url(u: str) -> str:
    u = (u or "").strip()
    if not re.match(r"^https?://", u):
        raise HTTPException(422, "URL phải bắt đầu bằng http:// hoặc https://")
    return u


def _auth(header: str) -> dict:
    header = (header or "").strip()
    if not header:
        return {}
    if ":" in header and not header.lower().startswith(("bearer ", "basic ")):
        k, v = header.split(":", 1)
        return {k.strip(): v.strip()}
    return {"Authorization": header}


# ------------------------------------------------------------------ thuê ngoài

def ext_public(e: ExternalAgent) -> dict:
    return {"id": e.id, "name": e.name, "description": e.description, "card_url": e.card_url,
            "endpoint_url": e.endpoint_url, "has_auth": bool(e.auth_header), "skills": e.skills or [],
            "enabled": e.enabled, "calls": e.calls, "last_error": e.last_error,
            "last_used_at": e.last_used_at.isoformat() if e.last_used_at else None}


def fetch_card(card_url: str, auth_header: str = "") -> dict:
    url = _clean_url(card_url)
    try:
        code, card = _http("GET", url, headers=_auth(auth_header), timeout=20)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(422, f"Không tải được Agent Card: {exc}"[:300]) from exc
    if code >= 400 or not isinstance(card, dict) or not card.get("name"):
        raise HTTPException(422, f"Agent Card không hợp lệ (HTTP {code}) — cần JSON có name, url")
    return card


def register(db: Session, org_id: int, data: dict) -> dict:
    auth = (data.get("auth_header") or "").strip()
    if data.get("card_url"):
        card = fetch_card(data["card_url"], auth)
        endpoint = card.get("url") or data.get("endpoint_url") or ""
        name = data.get("name") or card.get("name")
        desc = card.get("description") or ""
        skills = [{"id": s.get("id", ""), "name": s.get("name", ""), "description": (s.get("description") or "")[:300]}
                  for s in (card.get("skills") or []) if isinstance(s, dict)][:20]
    else:
        endpoint, name, desc, skills = data.get("endpoint_url") or "", data.get("name") or "", data.get("description") or "", []
    if not name:
        raise HTTPException(422, "Thiếu tên agent")
    e = ExternalAgent(organization_id=org_id, name=name.strip()[:160], description=desc[:2000],
                      card_url=(data.get("card_url") or "").strip(), endpoint_url=_clean_url(endpoint),
                      auth_header=auth, skills=skills, enabled=True)
    db.add(e); db.commit(); db.refresh(e)
    return ext_public(e)


def _ext(db: Session, org_id: int, ext_id: int) -> ExternalAgent:
    e = db.get(ExternalAgent, ext_id)
    if not e or e.organization_id != org_id:
        raise HTTPException(404, "Không có agent ngoài này")
    return e


def list_ext(db: Session, org_id: int) -> list[dict]:
    return [ext_public(e) for e in db.query(ExternalAgent).filter(ExternalAgent.organization_id == org_id)
            .order_by(ExternalAgent.id).all()]


def update_ext(db: Session, org_id: int, ext_id: int, data: dict) -> dict:
    e = _ext(db, org_id, ext_id)
    if data.get("enabled") is not None:
        e.enabled = bool(data["enabled"])
    if data.get("auth_header") is not None:
        e.auth_header = data["auth_header"].strip()
    if data.get("name"):
        e.name = data["name"].strip()[:160]
    db.add(e); db.commit()
    return ext_public(e)


def delete_ext(db: Session, org_id: int, ext_id: int) -> dict:
    e = _ext(db, org_id, ext_id)
    db.delete(e); db.commit()
    return {"deleted": ext_id}


def text_of_parts(parts: list | None) -> str:
    out = []
    for p in parts or []:
        if isinstance(p, dict) and (p.get("kind") or p.get("type")) == "text":
            out.append(p.get("text") or "")
    return "\n".join(x for x in out if x)


def reply_text(result: dict | None) -> str:
    """Rút chữ từ kết quả ``message/send``: Message, hoặc Task (artifacts / status.message)."""
    if not isinstance(result, dict):
        return ""
    if result.get("kind") == "message" or "parts" in result:
        return text_of_parts(result.get("parts"))
    texts = [text_of_parts(a.get("parts")) for a in (result.get("artifacts") or []) if isinstance(a, dict)]
    if not any(texts):
        texts.append(text_of_parts(((result.get("status") or {}).get("message") or {}).get("parts")))
    return "\n".join(t for t in texts if t)


def send(db: Session, org_id: int, ext_id: int, text: str, *, context_id: str | None = None,
         actor: Member | None = None, task_run_id: int | None = None) -> dict:
    e = _ext(db, org_id, ext_id)
    if not e.enabled:
        raise HTTPException(409, f"Agent ngoài {e.name} đang tắt")
    msg = {"role": "user", "parts": [{"kind": "text", "text": text}], "messageId": uuid.uuid4().hex, "kind": "message"}
    if context_id:
        msg["contextId"] = context_id
    body = {"jsonrpc": "2.0", "id": uuid.uuid4().hex, "method": "message/send",
            "params": {"message": msg, "configuration": {"blocking": True, "acceptedOutputModes": ["text/plain"]}}}
    started = time.monotonic()
    err, answer, ctx_out, state = "", "", context_id or "", ""
    try:
        code, res = _http("POST", e.endpoint_url, body, headers=_auth(e.auth_header))
        if not isinstance(res, dict):
            err = f"HTTP {code}: phản hồi không phải JSON"
        elif res.get("error"):
            err = f"{(res['error'] or {}).get('code', code)}: {(res['error'] or {}).get('message', '')}"[:300] \
                if isinstance(res["error"], dict) else str(res["error"])[:300]
        else:
            result = res.get("result") or {}
            answer = reply_text(result)
            ctx_out = result.get("contextId") or ctx_out
            state = ((result.get("status") or {}).get("state")) or ("completed" if answer else "")
    except Exception as exc:  # noqa: BLE001
        err = f"{type(exc).__name__}: {exc}"[:300]
    e.calls = (e.calls or 0) + 1
    e.last_used_at = datetime.utcnow()
    e.last_error = err
    db.add(e); db.commit()
    emit_event(db, organization_id=org_id, event_type="agent.a2a.outbound", source=SOURCE,
               company_id=actor.company_id if actor else None, aggregate_type="external_agent", aggregate_id=str(e.id),
               actor_member_id=actor.id if actor else None,
               payload={"external_agent": e.name, "chars_out": len(text), "chars_in": len(answer), "error": err,
                        "seconds": round(time.monotonic() - started, 1), "context_id": ctx_out, "task_run_id": task_run_id})
    if err and not answer:
        # 424 Failed Dependency (M2d.4): máy chủ ClawCompany vẫn ổn — agent bên kia từ chối/lỗi (vd. hết trần chi
        # của seat, hết quota model). Trước đây 502 khiến UI báo "Máy chủ gặp lỗi, thử lại sau ít giây" — sai hướng.
        raise HTTPException(424, f"{e.name} không trả lời được: {err}")
    return {"agent": e.name, "reply": answer[:8000], "context_id": ctx_out, "state": state, **({"warning": err} if err else {})}


# ------------------------------------------------------------------ mở cho bên ngoài

def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def exposure_public(x: A2AExposure | None, ag: Agent, base_url: str = "") -> dict:
    rid = ag.runtime_agent_id or ""
    base = base_url.rstrip("/")
    return {"agent_id": ag.id, "runtime_agent_id": rid, "enabled": bool(x and x.enabled),
            "token_prefix": x.token_prefix if x else "", "calls": x.calls if x else 0,
            "card_url": f"{base}/api/a2a/agents/{rid}/.well-known/agent-card.json" if rid else "",
            "endpoint_url": f"{base}/api/a2a/agents/{rid}" if rid else ""}


def expose(db: Session, org_id: int, agent_id: int, *, enabled: bool, rotate: bool = False, base_url: str = "") -> dict:
    from app.services import agent_hr
    ag, _m = agent_hr.seat(db, org_id, agent_id)
    if not (ag.runtime_agent_id or "").strip():
        raise HTTPException(409, "Seat chưa có agent trên gateway")
    x = db.query(A2AExposure).filter(A2AExposure.agent_id == ag.id).first()
    token = None
    if x is None:
        x = A2AExposure(organization_id=org_id, agent_id=ag.id)
        rotate = True
    if rotate and enabled:
        token = "cca2a_" + secrets.token_urlsafe(32)
        x.token_prefix, x.token_hash = token[:12], _hash(token)
    x.enabled = enabled
    db.add(x); db.commit()
    out = exposure_public(x, ag, base_url)
    if token:
        out["token"] = token          # chỉ hiện 1 lần
    return out


def exposure_status(db: Session, org_id: int, agent_id: int, base_url: str = "") -> dict:
    from app.services import agent_hr
    ag, _m = agent_hr.seat(db, org_id, agent_id)
    return exposure_public(db.query(A2AExposure).filter(A2AExposure.agent_id == ag.id).first(), ag, base_url)


def _exposed(db: Session, rid: str) -> tuple[A2AExposure, Agent, Member]:
    ag = db.query(Agent).filter(Agent.runtime_agent_id == rid).first()
    x = db.query(A2AExposure).filter(A2AExposure.agent_id == ag.id).first() if ag else None
    if not ag or not x or not x.enabled or ag.lifecycle in ("retired", "runtime_missing"):
        raise HTTPException(404, "Agent không mở A2A")
    return x, ag, db.get(Member, ag.member_id)


def agent_card(db: Session, rid: str, base_url: str) -> dict:
    from app.models import Company
    x, ag, m = _exposed(db, rid)
    co = db.get(Company, m.company_id) if m.company_id else None
    base = base_url.rstrip("/")
    return {
        "protocolVersion": PROTOCOL_VERSION, "name": f"{m.name} — {co.name}" if co else m.name,
        "description": f"{m.role or 'Nhân sự AI'}{' tại ' + co.name if co else ''}. Trả lời bằng tiếng Việt.",
        "url": f"{base}/api/a2a/agents/{rid}", "preferredTransport": "JSONRPC", "version": "1.0.0",
        "capabilities": {"streaming": False, "pushNotifications": False},
        "defaultInputModes": ["text/plain"], "defaultOutputModes": ["text/plain"],
        "securitySchemes": {"bearer": {"type": "http", "scheme": "bearer"}}, "security": [{"bearer": []}],
        "skills": [{"id": "chat", "name": m.role or "Trợ giúp", "description": f"Hỏi/giao việc cho {m.name}",
                    "tags": ["vi"], "examples": []}],
    }


def _rpc_error(rid_: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": rid_, "error": {"code": code, "message": message}}


async def handle_rpc(db: Session, runtime: Any, rid: str, body: Any, authorization: str) -> dict:
    from app.services import seat_limits
    req_id = body.get("id") if isinstance(body, dict) else None
    try:
        x, ag, m = _exposed(db, rid)
    except HTTPException:
        return _rpc_error(req_id, -32001, "Agent không mở A2A")
    tok = (authorization or "").removeprefix("Bearer ").strip()
    if not tok or _hash(tok) != x.token_hash:
        return _rpc_error(req_id, -32004, "Sai hoặc thiếu khoá A2A")
    if not isinstance(body, dict) or body.get("jsonrpc") != "2.0":
        return _rpc_error(req_id, -32600, "Yêu cầu JSON-RPC không hợp lệ")
    if body.get("method") != "message/send":
        return _rpc_error(req_id, -32601, f"Chưa hỗ trợ phương thức {body.get('method')} (chỉ message/send)")
    msg = (body.get("params") or {}).get("message") or {}
    text = text_of_parts(msg.get("parts"))
    if not text.strip():
        return _rpc_error(req_id, -32602, "Tin nhắn không có phần chữ")
    blocked = seat_limits.check(db, m)
    if blocked:
        return _rpc_error(req_id, -32003, blocked)
    if not getattr(runtime, "chat_stream", None):
        return _rpc_error(req_id, -32603, "Gateway không hỗ trợ")
    ctx = re.sub(r"[^A-Za-z0-9_-]", "", str(msg.get("contextId") or ""))[:48] or uuid.uuid4().hex[:16]
    key = f"agent:{rid}:a2a-{ctx}"
    answer, err = "", ""
    try:
        async for ev in runtime.chat_stream(rid, text[:12000], session_key=key, timeout_seconds=TIMEOUT):
            if ev["kind"] == "delta":
                answer = ev["text"]
            elif ev["kind"] == "final":
                answer = ev.get("text") or answer
                break
            elif ev["kind"] != "tool":
                err = str(ev.get("message") or "lỗi"); answer = ev.get("text") or answer
                break
    except Exception as exc:  # noqa: BLE001
        err = f"gateway: {exc}"[:300]
    x.calls = (x.calls or 0) + 1
    x.last_used_at = datetime.utcnow()
    db.add(x); db.commit()
    lease_row = None
    try:   # R2: ghế thuê → đo phiên A2A (usage thật của gateway) + ghi người gọi
        from app.services import seat_leases
        lease_row = await seat_leases.meter_session(db, runtime, m, ag, key, channel="a2a", caller=f"a2a:exposure:{x.id}:{ctx}")
    except Exception as exc:  # noqa: BLE001
        print(f"[lease] a2a meter {exc}")
    emit_event(db, organization_id=m.organization_id, event_type="agent.a2a.inbound", source=SOURCE,
               company_id=m.company_id, aggregate_type="member", aggregate_id=str(m.id), actor_member_id=m.id,
               payload={"session_key": key, "chars_in": len(text), "chars_out": len(answer), "error": err,
                        "lease_id": lease_row.lease_id if lease_row is not None else None,
                        "billed_usd": lease_row.billed_usd if lease_row is not None else None})
    if not answer:
        return _rpc_error(req_id, -32603, err or "Agent không trả lời")
    return {"jsonrpc": "2.0", "id": req_id,
            "result": {"kind": "message", "role": "agent", "messageId": uuid.uuid4().hex, "contextId": ctx,
                       "parts": [{"kind": "text", "text": answer}]}}
