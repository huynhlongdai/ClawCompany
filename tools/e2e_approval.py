#!/usr/bin/env python3
"""D1.1 — approval đầu-cuối qua API ClawCompany và gateway OpenClaw thật.

Đường đi: giao việc cho seat → agent gọi ``exec`` → gateway chặn lệnh, phát
``exec.approval.requested`` → follower ghi hàng ``approvals`` → người duyệt
trong Hộp việc (``POST /api/approvals/{id}/resolve``, đúng nút UI gọi) →
``exec.approval.resolve`` → lệnh chạy → agent trả kết quả.

Model là ``tools/scripted_llm.py`` (gọi exec một lần rồi trả lời); gateway,
tool exec, sổ duyệt và việc chạy lệnh là thật.

    python tools/e2e_approval.py [inbox|deny] [--base http://127.0.0.1:8000]
"""
from __future__ import annotations

import json
import sys
import time
import uuid

import httpx

MODE = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else "inbox"
BASE = sys.argv[sys.argv.index("--base") + 1] if "--base" in sys.argv else "http://127.0.0.1:8000"
SEAT = int(sys.argv[sys.argv.index("--seat") + 1]) if "--seat" in sys.argv else 2
# D1.2: --late N = đợi N giây rồi mới follow (mô phỏng follower bám muộn / API khởi động lại).
LATE = float(sys.argv[sys.argv.index("--late") + 1]) if "--late" in sys.argv else 0.0
c = httpx.Client(base_url=BASE, timeout=60)
tok = c.post("/api/auth/login", json={"email": "admin@clawcompany.local",
                                       "password": "ChangeMe123!"}).json()["access_token"]
H = {"Authorization": f"Bearer {tok}"}
out: dict = {"mode": MODE, "steps": []}


def step(name, ok, detail=""):
    out["steps"].append({"step": name, "ok": bool(ok), "detail": detail})
    print(("OK   " if ok else "LỖI ") + name + (f"\n      {str(detail)[:300]}" if detail else ""), flush=True)


def call(method, path, **kw):
    r = c.request(method, path, headers=H, **kw)
    try:
        return r.status_code, r.json()
    except Exception:  # noqa: BLE001
        return r.status_code, r.text[:300]


code, body = call("POST", "/api/v19/openclaw/bind", params={"organization_id": 1},
                  json={"member_id": SEAT, "runtime_agent_id": "dev"})
step("bind seat → agent 'dev'", code == 200, body)

sfx = uuid.uuid4().hex[:5]
_, comp = call("POST", "/api/v18/workspace/companies", json={"organization_id": 1, "name": f"Approval E2E {sfx}"})
_, proj = call("POST", "/api/v18/workspace/projects", json={"company_id": comp["id"], "name": f"Dự án {sfx}"})
_, task = call("POST", "/api/v18/workspace/tasks", json={"project_id": proj["id"], "title": f"Chạy lệnh kiểm tra {sfx}"})
tid = task["id"]
call("POST", f"/api/v18/workspace/tasks/{tid}/move", json={"status": "todo"})
call("POST", f"/api/v18/workspace/tasks/{tid}/assign", json={"assignee_member_id": SEAT})
code, started = call("POST", f"/api/v19/tasks/{tid}/start", params={"organization_id": 1})
step("start task (chat.send)", code == 200, started)
session = (started or {}).get("session_key") if isinstance(started, dict) else None
if LATE:
    time.sleep(LATE)
code, fol = call("POST", f"/api/v20/tasks/{tid}/follow", json={"session_key": session})
step("follow session", code == 200, fol)

approval = None
deadline = time.time() + 90
while time.time() < deadline and approval is None:
    _, rows = call("GET", "/api/approvals", params={"status": "pending"})
    for a in rows if isinstance(rows, list) else []:
        if session and session in (a.get("policy_key") or ""):
            approval = a
            break
    time.sleep(1.5)
step("hàng approvals từ exec.approval.requested", approval is not None,
     approval and {k: approval[k] for k in ("id", "action", "policy_key", "status")})
out["task_id"], out["session_key"] = tid, session
if approval is None:
    print(json.dumps(out, ensure_ascii=False)); sys.exit(1)

status = "approved" if MODE == "inbox" else "rejected"
t0 = time.time()
code, res = call("POST", f"/api/approvals/{approval['id']}/resolve",
                 json={"status": status, "resolution_note": "D1.1 e2e"})
step(f"duyệt trong Hộp việc ({status})", code == 200, res)

final = None
deadline = time.time() + 90
while time.time() < deadline:
    _, rows_ = call("GET", "/api/tasks")
    st = next((x.get("status") for x in rows_ if x.get("id") == tid), None) if isinstance(rows_, list) else None
    if st in ("review", "done", "blocked", "cancelled"):
        final = st
        break
    time.sleep(2)
out["elapsed_after_decision_s"] = round(time.time() - t0, 1)
_, runs = call("GET", f"/api/tasks/{tid}/runs")
out["runs"] = [{k: r.get(k) for k in ("id", "status", "started_at", "ended_at", "error_reason")}
               for r in (runs or {}).get("runs", [])] if isinstance(runs, dict) else runs
step("task kết thúc lượt chạy", final is not None, f"status={final} sau {out['elapsed_after_decision_s']}s")

_, tr = call("GET", f"/api/v19/tasks/{tid}/transcript", params={"organization_id": 1})
msgs = (tr or {}).get("messages") or [] if isinstance(tr, dict) else []
results = [m for m in msgs if m.get("role") == "toolResult" and m.get("toolName") == "exec"]
text = json.dumps(results, ensure_ascii=False)
# Kết quả tool (không phải đối số lời gọi) phải chứa dòng in ra của lệnh.
ran = any(not m.get("isError") and "clawcompany-approval-e2e" in json.dumps(m.get("content"), ensure_ascii=False)
          for m in results)
out["exec_results"] = [json.dumps(m.get("content"), ensure_ascii=False)[:400] for m in results]
step("lệnh đã chạy (kết quả trong transcript)" if MODE == "inbox" else "lệnh KHÔNG chạy",
     ran if MODE == "inbox" else not ran, text[:300])

_, ap = call("GET", "/api/approvals")
mine = [a for a in ap if session in (a.get("policy_key") or "")] if isinstance(ap, list) else []
out["approvals_for_session"] = [{k: a[k] for k in ("id", "status", "resolution_note")} for a in mine]
step("không có hàng approval trùng", len(mine) == 1, out["approvals_for_session"])

_, audit = call("GET", "/api/activity", params={"limit": 50})
trail = [a for a in audit if a.get("object_type") == "approval" and str(a.get("object_id")) == str(approval["id"])] \
    if isinstance(audit, list) else []
out["audit"] = [{"action": a["action"], "result": a["result"], "actor": a["actor_name"],
                 "at": a["created_at"]} for a in reversed(trail)]
need = {"approval.requested", "approval.decided", "approval.resolved"}
step("audit_events đủ ba mốc", need <= {a["action"] for a in trail}, out["audit"])
print(json.dumps(out, ensure_ascii=False, indent=1))
