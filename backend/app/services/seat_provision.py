"""Giai đoạn A — cho agent "sống thật" trên gateway.

Hai việc, tách nhau vì phạm vi khác nhau:

``provision_seat`` (một ghế, sửa B3 + B7)
    Tạo agent trên gateway nếu chưa có (``agents.create``), đặt tên/emoji, rồi
    ghi 5 file tiếng Việt sinh từ hồ sơ. File OpenClaw seed sẵn (SOUL/AGENTS/USER
    tiếng Anh, "untracked") được thay; file đã có bản ClawCompany thì đi qua
    ``agent_hr._regen`` — tôn trọng bản chỉnh tay và bản bị sửa trên gateway.
    MEMORY.md là của agent: chỉ ghi khi gateway chưa có.

``wire_gateway`` (cả tổ chức, sửa B5 + B9 + tầng model)
    MỘT ``config.patch`` duy nhất cho mọi ghế, vì gateway giới hạn tần suất ghi
    config và vì danh sách chặn MCP của mỗi ghế phụ thuộc vào các ghế khác:

    * ``mcp.servers["cc-<ghế>"]``: máy chủ MCP công ty, header là API key RIÊNG
      của ghế đó (MCP biết ai gọi mà không tin tham số model điền).
      ``mcp.servers`` là cấu hình toàn gateway, nên mỗi ghế chặn máy chủ của
      các ghế khác bằng ``tools.deny: ["cc-<ghế khác>__*"]`` — theo tài liệu
      9.8, chặn cả máy chủ thì gateway không kết nối luôn.
    * ``models.providers.custom.models``: thêm các model của 4 tầng + fallback.
    * ``agents.entries.<ghế>``: model chính/fallback, ``utilityModel`` và
      ``heartbeat.model`` = T1.
    * ``memory.search``: embedding ``text-embedding-3-small`` qua cùng endpoint
      và cùng SecretRef với provider chat (B9 — trước đó provider là ``openai``
      không có key nên index "dirty", vector search "paused").
    * W0 cách ly phiên (``session_isolation_values``): ``tools.sessions.visibility``
      = ``self``, ``tools.agentToAgent.enabled`` = ``false`` (hai khoá TOÀN gateway
      trên 9.8 — không có bản theo agent) và ``agents.entries.<ghế>.subagents.
      allowAgents`` = ``[<ghế>]``.
"""
from __future__ import annotations

import json
import secrets
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import pwd_context
from app.models import Agent, Member
from app.models.auth import APIKey
from app.runtime import openclaw_protocol as ocp
from app.services import agent_hr, model_routing
from app.services.audit import log_event
from app.services.openclaw_config import ConfigError, ConfigRegistry

MCP_PREFIX = "cc-"
MCP_KEY_NAME = "mcp:{rid}"
EMBED_MODEL = "text-embedding-3-small"


def mcp_server_name(rid: str) -> str:
    return f"{MCP_PREFIX}{rid}"


def mcp_scopes() -> list[str]:
    from app.services.company_mcp import TOOLS
    return sorted({t.scope for t in TOOLS.values()})


# --------------------------------------------------------------- một ghế

