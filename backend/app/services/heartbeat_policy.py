"""D2.1 / WP-6.2 — skill heartbeat và chính sách heartbeat của OpenClaw.

Hai việc, cả hai đã kiểm trên gateway thật 2026.9.8 (``_reports/wakeups-e2e.md``):

1. **Cài skill ``clawcompany-heartbeat``.** Kế hoạch viết "cài qua
   ``agents.files.set``" — không làm được: gateway chỉ nhận đúng 6 tên file
   bootstrap (AGENTS/SOUL/IDENTITY/USER/BOOTSTRAP/MEMORY.md), mọi tên khác trả
   ``unsupported file``. ``skills.library.save`` cần "durable Gateway profile",
   kết nối shared-token bị từ chối ``SKILL_LIBRARY_IDENTITY_REQUIRED``. Đường còn
   lại là ``skills.upload.begin/chunk/commit`` + ``skills.install
   source=upload`` — và nó chỉ chạy khi gateway bật
   ``skills.install.allowUploadedArchives``. Tắt thì trả lý do
   ``uploads_disabled``, không giả là đã cài.

2. **Tắt heartbeat của seat thừa hành** bằng ``config.patch``: mặc định
   OpenClaw đánh thức mỗi agent 30 phút một lần dù không có việc (đo được: một
   lượt ≈ 10k token). Từ D2.1, việc được đẩy tới seat qua hàng wakeup, nên chỉ
   giữ heartbeat cho một seat điều phối (Nina) kèm ``activeHours``;
   ``every: "0m"`` cho mọi seat khác (theo tài liệu OpenClaw: tắt nhịp định kỳ,
   wakeup theo sự kiện vẫn chạy).
"""
from __future__ import annotations

import base64
import hashlib
import io
import zipfile
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.models import Agent, Member

SKILL_SLUG = "clawcompany-heartbeat"
SKILL_FILE = Path(__file__).resolve().parents[1] / "skills" / SKILL_SLUG / "SKILL.md"
DEFAULT_EVERY = "30m"  # mặc định của OpenClaw khi heartbeat.every chưa đặt
OFF = "0m"
CHUNK = 256 * 1024


def skill_archive() -> tuple[bytes, str]:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("SKILL.md", SKILL_FILE.read_bytes())
    data = buf.getvalue()
    return data, hashlib.sha256(data).hexdigest()


def _reason(exc: Exception) -> str:
    text = str(exc)
    if "allowUploadedArchives" in text:
        return "uploads_disabled"
    if "SKILL_LIBRARY_IDENTITY_REQUIRED" in text:
        return "identity_required"
    return "gateway_error"


async def install_skill(runtime: Any, agent_ids: list[str]) -> list[dict]:
    """Tải gói skill lên một lần cho mỗi agent rồi ``skills.install``.

    Mỗi agent một upload: gateway gắn ``uploadId`` với một lần cài.
    """
    data, sha = skill_archive()
    out = []
    for agent_id in agent_ids:
        row = {"agent_id": agent_id, "slug": SKILL_SLUG, "sha256": sha}
        try:
            begin = await runtime.rpc("skills.upload.begin", {"kind": "skill-archive", "slug": SKILL_SLUG,
                                                              "sizeBytes": len(data), "sha256": sha, "force": True})
            uid = begin.get("uploadId")
            for off in range(0, len(data), CHUNK):
                await runtime.rpc("skills.upload.chunk", {"uploadId": uid, "offset": off,
                                                          "dataBase64": base64.b64encode(data[off:off + CHUNK]).decode()})
            await runtime.rpc("skills.upload.commit", {"uploadId": uid, "sha256": sha})
            res = await runtime.rpc("skills.install", {"source": "upload", "uploadId": uid, "slug": SKILL_SLUG,
                                                       "agentId": agent_id, "force": True, "sha256": sha})
            row.update(status="installed", result=res)
        except Exception as exc:  # noqa: BLE001 - trả lý do, không giả là đã cài
            row.update(status="failed", reason=_reason(exc), error=str(exc)[:300])
        out.append(row)
    return out


