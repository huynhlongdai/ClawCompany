"""M1: doctor 1 nút cho trang "Kết nối OpenClaw".

Mỗi mục trả ``{id, label, status: ok|warn|fail|skip, detail, fix}`` bằng tiếng
Việt; ``fix`` là việc cụ thể người vận hành làm được ngay. Mọi RPC đều có hạn
giờ và không bao giờ raise: doctor hỏng thì chính nó là một lỗi khó chẩn đoán.

Các khung đọc ở đây đều đo trên gateway 2026.9.8 thật: ``status`` →
``runtimeVersion``; ``models.list`` → ``models[{id, provider, available,
tags}]``; ``agents.list``; ``exec.approval.list``; ``skills.status``.
"""

from __future__ import annotations

import asyncio

from sqlalchemy.orm import Session

from app.core.config import settings
from app.runtime.factory import resolve_mode
from app.db.session import engine
from app.runtime import openclaw_protocol as ocp
from app.services import schema_status

RANK = {"ok": 0, "skip": 0, "warn": 1, "fail": 2}
STEP_TIMEOUT = 8.0


def _check(id_: str, label: str, status: str, detail: str = "", fix: str = "") -> dict:
    return {"id": id_, "label": label, "status": status, "detail": detail, "fix": fix}


def explain(exc: BaseException) -> tuple[str, str]:
    """(chi tiết, cách sửa) cho lỗi kết nối gateway."""
    text = str(exc)
    low = text.lower()
    if "chưa duyệt thiết bị" in text or "pairing" in low or "not_paired" in low:
        return text, "Trên máy gateway: openclaw devices list → openclaw devices approve <requestId>"
    if "unauthorized" in low or ("auth" in low and "token" in low) or "4001" in low or "4003" in low:
        return text, "Token sai: đặt OPENCLAW_API_TOKEN trùng gateway.auth.token của gateway."
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        return "Gateway không trả lời trong hạn.", "Kiểm tra container openclaw đang chạy và OPENCLAW_GATEWAY_WS đúng địa chỉ."
    if isinstance(exc, OSError) or "connect" in low or "refused" in low:
        return f"Không mở được kết nối: {text[:200]}", "Kiểm tra gateway đang chạy (docker compose ps openclaw) và địa chỉ OPENCLAW_GATEWAY_WS."
    return text[:300], "Xem log gateway: docker compose logs --tail 50 openclaw"


async def uploads_allowed(runtime) -> bool | None:
    """``skills.install.allowUploadedArchives`` trên gateway; ``None`` nếu không đọc được."""
    try:
        cfg = await _rpc(runtime, "config.get")
        import json
        data = json.loads(cfg.get("raw") or "{}")
        return bool(((data.get("skills") or {}).get("install") or {}).get("allowUploadedArchives", False))
    except Exception:  # noqa: BLE001 - không đọc được thì vẫn cho thử cài
        return None


async def _rpc(runtime, method: str, params: dict | None = None) -> dict:
    return await asyncio.wait_for(runtime.rpc(method, params or {}), timeout=STEP_TIMEOUT)