async def provision_seat(db: Session, principal, org_id: int, runtime: Any, agent_id: int) -> dict:
    if not agent_hr._has_rpc(runtime):
        raise HTTPException(409, "Runtime hiện tại không phải gateway OpenClaw thật (OPENCLAW_MODE=native)")
    agent, member = agent_hr.seat(db, org_id, agent_id)
    if agent.lifecycle == "retired":
        raise HTTPException(409, "Nhân sự đã nghỉ việc — không tạo lại trên gateway")
    rid = (agent.runtime_agent_id or "").strip()
    if not rid:
        raise HTTPException(409, "Ghế chưa có runtime_agent_id")
    out: dict[str, Any] = {"agent_id": agent.id, "runtime_agent_id": rid, "steps": [], "warnings": []}

    model = agent.model if agent_hr.is_runtime_model_ref(agent.model) else ""
    created = await runtime.create_agent(rid, {"model": model})
    out["steps"].append({"step": "agent", "status": created.get("status")})
    if not created.get("bound"):
        raise HTTPException(502, {"message": "Gateway không tạo được agent", **created, **out})
    if agent.lifecycle == "runtime_missing":
        agent.lifecycle = "active"; db.add(agent); db.commit()

    spec = agent_hr.hire_spec(db, agent)
    upd: dict[str, Any] = {"agentId": rid, "name": member.name}
    emoji = spec.get("emoji") or agent_hr.PERSONALITIES.get(
        spec.get("personality") or agent_hr.DEFAULT_PERSONALITY, {}).get("emoji")
    if emoji:
        upd["emoji"] = emoji
    try:
        await agent_hr._agents_update(db, runtime, agent, upd, principal.user_id)
        out["steps"].append({"step": "identity", "status": "ok"})
    except Exception as exc:  # noqa: BLE001
        out["warnings"].append(f"agents.update lỗi: {exc}")

    files = agent_hr.render_files(
        name=member.name, role=member.role,
        personality=spec.get("personality") or agent_hr.DEFAULT_PERSONALITY,
        emoji=spec.get("emoji") or "", job_description=spec.get("job_description") or "",
        manager_notes=spec.get("manager_notes") or "", monthly_budget=spec.get("monthly_budget"),
        address_style=spec.get("address_style") or agent_hr.DEFAULT_ADDRESS_STYLE,
        daily_cap_usd=spec.get("daily_cap_usd"),
        **agent_hr._ctx(db, member))
    snaps = agent_hr.snapshots(db, agent.id)
    generated = dict(spec.get("generated") or {})
    tracked: list[str] = []
    file_results: dict[str, dict] = {}
    for name in agent_hr.SEAT_FILES:
        if name not in files:
            continue
        if name in snaps:
            tracked.append(name)
            continue
        cur = await agent_hr._get_file(runtime, rid, name)
        if name in agent_hr.AGENT_OWNED_FILES and not cur["missing"] and cur["content"].strip():
            # Ký ức agent tự ghi: nhận làm bản ClawCompany, không ghi đè.
            agent_hr.put_snapshot(db, agent.id, name, cur["content"], source="gateway_accepted",
                                  user_id=principal.user_id, hash_=cur["hash"])
            file_results[name] = {"written": False, "reason": "agent_memory_kept"}
            continue
        try:
            h = await agent_hr._set_file(runtime, rid, name, files[name],
                                         expected_hash=None if cur["missing"] else cur["hash"])
        except Exception as exc:  # noqa: BLE001
            file_results[name] = {"written": False, "reason": "write_failed", "message": str(exc)[:300]}
            continue
        agent_hr.put_snapshot(db, agent.id, name, files[name], user_id=principal.user_id, hash_=h)
        generated[name] = h
        file_results[name] = {"written": True, "replaced_untracked": not cur["missing"]}
    spec["generated"] = generated
    agent_hr._save_spec(db, agent, spec); db.commit()
    if tracked:
        file_results.update(await agent_hr._regen(db, runtime, agent, member, tuple(tracked),
                                                  principal.user_id))
    out["files"] = file_results
    out["steps"].append({"step": "files", "status": "ok",
                         "written": sorted(n for n, r in file_results.items() if r.get("written"))})
    log_event(db, org_id, "agent.provision", "agents", agent.id, actor_name=f"user:{principal.user_id}",
              payload={"runtime_agent_id": rid, "files": out["steps"][-1]["written"],
                       "created": created.get("status")})
    return out


# --------------------------------------------------------------- cả tổ chức

