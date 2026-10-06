"""D3.4 mutation: mỗi đột biến phải làm test_d34 đỏ. Chạy: .venv/bin/python tools/mutate_d34.py"""
import subprocess, pathlib
B = pathlib.Path("/data/cc/backend")
R = "app/services/routines.py"
M = [
 ("M1 bỏ múi giờ (cron theo UTC)", R, "    return compute_next(cron, tz, base=_aware(after))", "    return compute_next(cron, \"UTC\", base=_aware(after))"),
 ("M2 trùng key vẫn tạo việc", R, "        return db.query(RoutineRun).filter(RoutineRun.idempotency_key == key[:200]).one(), False",
  "        run = RoutineRun(routine_id=r.id, trigger_kind=kind, idempotency_key=key[:200] + secrets.token_hex(3), status=\"queued\")\n        db.add(run); db.commit(); db.refresh(run)"),
 ("M3 webhook không bắt Idempotency-Key", R, "    if not idem:\n        raise", "    if False:\n        raise"),
 ("M4 webhook không kiểm secret", R, "    if not secret or not hmac.compare_digest(secret, t.secret or \"\"):", "    if False:"),
 ("M5 không tự dừng", R, "    r.enabled = False\n    r.paused_reason", "    r.enabled = True\n    r.paused_reason"),
 ("M6 tự dừng không audit", R, "    log_event(db, r.organization_id, \"routine.paused\"", "    (lambda *a, **k: None)(db, r.organization_id, \"routine.paused\""),
 ("M7 tự dừng không báo inbox", R, "    inbox.notify(db, organization_id=r.organization_id, recipients=[r.owner_member_id or r.assignee_member_id],",
  "    (lambda *a, **k: None)(db, organization_id=r.organization_id, recipients=[r.owner_member_id or r.assignee_member_id],"),
 ("M8 thành công không xoá chuỗi lỗi", R, "        r.consecutive_failures = 0\n    db.commit()", "        pass\n    db.commit()"),
 ("M9 không giới hạn đồng thời", R, "    if busy is not None:\n        _finish", "    if False:\n        _finish"),
 ("M10 skip_missed vẫn chạy bù", R, "        if missed and r.catch_up == \"run_once\" and not on_time:", "        if missed and not on_time:"),
 ("M11 run_once không chạy bù", R, "        if missed and r.catch_up == \"run_once\" and not on_time:", "        if False:"),
 ("M12 không dời giờ hẹn (chạy lại mỗi tick)", R, "        t.next_run_at = next_slot(t.cron, r.timezone, now)\n        db.commit()\n        if missed", "        db.commit()\n        if missed"),
 ("M13 seat bận tính là lỗi", R, "not wk.skip_reason.startswith(DEFERRABLE)", "True"),
 ("M14 không có cửa sổ trễ", R, "        on_time = [s for s in slots if now - s <= GRACE]", "        on_time = [s for s in slots if now == s]"),
 ("M15 run_only tạo việc mới mỗi lần", R, "    if task is None or task.status in (\"cancelled\", \"archived\"):", "    if True:"),
 ("M16 bật lại không xoá chuỗi lỗi", R, "        r.consecutive_failures, r.paused_reason = 0, \"\"", "        r.paused_reason = \"\""),
 ("M17 phòng không qua định tuyến", R, "    if r.department_id:\n        res = routing", "    if False:\n        res = routing"),
 ("M18 mẫu không kèm số liệu", R, "        text += snapshot_text(snapshot(db, r.organization_id, r.company_id, now))", "        pass"),
]
red = 0
for name, f, old, new in M:
    p = B / f; src = p.read_text()
    assert old in src, name
    p.write_text(src.replace(old, new, 1))
    try:
        r = subprocess.run([str(B.parent / ".venv/bin/python"), "-m", "pytest", "-q", "-x", "-p", "no:warnings",
                            "tests/test_d34_routines.py"], cwd=B, capture_output=True, text=True, timeout=300)
        ok = r.returncode != 0
        red += ok
        last = [l for l in r.stdout.splitlines() if "passed" in l or "failed" in l or "error" in l][-1:]
        print(f"{'ĐỎ ' if ok else 'XANH'} {name}: {last}", flush=True)
    finally:
        p.write_text(src)
print(f"{red}/{len(M)} đột biến bị bắt")