async def run(db: Session, runtime, organization_id: int) -> dict:
    checks: list[dict] = []

    sch = schema_status.status(engine)
    if sch["schema"] in ("ok", "unmanaged"):
        checks.append(_check("schema", "Cơ sở dữ liệu", "ok",
                             f"Migration {', '.join(sch['db'] or sch['code'])}"
                             + (" (SQLite dev)" if sch["schema"] == "unmanaged" else "")))
    else:
        checks.append(_check("schema", "Cơ sở dữ liệu", "fail",
                             sch.get("error") or f"DB ở {sch['db']}, code cần {sch['code']}",
                             sch.get("fix") or "Chạy: docker compose exec api alembic upgrade head"))

    native = resolve_mode(settings.openclaw_mode) == "native"
    if not native:
        checks.append(_check("mode", "Chế độ runtime", "fail",
                             f"Đang chạy chế độ '{settings.openclaw_mode}': agent chỉ là giả lập.",
                             "Đặt OPENCLAW_MODE=native và OPENCLAW_GATEWAY_WS=ws://<gateway>:18789 rồi khởi động lại api/worker."))
        return _summary(checks)
    checks.append(_check("mode", "Chế độ runtime", "ok", f"native → {settings.openclaw_gateway_ws}"))
    checks.append(_check("token", "Token gateway", "ok" if settings.openclaw_api_token else "warn",
                         "Đã cấu hình" if settings.openclaw_api_token else "Chưa có token",
                         "" if settings.openclaw_api_token else "Đặt OPENCLAW_API_TOKEN trùng gateway.auth.token."))

    try:
        status = await _rpc(runtime, ocp.M_STATUS)
        version = str(status.get("runtimeVersion") or status.get("version") or "?")
        checks.append(_check("connect", "Kết nối & xác thực thiết bị", "ok", f"OpenClaw {version}"))
    except Exception as exc:  # noqa: BLE001
        detail, fix = explain(exc)
        checks.append(_check("connect", "Kết nối & xác thực thiết bị", "fail", detail, fix))
        return _summary(checks)  # không kết nối được thì các bước sau vô nghĩa

    try:
        models = (await _rpc(runtime, ocp.M_MODELS_LIST)).get("models") or []
        usable = [m for m in models if m.get("available", True)]
        default = next((m for m in usable if "default" in (m.get("tags") or [])), usable[0] if usable else None)
        if default:
            checks.append(_check("model", "Model AI", "ok",
                                 f"{default.get('provider')}/{default.get('id')} · {len(usable)} model dùng được"))
        else:
            checks.append(_check("model", "Model AI", "fail", "Gateway chưa có model nào dùng được.",
                                 "Thêm provider vào models.providers và agents.defaults.model.primary trong openclaw.json (kèm API key)."))
    except Exception as exc:  # noqa: BLE001
        checks.append(_check("model", "Model AI", "warn", f"Không đọc được models.list: {str(exc)[:200]}"))

    roster: set[str] = set()
    try:
        roster = {str(a.get("id")) for a in await asyncio.wait_for(runtime.list_agents(), STEP_TIMEOUT)}
        from app.services import openclaw_alignment as align
        seats = align.company_agent_index(db, organization_id)
        orphan = sorted(k for k in seats if k not in roster)
        checks.append(_check("agents", "Agent ↔ ghế", "warn" if orphan else "ok",
                             f"{len(roster)} agent trên gateway, {len(seats)} ghế đã gắn"
                             + (f"; ghế lệch: {', '.join(orphan)}" if orphan else ""),
                             "Bấm \"Đối soát ngay\" rồi gắn lại ghế lệch, hoặc tạo agent đó trên gateway." if orphan else ""))
    except Exception as exc:  # noqa: BLE001
        checks.append(_check("agents", "Agent ↔ ghế", "warn", f"Không đọc được roster: {str(exc)[:200]}"))

    if settings.openclaw_request_approvals_scope:
        try:
            await _rpc(runtime, ocp.M_EXEC_APPROVAL_LIST)
            checks.append(_check("approvals", "Quyền duyệt lệnh", "ok", "operator.approvals hoạt động"))
        except Exception as exc:  # noqa: BLE001
            checks.append(_check("approvals", "Quyền duyệt lệnh", "fail", str(exc)[:200],
                                 "Duyệt nâng quyền thiết bị: openclaw devices list → openclaw devices approve <requestId>"))
    else:
        checks.append(_check("approvals", "Quyền duyệt lệnh", "warn", "Chưa xin scope operator.approvals",
                             "Đặt OPENCLAW_REQUEST_APPROVALS_SCOPE=true để duyệt lệnh exec ngay trên app."))

    try:
        from app.services import heartbeat_policy
        bound = [a.runtime_agent_id for _, a in heartbeat_policy.agent_seats(db, organization_id)]
        targets = [a for a in bound if a in roster]
        if not targets:
            checks.append(_check("heartbeat", "Skill heartbeat", "skip", "Chưa có ghế agent nào gắn với gateway."))
        else:
            missing = []
            for agent_id in targets:
                if not await asyncio.wait_for(heartbeat_policy.skill_present(runtime, agent_id), STEP_TIMEOUT):
                    missing.append(agent_id)
            item = _check("heartbeat", "Skill heartbeat", "warn" if missing else "ok",
                          f"Thiếu ở: {', '.join(missing)}" if missing else f"Đã cài cho {len(targets)} ghế",
                          "Bấm \"Cài ngay\" để agent tự báo cáo định kỳ." if missing else "")
            if missing:
                if await uploads_allowed(runtime) is False:
                    # Đo trên 2026.9.8: mặc định tắt → skills.upload báo UNAVAILABLE.
                    item["fix"] = ("Gateway đang chặn cài skill tải lên. Trên máy gateway chạy: "
                                   "openclaw config set skills.install.allowUploadedArchives true — rồi bấm \"Kiểm tra lại\".")
                else:
                    item["action"] = {"label": "Cài ngay", "method": "POST", "path": "/v19/openclaw/heartbeat-skill"}
            checks.append(item)
    except Exception as exc:  # noqa: BLE001
        checks.append(_check("heartbeat", "Skill heartbeat", "warn", f"Không kiểm được: {str(exc)[:200]}"))

    return _summary(checks)


def _summary(checks: list[dict]) -> dict:
    worst = max((RANK.get(c["status"], 0) for c in checks), default=0)
    overall = {0: "ok", 1: "warn", 2: "fail"}[worst]
    return {"status": overall, "checks": checks,
            "ok": sum(c["status"] == "ok" for c in checks), "total": len(checks)}
