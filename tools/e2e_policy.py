"""D2.2 — phép thử thật: giao → tự chạy → báo cáo qua MCP → review SỬA → làm lại → DUYỆT → done.

Gateway OpenClaw thật, model giả có kịch bản (exec → company_task_comment qua
MCP ClawCompany → trả lời cuối). Reviewer là người (Long) quyết qua API.
Không ai bấm dispatch.

usage: .venv/bin/python tools/e2e_policy.py [framelog]   (API chạy với WAKEUP_DRAIN_SECONDS>0)
"""
import json, sqlite3, sys, time, uuid
import httpx

API = "http://127.0.0.1:8000"
FRAMES = sys.argv[1] if len(sys.argv) > 1 else ""
SEAT, REVIEWER = 2, 1
DB = "/data/cc/backend/dev.db"
c = httpx.Client(base_url=API, timeout=60)
tok = c.post("/api/auth/login", json={"email": "admin@clawcompany.local", "password": "ChangeMe123!"}).json()["access_token"]
H = {"Authorization": f"Bearer {tok}"}
out = {"steps": []}
T0 = time.time()


def step(name, ok, detail=None):
    out["steps"].append({"step": name, "ok": bool(ok), "t": round(time.time() - T0, 1), "detail": detail})
    print(("OK   " if ok else "LỖI ") + f"[{time.time() - T0:6.1f}s] " + name,
          json.dumps(detail, ensure_ascii=False, default=str)[:400], flush=True)


def wait_for(fn, timeout=90, every=1.0):
    end = time.time() + timeout
    while time.time() < end:
        v = fn()
        if v:
            return v
        time.sleep(every)
    return None


def task(tid):
    return next((t for t in c.get("/api/tasks", headers=H).json() if t["id"] == tid), {})


def policy(tid):
    return c.get(f"/api/tasks/{tid}/execution-policy", headers=H).json()


def approve_exec(tid):
    for a in c.get("/api/approvals", params={"status": "pending"}, headers=H).json():
        if f"company-task-{tid}" in (a.get("policy_key") or ""):
            c.post(f"/api/approvals/{a['id']}/resolve", headers=H, json={"status": "approved", "resolution_note": "e2e D2.2"})
            return a["id"]
    return None


def chat_sends(session):
    if not FRAMES:
        return None
    n = 0
    for line in open(FRAMES):
        f = json.loads(line)
        if f["dir"] == "out" and f["frame"].get("method") == "chat.send" and \
                (f["frame"].get("params") or {}).get("sessionKey") == session:
            n += 1
    return n


def seat_free():
    con = sqlite3.connect(DB)
    n = con.execute("select count(*) from task_runs where member_id=? and status in ('queued','running') "
                    "and started_at > datetime('now','-30 minutes')", (SEAT,)).fetchone()[0]
    con.close()
    return n == 0


def one_round(tid, label):
    aid = wait_for(lambda: approve_exec(tid), timeout=90)
    st = wait_for(lambda: task(tid).get("status") if task(tid).get("status") in ("review", "blocked") else None,
                  timeout=90)
    p = policy(tid)
    step(f"{label}: lệnh được duyệt, run xong → {st}", st == "review",
         {"exec_approval": aid, "status": st, "state": p.get("state", {}).get("status"),
          "round": p.get("state", {}).get("round"), "missing_report": p.get("state", {}).get("missing_report")})
    return st


step("0. seat rảnh", wait_for(seat_free, timeout=90, every=2))
sfx = uuid.uuid4().hex[:5]
comp = c.post("/api/v18/workspace/companies", headers=H, json={"organization_id": 1, "name": f"Policy {sfx}"}).json()
proj = c.post("/api/v18/workspace/projects", headers=H, json={"company_id": comp["id"], "name": f"Dự án {sfx}"}).json()
t = c.post("/api/v18/workspace/tasks", headers=H, json={"project_id": proj["id"], "title": f"Kiểm tra máy chủ {sfx}"}).json()
tid = t["id"]
c.post(f"/api/v18/workspace/tasks/{tid}/move", headers=H, json={"status": "todo"})
r = c.put(f"/api/tasks/{tid}/execution-policy", headers=H,
          json={"stages": [{"type": "review", "participants": [REVIEWER]}]})
step("1. đặt policy: 1 chặng review (Long)", r.status_code == 200, r.json())
r = c.post(f"/api/v18/workspace/tasks/{tid}/assign", headers=H, json={"assignee_member_id": SEAT})
step("2. giao cho Nina (không bấm dispatch)", r.status_code == 200)

one_round(tid, "3. vòng 1")
j = c.get(f"/api/tasks/{tid}/journal", headers=H).json()
reports = [e for e in j["entries"] if e["kind"] == "result" and e.get("actor_member_id") == SEAT]
step("4. Nina tự ghi báo cáo qua MCP company_task_comment", len(reports) >= 1,
     [{"seq": e["seq"], "summary": e["summary"]} for e in reports])

bad = c.post(f"/api/v18/workspace/tasks/{tid}/move", headers=H, json={"status": "done"})
step("5. kéo thẳng sang done khi chặng chưa qua → 409", bad.status_code == 409, bad.json())

r = c.post(f"/api/tasks/{tid}/review", headers=H, json={"decision": "revise", "note": "Ghi thêm múi giờ của lần chạy"})
step("6. Long: SỬA", r.status_code == 200 and task(tid).get("status") == "in_progress", r.json().get("state", {}).get("status"))

wk = wait_for(lambda: next((w for w in c.get("/api/tasks/wakeups", headers=H, params={"task_id": tid}).json()
                             if w["reason"] == "changes_requested" and w["status"] == "dispatched"), None), timeout=60)
step("7. Nina được đánh thức (changes_requested) và tự chạy lại", wk is not None, wk)
one_round(tid, "8. vòng 2")

r = c.post(f"/api/tasks/{tid}/review", headers=H, json={"decision": "approve", "note": "Đạt"})
final = task(tid)
p = policy(tid)
step("9. Long: DUYỆT → done", r.status_code == 200 and final.get("status") == "done",
     {"status": final.get("status"), "history": [(h["round"], h["decision"]) for h in p["state"]["history"]]})

con = sqlite3.connect(DB)
runs = con.execute("select id, trigger_kind, status, cost_usd, tokens_in, tokens_out from task_runs where task_id=? order by id",
                   (tid,)).fetchall()
con.close()
step("10. hai lượt chạy, chi phí thật", len(runs) == 2,
     {"runs": runs, "cost_usd": round(sum(r[3] or 0 for r in runs), 6), "chat.send": chat_sends(f"agent:dev:company-task-{tid}")})
print(json.dumps({"task_id": tid, **out}, ensure_ascii=False, default=str))
