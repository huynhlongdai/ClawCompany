"""D2.3 — phép thử thật trên gateway OpenClaw 2026.9.8 (model giả, giá kiểu Sonnet).

P1 vòng thật: phong bì seat $5 → giao việc → giữ chỗ trước chat.send → run → quyết toán
   → đối chiếu nền theo sessions.usage → số trên /budgets-overview khớp gateway ±5%.
P2 hạn mức $0.10: ước tính từ run thật > $0.10 → wakeup skipped 'budget', 0 chat.send.
P3 ba nấc: phong bì L ≈ 1,1 × ước tính → 1 run → ≥80% cảnh báo + inbox + luật khối 6;
   việc kế tiếp bị chặn ở giữ chỗ (0 chat.send).
usage: .venv/bin/python tools/e2e_budget.py /tmp/frames_d23.jsonl  (API: WAKEUP_DRAIN_SECONDS>0)
"""
import json, sqlite3, sys, time, uuid
import httpx

API = "http://127.0.0.1:8000"
FRAMES = sys.argv[1] if len(sys.argv) > 1 else ""
PHASES = sys.argv[2].split(",") if len(sys.argv) > 2 else ["P1", "P2", "P3"]
SEAT = 2
DB = "/data/cc/backend/dev.db"
c = httpx.Client(base_url=API, timeout=90)
tok = c.post("/api/auth/login", json={"email": "admin@clawcompany.local", "password": "ChangeMe123!"}).json()["access_token"]
H = {"Authorization": f"Bearer {tok}"}
out = {"steps": [], "started": time.strftime("%Y-%m-%d %H:%M:%S")}
TITLE = "E2E D2.3"


def step(name, ok, detail=None):
    out["steps"].append({"step": name, "ok": bool(ok), "detail": detail})
    print(("OK   " if ok else "LỖI ") + name, json.dumps(detail, ensure_ascii=False, default=str)[:400], flush=True)


def wait_for(fn, timeout=90, every=1.0):
    end = time.time() + timeout
    while time.time() < end:
        v = fn()
        if v:
            return v
        time.sleep(every)
    return None


def new_task(title):
    sfx = uuid.uuid4().hex[:5]
    comp = c.post("/api/v18/workspace/companies", headers=H, json={"organization_id": 1, "name": f"D2.3 {sfx}"}).json()["id"]
    proj = c.post("/api/v18/workspace/projects", headers=H, json={"company_id": comp, "name": f"Dự án D2.3 {sfx}"}).json()
    t = c.post("/api/v18/workspace/tasks", headers=H, json={"project_id": proj["id"], "title": f"{TITLE} {title} {sfx}"}).json()
    c.post(f"/api/v18/workspace/tasks/{t['id']}/move", headers=H, json={"status": "todo"})
    return t["id"]


def assign(tid):
    return c.post(f"/api/v18/workspace/tasks/{tid}/assign", headers=H, json={"assignee_member_id": SEAT}).status_code


def wakes(tid):
    return c.get("/api/tasks/wakeups", headers=H, params={"task_id": tid}).json()


def status(tid):
    return next((t["status"] for t in c.get("/api/tasks", headers=H).json() if t["id"] == tid), None)


def approve_pending(session):
    for a in c.get("/api/approvals", params={"status": "pending"}, headers=H).json():
        if session in (a.get("policy_key") or ""):
            c.post(f"/api/approvals/{a['id']}/resolve", headers=H, json={"status": "approved", "resolution_note": "e2e D2.3"})
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


def sent_text(session):
    for line in open(FRAMES):
        f = json.loads(line)
        if f["dir"] == "out" and f["frame"].get("method") == "chat.send" and \
                (f["frame"].get("params") or {}).get("sessionKey") == session:
            return json.dumps(f["frame"].get("params"), ensure_ascii=False)
    return ""


def overview():
    return c.get("/api/v9/budgets-overview", headers=H).json()


def env_of(bid):
    return next(b for b in overview()["budgets"] if b["id"] == bid)


