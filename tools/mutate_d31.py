"""D3.1 mutation: mỗi đột biến phải làm test_d31 đỏ. Chạy: .venv/bin/python tools/mutate_d31.py"""
import subprocess, pathlib
B = pathlib.Path("/data/cc/backend")
R = "app/services/routing.py"
M = [
 ("M1 bỏ luật tự kích hoạt", R, "    if event.actor_member_id is not None and event.actor_member_id == event.head_member_id:", "    if False:"),
 ("M2 bỏ dedup", R, "    if event.pending:\n        return False, \"dedup_pending\"", "    if False:\n        return False, \"dedup_pending\""),
 ("M3 comment có @ vẫn đánh thức", R, "        if event.mentions:\n", "        if False:\n"),
 ("M4 tham chiếu không đánh thức", R, "        return True, \"task_reference\"", "        return False, \"task_reference\""),
 ("M5 lượt định tuyến giữ task", "app/services/wakeup.py", "        run = await routing.dispatch_routing(db, task, member, agent, wakeup_id=primary.id)",
  "        from app.services import task_lifecycle as _lc\n        run = await routing.dispatch_routing(db, task, member, agent, wakeup_id=primary.id); _lc.checkout(db, task, run.id)"),
 ("M6 kết thúc định tuyến đổi trạng thái task", "app/services/runtime_stream.py", "    if event.get(\"terminal\") and route_run is not None:", "    if False:"),
 ("M7 không ghi lý do vào event", R, "\"to_member_id\": target.id, \"reason\": reason,", "\"to_member_id\": target.id,"),
 ("M8 giao cho người ngoài phòng", R, "    if dept is not None and target.department_id != dept.id:", "    if False:"),
 ("M9 không chặn người không phải trưởng phòng", R, "    if not is_head and actor.department_id is not None:", "    if False:"),
 ("M10 sổ ghi của trưởng phòng không mang actor", R, "    task_journal.append(db, task, kind=\"decision\", actor_member_id=actor.id,", "    task_journal.append(db, task, kind=\"decision\", actor_member_id=None,"),
 ("M11 gói không có nhân sự phòng", R, "    for r in roster(db, dept) if dept else []:", "    for r in []:"),
 ("M12 chi phí phiên định tuyến không vào run", "app/services/runtime_stream.py", "raw=event[\"raw\"], run=route_run)", "raw=event[\"raw\"], run=None)"),
 ("M13 comment báo cáo của người nhận đánh thức", R, "    if task.assignee_member_id is not None and entry.kind != \"blocker\":\n        return", "    pass"),
]
red = 0
for name, f, old, new in M:
    p = B / f; src = p.read_text()
    assert old in src, name
    p.write_text(src.replace(old, new, 1))
    try:
        r = subprocess.run([str(B.parent / ".venv/bin/python"), "-m", "pytest", "-q", "-x", "-p", "no:warnings",
                            "tests/test_d31_routing.py"], cwd=B, capture_output=True, text=True, timeout=300)
        ok = r.returncode != 0
        red += ok
        last = [l for l in r.stdout.splitlines() if "passed" in l or "failed" in l][-1:]
        print(f"{'ĐỎ ' if ok else 'XANH'} {name}: {last}", flush=True)
    finally:
        p.write_text(src)
print(f"{red}/{len(M)} đột biến bị bắt")
