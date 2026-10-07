#!/usr/bin/env python3
"""Gate M4a — Công việc & lượt chạy trên gateway THẬT (chạy trên máy chủ có docker compose).

  GATE_PASSWORD=... python3 tools/gate_m4a.py

Mỗi bước đối chiếu độc lập (RPC trực tiếp tới gateway qua container api), không tin phản hồi ClawCompany:
  1. Tạo việc trên /api/work: giao agent A, review chéo bởi agent B → Cần làm, có chặng review.
  2. Agent A chạy THẬT (beat drain wakeup 'assigned') → lượt chạy có runId, phiên có trong sessions.list,
     câu trả lời cuối được ghi thành "Kết quả" của A, việc sang Chờ duyệt (không kẹt "thiếu báo cáo").
  3. Chi phí lượt chạy khớp sessions.usage của gateway ±5%.
  4. Review chéo: B (≠ A) review trong phòng họp thật → quyết định DUYỆT/SỬA được ghi, việc đi đúng
     (Xong, hoặc về Đang làm + A được đánh thức). Chi phí phòng review khớp sessions.usage ±5%.
  5. Dòng thời gian: tổng chi phí side-peek = lượt chạy + review; khớp số trên danh sách.
  6. Bảng: revision cũ → 409 tiếng Việt; chuyển sai luồng → 409 tiếng Việt; chuyển đúng → OK; lọc #id.
  7. Đường cũ có header Deprecation; "Chạy ngay" khi chưa giao → 409 tiếng Việt.
"""
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

API = os.environ.get("GATE_API", "http://127.0.0.1:8000/api")
EMAIL = os.environ.get("GATE_EMAIL", "admin@clawcompany.local")
PASSWORD = os.environ["GATE_PASSWORD"]
API_C, GW_C = "clawcompany-api-1", "clawcompany-openclaw-1"
RESULTS: list[tuple[str, bool, str]] = []
TOKEN = ""

HELPER = r'''
import asyncio, json, sys
from app.runtime.factory import get_runtime
async def main():
    rt = get_runtime(); mode = sys.argv[1]; arg = json.loads(sys.argv[2])
    if mode == "rpc":
        out = await rt.rpc(arg["method"], arg.get("params") or {})
    else:
        run = await rt.run_agent(arg["agent"], arg["text"], {}, session_key=arg["key"])
        out = {"run_id": getattr(run, "run_id", None) or getattr(run, "id", None)}
    print(json.dumps(out, default=str))
asyncio.run(main())
'''


def check(name: str, ok: bool, detail: str = "") -> bool:
    RESULTS.append((name, bool(ok), detail))
    print(("PASS " if ok else "FAIL ") + name + (f" — {detail}" if detail else ""), flush=True)
    return bool(ok)


def api(method: str, path: str, body=None, expect=(200,)):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(API + path, data=data, method=method,
                                 headers={"Content-Type": "application/json",
                                          **({"Authorization": f"Bearer {TOKEN}"} if TOKEN else {})})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            code, text = r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        code, text = e.code, e.read().decode()
    try:
        payload = json.loads(text)
    except Exception:
        payload = text
    if code not in expect:
        raise SystemExit(f"{method} {path} → {code}: {text[:400]}")
    return code, payload


def helper(mode: str, arg: dict):
    p = subprocess.run(["docker", "exec", "-w", "/app", "-e", "PYTHONPATH=/app", API_C, "python", "-c", HELPER,
                        mode, json.dumps(arg)], capture_output=True, text=True, timeout=120)
    if p.returncode != 0:
        raise RuntimeError(p.stderr.strip()[-400:])
    return json.loads(p.stdout.strip().splitlines()[-1])


def rpc(method: str, params: dict | None = None):
    return helper("rpc", {"method": method, "params": params or {}})


DOER = os.environ.get("GATE_DOER", "Mai Anh")
REVIEWER = os.environ.get("GATE_REVIEWER", "Hải Đăng")


def usage_cost(key: str) -> float | None:
    out = rpc("sessions.usage", {"key": key})
    for s in out.get("sessions") or []:
        if s.get("key") == key and isinstance(s.get("usage"), dict):
            return float(s["usage"].get("totalCost") or 0)
    return None


def within(local: float, gw: float | None, pct: float = 5.0) -> bool:
    if gw is None:
        return False
    if gw == 0:
        return local == 0
    return abs(local - gw) / gw * 100 <= pct