def make_env(name, limit, warn=80):
    r = c.post("/api/v9/budgets", headers=H, json={"organization_id": 1, "name": name, "amount_limit": limit,
                                                   "scope_type": "member", "scope_id": SEAT, "warn_pct": warn})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def archive(bid):
    db = sqlite3.connect(DB); db.execute("update budget_envelopes set status='archived' where id=?", (bid,)); db.commit()


def seat_runs():
    db = sqlite3.connect(DB)
    rows = db.execute("select id,cost_usd from task_runs where member_id=? and cost_usd>0 order by id desc limit 10",
                      (SEAT,)).fetchall()
    return rows


def preflight():
    db = sqlite3.connect(DB)
    db.execute("update budget_envelopes set status='archived' where name like 'E2E D2.%' and status!='archived'")
    db.execute("update members set status='active' where id=? and status='paused'", (SEAT,))
    db.commit()
    left = [t for t in c.get("/api/tasks", headers=H).json()
            if t.get("assignee_member_id") == SEAT and t["status"] in ("backlog", "todo", "in_progress", "blocked")]
    for t in left:
        c.post(f"/api/v18/workspace/tasks/{t['id']}/move", headers=H, json={"status": "cancelled"})
    for a in c.get("/api/approvals", params={"status": "pending"}, headers=H).json():
        c.post(f"/api/approvals/{a['id']}/resolve", headers=H, json={"status": "rejected", "resolution_note": "e2e preflight"})
    db = sqlite3.connect(DB)
    stale = [r[0] for r in db.execute("select r.id from task_runs r join tasks t on t.id=r.task_id where r.member_id=? "
                                      "and r.status in ('queued','running') and t.status='cancelled'", (SEAT,))]
    db.execute(f"update task_runs set status='cancelled', ended_at=datetime('now') where id in ({','.join(map(str, stale)) or '0'})")
    db.commit()
    out["stale_runs_closed"] = stale
    step("0. preflight: phong bì E2E cũ archived, việc mở của seat huỷ", True, {"cancelled": [t["id"] for t in left]})


def run_once(tid, timeout=120):
    session = f"agent:dev:company-task-{tid}"
    t0 = time.time(); assign(tid)
    wk = wait_for(lambda: next((w for w in wakes(tid) if w["status"] != "queued"), None), timeout=60)
    held = None
    if wk and wk["status"] == "dispatched":
        held = env_snapshot()
    aid = wait_for(lambda: approve_pending(session), timeout=60) if wk and wk["status"] == "dispatched" else None
    st = wait_for(lambda: status(tid) if status(tid) in ("review", "blocked", "done") else None, timeout=timeout) if aid else status(tid)
    return {"task": tid, "session": session, "wakeup": wk, "approval": aid, "status": st,
            "latency_s": round(time.time() - t0, 1), "held_during_run": held}


CUR = {"bid": None}


def env_snapshot():
    if CUR["bid"] is None:
        return None
    b = env_of(CUR["bid"])
    return {"reserved": b["amount_reserved"], "spent": b["amount_spent"]}


preflight()
est_before = seat_runs()
out["estimate_input_runs"] = est_before

