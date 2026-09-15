#!/usr/bin/env python3
"""Đường dây OpenClaw đầu-cuối, qua API ClawCompany thật.

Khác với ``tools/probe_*.py`` (dò thẳng adapter), script này đi đúng con đường
người dùng đi: đăng nhập -> xem roster gateway -> bind một agent seat -> tạo
việc -> start -> đọc transcript -> đọc kênh live của v35.

Cần: devstack đang chạy, API ở 127.0.0.1:8000 với OPENCLAW_MODE=native, và một
gateway OpenClaw thật ở ws://127.0.0.1:18789.
"""
from __future__ import annotations

import json
import sys
import uuid

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
ADMIN = {"email": "admin@clawcompany.local", "password": "ChangeMe123!"}

client = httpx.Client(base_url=BASE, timeout=60.0)
steps: list[tuple[str, bool, str]] = []


def step(name: str, ok: bool, detail: str = "") -> None:
    steps.append((name, ok, detail))
    mark = "OK  " if ok else "LỖI "
    print(f"{mark} {name}" + (f"\n       {detail[:400]}" if detail else ""))


def call(method: str, path: str, **kwargs) -> tuple[int, object]:
    response = client.request(method, path, headers=HEADERS, **kwargs)
    try:
        return response.status_code, response.json()
    except Exception:
        return response.status_code, response.text[:400]


token = client.post("/api/auth/login", json=ADMIN).json()["access_token"]
HEADERS = {"Authorization": f"Bearer {token}"}
step("đăng nhập admin", True)

# 1. Giao thức và sức khoẻ gateway -----------------------------------------
code, body = call("GET", "/api/v19/openclaw/protocol")
protocol = body if isinstance(body, dict) else {}
step("v19 protocol", code == 200,
     f"mode={protocol.get('mode') or (protocol.get('runtime') or {}).get('mode')} "
     f"khoá={sorted(protocol)[:6]}")

code, body = call("GET", "/api/v19/openclaw/health")
health = (body or {}).get("health", {}) if isinstance(body, dict) else {}
runtime_info = (body or {}).get("runtime", {}) if isinstance(body, dict) else {}
step("v19 health (gateway thật)", code == 200 and health.get("status") == "healthy",
     f"mode={runtime_info.get('mode')} status={health.get('status')} "
     f"runtimeVersion={(health.get('result') or {}).get('runtimeVersion')}")

# 2. Roster agent trên gateway ---------------------------------------------
code, body = call("GET", "/api/v19/openclaw/agents", params={"organization_id": 1})
gateway_agents = body.get("agents", []) if isinstance(body, dict) else body
step("v19 gateway agents", code == 200 and bool(gateway_agents),
     json.dumps(gateway_agents, ensure_ascii=False)[:250])

code, body = call("GET", "/api/v19/openclaw/seats", params={"organization_id": 1})
seats = body.get("seats", []) if isinstance(body, dict) else body
if isinstance(seats, dict):   # company_agent_index có thể trả dict theo agent id
    seats = list(seats.values())
step("v19 company seats", code == 200, f"{len(seats)} ghế agent")

# 3. Đối chiếu seat với roster ---------------------------------------------
code, body = call("POST", "/api/v19/openclaw/reconcile", params={"organization_id": 1})
step("v19 reconcile", code == 200, json.dumps(body, ensure_ascii=False)[:300])

# 4. Bind một seat vào agent 'dev' của gateway ------------------------------
seat_id = None
for entry in seats:
    if isinstance(entry, dict):
        seat_id = entry.get("member_id") or entry.get("id")
        if seat_id:
            break
if seat_id:
    code, body = call("POST", "/api/v19/openclaw/bind",
                      params={"organization_id": 1},
                      json={"member_id": seat_id, "runtime_agent_id": "dev"})
    step("v19 bind seat -> agent 'dev'", code == 200,
         json.dumps(body, ensure_ascii=False)[:300])
    if code == 200 and isinstance(body, dict):
        print(f"       session key: {body.get('main_session_key')}")
else:
    step("v19 bind seat", False, "không có ghế agent nào trong seed")

# 5. Tạo việc rồi dispatch --------------------------------------------------
suffix = uuid.uuid4().hex[:6]
code, company = call("POST", "/api/v18/workspace/companies",
                     json={"organization_id": 1, "name": f"E2E {suffix}", "industry": "AI"})
code, project = call("POST", "/api/v18/workspace/projects",
                     json={"company_id": company["id"], "name": f"Dự án {suffix}"})
code, task = call("POST", "/api/v18/workspace/tasks",
                  json={"project_id": project["id"], "title": f"Việc {suffix}"})
task_id = task.get("id")
step("tạo công ty/dự án/việc", bool(task_id), f"task_id={task_id}")

if seat_id and task_id:
    call("POST", f"/api/v18/workspace/tasks/{task_id}/move", json={"status": "todo"})
    call("POST", f"/api/v18/workspace/tasks/{task_id}/assign",
         json={"assignee_member_id": seat_id})
    code, body = call("POST", f"/api/v19/tasks/{task_id}/start",
                      params={"organization_id": 1})
    # Gateway dev không có credential model, nên một lượt chạy có thể dừng ở
    # tầng model. Điều cần kiểm ở đây là ClawCompany ĐI QUA được tầng giao
    # thức: có session key, có phản hồi, không phải 1008 hay INVALID_REQUEST.
    detail = json.dumps(body, ensure_ascii=False)[:400]
    protocol_ok = code < 500 and "INVALID_REQUEST" not in detail and "1008" not in detail
    step("v19 start task (dispatch qua chat.send)", protocol_ok, f"HTTP {code} {detail}")

    code, body = call("GET", f"/api/v19/tasks/{task_id}/transcript",
                      params={"organization_id": 1})
    step("v19 transcript", code == 200, json.dumps(body, ensure_ascii=False)[:300])

# 6. Kênh live của v35 ------------------------------------------------------
for path in ("/api/v35/live/readiness", "/api/v35/live/snapshot",
             "/api/v35/live/tasks", "/api/v35/live/events"):
    code, body = call("GET", path, params={"organization_id": 1})
    step(f"v35 {path.rsplit('/', 1)[-1]}", code == 200,
         json.dumps(body, ensure_ascii=False)[:220])

# 7. SSE: mở kênh và đọc vài frame -----------------------------------------
try:
    with client.stream("GET", "/api/v35/live/stream",
                       params={"organization_id": 1, "seconds": 6},  # API đòi seconds >= 5
                       headers=HEADERS) as response:
        frames = []
        for line in response.iter_lines():
            if line:
                frames.append(line)
            if len(frames) >= 4:
                break
    step("v35 SSE stream", response.status_code == 200,
         f"HTTP {response.status_code}, {len(frames)} dòng: " + " | ".join(frames[:3])[:250])
except Exception as exc:  # noqa: BLE001
    step("v35 SSE stream", False, f"{type(exc).__name__}: {exc}")

failed = [name for name, ok, _ in steps if not ok]
print(f"\n{len(steps) - len(failed)}/{len(steps)} bước OK")
if failed:
    print("lỗi ở: " + ", ".join(failed))
raise SystemExit(1 if failed else 0)
