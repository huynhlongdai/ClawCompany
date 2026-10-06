"""D2.1 — phép thử thật: giao việc / @nhắc tên / hết ngân sách → wakeup → run
trên gateway OpenClaw thật (model giả có kịch bản). Không ai bấm dispatch.

usage: .venv/bin/python tools/e2e_wakeup.py [framelog]   (API chạy với WAKEUP_DRAIN_SECONDS>0)
"""
import json, sqlite3, sys, time, uuid
import httpx

API = "http://127.0.0.1:8000"
FRAMES = sys.argv[1] if len(sys.argv) > 1 else ""
SEAT = 2
c = httpx.Client(base_url=API, timeout=60)
tok = c.post("/api/auth/login", json={"email": "admin@clawcompany.local", "password": "ChangeMe123!"}).json()["access_token"]
H = {"Authorization": f"Bearer {tok}"}
out = {"steps": []}


def step(name, ok, detail=None):
    out["steps"].append({"step": name, "ok": bool(ok), "detail": detail})
    print(("OK   " if ok else "LỖI ") + name, json.dumps(detail, ensure_ascii=False, default=str)[:300])


def new_task(title):
    sfx = uuid.uuid4().hex[:5]
    comp = c.post("/api/v18/workspace/companies", headers=H, json={"organization_id": 1, "name": f"Wakeup {sfx}"}).json()
    proj = c.post("/api/v18/workspace/projects", headers=H, json={"company_id": comp["id"], "name": f"Dự án {sfx}"}).json()
    t = c.post("/api/v18/workspace/tasks", headers=H, json={"project_id": proj["id"], "title": f"{title} {sfx}"}).json()
    c.post(f"/api/v18/workspace/tasks/{t['id']}/move", headers=H, json={"status": "todo"})
    return t["id"]


def assign(tid):
    r = c.post(f"/api/v18/workspace/tasks/{tid}/assign", headers=H, json={"assignee_member_id": SEAT})
    return r.status_code


def wakes(tid):
    return c.get("/api/tasks/wakeups", headers=H, params={"task_id": tid}).json()


def wait_for(fn, timeout=90, every=1.0):
    end = time.time() + timeout
    while time.time() < end:
        v = fn()
        if v:
            return v
        time.sleep(every)
    return None


def status(tid):
    return next((t["status"] for t in c.get("/api/tasks", headers=H).json() if t["id"] == tid), None)


def approve_pending(session):
    rows = c.get("/api/approvals", params={"status": "pending"}, headers=H).json()
    for a in rows:
        if session in (a.get("policy_key") or ""):
            c.post(f"/api/approvals/{a['id']}/resolve", headers=H, json={"status": "approved", "resolution_note": "e2e D2.1"})
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


E2E_TITLES = ("Kiểm tra máy chủ", "Tổng hợp log", "Viết báo cáo tuần", "Việc khi hết tiền")
DB = "/data/cc/backend/dev.db"


def preflight():
    """Dọn rác của lần chạy trước: việc e2e còn mở của seat bị huỷ, lệnh chờ
    duyệt của chúng bị từ chối, rồi đợi seat rảnh. Không có bước này, việc
    tồn đọng được requeue sẽ chiếm seat và làm sai mọi kịch bản phía sau."""
    left = [t for t in c.get("/api/tasks", headers=H).json()
            if t.get("assignee_member_id") == SEAT and t["status"] in ("backlog", "todo", "in_progress", "blocked")
            and t["title"].startswith(E2E_TITLES)]
    for t in left:
        c.post(f"/api/v18/workspace/tasks/{t['id']}/move", headers=H, json={"status": "cancelled"})
    for a in c.get("/api/approvals", params={"status": "pending"}, headers=H).json():
        if any(f"company-task-{t['id']}" in (a.get("policy_key") or "") for t in left):
            c.post(f"/api/approvals/{a['id']}/resolve", headers=H, json={"status": "rejected", "resolution_note": "e2e preflight"})

    def seat_free():
        con = sqlite3.connect(DB)
        n = con.execute("select count(*) from task_runs where member_id=? and status in ('queued','running') "
                        "and started_at > datetime('now','-30 minutes')", (SEAT,)).fetchone()[0]
        con.close()
        return n == 0
    free = wait_for(seat_free, timeout=90, every=2)
    step("0. preflight: dọn việc e2e cũ, seat rảnh", free, {"cancelled": [t["id"] for t in left]})
    if not free:
        sys.exit(1)