if "P1" in PHASES:
    bid = CUR["bid"] = make_env(f"{TITLE} vòng thật $5", 5.0)
    tid = new_task("vòng thật")
    r = run_once(tid)
    step("P1a. giao việc → giữ chỗ trước chat.send → run → review",
         r["wakeup"] and r["wakeup"]["status"] == "dispatched" and r["status"] == "review"
         and (r["held_during_run"] or {}).get("reserved", 0) > 0, r)
    rec = None

    def settled():
        b = env_of(bid)
        g = c.get("/api/tasks/cost-reconciliation", headers=H, params={"task_id": tid}).json()
        rows = g.get("rows") or g.get("tasks") or []
        gw = next((x["gateway"]["cost_usd"] for x in rows if x.get("task_id") == tid and x.get("gateway")), None)
        if gw and b["amount_reserved"] == 0 and abs(b["amount_spent"] - gw) <= 0.05 * gw:
            return {"budget": b, "gateway_usd": gw, "reconciliation": rows}
        settled.last = {"budget": b, "gateway_usd": gw, "raw": g}
        return None
    settled.last = None
    rec = wait_for(settled, timeout=40, every=2)
    info = rec or settled.last
    b = info["budget"]; gw = info["gateway_usd"]
    dev = abs(b["amount_spent"] - gw) / gw * 100 if gw else None
    step("P1b. số trên UI (budgets-overview) khớp gateway sessions.usage ±5%",
         rec is not None, {"ui_spent_usd": b["amount_spent"], "gateway_usd": gw, "deviation_pct": dev,
                           "reserved_after": b["amount_reserved"], "by_seat": b["spend"]["by_seat"],
                           "by_task": b["spend"]["by_task"], "runs": b["spend"]["runs"],
                           "chat.send": chat_sends(r["session"])})
    out["P1"] = {"task": tid, "budget_id": bid, "gateway_usd": gw, "ui_spent_usd": b["amount_spent"], "deviation_pct": dev}
    archive(bid)

if "P2" in PHASES:
    bid = CUR["bid"] = make_env(f"{TITLE} hạn mức $0.10", 0.10)
    runs = seat_runs()
    est = max(0.05, sum(x[1] for x in runs) / len(runs)) if runs else 0.05
    tid = new_task("hạn mức 0.10")
    r = run_once(tid)
    time.sleep(3)
    sends = chat_sends(r["session"])
    step("P2. seat hạn mức $0.10 → wakeup skipped 'budget', gateway không nhận chat.send",
         r["wakeup"] and r["wakeup"]["status"] == "skipped" and r["wakeup"]["skip_reason"].startswith("budget")
         and sends == 0, {"estimate_usd": round(est, 6), "recent_runs": runs, "wakeup": r["wakeup"], "chat.send": sends,
                          "budget": env_of(bid)})
    out["P2"] = {"task": tid, "budget_id": bid, "estimate_usd": est}
    archive(bid)

if "P3" in PHASES:
    runs = seat_runs()
    est = max(0.05, sum(x[1] for x in runs) / len(runs)) if runs else 0.05
    limit = round(est * 1.1, 6)
    bid = CUR["bid"] = make_env(f"{TITLE} ba nấc", limit, warn=80)
    tid = new_task("ba nấc — lượt 1")
    r = run_once(tid)
    b = wait_for(lambda: (lambda x: x if x["amount_reserved"] == 0 and x["amount_spent"] > 0 else None)(env_of(bid)), timeout=40, every=2)
    inbox = [i for i in c.get("/api/inbox", headers=H).json() if str(i.get("related_id")) == str(bid)] \
        if c.get("/api/inbox", headers=H).status_code == 200 else None
    step("P3a. 1 run thật đẩy phong bì qua nấc cảnh báo (≥80%) + inbox",
         b and b["threshold_state"] in ("warned", "exhausted"), {"limit": limit, "estimate": est, "run": r, "budget": b,
                                                                "inbox": inbox})
    t2 = new_task("ba nấc — lượt 2 (không critical)")
    pv = c.get(f"/api/tasks/{t2}/context-pack", headers=H)
    txt = pv.json().get("text", "") if pv.status_code == 200 else ""
    step("P3b. gói ngữ cảnh của việc kế tiếp có luật 'CHỈ làm việc critical' ở khối 6",
         "CHỈ làm việc critical" in txt, {"http": pv.status_code, "line": next((l for l in txt.splitlines() if "critical" in l), None)})
    r2 = run_once(t2)
    sends = chat_sends(r2["session"])
    step("P3c. việc kế tiếp bị chặn ở bước giữ chỗ → 0 chat.send",
         r2["wakeup"] and r2["wakeup"]["status"] == "skipped" and sends == 0, {"wakeup": r2["wakeup"], "chat.send": sends})
    out["P3"] = {"tasks": [tid, t2], "budget_id": bid, "limit": limit}

print(json.dumps(out, ensure_ascii=False, default=str))
