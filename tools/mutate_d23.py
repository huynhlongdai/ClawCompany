"""D2.3 mutation: mỗi đột biến phải làm test_d23 đỏ. Chạy: .venv/bin/python tools/mutate_d23.py"""
import subprocess, sys, pathlib
B = pathlib.Path("/data/cc/backend")
M = [
 ("M1 bỏ cổng ngân sách trước chat.send", "app/services/wakeup.py",
  "    why, envs, amount = budget_scope.gate(db, member, task)\n    if why:", "    why, envs, amount = budget_scope.gate(db, member, task)\n    if False:"),
 ("M2 không trả phần giữ thừa", "app/services/budget_scope.py",
  "        if final and held > EPS:", "        if False and held > EPS:"),
 ("M3 không gắn phần giữ vào run", "app/services/wakeup.py",
  "        budget_scope.rekey(db, hold_key, budget_scope.run_key(run_id))", "        pass"),
 ("M4 100% không dừng seat", "app/services/budget_scope.py",
  "            m.status = \"paused\"; db.add(m); paused.append(m.id)", "            paused.append(m.id)"),
 ("M5 override không ghi audit", "app/services/budget_scope.py",
  "    log_event(db, env.organization_id, \"budget.override\"", "    (lambda *a, **k: None)(db, env.organization_id, \"budget.override\""),
 ("M6 khối 6 không có luật critical", "app/services/work_context.py",
  "    block.lines.extend(budget_lines or [])", "    pass"),
 ("M7 true-up không trừ run trước cùng phiên", "app/services/budget_scope.py",
  "    actual = max(0.0, round(float(usage[\"cost_usd\"]) - before, 10))", "    actual = max(0.0, round(float(usage[\"cost_usd\"]), 10))"),
 ("M8 dispatch lỗi không trả phần giữ", "app/services/wakeup.py",
  "        budget_scope.release_key(db, hold_key, \"runtime lỗi — trả phần giữ\")", "        pass"),
 ("M9 ước tính bỏ lịch sử run thật", "app/services/budget_scope.py",
  "    return round(max(base, avg), 6)", "    return round(base, 6)"),
 ("M10 phạm vi project bị bỏ qua", "app/services/budget_scope.py",
  "        return task is not None and sid is not None and task.project_id == sid", "        return False"),
 ("M11 override không cần quyền manager", "app/api/v9.py",
  "def budget_override(budget_id: int, payload: BudgetOverride, principal: Principal = Depends(require_role(\"manager\")),",
  "def budget_override(budget_id: int, payload: BudgetOverride, principal: Principal = Depends(require_human()),"),
]
red = 0
for name, f, old, new in M:
    p = B / f; src = p.read_text()
    assert old in src, name
    p.write_text(src.replace(old, new, 1))
    try:
        r = subprocess.run([str(B.parent / ".venv/bin/python"), "-m", "pytest", "-q", "-x", "-p", "no:warnings",
                            "tests/test_d23_budget_scopes.py"], cwd=B, capture_output=True, text=True, timeout=300)
        ok = r.returncode != 0
        red += ok
        last = [l for l in r.stdout.splitlines() if "passed" in l or "failed" in l][-1:]
        print(f"{'ĐỎ ' if ok else 'XANH'} {name}: {last}", flush=True)
    finally:
        p.write_text(src)
print(f"{red}/{len(M)} đột biến bị bắt")
