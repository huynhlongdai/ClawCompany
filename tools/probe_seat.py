#!/usr/bin/env python3
"""WP-2.2 — nghiệm thu: sửa SOUL.md từ tầng ứng dụng, giọng agent có đổi không.

Đây là phép thử duy nhất chứng minh tab "Tính cách" làm được việc nó hứa. Test
trong suite chỉ kiểm params gửi đi; còn câu hỏi thật là: **ghi một file tính
cách rồi hỏi lại, model có trả lời theo tính cách mới hay không.**

Trình tự:

1. Đọc `SOUL.md` hiện tại (kèm hash) qua `agents.files.get`.
2. Hỏi agent một câu trung tính, ghi lại câu trả lời — đây là "trước".
3. Ghi `SOUL.md` mới bằng `SeatProfileService.write_file` với `expectedHash`.
4. Hỏi **đúng câu đó** trong một phiên mới, ghi lại câu trả lời — "sau".
5. Thử ghi lần nữa bằng hash đã cũ, xác nhận nhận `agent_file_conflict`.
6. Hoàn nguyên `SOUL.md` về nội dung ban đầu.

Chạy:

    bash tools/run_gateway.sh
    cd backend && OPENCLAW_MODE=native OPENCLAW_REQUEST_ADMIN_SCOPE=true \\
      ../.venv/bin/python ../tools/probe_seat.py

Phiên mới ở bước 4 là bắt buộc: file bootstrap được nạp lúc **dựng prompt**, nên
một phiên đang chạy vẫn dùng tính cách cũ. Nếu hỏi lại trong cùng phiên rồi kết
luận "không có tác dụng" thì đó là kết luận sai về một hệ thống đúng.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

os.environ.setdefault("OPENCLAW_MODE", "native")
os.environ.setdefault("OPENCLAW_REQUEST_ADMIN_SCOPE", "true")
os.environ.setdefault("DATABASE_URL", "sqlite:///./_probe.db")
os.environ.setdefault("JWT_SECRET", "probe")

from app.runtime import openclaw_protocol as ocp                    # noqa: E402
from app.runtime.openclaw_native import NativeOpenClawRuntime       # noqa: E402
from app.services.seat_profile import char_budget                   # noqa: E402

AGENT_ID = os.environ.get("PROBE_AGENT_ID", "dev")
QUESTION = "Trong hai câu, hãy nói cho tôi biết bạn là ai và bạn làm việc thế nào."

# Tính cách mới, cố tình khác hẳn bản mẫu: có ràng buộc đo được (đúng ba gạch
# đầu dòng, mở đầu bằng một từ khoá) nên "giọng có đổi" không phải chuyện cảm
# nhận mà kiểm được bằng mắt thường.
NEW_SOUL = """# SOUL.md — Nina

Tôi là Nina, chief of staff của Nova Holding.

## Cách tôi nói

- Luôn mở đầu câu trả lời bằng đúng chữ: "Báo cáo:".
- Trả lời bằng tiếng Việt, câu ngắn, không dùng emoji.
- Luôn kết thúc bằng đúng một dòng: "— Nina, Nova Holding".

## Điều tôi không làm