def _mint_seat_key(db: Session, org_id: int, member: Member, rid: str, user_id: int | None) -> str:
    """Key MCP mới cho ghế; key MCP cũ của ghế bị vô hiệu (xoay vòng)."""
    name = MCP_KEY_NAME.format(rid=rid)
    for old in db.query(APIKey).filter(APIKey.organization_id == org_id, APIKey.member_id == member.id,
                                       APIKey.name == name, APIKey.is_active == True).all():  # noqa: E712
        old.is_active = False; db.add(old)
    raw = "cc_" + secrets.token_urlsafe(32)
    db.add(APIKey(organization_id=org_id, member_id=member.id, name=name, key_prefix=raw[:12],
                  key_hash=pwd_context.hash(raw), scopes=json.dumps(mcp_scopes()),
                  created_by_user_id=user_id))
    return raw


# Ghế thừa hành không cần chạy lệnh shell: chặn exec/process ở tầng gateway.
# (Sandbox thật cần docker trong container gateway — chưa có, và mount
# docker.sock cho nó là trao quyền root máy chủ; để anh quyết riêng.)
EXECUTOR_DENY = ("exec", "process")
_MANAGED = set(EXECUTOR_DENY)


def seat_deny(db: Session, member: Member, rid: str, all_servers: list[str], current: list) -> list[str]:
    """``tools.deny`` của một ghế = phần người khác đặt + phần ClawCompany quản.

    Phần quản (tính lại mỗi lần, nên bỏ "Tắt" thì gateway cũng mở lại):
    * máy chủ MCP của các ghế khác (``cc-<ghế khác>__*``);
    * tool công ty đang ở mức ``off`` với ghế này (``cc-<ghế>__<tool>``) —
      tầng 1 khớp tầng 2 (B-tool: "Tắt" phải thành ``tools.deny``);
    * ``exec``/``process`` khi quyền ``gateway_shell`` của ghế là ``off``.
    """
    from app.services import tool_permissions
    from app.services.company_mcp import TOOLS
    own = mcp_server_name(rid)
    keep = [d for d in (current or []) if not str(d).startswith(MCP_PREFIX) and d not in _MANAGED]
    managed = [f"{s}__*" for s in all_servers if s != own]
    managed += [f"{own}__{t}" for t in sorted(TOOLS) if tool_permissions.resolve(db, member, t)[0] == "off"]
    if tool_permissions.resolve(db, member, tool_permissions.SHELL)[0] == "off":
        managed += list(EXECUTOR_DENY)
    return keep + managed


# Mức quyền shell → exec.mode của OpenClaw. "ask" = danh sách cho phép + hỏi
# khi lệnh lạ; không có ai duyệt thì askFallback mặc định là từ chối.
SHELL_MODE = {"allowed": "full", "ask": "ask", "off": "deny"}


def seat_exec_mode(db: Session, member: Member) -> str:
    from app.services import tool_permissions
    return SHELL_MODE[tool_permissions.resolve(db, member, tool_permissions.SHELL)[0]]


def _embed_remote(config: dict) -> dict | None:
    custom = (((config.get("models") or {}).get("providers") or {}).get("custom")) or {}
    base = custom.get("baseUrl")
    key = custom.get("apiKey")
    if not base or not key:
        return None
    if isinstance(key, dict) and key.get("id") == "__OPENCLAW_REDACTED__":
        # config.get che id; SecretRef của bản cài này luôn là singleValue "value"
        # (tools/openclaw_setup.sh). Ghi lại đúng tham chiếu, không bao giờ là key.
        key = {**key, "id": "value"}
    return {"baseUrl": base, "apiKey": key}


def _same_remote(cur: dict, want: dict) -> bool:
    """So sánh có tính tới việc config.get che ``id`` của SecretRef."""
    if cur.get("baseUrl") != want.get("baseUrl"):
        return False
    a, b = cur.get("apiKey"), want.get("apiKey")
    if isinstance(a, dict) and isinstance(b, dict):
        return a.get("source") == b.get("source") and a.get("provider") == b.get("provider") \
            and a.get("id") in (b.get("id"), "__OPENCLAW_REDACTED__")
    return a == b


def _merge_models(existing: list, wanted: list) -> list:
    by_id = {m.get("id"): m for m in existing if isinstance(m, dict)}
    for m in wanted:
        by_id[m["id"]] = {**by_id.get(m["id"], {}), **m}
    return list(by_id.values())