async def skill_present(runtime: Any, agent_id: str) -> dict | None:
    """Đọc lại từ ``skills.status``: chỉ coi là cài khi gateway liệt kê skill."""
    st = await runtime.rpc("skills.status", {"agentId": agent_id})
    for s in st.get("skills") or []:
        if s.get("name") == SKILL_SLUG or s.get("skillKey") == SKILL_SLUG:
            return {k: s.get(k) for k in ("name", "source", "filePath", "eligible", "disabled", "modelVisible")}
    return None


def agent_seats(db: Session, organization_id: int) -> list[tuple[Member, Agent]]:
    rows = (db.query(Member, Agent).join(Agent, Agent.member_id == Member.id)
            .filter(Member.organization_id == organization_id, Member.member_type == "agent")
            .order_by(Member.id).all())
    return [(m, a) for m, a in rows if (a.runtime_agent_id or "").strip()]


def plan(seats: list[tuple[Member, Agent]], config_entries: set[str], *, keeper_member_id: int | None,
         active_hours: dict | None, keeper_every: str = DEFAULT_EVERY) -> dict:
    """Patch tối thiểu. Thuần, không gọi gateway.

    Chỉ ghi vào ``agents.entries.<id>`` đã có trong config: ghi vào id chưa có
    sẽ tạo một entry mới chỉ có ``heartbeat`` — tức là sinh agent ma trong
    roster của gateway. Seat như vậy được báo ``not_in_config``.
    """
    values: dict[tuple[str, ...], Any] = {}
    rows = []
    for m, a in seats:
        rid = a.runtime_agent_id
        keep = m.id == keeper_member_id
        row = {"member_id": m.id, "name": m.name, "agent_id": rid,
               "heartbeat": "keep" if keep else "off"}
        if rid not in config_entries:
            row["heartbeat"] = "not_in_config"
            rows.append(row)
            continue
        if keep:
            values[("agents", "entries", rid, "heartbeat", "every")] = keeper_every
            if active_hours:
                values[("agents", "entries", rid, "heartbeat", "activeHours")] = dict(active_hours)
            row.update(every=keeper_every, activeHours=active_hours)
        else:
            values[("agents", "entries", rid, "heartbeat", "every")] = OFF
            row.update(every=OFF)
        rows.append(row)
    return {"values": values, "rows": rows}


def active_minutes(active_hours: dict | None) -> int:
    if not active_hours:
        return 24 * 60

    def mins(s: str) -> int:
        h, m = (s or "00:00").split(":")[:2]
        return int(h) * 60 + int(m)
    start, end = mins(active_hours.get("start", "00:00")), mins(active_hours.get("end", "24:00"))
    span = end - start if end > start else 24 * 60 - start + end
    return span


def every_minutes(every: str) -> int:
    s = (every or DEFAULT_EVERY).strip().lower()
    if s.endswith("h"):
        return int(float(s[:-1]) * 60)
    if s.endswith("m"):
        return int(float(s[:-1]))
    return int(float(s))


def daily_cost(rows: list[dict], per_turn_usd: float) -> float:
    """Chi phí/ngày theo nhịp đã đặt, từ chi phí một lượt heartbeat ĐO được."""
    total = 0.0
    for r in rows:
        every = r.get("every", DEFAULT_EVERY)
        n = every_minutes(every)
        if n <= 0:
            continue
        total += active_minutes(r.get("activeHours")) / n * per_turn_usd
    return round(total, 4)


async def apply(db: Session, organization_id: int, registry: Any, *, keeper_member_id: int | None,
                active_hours: dict | None, keeper_every: str = DEFAULT_EVERY, dry_run: bool = False) -> dict:
    snap = await registry.snapshot()
    agents_cfg = ((snap.get("config") or {}).get("agents") or {})
    entries = set((agents_cfg.get("entries") or {}).keys())
    p = plan(agent_seats(db, organization_id), entries, keeper_member_id=keeper_member_id,
             active_hours=active_hours, keeper_every=keeper_every)
    result = {"rows": p["rows"], "dry_run": dry_run, "patched": False}
    if p["values"]:
        res = await registry.patch(p["values"], base_hash=snap.get("hash"), dry_run=dry_run,
                                   note="ClawCompany D2.1: chỉ giữ heartbeat cho seat điều phối")
        result.update(patched=not dry_run, patch=res if dry_run else {"ok": True})
    return result