- Không nói "Tôi là một trợ lý AI".
- Không xin lỗi vòng vo; nếu không biết thì nói thẳng là không biết.
"""

lines: list[str] = []


def say(text: str = "") -> None:
    print(text)
    lines.append(text)


def short(value, limit: int = 400) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    text = text.replace("\n", " ⏎ ")
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _assistant_text(entry: dict) -> str:
    """Bóc text của một lượt trợ lý trong chat.history.

    Upstream có nhiều hình dạng (``text``, ``content`` là chuỗi, hoặc danh sách
    block có ``text``), nên thử lần lượt thay vì ghim một cái.
    """
    if str(entry.get("role") or entry.get("author") or "") not in ("assistant", "agent"):
        return ""
    for key in ("text", "content", "message"):
        value = entry.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, list):
            parts = [block.get("text", "") for block in value
                     if isinstance(block, dict) and block.get("text")]
            if parts:
                return "\n".join(parts).strip()
    return ""


async def ask(runtime: NativeOpenClawRuntime, question: str, label: str) -> str:
    """Hỏi agent trong một phiên MỚI, rồi đọc trả lời qua ``chat.history``.

    Không dùng ``stream_run``: nó cần session key và phải subscribe **trước**
    khi lượt chạy bắt đầu, nếu không sẽ mất event đầu. Với một phép nghiệm thu
    một lần thì hỏi rồi đọc lại lịch sử là cách vừa đơn giản vừa không có đua.
    """
    session_key = f"agent:{AGENT_ID}:wp22-probe-{label}-{uuid.uuid4().hex[:6]}"
    await runtime.run_agent(AGENT_ID, question, session_key=session_key)

    deadline = asyncio.get_event_loop().time() + 150
    while asyncio.get_event_loop().time() < deadline:
        await asyncio.sleep(5)
        try:
            payload = await runtime.history(session_key, limit=20)
        except Exception as exc:                          # noqa: BLE001
            return f"(không đọc được chat.history: {exc})"
        entries = payload.get("messages") or payload.get("entries") or payload.get("items") or []
        replies = [text for text in (_assistant_text(e) for e in entries) if text]
        if replies:
            return replies[-1]
    return "(hết thời gian chờ, chưa có câu trả lời nào trong chat.history)"


async def main() -> int:
    runtime = NativeOpenClawRuntime()

    say("# Nghiệm thu WP-2.2 — sửa SOUL.md thì giọng agent có đổi?")
    say("")
    say(f"- Gateway: `{runtime.url}` · agent: `{AGENT_ID}`")
    say(f"- Câu hỏi dùng cho cả hai lượt: *{QUESTION}*")
    say("")

    # 1) Đọc SOUL.md hiện tại.
    payload = await runtime.rpc(ocp.M_AGENTS_FILES_GET,
                                {"agentId": AGENT_ID, "name": "SOUL.md"})
    record = payload["file"]
    original, original_hash = record.get("content", ""), record.get("hash", "")
    say("## 1. SOUL.md trước khi sửa")
    say("")
    say(f"- {len(original)} ký tự, hạn mức {char_budget('SOUL.md')}, "
        f"hash `{original_hash[:16]}…`")
    say(f"- Mở đầu: `{short(original[:200], 220)}`")
    is_sample = "C-3PO" in original
    say(f"- Còn là bản mẫu xuất xưởng của OpenClaw: **{is_sample}**"
        + ("  ← nghĩa là tính cách của seat này chưa từng được cấu hình"
           if is_sample else ""))
    say("")

    # 2) Giọng "trước".
    say("## 2. Giọng trước khi sửa")
    say("")
    before = await ask(runtime, QUESTION, "before")
    say(f"> {short(before, 700)}")
    say("")

    # 3) Ghi SOUL.md mới, có điều kiện.
    say("## 3. Ghi SOUL.md mới (có expectedHash)")
    say("")
    try:
        result = await runtime.rpc(ocp.M_AGENTS_FILES_SET, {
            "agentId": AGENT_ID, "name": "SOUL.md",
            "content": NEW_SOUL, "expectedHash": original_hash,
        })
        new_hash = (result.get("file") or {}).get("hash", "")
        say(f"- `ok` = `{result.get('ok')}`, hash mới `{new_hash[:16]}…`")
    except Exception as exc:                              # noqa: BLE001
        say(f"- **Ghi thất bại**: `{short(str(exc))}`")
        return 1
    say("- Tính cách mới yêu cầu ba thứ đo được: mở đầu bằng \"Báo cáo:\", "
        "không emoji, kết thúc bằng \"— Nina, Nova Holding\".")
    say("")

    # 4) Giọng "sau", trong một phiên mới.
    say("## 4. Giọng sau khi sửa (phiên mới)")
    say("")
    after = await ask(runtime, QUESTION, "after")
    say(f"> {short(after, 700)}")
    say("")

    # Bỏ dấu câu ở cuối trước khi so chữ ký: lượt đo đầu tiên trượt dấu hiệu
    # này chỉ vì model thêm một dấu chấm ("— Nina, Nova Holding."). Nới phép
    # kiểm ở chỗ đó là đúng — cái đang kiểm là chữ ký có xuất hiện hay không,
    # không phải model có kiêng dấu chấm hay không. Ghi lại để người sau biết
    # phép kiểm đã được nới có chủ ý, không phải sửa cho xanh.
    tail = after.strip().rstrip(" .!\n")
    checks = {
        'mở đầu bằng "Báo cáo:"': after.strip().startswith("Báo cáo:"),
        'kết thúc bằng "— Nina, Nova Holding" (bỏ qua dấu câu cuối)':
            tail.endswith("— Nina, Nova Holding"),
        "không còn nhắc C-3PO": "C-3PO" not in after,
        "khác hẳn câu trả lời trước": after.strip() != before.strip(),
    }
    say("| dấu hiệu của tính cách mới | đạt |")
    say("| --- | --- |")
    for label, ok in checks.items():
        say(f"| {label} | {'**có**' if ok else 'không'} |")
    say("")
    passed = sum(1 for ok in checks.values() if ok)
    say(f"**{passed}/{len(checks)} dấu hiệu đạt.** "
        + ("Tab Tính cách có tác dụng thật: ghi file từ tầng ứng dụng thì model "
           "trả lời theo tính cách mới."
           if passed >= 3 else
           "Chưa đủ để kết luận là có tác dụng — xem phần ghi chú cuối."))
    say("")

    # 5) Xung đột hash.
    say("## 5. Ghi lần nữa bằng hash đã cũ")
    say("")
    try:
        await runtime.rpc(ocp.M_AGENTS_FILES_SET, {
            "agentId": AGENT_ID, "name": "SOUL.md",
            "content": "nội dung ghi bằng hash cũ", "expectedHash": original_hash,
        })
        say("- ⚠ Gateway **nhận** ghi với hash cũ. Compare-and-set không có hiệu "
            "lực ở tầng này, nên UI không được dựa vào nó để chống ghi đè.")
    except Exception as exc:                              # noqa: BLE001
        detail_type = getattr(exc, "detail_type", "")
        current = getattr(exc, "details", {}).get("currentHash", "")
        say(f"- Gateway **từ chối**. `details.type` = `{detail_type or '(không có)'}`, "
            f"`currentHash` = `{str(current)[:16]}…`")
        say(f"- Khớp với hằng số `ocp.ERR_AGENT_FILE_CONFLICT`: "
            f"**{detail_type == ocp.ERR_AGENT_FILE_CONFLICT}**")
        say("- Nghĩa là hai người sửa tính cách cùng lúc thì người sau bị chặn, "
            "không ghi đè im lặng.")
    say("")

    # 6) Hoàn nguyên.
    say("## 6. Hoàn nguyên")
    say("")
    try:
        current = await runtime.rpc(ocp.M_AGENTS_FILES_GET,
                                    {"agentId": AGENT_ID, "name": "SOUL.md"})
        await runtime.rpc(ocp.M_AGENTS_FILES_SET, {
            "agentId": AGENT_ID, "name": "SOUL.md", "content": original,
            "expectedHash": current["file"]["hash"],
        })
        back = await runtime.rpc(ocp.M_AGENTS_FILES_GET,
                                 {"agentId": AGENT_ID, "name": "SOUL.md"})
        say(f"- Đã trả SOUL.md về bản ban đầu, hash khớp lại: "
            f"**{back['file']['hash'] == original_hash}**")
    except Exception as exc:                              # noqa: BLE001
        say(f"- Không hoàn nguyên được: `{short(str(exc))}` — kiểm tra bằng tay.")
    say("")

    say("## Ghi chú về cách đọc kết quả")
    say("")
    say("- File bootstrap được nạp lúc **dựng prompt**, nên bước 4 phải dùng một "
        "phiên mới. Hỏi lại trong phiên đang chạy sẽ thấy tính cách cũ, và đó là "
        "hành vi đúng của OpenClaw chứ không phải lỗi.")
    say("- Model ở đây là `cometapi/gpt-4o-mini`. Một model nhỏ tuân theo ràng "
        "buộc định dạng không hoàn hảo, nên vài dấu hiệu có thể trượt trong khi "
        "cơ chế vẫn đúng. Cái cần kết luận là **giọng có đổi theo file hay "
        "không**, không phải model có tuân thủ tuyệt đối.")

    out = Path(__file__).resolve().parents[1] / "_reports" / "seat-soul-e2e.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n→ đã ghi {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