# --------------------------------------------------------------- W0 cách ly phiên

# Đo trên gateway thật 2026.9.8 (config.schema.lookup, 17/10/2026 — docs/work-module-review.md §W0):
#   tools.sessions.visibility  enum self|tree|agent|all, mặc định "all" = mọi phiên trên gateway, kể cả agent khác;
#   tools.agentToAgent.enabled mặc định true, allow rỗng = mọi cặp agent;
#   agents.entries.*.subagents.allowAgents  mặc định "chỉ chính agent đó" (docs sessions-and-subagents).
# Hai khoá đầu chỉ có ở gốc ``tools`` (agents.entries.*.tools không có ``sessions``/``agentToAgent``) nên đặt cho
# cả gateway: bên cho thuê và bên thuê ghế (R2) dùng chung gateway không đọc/nhắn được phiên của nhau. Mọi trao
# đổi giữa nhân sự đi qua task/bàn giao/A2A của ClawCompany (có chủ, có sổ, có chi phí). Cả ba khoá reloadKind=hot.
SESSION_VISIBILITY = "self"
ISOLATION_GLOBAL: dict[tuple, Any] = {
    ("tools", "sessions", "visibility"): SESSION_VISIBILITY,
    ("tools", "agentToAgent", "enabled"): False,
}


def _get_path(config: dict, path: tuple) -> Any:
    cur: Any = config
    for k in path:
        if not isinstance(cur, dict) or k not in cur:
            return None
        cur = cur[k]
    return cur


def session_isolation_values(config: dict, rids: list[str]) -> tuple[dict[tuple, Any], list[tuple]]:
    """Các giá trị cần ghi (chỉ phần đang lệch) + replace_paths cho mảng allowAgents. Không có gì lệch → ({}, [])."""
    values: dict[tuple, Any] = {}
    replace: list[tuple] = []
    for path, want in ISOLATION_GLOBAL.items():
        if _get_path(config or {}, path) != want:
            values[path] = want
    for rid in sorted(set(r for r in rids if r)):
        path = ("agents", "entries", rid, "subagents", "allowAgents")
        if _get_path(config or {}, path) != [rid]:
            values[path] = [rid]
            replace.append(path)
    return values, replace


def session_isolation_report(config: dict, rids: list[str]) -> dict:
    """Đọc-chỉ: gateway đang ở đâu so với mức an toàn (giá trị None = chưa đặt → mặc định mở của OpenClaw)."""
    values, _ = session_isolation_values(config, rids)
    drift = [{"path": ".".join(p), "current": _get_path(config or {}, p), "want": v} for p, v in values.items()]
    return {"ok": not drift, "drift": drift,
            "visibility": _get_path(config or {}, ("tools", "sessions", "visibility")),
            "agent_to_agent_enabled": _get_path(config or {}, ("tools", "agentToAgent", "enabled")),
            "seats": len(set(r for r in rids if r))}


def company_seat_rids(db: Session, org_id: int | None = None) -> list[str]:
    q = select(Agent.runtime_agent_id).join(Member, Agent.member_id == Member.id).where(
        Agent.runtime_agent_id.isnot(None), Agent.runtime_agent_id != "", Agent.lifecycle != "retired")
    if org_id is not None:
        q = q.where(Member.organization_id == org_id)
    return sorted({r for (r,) in db.execute(q).all() if r})


