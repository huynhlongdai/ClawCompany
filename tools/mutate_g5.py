"""G5 (giả lập) mutation. Chạy: .venv/bin/python tools/mutate_g5.py"""
import subprocess, pathlib
B = pathlib.Path("/data/cc/backend")
M = [
 ("M1 reviewer agent vẫn ping người", "app/services/inbox.py", "            return []   # G5: reviewer là agent", "            pass   # G5: reviewer là agent"),
 ("M2 không review chéo", "app/services/strategy.py", '        if t.get("reviewer_member_id"):\n            # Review chéo', '        if False:\n            # Review chéo'),
 ("M3 không báo hoàn thành", "app/services/strategy.py", '        inbox.notify(db, organization_id=goal.organization_id, recipients=recipients, kind="goal_completed",', '        (lambda *a, **k: None)(db, organization_id=goal.organization_id, recipients=recipients, kind="goal_completed",'),
 ("M4 hoàn thành khi mới xong một việc", "app/services/strategy.py", "        if live and len(done) < len(live):", "        if False:"),
 ("M5 lifecycle không gọi kiểm hoàn thành", "app/services/task_lifecycle.py", "            strategy.on_task_closed(db, task)", "            pass"),
]
red = 0
for name, f, old, new in M:
    p = B / f; src = p.read_text()
    assert old in src, name
    p.write_text(src.replace(old, new, 1))
    try:
        r = subprocess.run([str(B.parent / ".venv/bin/python"), "-m", "pytest", "-q", "-x", "-p", "no:warnings",
                            "tests/test_g5_company_demo.py", "tests/test_d33_strategy.py"], cwd=B,
                           capture_output=True, text=True, timeout=300)
        ok = r.returncode != 0
        red += ok
        last = [l for l in r.stdout.splitlines() if "passed" in l or "failed" in l][-1:]
        print(f"{'ĐỎ ' if ok else 'XANH'} {name}: {last}", flush=True)
    finally:
        p.write_text(src)
print(f"{red}/{len(M)} đột biến bị bắt")
