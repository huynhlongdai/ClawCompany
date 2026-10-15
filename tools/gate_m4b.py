#!/usr/bin/env python3
"""Gate M4b — Hộp việc & phê duyệt & chi phí trên gateway THẬT (chạy trên máy chủ có docker compose).

  GATE_PASSWORD=... python3 tools/gate_m4b.py

  1. Giao việc cho seat lead (shell = ask) buộc agent gọi exec → gateway chặn, thẻ duyệt "gateway" vào Hộp việc.
  2. Hai lần bấm duyệt đồng thời: một thắng, một 409; duyệt đi tới exec.approval.resolve.
  3. Lệnh chạy thật, agent báo đúng kết quả; gateway hết hàng chờ; thẻ rời Hộp việc.
  4. Chi phí lượt chạy khớp sessions.usage ±5%; bảng Chi phí có tiền model.
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



SEAT = os.environ.get("GATE_SEAT", "Trưởng phòng bán hàng")   # seat lead: shell = "ask" → exec phải xin duyệt


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


def gateway_cards(tid: int) -> list[dict]:
    _, r = api("GET", "/inbox/items?status=open")
    items = [x for g in (r.get("groups") or []) for x in (g.get("items") or [])]   # /inbox/items trả theo nhóm
    return [c for c in items if (c.get("approval") or {}).get("kind") == "gateway"
            and ((c.get("task") or {}).get("id") == tid or c.get("task_id") == tid)]


def main() -> int:
    global TOKEN
    _, login = api("POST", "/auth/login", {"email": EMAIL, "password": PASSWORD})
    TOKEN = login["access_token"]
    tag = time.strftime("%H%M%S")
    _, meta = api("GET", "/work/meta")
    seat = next(m for m in meta["members"] if m["name"] == SEAT or (m.get("role") or "") == SEAT)
    proj = next(p for p in meta["projects"] if p["company_id"] == seat["company_id"])
    print(f"   seat {seat['name']} #{seat['id']} · dự án {proj['name']}")

    # 1 ---- giao việc buộc agent gọi exec (seat lead: shell = ask)
    if os.environ.get("GATE_TASK"):                       # nối tiếp một việc đang chờ duyệt (seat bận 1 lượt/lần)
        _, t = api("GET", f"/work/tasks/{os.environ['GATE_TASK']}")
    else:
        _, t = api("POST", "/work/tasks", {
            "title": f"Gate M4b {tag}: kiểm tra năm hiện tại trên máy chủ", "project_id": proj["id"], "priority": "high",
            "assignee_member_id": seat["id"],
            "description": "Dùng công cụ exec chạy đúng lệnh `date +%Y` (không dùng cách khác), rồi báo lại đúng con số in ra.",
            "acceptance_criteria": "Có con số năm do lệnh in ra.", "start": True}, expect=(201,))
    tid = t["id"]
    print(f"   việc #{tid}")

    # 2 ---- lệnh exec thật bị gateway chặn → thẻ duyệt "gateway" trong Hộp việc
    t0, cards = time.time(), []
    while time.time() - t0 < 240 and not cards:
        time.sleep(5)
        cards = gateway_cards(tid)
    card = cards[0] if cards else {}
    ap = card.get("approval") or {}
    check("exec thật bị gateway chặn → thẻ duyệt loại gateway trong Hộp việc, gắn đúng việc", bool(cards),
          f"{ap.get('action', '')[:80]} · can_decide={ap.get('can_decide')} · sau {int(time.time() - t0)}s")
    if not cards:
        return summary()
    check("thẻ có nội dung lệnh để người duyệt hiểu", "date" in json.dumps(ap, ensure_ascii=False), ap.get("summary", "")[:120])
    check("gateway (exec.approval.list) đang giữ đúng lệnh này", "date +%Y" in json.dumps(rpc("exec.approval.list", {}), ensure_ascii=False))

    # 3 ---- hai cú chạm cùng lúc: một thắng, một 409
    import concurrent.futures as cf
    body = {"decision": "approve", "note": "gate M4b", "expected_revision": ap["revision"]}
    with cf.ThreadPoolExecutor(2) as ex:
        res = list(ex.map(lambda _: api("POST", f"/inbox/approvals/{ap['id']}/decide", body, expect=(200, 409)), range(2)))
    codes = sorted(c for c, _ in res)
    win = next(p for c, p in res if c == 200) if 200 in codes else {}
    check("hai lần bấm duyệt đồng thời: đúng một 200, một 409", codes == [200, 409], f"{codes}")
    check("duyệt gửi tới gateway (exec.approval.resolve) thành công", bool(win.get("delivered", True)) and win.get("status") == "approved",
          str(win.get("message", ""))[:160])

    # 4 ---- lệnh chạy thật, agent báo kết quả
    t0, d, ok = time.time(), {}, False
    while time.time() - t0 < 240:
        _, d = api("GET", f"/work/tasks/{tid}")
        runs = [e for e in d["timeline"] if e["type"] == "run"]
        if runs and runs[-1]["status"] in ("completed", "failed") and d["status"] != "in_progress":
            ok = True
            break
        time.sleep(5)
    runs = [e for e in d.get("timeline", []) if e["type"] == "run"]
    r1 = runs[-1] if runs else {}
    res_ = [x for x in r1.get("entries", []) if x["kind"] == "result"]
    txt = res_[0]["detail"] if res_ else ""
    year = time.strftime("%Y")
    check("sau khi duyệt, lệnh chạy và agent báo đúng năm", ok and r1.get("status") == "completed" and year in txt,
          f"status={r1.get('status')} · {txt[:120]!r}")
    pend2 = rpc("exec.approval.list", {})
    check("gateway không còn lệnh date +%Y đang chờ", "date +%Y" not in json.dumps(pend2, ensure_ascii=False))
    check("thẻ duyệt rời khỏi Hộp việc", not gateway_cards(tid))

    # 5 ---- chi phí khớp gateway ±5%
    sk = r1.get("session_key", "")
    time.sleep(3)
    local = sum(e["cost_usd"] for e in runs if e["session_key"] == sk)
    gw = usage_cost(sk)
    check("chi phí lượt chạy khớp sessions.usage ±5%", within(local, gw) and local > 0, f"local={local:.6f} gateway={gw}")
    _, ov = api("GET", "/costs/overview?days=1")
    today = ov["totals"]["today"]
    today = today.get("cost_usd", 0) if isinstance(today, dict) else today
    check("bảng Chi phí hôm nay có tiền model (>0)", float(today or 0) > 0, f"today={today}")
    return summary()


def summary() -> int:
    ok = sum(1 for _, p, _ in RESULTS if p)
    print(f"\nGATE M4b: {ok}/{len(RESULTS)} PASS")
    return 0 if ok == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