async def ensure_session_isolation(db: Session, runtime: Any, *, dry_run: bool = False) -> dict:
    """Đặt ba khoá cách ly cho mọi ghế ClawCompany đang có trên gateway (mọi tổ chức — khoá gốc là toàn gateway).

    Idempotent: chỉ patch phần lệch; đã đúng → không gọi config.patch."""
    if not agent_hr._has_rpc(runtime):
        return {"skipped": "runtime không phải gateway thật"}
    registry = ConfigRegistry(runtime)
    snap = await registry.snapshot()
    config = snap["config"] or {}
    try:
        roster = {agent_hr._rid_of(a) for a in await runtime.list_agents()}
    except Exception:  # noqa: BLE001 — không đọc được roster thì chỉ đặt khoá gốc
        roster = set()
    rids = [r for r in company_seat_rids(db) if r in roster]
    values, replace = session_isolation_values(config, rids)
    if not values:
        return {"changed": [], **session_isolation_report(config, rids)}
    result = await registry.patch(values, base_hash=snap["hash"] or None, replace_paths=replace,
                                  note="ClawCompany W0 · cách ly phiên giữa agent", dry_run=dry_run)
    return {"changed": [".".join(p) for p in values], "dry_run": dry_run,
            "changed_paths": result.get("changed_paths"), "seats": len(rids)}


def schedule_session_isolation() -> None:
    """Chạy nền khi API khởi động (native): gateway mới dựng/khôi phục cũng về mức an toàn mà không cần ai bấm."""
    import asyncio
    import logging
    from app.db.session import SessionLocal
    from app.runtime.factory import get_runtime
    runtime = get_runtime()
    if not agent_hr._has_rpc(runtime):
        return
    db = SessionLocal()
    try:
        out = asyncio.run(ensure_session_isolation(db, runtime))
        logging.getLogger(__name__).info("W0 session isolation: %s", out)
    except Exception:  # noqa: BLE001
        logging.getLogger(__name__).exception("W0: không đặt được cách ly phiên trên gateway")
    finally:
        db.close()


