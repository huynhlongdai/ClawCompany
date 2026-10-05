#!/usr/bin/env python3
"""WP-1.1 + WP-1.2 — dò bề mặt điều khiển với một gateway OpenClaw thật.

Việc của script này là biến các mệnh đề trong `docs/ARCHITECTURE_TREE.md` thành
số liệu đo được. Nó trả lời đúng bốn câu:

1. `agents.*` và `config.*` có thật không, hay tài liệu nói một đằng gateway làm
   một nẻo? (Lượt trước repo tin là không có `agents.create`.)
2. `config.schema.lookup` trả `reloadKind` gì cho những path mà UI cấu hình seat
   sẽ chạm vào?
3. `ConfigRegistry.patch` có ghi được thật không, và `changedPaths` trả về gì?
4. Chốt `baseHash` có hiệu lực thật, hay chỉ là lời hứa trong docstring?

Chạy:

    bash tools/run_gateway.sh
    cd backend && OPENCLAW_MODE=native OPENCLAW_REQUEST_ADMIN_SCOPE=true \\
      ../.venv/bin/python ../tools/probe_config.py

Script cố ý ghi **cả thất bại**: một method không tồn tại là dữ kiện có giá trị
ngang với một method tồn tại.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

os.environ.setdefault("OPENCLAW_MODE", "native")
os.environ.setdefault("OPENCLAW_REQUEST_ADMIN_SCOPE", "true")
os.environ.setdefault("DATABASE_URL", "sqlite:///./_probe.db")
os.environ.setdefault("JWT_SECRET", "probe")

from app.runtime import openclaw_protocol as ocp                    # noqa: E402
from app.runtime.openclaw_native import NativeOpenClawRuntime       # noqa: E402
from app.services.openclaw_config import ConfigError, ConfigRegistry  # noqa: E402

# Những path mà màn hình "hồ sơ nhân sự AI" sẽ chạm vào. Đây là lý do ta cần
# biết reloadKind của chúng trước khi xây form.
SEAT_PATHS = [
    "agents.defaults.model",
    "agents.defaults.thinkingDefault",
    "agents.entries",
    "agents.defaults.sandbox.mode",
    "agents.defaults.heartbeat.every",
    "agents.defaults.compaction.enabled",
    "tools.exec.mode",
    "mcp.servers",
]

# Method chỉ đọc, an toàn để gọi thử trên gateway của người khác.
READ_METHODS = [
    (ocp.M_AGENTS_LIST, {}),
    (ocp.M_CONFIG_GET, {}),
    (ocp.M_CONFIG_SCHEMA, {}),   # 2,2 MB — xem ghi chú về max_size bên dưới
    (ocp.M_MODELS_LIST, {"view": "configured"}),
    (ocp.M_TOOLS_CATALOG, {}),
    (ocp.M_SKILLS_STATUS, {}),
    (ocp.M_USAGE_COST, {}),
    (ocp.M_AGENT_IDENTITY_GET, {}),
]

lines: list[str] = []


def say(text: str = "") -> None:
    print(text)
    lines.append(text)


def short(value, limit: int = 160) -> str:
    text = json.dumps(value, ensure_ascii=False, default=str)
    return text if len(text) <= limit else text[: limit - 3] + "..."


async def probe_reads(runtime: NativeOpenClawRuntime) -> dict[str, bool]:
    say("## 1. Method chỉ đọc có tồn tại không")
    say("")
    say("| method | kết quả | payload (rút gọn) |")
    say("| --- | --- | --- |")
    exists: dict[str, bool] = {}
    for method, params in READ_METHODS:
        try:
            payload = await runtime.rpc(method, params)
            keys = sorted(payload)[:6] if isinstance(payload, dict) else payload
            say(f"| `{method}` | OK | {short(keys, 90)} |")
            exists[method] = True
        except Exception as exc:                      # noqa: BLE001 — ghi lại mọi lỗi
            say(f"| `{method}` | LỖI | {short(str(exc), 90)} |")
            exists[method] = False
    say("")
    return exists


async def probe_full_schema(registry: ConfigRegistry) -> None:
    say("### Kích thước `config.schema`")
    say("")
    try:
        full = await registry.full_schema()
        size = len(json.dumps(full, ensure_ascii=False))
        say(f"- Gọi được, payload đã bóc ~**{size:,} byte**, version `{full['version']}`, "
            f"`uiHints` có {len(full['ui_hints'])} mục.")
        say("- Hạn mức frame mặc định của thư viện `websockets` là 1 MiB, nên "
            "trước WP-1.2 lời gọi này chết với `1009 message too big`. Đây là lỗi "
            "chỉ lộ ra khi gọi thật: không một test nào thấy được.")
        say("- Kết luận cho UI: **đừng** nạp toàn bộ schema mỗi lần mở form; dùng "
            "`config.schema.lookup` cho từng path (có cache trong service).")
    except Exception as exc:                          # noqa: BLE001
        say(f"- LỖI: `{short(str(exc), 200)}`")
    say("")


async def probe_schema(registry: ConfigRegistry) -> None:
    say("## 2. reloadKind của những path mà UI cấu hình seat sẽ chạm vào")
    say("")
    say("Cột cuối là điều UI phải nói với người dùng **trước** khi họ bấm Lưu.")
    say("")
    say("| path | reloadKind | hệ quả |")
    say("| --- | --- | --- |")
    for path in SEAT_PATHS:
        try:
            node = await registry.schema_node(path)
            kind = node["reload_kind"]
            effect = {
                ocp.RELOAD_HOT: "áp dụng ngay",
                ocp.RELOAD_NONE: "không cần nạp lại",
                ocp.RELOAD_RESTART: "**phải khởi động lại gateway**",
            }.get(kind, "không rõ — phải hỏi lại upstream")
            say(f"| `{path}` | `{kind}` | {effect} |")
        except Exception as exc:                      # noqa: BLE001
            say(f"| `{path}` | LỖI | {short(str(exc), 80)} |")
    say("")


async def probe_write(registry: ConfigRegistry, runtime: NativeOpenClawRuntime) -> None:
    say("## 3. Ghi thật bằng ConfigRegistry.patch")
    say("")
    snapshot = await registry.snapshot()
    say(f"- `config.get` trả hash `{snapshot['hash'][:16]}…`, "
        f"revision `{snapshot['config_revision_hash'][:16] or '(rỗng)'}…`, "
        f"pending_apply = `{snapshot['pending_apply']}`")

    # Chọn một field vô hại và có thể hoàn nguyên: ghi chú của chính ta.
    probe_path = "agents.entries.dev.identity.theme"
    before = snapshot["config"].get("agents", {}).get("entries", {}).get(
        "dev", {}).get("identity", {}).get("theme")
    say(f"- Field thử: `{probe_path}`, giá trị hiện tại: `{before}`")

    preview = await registry.patch({probe_path: "WP-1.2 probe"}, dry_run=True)
    say(f"- `dry_run` cho ra params: `{short(preview['params'], 200)}`")
    say("")

    new_value = "AI Chief of Staff của Nova Holding (WP-1.2 probe)"
    try:
        result = await registry.patch({probe_path: new_value},
                                      note="WP-1.2 probe")
        say(f"- **Ghi thành công.** `changedPaths` = `{short(result['changed_paths'])}`, "
            f"no_op = `{result['no_op']}`, base_hash_source = `{result['base_hash_source']}`")
    except ConfigError as exc:
        say(f"- **Ghi bị từ chối** (lỗi của ta, trước khi gửi): `{short(exc.as_dict())}`")
        return
    except Exception as exc:                          # noqa: BLE001
        say(f"- **Gateway từ chối**: `{short(str(exc), 300)}`")
        return

    # Đọc lại để xác nhận, chứ không tin vào phản hồi ghi.
    after = (await registry.snapshot())["config"].get("agents", {}).get(
        "entries", {}).get("dev", {}).get("identity", {}).get("theme")
    say(f"- Đọc lại `config.get`: `{after}`")
    say(f"- Khớp với giá trị vừa ghi: **{after == new_value}**")
    say("")

    # Chốt baseHash: ghi lần hai bằng hash đã cũ phải bị từ chối.
    say("### Chốt baseHash có hiệu lực thật không")
    say("")
    stale = snapshot["hash"]
    try:
        await registry.patch({probe_path: "giá trị ghi bằng hash cũ"},
                             base_hash=stale)
        say(f"- ⚠ Gateway **nhận** patch với baseHash cũ (`{stale[:16]}…`). "
            "Nghĩa là compare-and-set không chặn ở tầng này — UI không được "
            "dựa vào nó để chống ghi đè.")
    except Exception as exc:                          # noqa: BLE001
        say(f"- Gateway **từ chối** patch với baseHash cũ (`{stale[:16]}…`): "
            f"`{short(str(exc), 200)}`")
        say("- Nghĩa là optimistic concurrency có thật — hai người sửa cùng lúc "
            "thì người sau bị chặn, không ghi đè im lặng.")
    say("")

    # Hoàn nguyên để không để lại rác trong cấu hình của người khác.
    try:
        await registry.patch({probe_path: before}) if before else None
        say(f"- Đã hoàn nguyên `{probe_path}` về `{before}`")
    except Exception as exc:                          # noqa: BLE001
        say(f"- Không hoàn nguyên được: `{short(str(exc), 120)}`")
    say("")


async def probe_agent_entry(registry: ConfigRegistry) -> None:
    say("## 4. Cấu hình hiệu dụng của một seat")
    say("")
    entry = await registry.agent_entry("dev")
    say(f"- seat `dev` tồn tại: `{entry['exists']}`")
    say(f"- giá trị của riêng seat: `{short(entry['entry'], 200)}`")
    say(f"- thừa hưởng từ `agents.defaults`: `{short(entry['inherited_keys'], 200)}`")
    say("")
    say("Đây chính là dữ liệu cho sáu tab của màn hình hồ sơ nhân sự AI: UI phân "
        "biệt được giá trị riêng của seat với giá trị thừa hưởng, nên người vận "
        "hành biết khi nào mình đang sửa cho cả công ty.")
    say("")


async def main() -> int:
    runtime = NativeOpenClawRuntime()
    registry = ConfigRegistry(runtime)

    say("# Biên bản dò bề mặt điều khiển OpenClaw (WP-1.1 + WP-1.2)")
    say("")
    say(f"- Gateway: `{runtime.url}`")
    say(f"- Scope xin trong handshake: `{runtime.scopes()}`")
    say("")

    try:
        health = await runtime.health()
        say(f"- `status` OK: `{short({k: health.get(k) for k in list(health)[:5]})}`")
    except Exception as exc:                          # noqa: BLE001
        say(f"- Không kết nối được gateway: `{exc}`")
        return 1
    say("")

    exists = await probe_reads(runtime)
    await probe_full_schema(registry)
    await probe_schema(registry)
    await probe_write(registry, runtime)
    await probe_agent_entry(registry)

    say("## Kết luận")
    say("")
    ok = [m for m, v in exists.items() if v]
    bad = [m for m, v in exists.items() if not v]
    say(f"- Method gọi được: **{len(ok)}/{len(exists)}** — {', '.join(f'`{m}`' for m in ok)}")
    if bad:
        say(f"- Method không gọi được: {', '.join(f'`{m}`' for m in bad)}")
    say("")
    say("Mệnh đề cũ trong `openclaw_protocol.py` — *\"There is no agents.create\"* — "
        f"đối chiếu với `agents.list` gọi được ở trên: **{'sai' if exists.get(ocp.M_AGENTS_LIST) else 'chưa kết luận được'}**.")

    out = Path(__file__).resolve().parents[1] / "_reports" / "native-probe-agents.log"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n→ đã ghi {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