def finish(tid):
    session = f"agent:dev:company-task-{tid}"
    aid = wait_for(lambda: approve_pending(session), timeout=60)
    st = wait_for(lambda: status(tid) if status(tid) in ("review", "blocked") else None, timeout=60)
    return aid, st


preflight()
# A. Giao việc → run ≤ 60 giây, không ai bấm dispatch.
x = new_task("Kiểm tra máy chủ")
t0 = time.time(); code = assign(x)
wk = wait_for(lambda: next((w for w in wakes(x) if w["status"] != "queued"), None), timeout=60)
lat = round(time.time() - t0, 1)
step("A. giao việc → wakeup dispatched ≤ 60s", wk and wk["status"] == "dispatched" and lat <= 60,
     {"task": x, "assign_http": code, "latency_s": lat, "wakeup": wk})
# D. Seat bận: giao thêm việc Y trong lúc X đang chạy → bỏ qua seat_busy, rồi tự xếp lại khi X xong.
y = new_task("Tổng hợp log")
assign(y)
wy = wait_for(lambda: next((w for w in wakes(y) if w["status"] != "queued"), None), timeout=40)
step("D1. việc thứ hai lúc seat bận → skipped seat_busy", wy and wy["skip_reason"].startswith("seat_busy"), wy)
aid, st = finish(x)
step("A2. lệnh được duyệt, X sang review", st == "review", {"approval": aid, "status": st, "chat.send": chat_sends(f"agent:dev:company-task-{x}")})
wy2 = wait_for(lambda: next((w for w in wakes(y) if w["status"] == "dispatched"), None), timeout=60)
step("D2. X xong → Y được xếp lại và chạy", bool(wy2), wy2)
aid, st = finish(y)
step("D3. Y sang review", st == "review", {"approval": aid, "status": st})

# B. Hai sự kiện trong 10 giây → 1 run.
z = new_task("Viết báo cáo tuần")
assign(z)
time.sleep(2)
cm = c.post(f"/api/tasks/{z}/journal", headers=H, json={"summary": "@Nina nhớ ghi rõ nguồn số liệu"}).json()
wz = wait_for(lambda: (lambda ws: ws if ws and all(w["status"] != "queued" for w in ws) else None)(wakes(z)), timeout=60)
reasons = sorted((w["reason"], w["status"]) for w in (wz or []))
aid, st = finish(z)
sends = chat_sends(f"agent:dev:company-task-{z}")
step("B. giao + @nhắc trong 10s → 1 run (1 chat.send)",
     reasons == [("assigned", "dispatched"), ("mentioned", "coalesced")] and (sends in (None, 1)),
     {"task": z, "comment": cm, "wakeups": reasons, "chat.send": sends, "status": st})

# C. Hết ngân sách → skipped budget, gateway không nhận chat.send.
nina_company = next(m for m in c.get("/api/members", headers=H).json() if m["id"] == SEAT)["company_id"]
env = c.post("/api/v9/budgets", headers=H, json={"organization_id": 1, "company_id": nina_company,
                                                 "name": "E2E D2.1 hạn mức $0.04", "amount_limit": 0.04}).json()
b = new_task("Việc khi hết tiền")
assign(b)
wb = wait_for(lambda: next((w for w in wakes(b) if w["status"] != "queued"), None), timeout=40)
time.sleep(3)
sends_b = chat_sends(f"agent:dev:company-task-{b}")
step("C. hết ngân sách → skipped 'budget', gateway không nhận chat.send",
     wb and wb["skip_reason"].startswith("budget") and sends_b in (None, 0), {"wakeup": wb, "chat.send": sends_b})
db = sqlite3.connect("/data/cc/backend/dev.db"); db.execute("update budget_envelopes set status='archived' where id=?", (env["id"],)); db.commit()

out["tasks"] = {"A": x, "D": y, "B": z, "C": b}
print(json.dumps(out, ensure_ascii=False, default=str))
