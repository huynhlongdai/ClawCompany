#!/usr/bin/env python3
"""WP-4.3 — Nghiệm thu: Nina bàn giao cho Mia, Mia thật sự nhận việc.

Mệnh đề cần chứng minh: **một bàn giao khiến người nhận nhận được việc, kèm
hướng dẫn bàn giao trong gói ngữ cảnh** — không phải nằm im chờ ai đó dispatch tay.

Trình tự, tất cả qua **HTTP API** để chứng minh cả đường dây:

1. Xác nhận chủ việc ban đầu (Nina) và seat của hai người.
2. Tạo artifact rồi bàn giao Nina → Mia kèm hướng dẫn cụ thể.
3. Đọc phản hồi: có dispatch không, lý do gì, chủ việc chuyển chưa.
4. Đọc sổ ghi task: mục `handoff` có nội dung hướng dẫn chưa.
5. Đọc gói ngữ cảnh mà Mia thật sự nhận: khối 1 là Mia chưa, khối 5 có hướng dẫn chưa.
6. Hỏi chính Mia một câu chỉ trả lời được nếu cô đọc được hướng dẫn bàn giao.

Chạy (cần devstack + gateway + API đang lên):

    cd backend && OPENCLAW_MODE=native ../.venv/bin/python ../tools/probe_handoff.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import uuid
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

os.environ.setdefault("OPENCLAW_MODE", "native")
os.environ.setdefault("JWT_SECRET", "probe")

API = os.environ.get("CC_API", "http://127.0.0.1:8000")
EMAIL, PASSWORD = "admin@clawcompany.local", "ChangeMe123!"

# Hướng dẫn bàn giao cố ý mang một chi tiết **không nằm ở đâu khác** trong hệ
# thống, để câu hỏi ở bước 6 chỉ trả lời được nếu Mia thật sự đọc được nó.
INSTRUCTIONS = ("Ba hook đầu phải tránh nhạc có bản quyền. Sophia đã loại hook "
                "về giảm giá sốc, đừng đưa lại. Hạn nội bộ là thứ Năm 18/09.")
SECRET_DETAIL = "thứ Năm 18/09"

QUESTION = ("Theo hướng dẫn bàn giao bạn vừa nhận: hạn nội bộ là ngày nào, và "
            "hook nào đã bị loại? Trả lời ngắn.")

lines: list[str] = []


def say(text: str = "") -> None:
    print(text)
    lines.append(text)


def setup(client: httpx.Client, headers: dict) -> dict:
    """Hai seat khớp roster gateway, và một task thuộc Nina."""
    from sqlalchemy import select

    from app.db.session import SessionLocal
    from app.models.entities import Agent, Member, Project, Task

    db = SessionLocal()
    nina = db.execute(select(Member).where(Member.name == "Nina")).scalars().first()
    mia = db.execute(select(Member).where(Member.name == "Mia")).scalars().first()
    if not nina or not mia:
        raise SystemExit("cần seed có Nina và Mia")

    # Mia phải có seat runtime thật (đã tạo bằng agents.create ở WP-4.1).
    mia_agent = db.execute(select(Agent).where(Agent.member_id == mia.id)).scalars().first()
    if not mia_agent:
        mia_agent = Agent(member_id=mia.id, runtime_provider="openclaw")
        db.add(mia_agent)
    mia_agent.runtime_agent_id = "mia"
    mia_agent.lifecycle = "active"
    db.add(mia_agent)

    # Task mới cho mỗi lần chạy, thuộc Nina, để phép đo không bị nhiễu bởi lần trước.
    project = db.execute(select(Project).order_by(Project.id)).scalars().first()
    task = Task(project_id=project.id,
                title=f"Hoàn thiện bộ hook TikTok (probe {int(time.time()) % 100000})",
                description="Viết bản cuối cho 5 hook đã được chọn trong cuộc họp.",
                assignee_member_id=nina.id, status="backlog", priority="high")
    db.add(task); db.commit(); db.refresh(task)

    out = {"nina_id": nina.id, "mia_id": mia.id, "task_id": task.id,
           "org_id": nina.organization_id, "company_id": project.company_id,
           "project_id": project.id, "task_title": task.title}
    db.close()
    return out


async def ask_mia(question: str, session_key: str) -> str:
    """Hỏi Mia trong **đúng phiên của task** mà cô vừa nhận việc.

    Phải dùng phiên đó, không phải phiên mới: gói ngữ cảnh nằm trong phiên ấy.
    Và phải chờ lượt trước xong — một phiên chỉ chạy một lượt, message thứ hai
    gửi vào phiên đang chạy sẽ bị `steer` vào lượt đó thay vì tạo lượt mới.
    """
    from app.runtime.openclaw_native import NativeOpenClawRuntime

    runtime = NativeOpenClawRuntime()

    async def assistant_keys() -> set[str]:
        try:
            payload = await runtime.history(session_key, limit=50)
        except Exception:                                 # noqa: BLE001
            return set()
        return {str(e.get("id") or f"pos{i}")
                for i, e in enumerate(payload.get("messages") or [])
                if str(e.get("role") or e.get("author") or "") in ("assistant", "agent")}

    # Chờ lượt nhận việc kết thúc trước khi hỏi thêm.
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        if await assistant_keys():
            break
        await asyncio.sleep(5)

    before = await assistant_keys()
    await runtime.run_agent("mia", question, session_key=session_key)
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        await asyncio.sleep(5)
        try:
            payload = await runtime.history(session_key, limit=50)
        except Exception as exc:                          # noqa: BLE001
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
    return "(hết thời gian chờ)"


def main() -> int:
    client = httpx.Client(base_url=API, timeout=400.0)
    token = client.post("/api/auth/login",
                        json={"email": EMAIL, "password": PASSWORD}).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    ctx = setup(client, headers)

    say("# Nghiệm thu WP-4.3 — bàn giao khiến người nhận thật sự nhận việc")
    say("")
    say(f"- API `{API}` · task #{ctx['task_id']}: *{ctx['task_title']}*")
    say(f"- Chủ việc ban đầu: **Nina** (member {ctx['nina_id']}, seat `dev`)")
    say(f"- Người nhận bàn giao: **Mia** (member {ctx['mia_id']}, seat `mia`)")
    say("")

    # 1) Tạo artifact để có thứ mà bàn giao.
    artifact = client.post("/api/v10/artifacts", headers=headers, json={
        "organization_id": ctx["org_id"], "company_id": ctx["company_id"],
        "project_id": ctx["project_id"], "task_id": ctx["task_id"],
        "name": "hooks-final.md", "logical_path": "content/hooks-final.md",
        "artifact_type": "deliverable", "bundle_key": f"hooks-{uuid.uuid4().hex[:6]}",
        "content_text": "# 5 hook đã chọn\n1. Hướng dẫn phối đồ mùa hè\n…",
        "created_by_member_id": ctx["nina_id"],
    })
    if artifact.status_code >= 400:
        say(f"- Không tạo được artifact: {artifact.status_code} {artifact.text[:300]}")
        return 1
    artifact_id = artifact.json().get("id") or artifact.json().get("artifact", {}).get("id")
    say(f"- Đã tạo artifact #{artifact_id}")
    say("")

    # 2) Bàn giao.
    say("## Bàn giao Nina → Mia")
    say("")
    say(f"Hướng dẫn kèm theo: _{INSTRUCTIONS}_")
    say("")
    response = client.post(f"/api/v10/artifacts/{artifact_id}/handoff", headers=headers,
                           json={"to_member_id": ctx["mia_id"],
                                 "from_member_id": ctx["nina_id"],
                                 "task_id": ctx["task_id"], "purpose": "continue_work",
                                 "instructions": INSTRUCTIONS, "dispatch": True})
    if response.status_code >= 400:
        say(f"- LỖI {response.status_code}: {response.text[:400]}")
        return 1
    body = response.json()
    outcome = body["dispatch"]
    say(f"- `dispatched` = **{outcome['dispatched']}**, `reason` = `{outcome['reason']}`")
    say(f"- Ghi sổ: `{json.dumps(outcome['journal'], ensure_ascii=False)}`")
    say(f"- Chuyển chủ việc: `{json.dumps(outcome.get('reassign', {}), ensure_ascii=False)}`")
    say(f"- Tự nhận bàn giao: `{outcome.get('accepted')}`")
    say(f"- Phiên của lượt chạy: `{outcome.get('runtime_session_key')}`")
    say("")

    # 3) Sổ ghi task.
    say("## Sổ ghi của task, đọc lại từ database")
    say("")
    from sqlalchemy import select

    from app.db.session import SessionLocal
    from app.models.entities import Member, Task
    from app.models.v37 import TaskJournalEntry
    from app.services import work_context as wc

    db = SessionLocal()
    entries = db.execute(
        select(TaskJournalEntry).where(TaskJournalEntry.task_id == ctx["task_id"])
        .order_by(TaskJournalEntry.seq)).scalars().all()
    say("| seq | loại | ai | tóm tắt |")
    say("| --- | --- | --- | --- |")
    for entry in entries:
        actor = db.get(Member, entry.actor_member_id) if entry.actor_member_id else None
        say(f"| {entry.seq} | `{entry.kind}` | {actor.name if actor else 'hệ thống'} | "
            f"{entry.summary[:110]} |")
    say("")

    # 4) Gói ngữ cảnh mà Mia nhận.
    task = db.get(Task, ctx["task_id"])
    say(f"- Chủ việc trong database sau bàn giao: "
        f"**{db.get(Member, task.assignee_member_id).name}**")
    pack = wc.build_pack(db, task, organization_id=ctx["org_id"])
    checks = {
        "khối 1 nói đúng người nhận (Mia)": "Bạn là **Mia**" in pack["text"],
        "khối 5 có tên người bàn giao (Nina)": "Nina bàn giao" in pack["text"],
        "khối 5 mang nguyên hướng dẫn": SECRET_DETAIL in pack["text"],
        "khối 4 có mục handoff trong sổ": "handoff" in pack["text"],
    }
    say("")
    say("| kiểm tra gói ngữ cảnh | đạt |")
    say("| --- | --- |")
    for label, ok in checks.items():
        say(f"| {label} | {'**có**' if ok else 'không'} |")
    say("")
    say(f"- Gói dài {pack['chars']}/{pack['budget_chars']} ký tự.")
    say("")
    db.close()

    # 5) Hỏi chính Mia.
    say("## Hỏi chính Mia, trong phiên cô vừa nhận việc")
    say("")
    session_key = outcome.get("runtime_session_key") or ""
    if not session_key:
        say("- Không có phiên nào để hỏi (lượt chạy chưa xảy ra).")
    else:
        say(f"**Hỏi:** {QUESTION}")
        say("")
        answer = asyncio.run(ask_mia(QUESTION, session_key))
        say(f"> {answer[:700].replace(chr(10), ' ⏎ ')}")
        say("")
        hit = SECRET_DETAIL in answer or "18/09" in answer or "18/9" in answer
        say(f"- Nhắc đúng hạn nội bộ (`{SECRET_DETAIL}`): **{hit}**")
        say(f"- Nhắc hook đã bị loại (giảm giá sốc): "
            f"**{'giảm giá' in answer.lower()}**")
        say("")
        say("Chi tiết này **không nằm ở đâu khác** trong hệ thống: không ở tiêu đề "
            "task, không ở mô tả, không ở dự án. Nó chỉ có trong `instructions` "
            "của bàn giao. Trả lời đúng nghĩa là hướng dẫn bàn giao đã đi qua "
            "sổ ghi → gói ngữ cảnh → tới model.")
    say("")

    say("## Kết luận")
    say("")
    say("Trước WP-4.3: `handoff_artifact` tạo hàng database, gửi tin nhắn, phát "
        "event — rồi nằm im. Người nhận, kể cả khi là agent, không nhận được việc "
        "gì cho tới khi có người vào dispatch tay.")
    say("")
    say("Sau WP-4.3: một lời gọi API bàn giao vừa ghi sổ, vừa chuyển chủ việc, "
        "vừa tự nhận bàn giao qua đúng hàm của v10, vừa giao việc cho seat của "
        "người nhận — và gói ngữ cảnh của họ mang theo hướng dẫn bàn giao.")

    path = Path(__file__).resolve().parents[1] / "_reports" / "handoff-dispatch-e2e.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n→ đã ghi {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
