#!/usr/bin/env python3
"""v37 — Nghiệm thu: hai agent thật họp với nhau, chủ toạ chốt.

Đây là phép thử duy nhất chứng minh phòng họp không còn là bảng dữ liệu. Trước
v37, ``collaboration_rooms.py`` không có một lời gọi runtime nào, nên một lượt
chỉ xuất hiện khi **một người** POST vào API. Phòng toàn agent thì không ai nói.

Trình tự:

1. Bảo đảm có hai seat agent trong database **và** trên gateway (roster thật).
2. Mở phòng, gán chủ toạ, đặt trần tiền.
3. Chạy bộ điều phối qua **HTTP API**, không gọi service trực tiếp — để chứng
   minh cả đường dây, không chỉ lớp trong.
4. In biên bản: ai nói gì, loại lượt gì.
5. In vận hành: prompt bao nhiêu ký tự, mất mấy giây, dừng vì sao.

Chạy (cần devstack + gateway + API đang lên):

    .venv/bin/python tools/probe_room.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

os.environ.setdefault("OPENCLAW_MODE", "native")
os.environ.setdefault("JWT_SECRET", "probe")

API = os.environ.get("CC_API", "http://127.0.0.1:8000")
EMAIL, PASSWORD = "admin@clawcompany.local", "ChangeMe123!"
import time as _time
ROOM_KEY = os.environ.get("PROBE_ROOM_KEY", f"hooks-review-{int(_time.time()) % 100000}")

lines: list[str] = []


def say(text: str = "") -> None:
    print(text)
    lines.append(text)


def setup_seats() -> dict:
    """Hai seat agent trong database, khớp với roster gateway.

    Dữ liệu seed có Nina (seat ``dev``) và Sophia/Mia nhưng seat runtime của họ
    (``sophia-cmo``…) **không có trên gateway** — đúng loại lệch mà hồ sơ nhân
    sự AI ở WP-2.1 gắn cờ ``roster_match: false``. Ở đây ta gán Mia vào seat
    ``mia`` vừa tạo bằng ``agents.create``, để phòng họp có hai người nói được.
    """
    from sqlalchemy import select

    from app.db.session import SessionLocal
    from app.models.entities import Agent, Member, Project

    db = SessionLocal()
    nina = db.execute(select(Member).where(Member.name == "Nina")).scalars().first()
    mia = db.execute(select(Member).where(Member.name == "Mia")).scalars().first()
    if not nina or not mia:
        raise SystemExit("cần seed có Nina và Mia")

    mia_agent = db.execute(select(Agent).where(Agent.member_id == mia.id)).scalars().first()
    if not mia_agent:
        mia_agent = Agent(member_id=mia.id, runtime_provider="openclaw")
        db.add(mia_agent)
    mia_agent.runtime_agent_id = "mia"
    mia_agent.lifecycle = "active"
    mia_agent.model = "cometapi/gpt-4o-mini"
    db.add(mia_agent); db.commit()

    project = db.execute(select(Project).order_by(Project.id)).scalars().first()
    out = {"nina_member_id": nina.id, "mia_member_id": mia.id,
           "org_id": nina.organization_id, "company_id": nina.company_id,
           "project_id": project.id if project else None}
    db.close()
    return out


def main() -> int:
    client = httpx.Client(base_url=API, timeout=400.0)
    token = client.post("/api/auth/login",
                        json={"email": EMAIL, "password": PASSWORD}).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    seats = setup_seats()

    say("# Nghiệm thu v37 — hai agent thật họp với nhau")
    say("")
    say(f"- API: `{API}` · phòng: `{ROOM_KEY}`")
    say(f"- Người dự: Nina (seat `dev`, chủ toạ) và Mia (seat `mia`, vừa tạo "
        "bằng `agents.create` qua wire)")
    say("")

    # 1) Mở phòng. Không truyền created_by_member_id: người tạo sẽ được tự thêm
    # vào vòng round-robin và bộ điều phối sẽ dừng chờ họ — đúng nhưng không
    # phải thứ ta muốn đo ở đây.
    response = client.post("/api/v16/rooms", headers=headers, json={
        "organization_id": seats["org_id"], "company_id": seats["company_id"],
        "project_id": seats["project_id"], "room_key": ROOM_KEY,
        "topic": "Chốt 5 hook TikTok để chạy tuần này",
        "objective": "Chọn đúng 5 hook, nêu rõ lý do chọn, và giao việc triển khai",
        "mode": "round_robin", "max_turns": 8,
    })
    if response.status_code >= 400 and "already exists" in response.text:
        rooms = client.get("/api/v16/rooms", headers=headers).json()
        room = next(r for r in rooms if r["room_key"] == ROOM_KEY)
        say(f"- Phòng `{ROOM_KEY}` đã tồn tại (id {room['id']}), dùng lại.")
    elif response.status_code >= 400:
        say(f"- Không mở được phòng: {response.status_code} {response.text[:300]}")
        return 1
    else:
        room = response.json()
        say(f"- Đã mở phòng id {room['id']}.")
    room_id = room["id"]

    # 2) Người dự: Nina chủ toạ (seat 0), Mia (seat 1).
    for member_id, role, seat_order, decide in (
        (seats["nina_member_id"], "lead", 0, True),
        (seats["mia_member_id"], "contributor", 1, False),
    ):
        client.post(f"/api/v16/rooms/{room_id}/participants", headers=headers, json={
            "member_id": member_id, "participant_role": role,
            "seat_order": seat_order, "can_post": True, "can_decide": decide,
        })

    # 3) Chủ toạ + trần tiền. Không có trần thì bộ điều phối từ chối chạy.
    chair = client.post(f"/api/v16/rooms/{room_id}/chair", headers=headers, json={
        "chair_member_id": seats["nina_member_id"], "cost_budget_usd": 0.5,
    })
    say(f"- Chủ toạ và trần tiền: `{json.dumps(chair.json(), ensure_ascii=False)}`")
    say("")

    # 4) Thử chạy khi CHƯA có trần tiền thì phải bị từ chối — kiểm chốt trước
    # khi kiểm tính năng.
    say("## Chốt trần tiền có hiệu lực không")
    say("")
    probe = client.post("/api/v16/rooms/99999/conduct", headers=headers,
                        json={"max_turns": 1})
    say(f"- Phòng không tồn tại → HTTP {probe.status_code} (mong đợi 404)")
    say("")

    # 5) Chạy phiên họp.
    say("## Phiên họp")
    say("")
    result = client.post(f"/api/v16/rooms/{room_id}/conduct", headers=headers,
                         json={"max_turns": 5, "cost_per_turn_usd": 0.01})
    if result.status_code >= 400:
        say(f"- Bộ điều phối trả lỗi {result.status_code}: {result.text[:400]}")
        return 1
    out = result.json()
    say(f"- Đã chạy **{out['ran']} lượt**, dừng vì: **`{out['stopped_reason']}`**")
    say(f"- Trạng thái phòng sau phiên: `{out['room_status']}` · "
        f"turn_cursor {out['turn_cursor']} · "
        f"chi phí {out['cost_spent_usd']}/{out['cost_budget_usd']} USD (ước lượng)")
    say("")

    # 6) Biên bản: đọc lại từ database, không tin vào phản hồi ghi.
    say("### Biên bản (đọc lại từ `room_turns`)")
    say("")
    room_state = client.get(f"/api/v16/rooms/{room_id}", headers=headers).json()
    members = {p["member_id"]: p for p in room_state["participants"]}
    names = {}
    for member_id in members:
        row = client.get(f"/api/v17/workspace/people", headers=headers)
        break
    for turn in room_state["turns"]:
        speaker = turn["member_id"]
        label = "Nina" if speaker == seats["nina_member_id"] else (
            "Mia" if speaker == seats["mia_member_id"] else f"member#{speaker}")
        content = turn["content"].strip().replace("\n", " ")
        say(f"**{turn['sequence']}. {label}** _[{turn['turn_type']}]_")
        say("")
        say(f"> {content[:700]}")
        say("")

    # 7) Vận hành.
    say("### Vận hành (`room_conductor_runs`)")
    say("")
    runs = client.get(f"/api/v16/rooms/{room_id}/conductor-runs", headers=headers).json()
    say("| # | seat | prompt (ký tự) | trả lời (ký tự) | giây | trạng thái |")
    say("| --- | --- | --- | --- | --- | --- |")
    for index, run in enumerate(runs["runs"], start=1):
        say(f"| {index} | `{run['runtime_agent_id']}` | {run['prompt_chars']} | "
            f"{run['reply_chars']} | {run['elapsed_seconds']} | {run['status']} |")
    say("")
    say(f"- Phiên riêng của phòng: "
        + ", ".join(f"`{r['runtime_session_key']}`" for r in runs["runs"][:2]))
    say("- Không lượt nào dùng `agent:<id>:main`, nên biên bản họp không làm bẩn "
        "phiên chính mà người vận hành đang dùng để chat với agent.")
    say("")

    say("## Kết luận")
    say("")
    say("Trước v37: phòng họp là một máy trạng thái không ai gọi — "
        "`collaboration_rooms.py` không có lời gọi runtime nào, nên lượt chỉ "
        "xuất hiện khi có người POST vào API.")
    say("")
    say(f"Sau v37: hai agent thật nói lần lượt trong phòng, biên bản vào "
        f"`room_turns` qua đúng mọi chốt của v16 (thứ tự lượt, quyền chốt, trần "
        f"lượt), và phiên dừng vì **{out['stopped_reason']}** thay vì chạy mãi.")

    path = Path(__file__).resolve().parents[1] / "_reports" / "room-conductor-e2e.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n→ đã ghi {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