def poll(task_id: int, pred, timeout: int, every: int = 5):
    t0, last = time.time(), None
    while time.time() - t0 < timeout:
        _, last = api("GET", f"/work/tasks/{task_id}")
        if pred(last):
            return last, True
        time.sleep(every)
    return last, False


def main() -> int:
    global TOKEN
    _, login = api("POST", "/auth/login", {"email": EMAIL, "password": PASSWORD})
    TOKEN = login["access_token"]
    tag = time.strftime("%H%M%S")
    _, meta = api("GET", "/work/meta")
    doer = next(m for m in meta["members"] if m["name"] == DOER)
    rev = next(m for m in meta["members"] if m["name"] == REVIEWER)
    proj = next(p for p in meta["projects"] if p["company_id"] == doer["company_id"])
    print(f"   người làm {doer['name']} #{doer['id']} · review {rev['name']} #{rev['id']} · dự án {proj['name']}")

    # 1 ---- tạo việc
    code, t = api("POST", "/work/tasks", {
        "title": f"Gate M4a {tag}: viết 3 caption Facebook cho bộ sưu tập hè", "project_id": proj["id"],
        "priority": "high", "assignee_member_id": doer["id"], "reviewer_member_ids": [rev["id"]],
        "description": "Viết 3 caption ngắn (mỗi caption ≤ 25 từ) giới thiệu bộ sưu tập hè của Nova Fashion. "
                       "Trả lời bằng đúng 3 dòng đánh số, mỗi dòng có 1 hashtag.",
        "acceptance_criteria": "Đủ 3 caption đánh số; mỗi caption ≤ 25 từ; mỗi caption có ít nhất 1 hashtag.",
        "start": True}, expect=(201,))
    tid = t["id"]
    print(f"   việc #{tid}")
    check("tạo việc: Cần làm, có review chéo bởi người khác", t["status"] == "todo" and t["review"]["needed"]
          and [r["id"] for r in t["review"]["reviewers"]] == [rev["id"]] and rev["id"] != doer["id"])

    # 2 ---- agent làm thật
    d, ok = poll(tid, lambda x: any(e["type"] == "run" and e["status"] in ("completed", "failed") for e in x["timeline"])
                 and x["status"] != "in_progress", 240)
    runs = [e for e in d["timeline"] if e["type"] == "run"]
    r1 = runs[0] if runs else {}
    check("lượt chạy thật kết thúc (beat drain → chat.send → follower)", ok and r1.get("status") == "completed",
          f"status={r1.get('status')} task={d['status']} err={r1.get('error_reason')}")
    check("lượt chạy có runId + phiên của agent", bool(r1.get("runtime_run_id")) and bool(r1.get("session_key")),
          f"{r1.get('runtime_run_id')} {r1.get('session_key')}")
    keys = [s.get("key") for s in rpc("sessions.list", {"limit": 500}).get("sessions", [])]
    check("sessions.list (gateway) có phiên của lượt chạy", r1.get("session_key") in keys)
    res = [x for x in r1.get("entries", []) if x["kind"] == "result"]
    check("câu trả lời cuối của agent được ghi thành Kết quả của người làm", bool(res) and res[0]["who"]["id"] == doer["id"],
          (res[0]["detail"][:120].replace("\n", " | ") if res else "không có"))
    check("việc sang Chờ duyệt / đã review (không kẹt thiếu báo cáo)", d["status"] in ("review", "done", "in_progress")
          and not d["review"]["missing_report"], f"status={d['status']}")

    # 3 ---- chi phí lượt chạy
    sk = r1.get("session_key", "")
    time.sleep(3)
    local = sum(e["cost_usd"] for e in runs if e["session_key"] == sk)
    gw = usage_cost(sk)
    check("chi phí lượt chạy khớp sessions.usage ±5%", within(local, gw) and local > 0, f"local={local:.6f} gateway={gw}")

    # 4 ---- review chéo bằng phòng họp thật
    d, ok = poll(tid, lambda x: bool(x["review"]["history"]), 300)
    h = (d["review"]["history"] or [{}])[0]
    check("review chéo: người review (≠ người làm) ra quyết định", ok and h.get("reviewer", {}).get("id") == rev["id"]
          and rev["id"] != doer["id"] and h.get("decision") in ("approve", "revise"),
          f"{h.get('decision')} via={h.get('via')} vòng {h.get('round')}")
    if h.get("decision") == "approve":
        check("DUYỆT → việc Xong", d["status"] == "done", d["status"])
    else:
        _, wk = api("GET", f"/tasks/wakeups?task_id={tid}&member_id={doer['id']}")
        check("SỬA → về Đang làm/làm lại + người làm được đánh thức (changes_requested)",
              d["status"] in ("in_progress", "review", "done") and any(w["reason"] == "changes_requested" for w in wk), d["status"])
    rooms = [e for e in d["timeline"] if e["type"] == "review_room"]
    room = rooms[0] if rooms else {"speakers": [], "cost_usd": 0, "turns": 0}
    check("phòng review có trong dòng thời gian, có lượt nói", room["turns"] > 0, f"{room['turns']} lượt")
    rkeys = sorted({s["session_key"] for s in room["speakers"] if s.get("session_key")})
    gw_room = sum(usage_cost(k) or 0 for k in rkeys)
    check("chi phí phòng review khớp sessions.usage ±5%", within(room["cost_usd"], gw_room) and room["cost_usd"] > 0,
          f"local={room['cost_usd']:.6f} gateway={gw_room:.6f} phiên={rkeys}")

    # 5 ---- dòng thời gian & danh sách khớp nhau
    _, d = api("GET", f"/work/tasks/{tid}")
    runs = [e for e in d["timeline"] if e["type"] == "run"]
    rc = sum(e["cost_usd"] for e in d["timeline"] if e["type"] == "review_room")
    # mỗi phần đã làm tròn 6 số lẻ, tổng làm tròn từ số gốc → lệch tối đa 1e-6 mỗi phần (gate lần 7: 0.008170 vs 0.008171)
    parts = len(runs) + len([e for e in d["timeline"] if e["type"] == "review_room"])
    want = sum(e["cost_usd"] for e in runs) + rc
    check("tổng chi phí side-peek = lượt chạy + review", abs(d["totals"]["cost_usd"] - want) <= parts * 1e-6 + 1e-12,
          f"{d['totals']['cost_usd']:.6f} (cộng từng phần {want:.6f})")
    _, lst = api("GET", f"/work/tasks?q=%23{tid}")
    check("danh sách: lọc #id ra đúng việc, chi phí khớp side-peek", [i["id"] for i in lst["items"]] == [tid]
          and abs(lst["items"][0]["runs"]["cost_usd"] - d["totals"]["cost_usd"]) < 1e-6)

    # 6 ---- bảng: revision & luồng chuyển
    _, dr = api("POST", "/work/tasks", {"title": f"Gate M4a {tag}: bản nháp", "project_id": proj["id"], "start": False},
                expect=(201,))
    did = dr["id"]
    c, e = api("POST", f"/work/tasks/{did}/move", {"status": "todo", "expected_revision": "task:0:cũ"}, expect=(409,))
    check("kéo thẻ với revision cũ → 409 tiếng Việt", e["detail"]["error"] == "stale_revision", e["detail"]["message"])
    c, e = api("POST", f"/work/tasks/{did}/move", {"status": "done"}, expect=(409,))
    check("chuyển sai luồng (Tồn đọng → Xong) → 409 tiếng Việt", e["detail"]["error"] == "invalid_transition", e["detail"]["message"])
    c, e = api("POST", f"/work/tasks/{did}/run", expect=(409,))
    check("Chạy ngay khi chưa giao → 409 tiếng Việt", e["detail"]["error"] == "no_assignee", e["detail"]["message"])
    c, mv = api("POST", f"/work/tasks/{did}/move", {"status": "todo", "expected_revision": dr["revision"]})
    check("kéo thẻ đúng luồng với revision mới → OK", mv["status"] == "todo")
    api("POST", f"/work/tasks/{did}/move", {"status": "cancelled"})

    # 7 ---- đường cũ
    req = urllib.request.Request(API + "/v17/workspace/tasks", headers={"Authorization": f"Bearer {TOKEN}"})
    with urllib.request.urlopen(req, timeout=60) as r:
        dep, link = r.headers.get("Deprecation"), r.headers.get("Link", "")
    check("đường cũ /v17/workspace/tasks có header Deprecation → /api/work", dep == "true" and "/api/work/tasks" in link, link)
    return summary()


def summary() -> int:
    ok = sum(1 for _, p, _ in RESULTS if p)
    print(f"\nGATE M4a: {ok}/{len(RESULTS)} PASS")
    return 0 if ok == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
