"""D3.2 mutation: mỗi đột biến phải làm test_d32 đỏ. Chạy: .venv/bin/python tools/mutate_d32.py"""
import subprocess, pathlib
B = pathlib.Path("/data/cc/backend")
F = "app/services/dispatch_policy.py"
M = [
 ("M1 bỏ lọc phòng ban", "        if seat.department_id != need.department_id:", "        if False:"),
 ("M2 kỹ năng chỉ cần một", "            missing = sorted(want - _norm(seat.skills))", "            missing = [] if want & _norm(seat.skills) else sorted(want)"),
 ("M3 bỏ kiểm active", "        if (seat.member_status or \"\") != \"active\":", "        if False:"),
 ("M4 tải dùng > thay vì >=", "        if seat.open_runs >= need.max_open_runs:", "        if seat.open_runs > need.max_open_runs:"),
 ("M5 bỏ kiểm hạn mức", "        if seat.budget_remaining_usd is not None and seat.budget_remaining_usd + 1e-9 < need_usd:", "        if False:"),
 ("M6 không ai đủ → chọn bừa", "        if not keep:\n", "        if not keep and False:\n"),
 ("M7 chọn theo id thay vì tải", "    pool.sort(key=lambda s: (s.open_runs,", "    pool.sort(key=lambda s: (0,"),
 ("M8 đếm cả run đã xong", "TaskRun.status.in_(OPEN_RUN_STATUSES)", "TaskRun.status.isnot(None)"),
 ("M9 bỏ phong bì exhausted", "                block = block or f\"phong bì", "                block = block and f\"phong bì"),
 ("M10 không ghi lý do vào event", "    payload = decision.as_dict()\n", "    payload = {}\n"),
]
red = 0
for name, old, new in M:
    p = B / F; src = p.read_text()
    assert old in src, name
    p.write_text(src.replace(old, new, 1))
    try:
        r = subprocess.run([str(B.parent / ".venv/bin/python"), "-m", "pytest", "-q", "-x", "-p", "no:warnings",
                            "tests/test_d32_dispatch_policy.py"], cwd=B, capture_output=True, text=True, timeout=300)
        ok = r.returncode != 0
        red += ok
        last = [l for l in r.stdout.splitlines() if "passed" in l or "failed" in l][-1:]
        print(f"{'ĐỎ ' if ok else 'XANH'} {name}: {last}", flush=True)
    finally:
        p.write_text(src)
print(f"{red}/{len(M)} đột biến bị bắt")
