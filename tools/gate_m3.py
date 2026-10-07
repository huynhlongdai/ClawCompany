#!/usr/bin/env python3
"""Gate M3 — Nhân sự AI trên gateway THẬT (chạy trên máy chủ có docker compose).

  GATE_PASSWORD=... python3 tools/gate_m3.py [--keep]

Kiểm, mỗi bước đối chiếu độc lập với gateway (RPC trực tiếp + file trên đĩa của
container openclaw), không tin phản hồi của ClawCompany:
  1. Tuyển trên UI (POST /api/agents/hire) → có trong agents.list + đủ 5 file.
  2. Sửa SOUL trên UI (PUT files) → file trên đĩa gateway đổi đúng nội dung.
  3. Sửa tay trên gateway (ghi thẳng vào file) → GET drift báo edited_on_gateway.
  4. Đồng bộ lại: pull rồi push → hết lệch, đĩa = bản ClawCompany.
  5. Sửa hồ sơ (tên, tính cách) → agents.list + IDENTITY.md/SOUL.md trên đĩa đổi.
  6. Tạm dừng → dispatch bị chặn; tiếp tục → active.
  7. Tạo phiên thật (chat) rồi cho nghỉ → sessions.list của agent = 0, agent khỏi roster.
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


def gw_sh(cmd: str) -> str:
    p = subprocess.run(["docker", "exec", GW_C, "sh", "-c", cmd], capture_output=True, text=True, timeout=60)
    return p.stdout


def roster_row(rid: str):
    return next((a for a in rpc("agents.list").get("agents", []) if a.get("id") == rid), None)


def sessions_of(rid: str) -> list:
    rows = rpc("sessions.list", {"limit": 500}).get("sessions", [])
    return [s for s in rows if s.get("agentId") == rid or str(s.get("key", "")).startswith(f"agent:{rid}:")]


def main() -> int:
    global TOKEN
    keep = "--keep" in sys.argv
    _, login = api("POST", "/auth/login", {"email": EMAIL, "password": PASSWORD})
    TOKEN = login["access_token"]
    tag = time.strftime("%H%M%S")
    _, opts = api("GET", "/agents/hire/options")
    check("hire/options có model từ models.list", bool(opts["models"]), ", ".join(m["id"] for m in opts["models"]))
    co = next((c for c in opts["companies"] if any(d["company_id"] == c["id"] for d in opts["departments"])), None)
    dept = next(d for d in opts["departments"] if d["company_id"] == co["id"])
    model = next((m["id"] for m in opts["models"] if m.get("default")), opts["models"][0]["id"] if opts["models"] else "")
    name = f"Gate M3 Ngọc Ánh {tag}"
    # 1 ---- tuyển
    _, hired = api("POST", "/agents/hire", {
        "name": name, "role": "Chuyên viên chăm sóc khách hàng", "company_id": co["id"], "department_id": dept["id"],
        "model": model, "personality": "than-thien", "monthly_budget": 15,
        "job_description": "Trả lời khách hàng\nGhi nhận phản hồi", "manager_notes": "- Báo cáo ngắn gọn mỗi sáng"})
    aid, rid = hired["agent_id"], hired["runtime_agent_id"]
    print(f"   seat #{aid} · {rid} · {co['name']} / {dept['name']}")
    check("hire trả status active", hired["status"] == "active", f"{hired['status']} {hired['warnings']}")
    row = roster_row(rid)
    check("agents.list (gateway) có agent mới", row is not None, json.dumps(row, ensure_ascii=False)[:160] if row else "")
    ws = (row or {}).get("workspace", f"/home/node/.openclaw/workspace-{rid}")
    on_disk = gw_sh(f"ls {ws}").split()
    five = ["IDENTITY.md", "SOUL.md", "AGENTS.md", "USER.md", "MEMORY.md"]
    check("đủ 5 file trên đĩa gateway", all(f in on_disk for f in five), " ".join(sorted(on_disk)))
    got = {f: rpc("agents.files.get", {"agentId": rid, "name": f}).get("file", {}) for f in five}
    check("agents.files.get: 5 file không missing", all(not g.get("missing") for g in got.values()),
          ", ".join(f"{k}:{'missing' if v.get('missing') else len(v.get('content') or '')}" for k, v in got.items()))
    check("IDENTITY.md mang tên tiếng Việt", f"**Name:** {name}" in (got["IDENTITY.md"].get("content") or ""))
    ident = rpc("agent.identity.get", {"agentId": rid})
    check("agent.identity.get = tên đã tuyển", ident.get("name") == name, str(ident.get("name")))
    _, d0 = api("GET", f"/agents/{aid}/drift")
    check("drift ngay sau tuyển: khớp", d0["in_sync"] is True, str([(f["name"], f["status"]) for f in d0["files"]]))
    # 2 ---- sửa SOUL trên UI
    _, prof = api("GET", f"/agents/{aid}/profile")
    soul = next(f for f in prof["files"] if f["name"] == "SOUL.md")
    new_soul = soul["content"] + f"\n## Ghi chú gate M3 {tag}\n- Luôn chào khách bằng tên.\n"
    api("PUT", f"/agents/{aid}/files/SOUL.md", {"content": new_soul, "expected_hash": soul["hash"]})
    disk = gw_sh(f"cat {ws}/SOUL.md")
    check("sửa SOUL trên UI → file trên gateway đổi", disk == new_soul, f"{len(disk)} ký tự")
    _, d1 = api("GET", f"/agents/{aid}/drift")
    check("drift sau khi sửa trên UI: khớp", d1["in_sync"] is True)
    # 3 ---- sửa tay trên gateway
    gw_sh(f"printf '\\n- Sửa tay trên máy gateway {tag}\\n' >> {ws}/SOUL.md")
    _, d2 = api("GET", f"/agents/{aid}/drift")
    st = {f["name"]: f for f in d2["files"]}
    check("sửa tay trên gateway → UI báo lệch (edited_on_gateway)",
          d2["in_sync"] is False and st["SOUL.md"]["status"] == "edited_on_gateway",
          f"drift_count={d2.get('drift_count')}")
    check("lệch kèm nội dung gateway để so", f"Sửa tay trên máy gateway {tag}" in (st["SOUL.md"].get("gateway_content") or ""))
    # 4 ---- đồng bộ lại
    _, rp = api("POST", f"/agents/{aid}/resync", {"direction": "pull", "files": ["SOUL.md"]})
    check("Đồng bộ lại · nhận bản gateway → hết lệch", rp["drift"]["in_sync"] is True)
    gw_sh(f"printf '\\n- Sửa tay lần 2 {tag}\\n' >> {ws}/SOUL.md")
    _, d3 = api("GET", f"/agents/{aid}/drift")
    accepted = next(f for f in d3["files"] if f["name"] == "SOUL.md")["clawcompany_content"]
    _, ps = api("POST", f"/agents/{aid}/resync", {"direction": "push"})
    disk = gw_sh(f"cat {ws}/SOUL.md")
    check("Đồng bộ lại · đẩy bản ClawCompany lên → đĩa = bản ClawCompany",
          ps["drift"]["in_sync"] is True and disk == accepted and "lần 2" not in disk)
    # 5 ---- sửa hồ sơ 2 chiều
    new_name = f"Gate M3 Ngọc Ánh Lê {tag}"
    _, up = api("PATCH", f"/agents/{aid}/hr", {"name": new_name, "personality": "ngan-gon", "role": "Trưởng nhóm CSKH"})
    row = roster_row(rid)
    check("sửa tên → agents.list (gateway) đổi tên", (row or {}).get("name") == new_name, str((row or {}).get("name")))
    idf = gw_sh(f"cat {ws}/IDENTITY.md")
    check("sửa hồ sơ → IDENTITY.md trên đĩa đổi", f"**Name:** {new_name}" in idf and "Trưởng nhóm CSKH" in idf)
    soul_now = gw_sh(f"cat {ws}/SOUL.md")
    check("đổi tính cách: SOUL đã chỉnh tay được giữ nguyên (báo customized)",
          up["files"].get("SOUL.md", {}).get("reason") == "customized" and soul_now == accepted,
          json.dumps(up["files"].get("SOUL.md"), ensure_ascii=False)[:160])
    _, up2 = api("PATCH", f"/agents/{aid}/hr", {"regenerate_files": ["SOUL.md"]})
    check("Sinh lại SOUL từ hồ sơ → file trên gateway mang tính cách mới",
          up2["files"].get("SOUL.md", {}).get("written") is True and "Ngắn gọn" in gw_sh(f"cat {ws}/SOUL.md"))
    _, d4 = api("GET", f"/agents/{aid}/drift")
    check("sau sửa hồ sơ: không lệch", d4["in_sync"] is True, str([(f["field"], f["match"]) for f in d4["fields"]]))
    # 6 ---- tạm dừng / tiếp tục
    _, pz = api("POST", f"/agents/{aid}/lifecycle", {"action": "pause"})
    _, rs = api("GET", "/agents/roster")
    me = next(i for i in rs["items"] if i["agent_id"] == aid)
    check("tạm dừng → lifecycle paused", pz["lifecycle"] == "paused" and me["lifecycle"] == "paused")
    _, rz = api("POST", f"/agents/{aid}/lifecycle", {"action": "resume"})
    check("tiếp tục → active", rz["lifecycle"] == "active")
    # 7 ---- phiên thật rồi cho nghỉ
    for i in (1, 2):
        helper("run", {"agent": rid, "text": "Chào bạn, giới thiệu ngắn về mình trong 1 câu.", "key": f"agent:{rid}:gate-m3-{i}"})
    time.sleep(6)
    before = sessions_of(rid)
    check("có phiên thật trên gateway trước khi nghỉ", len(before) >= 2, str([s.get("key") for s in before]))
    if keep:
        print("--keep: bỏ qua bước cho nghỉ"); return summary()
    _, rt = api("POST", f"/agents/{aid}/lifecycle", {"action": "retire", "reason": "gate M3"})
    g = rt["gateway"]
    check("cho nghỉ: ClawCompany báo sessions_after = 0", g.get("sessions_after") == 0,
          f"before={g.get('sessions_before')} after={g.get('sessions_after')} removed={g.get('agent_removed')} warn={rt['warnings']}")
    left = sessions_of(rid)
    check("cho nghỉ → sessions.list (gateway) của agent = 0", len(left) == 0, str([s.get("key") for s in left]))
    check("cho nghỉ → agent khỏi agents.list", roster_row(rid) is None)
    check("cho nghỉ → workspace đã dọn khỏi đĩa", gw_sh(f"test -d {ws} && echo yes || echo no").strip() == "no")
    _, prof2 = api("GET", f"/agents/{aid}/drift")
    check("sau nghỉ: hồ sơ vẫn đọc được, 5 file đã lưu", prof2["lifecycle"] == "retired"
          and all(f.get("has_snapshot") for f in prof2["files"]))
    return summary()


def summary() -> int:
    ok = sum(1 for _, p, _ in RESULTS if p)
    print(f"\nGATE M3: {ok}/{len(RESULTS)} PASS")
    return 0 if ok == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