async def wire_gateway(db: Session, principal, org_id: int, runtime: Any, *, mcp_url: str | None = None,
                       models: bool = True, memory: bool = True, mcp: bool = True,
                       seat_models: bool = True, allow_restart: bool = False,
                       dry_run: bool = False) -> dict:
    if not agent_hr._has_rpc(runtime):
        raise HTTPException(409, "Runtime hiện tại không phải gateway OpenClaw thật (OPENCLAW_MODE=native)")
    registry = ConfigRegistry(runtime)
    snap = await registry.snapshot()
    config = snap["config"] or {}
    try:
        roster = {agent_hr._rid_of(a) for a in await runtime.list_agents()}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"Không đọc được roster gateway: {exc}") from exc
    rows = db.execute(
        select(Agent, Member).join(Member, Agent.member_id == Member.id)
        .where(Member.organization_id == org_id, Agent.runtime_agent_id.isnot(None),
               Agent.runtime_agent_id != "", Agent.lifecycle != "retired")
    ).all()
    seats = [(a, m) for a, m in rows if a.runtime_agent_id in roster]
    skipped = sorted(a.runtime_agent_id for a, _ in rows if a.runtime_agent_id not in roster)
    entries = ((config.get("agents") or {}).get("entries")) or {}
    url = mcp_url or settings.clawcompany_mcp_url

    values: dict[tuple, Any] = {}
    replace: list[tuple] = []
    keys: dict[str, str] = {}
    summary: dict[str, Any] = {"seats": [a.runtime_agent_id for a, _ in seats], "skipped_not_on_gateway": skipped}

    if models:
        current = ((((config.get("models") or {}).get("providers") or {}).get("custom")) or {}).get("models") or []
        values[("models", "providers", "custom", "models")] = _merge_models(current, model_routing.provider_models())
        replace.append(("models", "providers", "custom", "models"))
        summary["models"] = [m["id"] for m in model_routing.provider_models()]

    if memory:
        remote = _embed_remote(config)
        cur = ((config.get("memory") or {}).get("search")) or {}
        same = remote and cur.get("provider") == "openai" and cur.get("model") == EMBED_MODEL \
            and _same_remote(cur.get("remote") or {}, remote)
        if same:
            # Không gửi lại: memory.search là đường cần khởi động lại gateway,
            # gửi giá trị y hệt vẫn bị tính là "chạm" → 409 vô cớ khi nối lại MCP.
            summary["memory"] = "đã đúng, không đổi"
        elif remote:
            values[("memory", "search", "provider")] = "openai"
            values[("memory", "search", "model")] = EMBED_MODEL
            values[("memory", "search", "remote")] = remote
            summary["memory"] = {"provider": "openai", "model": EMBED_MODEL, "baseUrl": remote["baseUrl"]}
        else:
            summary["memory"] = "bỏ qua: provider custom chưa có baseUrl/apiKey"

    all_servers = [mcp_server_name(a.runtime_agent_id) for a, _ in seats]
    for agent, member in seats:
        rid = agent.runtime_agent_id
        entry = entries.get(rid) or {}
        if mcp:
            key = "<sẽ sinh khi chạy thật>" if dry_run else _mint_seat_key(db, org_id, member, rid, principal.user_id)
            keys[rid] = key
            values[("mcp", "servers", mcp_server_name(rid))] = {
                "enabled": True, "url": url, "transport": "streamable-http",
                "headers": {"X-API-Key": key, "X-ClawCompany-Seat": rid},
                "toolFilter": {"include": ["company_*"]},
                "connectionTimeoutMs": 10000, "requestTimeoutMs": 30000,
            }
            path = ("agents", "entries", rid, "tools", "deny")
            values[path] = seat_deny(db, member, rid, all_servers,
                                     ((entry.get("tools") or {}).get("deny")) or [])
            replace.append(path)
            values[("agents", "entries", rid, "tools", "elevated", "enabled")] = False
            values[("agents", "entries", rid, "tools", "exec", "mode")] = seat_exec_mode(db, member)
            # Tool đọc/ghi file chỉ trong workspace của ghế: không đọc được
            # openclaw.json (nơi có key MCP của mọi ghế) hay workspace ghế khác.
            # Chuyển key sang .env không giúp gì — OpenClaw ghi rõ .env cũng là
            # file agent đọc được; ranh giới thật là giới hạn đường dẫn này.
            values[("agents", "entries", rid, "tools", "fs", "workspaceOnly")] = True
        if seat_models:
            from app.services import tool_permissions
            cfg = model_routing.seat_model_config(
                member.role or "", lead=tool_permissions.seat_tier(db, member) == "lead",
                fallback=((agent_hr.hire_spec(db, agent).get("model_policy") or {}).get("fallback")))
            values[("agents", "entries", rid, "model")] = cfg["model"]
            values[("agents", "entries", rid, "utilityModel")] = cfg["utilityModel"]
            values[("agents", "entries", rid, "heartbeat", "model")] = cfg["heartbeat"]["model"]
            values[("agents", "entries", rid, "heartbeat", "lightContext")] = True
            if isinstance(entry.get("model"), dict) and entry["model"].get("fallbacks"):
                replace.append(("agents", "entries", rid, "model", "fallbacks"))
            if not dry_run:
                agent.model = cfg["model"]["primary"]; db.add(agent)

    # W0: mỗi lần nối dây cũng kéo gateway về mức cách ly phiên (chỉ phần lệch).
    iso_values, iso_replace = session_isolation_values(config, [a.runtime_agent_id for a, _ in seats])
    values.update(iso_values)
    replace += iso_replace
    summary["session_isolation"] = [".".join(p) for p in iso_values] or "đã đúng, không đổi"

    if not values:
        raise HTTPException(422, "Không có gì để ghi")
    try:
        result = await registry.patch(values, base_hash=snap["hash"] or None, replace_paths=replace,
                                      note=f"ClawCompany giai đoạn A · {len(seats)} ghế",
                                      allow_restart=allow_restart, dry_run=dry_run)
    except ConfigError as exc:
        db.rollback()
        raise HTTPException(409, {"message": str(exc), **exc.as_dict()}) from exc
    if dry_run:
        db.rollback()
    else:
        db.commit()
        log_event(db, org_id, "gateway.wired", "organization", org_id,
                  actor_name=f"user:{principal.user_id}",
                  payload={**summary, "changed_paths": result.get("changed_paths", [])[:50]})
    # Không bao giờ trả key ra ngoài: nó đã nằm trong config gateway.
    return {**summary, "mcp_servers": all_servers if mcp else [],
            "dry_run": dry_run, "changed_paths": result.get("changed_paths"),
            "requires_restart": result.get("requires_restart") or (result.get("reload") or {}).get("requires_restart"),
            "reload": result.get("reload")}


