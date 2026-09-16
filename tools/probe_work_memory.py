#!/usr/bin/env python3
"""Đo khoảng trống của tầng bộ nhớ công việc, trước khi xây nó.

Phép đo này tồn tại để mệnh đề "agent không biết gì về công việc của nó" trở
thành số liệu chứ không phải nhận định. Ba câu hỏi:

1. Prompt mà agent nhận hôm nay dài bao nhiêu, gồm những gì?
2. Cùng một task đó, database của công ty **thật sự biết** những gì?
3. Hỏi agent ba câu cần bối cảnh công việc, nó trả lời được không?

Chạy:

    bash tools/run_gateway.sh
    cd backend && OPENCLAW_MODE=native ../.venv/bin/python ../tools/probe_work_memory.py
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
os.environ.setdefault("JWT_SECRET", "probe")

from sqlalchemy import select                                        # noqa: E402

from app.db.session import SessionLocal                              # noqa: E402
from app.models.entities import Company, Member, Project, Task       # noqa: E402
from app.runtime.openclaw_native import NativeOpenClawRuntime        # noqa: E402
from app.services import openclaw_alignment as align                 # noqa: E402
from app.services import work_context                                # noqa: E402

AGENT_ID = os.environ.get("PROBE_AGENT_ID", "dev")

# Ba câu hỏi mà một nhân viên thật trả lời được sau khi nhận việc. Chúng cố ý
# cần thông tin nằm ở *công ty*, không nằm trong tiêu đề task.
QUESTIONS = [
    "Việc tôi đang nhận thuộc dự án nào, và dự án đó nhằm mục tiêu gì?",
    "Ai giao việc này cho tôi, và người đó là quản lý của tôi hay đồng nghiệp?",
    "Hạn chót của việc này là khi nào, và còn bao nhiêu ngày nữa?",
]

lines: list[str] = []


def say(text: str = "") -> None:
    print(text)
    lines.append(text)


async def ask(runtime: NativeOpenClawRuntime, question: str, label: str) -> str:
    """Hỏi trong một phiên mới, đọc trả lời qua chat.history (không đua event)."""
    session_key = f"agent:{AGENT_ID}:wm-probe-{label}-{uuid.uuid4().hex[:6]}"
    await runtime.run_agent(AGENT_ID, question, session_key=session_key)
    deadline = asyncio.get_event_loop().time() + 150
    while asyncio.get_event_loop().time() < deadline:
        await asyncio.sleep(5)
        try:
            payload = await runtime.history(session_key, limit=20)
        except Exception as exc:                          # noqa: BLE001
            return f"(không đọc được chat.history: {exc})"
        entries = payload.get("messages") or payload.get("entries") or payload.get("items") or []
        for entry in reversed(entries):
            if str(entry.get("role") or entry.get("author") or "") not in ("assistant", "agent"):
                continue
            for key in ("text", "content", "message"):
                value = entry.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
                if isinstance(value, list):
                    parts = [b.get("text", "") for b in value
                             if isinstance(b, dict) and b.get("text")]
                    if parts:
                        return "\n".join(parts).strip()
    return "(hết thời gian chờ)"


async def main() -> int:
    db = SessionLocal()
    runtime = NativeOpenClawRuntime()

    say("# Đo khoảng trống của tầng bộ nhớ công việc")
    say("")
    say(f"- Gateway: `{runtime.url}` · agent: `{AGENT_ID}`")
    say("")

    task = db.execute(select(Task).order_by(Task.id)).scalars().first()
    if not task:
        say("Không có task nào trong database. Chạy `seed.py` trước.")
        return 1
    project = db.get(Project, task.project_id)
    company = db.get(Company, project.company_id) if project else None
    assignee = db.get(Member, task.assignee_member_id) if task.assignee_member_id else None
    manager = db.get(Member, assignee.manager_id) if assignee and assignee.manager_id else None

    # ---------------------------------------------------------------- 1
    say("## 1. Prompt mà agent nhận hôm nay")
    say("")
    brief = align.task_brief(db, task)
    say("```")
    say(brief)
    say("```")
    say("")
    say(f"- Dài **{len(brief)} ký tự**, {len(brief.splitlines())} dòng.")
    say(f"- Trong đó phần thoả thuận làm việc chung là "
        f"{len(brief) - len(task.title) - len(task.description or ''):,} ký tự — "
        "tức phần lớn prompt là văn bản cố định, giống nhau cho mọi task.")
    say("")

    # ---------------------------------------------------------------- 2
    say("## 2. Cùng task đó, database công ty biết những gì")
    say("")
    say("| dữ kiện | database có | agent có nhận được không |")
    say("| --- | --- | --- |")
    facts = [
        ("Tiêu đề task", task.title, "CÓ"),
        ("Mô tả task", (task.description or "")[:60] or "(trống)", "CÓ"),
        ("Mức ưu tiên", task.priority, "không"),
        ("Trạng thái", task.status, "không"),
        ("Thuộc dự án", project.name if project else "(không có)", "không"),
        ("Mục tiêu dự án", ((project.description or "")[:60] if project else "") or "(trống)", "không"),
        ("Tiến độ dự án", f"{project.progress}%" if project else "-", "không"),
        ("Hạn chót dự án", str(project.due_date) if project and project.due_date else "(chưa đặt)", "không"),
        ("Công ty", company.name if company else "(không có)", "không"),
        ("Người được giao", assignee.name if assignee else "(chưa giao)", "không"),
        ("Vai của người được giao", assignee.role if assignee else "-", "không"),
        ("Quản lý trực tiếp", manager.name if manager else "(không có)", "không"),
    ]
    for label, value, received in facts:
        mark = "**CÓ**" if received == "CÓ" else "không"
        say(f"| {label} | {value} | {mark} |")
    missing = sum(1 for _, _, r in facts if r != "CÓ")
    say("")
    say(f"**{missing}/{len(facts)} dữ kiện mà công ty đã biết không hề đi vào prompt.**")
    say("")

    # ---------------------------------------------------------------- 3
    say("## 3. Hỏi agent ba câu cần bối cảnh công việc")
    say("")
    say("Hỏi trong phiên mới, không kèm gói ngữ cảnh nào — đúng như hôm nay "
        "agent làm việc.")
    say("")
    for index, question in enumerate(QUESTIONS):
        answer = await ask(runtime, question, f"q{index}")
        say(f"**Hỏi:** {question}")
        say("")
        say(f"> {answer[:600].replace(chr(10), ' ⏎ ')}")
        say("")

    # ---------------------------------------------------------------- 4
    say("## 4. Sau khi có gói ngữ cảnh: hỏi lại đúng ba câu đó")
    say("")
    pack = work_context.build_pack(db, task, organization_id=1)
    say(f"- Gói ngữ cảnh bảy khối dài **{pack['chars']} ký tự** "
        f"(ngân sách {pack['budget_chars']}), so với {len(brief)} ký tự của brief cũ.")
    say("| khối | ký tự | trần |")
    say("| --- | --- | --- |")
    for block in pack["blocks"]:
        say(f"| {block['index']}. {block['title']} | {block['chars']} | {block['budget']} |")
    say("")
    say("Lần này gửi gói ngữ cảnh vào phiên trước, rồi hỏi **cùng ba câu** "
        "trong cùng phiên đó — đúng như một nhân viên được giao việc rồi bị hỏi lại.")
    say("")

    import uuid as _uuid
    session_key = f"agent:{AGENT_ID}:wm-after-{_uuid.uuid4().hex[:6]}"

    async def assistant_keys() -> set[str]:
        try:
            payload = await runtime.history(session_key, limit=50)
        except Exception:                                 # noqa: BLE001
            return set()
        out = set()
        for index, entry in enumerate(payload.get("messages") or []):
            if str(entry.get("role") or entry.get("author") or "") in ("assistant", "agent"):
                out.add(str(entry.get("id") or f"pos{index}"))
        return out

    async def send_and_wait(text: str, *, label: str) -> str:
        """Gửi một lượt rồi **chờ nó xong** trước khi gửi lượt sau.

        Bản đầu của phép đo này gửi gói ngữ cảnh rồi ngủ 12 giây và hỏi luôn —
        cả ba câu đều hết thời gian chờ. Nguyên nhân chính là ràng buộc vật lý
        đã ghi trong `docs/AGENT_WORK_MEMORY.md`: **một phiên chỉ chạy một lượt
        tại một thời điểm**, và message thứ hai gửi vào phiên đang chạy sẽ bị
        `steer` vào chính lượt đó (queue mode mặc định) thay vì tạo lượt mới —
        nên không có câu trả lời riêng nào xuất hiện.

        Cách đúng, và cũng là cách một người dùng thật phải làm: chờ lượt trước
        kết thúc.
        """
        before = await assistant_keys()
        await runtime.run_agent(AGENT_ID, text, session_key=session_key)
        deadline = asyncio.get_event_loop().time() + 180
        while asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(5)
            try:
                payload = await runtime.history(session_key, limit=50)
            except Exception as exc:                      # noqa: BLE001
                return f"(lỗi đọc history: {exc})"
            for index, entry in enumerate(payload.get("messages") or []):
                if str(entry.get("role") or entry.get("author") or "") not in ("assistant", "agent"):
                    continue
                key = str(entry.get("id") or f"pos{index}")
                if key in before:
                    continue
                value = entry.get("text") or entry.get("content") or ""
                if isinstance(value, list):
                    value = "\n".join(b.get("text", "") for b in value
                                       if isinstance(b, dict) and b.get("text"))
                if isinstance(value, str) and value.strip():
                    return value.strip()
        return f"(hết thời gian chờ ở {label})"

    ack = await send_and_wait(pack["text"], label="gói ngữ cảnh")
    say(f"- Agent nhận gói và phản hồi: _{ack[:200].replace(chr(10), ' ')}…_")
    say("")

    for index, question in enumerate(QUESTIONS):
        answer = await send_and_wait(question, label=f"câu {index + 1}")
        say(f"**Hỏi:** {question}")
        say("")
        say(f"> {answer[:600].replace(chr(10), ' ⏎ ')}")
        say("")

    say("## Kết luận")
    say("")
    say("Trước: agent không có đường nào để biết những dữ kiện trên: chúng nằm trong "
        "Postgres của ClawCompany, còn prompt thì không mang chúng, và bộ nhớ "
        "của OpenClaw thì per-agent nên cũng không chứa việc của công ty.")
    say("")
    say("Sau: cùng ba câu, cùng một seat, cùng một model — khác duy nhất ở chỗ "
        "phiên đã nhận gói ngữ cảnh bảy khối. Đó là toàn bộ điều mà tầng bộ nhớ "
        "công việc phải làm.")

    out = Path(__file__).resolve().parents[1] / "_reports" / "work-memory-gap.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n→ đã ghi {out}")
    db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