async def provision_all(db: Session, principal, org_id: int, runtime: Any, **wire_kwargs) -> dict:
    rows = db.execute(
        select(Agent.id, Agent.runtime_agent_id).join(Member, Agent.member_id == Member.id)
        .where(Member.organization_id == org_id, Member.member_type == "agent",
               Agent.runtime_agent_id.isnot(None), Agent.runtime_agent_id != "",
               Agent.lifecycle != "retired")
    ).all()
    seats = []
    for agent_id, rid in rows:
        try:
            r = await provision_seat(db, principal, org_id, runtime, agent_id)
            seats.append({"runtime_agent_id": rid, "ok": True,
                          "written": r["steps"][-1].get("written", []), "warnings": r["warnings"]})
        except HTTPException as exc:
            seats.append({"runtime_agent_id": rid, "ok": False, "error": exc.detail})
    wired = await wire_gateway(db, principal, org_id, runtime, **wire_kwargs)
    return {"seats": seats, "gateway": wired}


async def sync_tool_policy(db: Session, org_id: int, runtime: Any) -> dict:
    """Chỉ tính lại ``tools.deny`` của mọi ghế đã nối MCP. Không xoay key.

    Gọi sau khi đổi mức quyền tool: "Tắt" trên ClawCompany có hiệu lực ở gateway
    (tool biến mất khỏi agent), không chỉ bị từ chối lúc gọi.
    """
    if not agent_hr._has_rpc(runtime):
        return {"skipped": "runtime không phải gateway thật"}
    registry = ConfigRegistry(runtime)
    snap = await registry.snapshot()
    config = snap["config"] or {}
    servers = set(((config.get("mcp") or {}).get("servers") or {}).keys())
    entries = ((config.get("agents") or {}).get("entries")) or {}
    rows = db.execute(
        select(Agent, Member).join(Member, Agent.member_id == Member.id)
        .where(Member.organization_id == org_id, Agent.lifecycle != "retired")).all()
    wired = [(a, m) for a, m in rows if mcp_server_name(a.runtime_agent_id or "") in servers]
    all_servers = [mcp_server_name(a.runtime_agent_id) for a, _ in wired]
    values: dict[tuple, Any] = {}
    replace: list[tuple] = []
    for agent, member in wired:
        rid = agent.runtime_agent_id
        current = (((entries.get(rid) or {}).get("tools") or {}).get("deny")) or []
        new = seat_deny(db, member, rid, all_servers, current)
        if new != current:
            path = ("agents", "entries", rid, "tools", "deny")
            values[path] = new
            replace.append(path)
        mode = seat_exec_mode(db, member)
        if (((entries.get(rid) or {}).get("tools") or {}).get("exec") or {}).get("mode") != mode:
            values[("agents", "entries", rid, "tools", "exec", "mode")] = mode
    if not values:
        return {"changed": []}
    result = await registry.patch(values, base_hash=snap["hash"] or None, replace_paths=replace,
                                  note="ClawCompany · đồng bộ quyền tool")
    return {"changed": sorted({p[2] for p in values}), "changed_paths": result.get("changed_paths")}


def schedule_tool_policy_sync(org_id: int) -> None:
    """Chạy trong BackgroundTasks (phiên DB riêng); lỗi chỉ ghi log, không làm hỏng request."""
    import asyncio
    import logging
    from app.db.session import SessionLocal
    from app.runtime.factory import get_runtime
    runtime = get_runtime()
    if not agent_hr._has_rpc(runtime):
        return
    db = SessionLocal()
    try:
        asyncio.run(sync_tool_policy(db, org_id, runtime))
    except Exception:  # noqa: BLE001
        logging.getLogger(__name__).exception("đồng bộ quyền tool lên gateway lỗi")
    finally:
        db.close()
