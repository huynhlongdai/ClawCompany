"""D3.3 mutation: mỗi đột biến phải làm test_d33 đỏ. Chạy: .venv/bin/python tools/mutate_d33.py"""
import subprocess, pathlib
B = pathlib.Path("/data/cc/backend")
S = "app/services/strategy.py"
M = [
 ("M1 goal mới không đánh thức Nina", S, '        wk = wakeup.enqueue_for_task(db, task, "goal_created"', '        wk = None and wakeup.enqueue_for_task(db, task, "goal_created"'),
 ("M2 gói thiếu danh sách phòng", S, '    for d in _roster(db, company_id):\n        ppl', '    for d in []:\n        ppl'),
 ("M3 không bắt acceptance_criteria", S, '        if not ac:\n            raise', '        if False:\n            raise'),
 ("M4 không kiểm vòng phụ thuộc", S, '            raise StrategyError("invalid_argument", "Phụ thuộc tạo vòng: "', '            return\n            raise StrategyError("invalid_argument", "Phụ thuộc tạo vòng: "'),
 ("M5 không kiểm ngân sách mục tiêu", S, '    if env is not None and total > float(env.amount_limit or 0) + 1e-9:', '    if False:'),
 ("M6 gửi chồng khi đang chờ", S, '    if current is not None and current.status == "pending":', '    if False:'),
 ("M7 gửi lại tạo approval mới", S, '    if current is not None:   # revision_requested', '    if False:   # revision_requested'),
 ("M8 gửi lại không tăng revision", S, '        current.revision = (current.revision or 1) + 1', '        pass'),
 ("M9 yêu cầu sửa không đánh thức Nina", S, '        wk = wakeup.enqueue_for_task(db, task, "changes_requested",', '        wk = None and wakeup.enqueue_for_task(db, task, "changes_requested",'),
 ("M10 yêu cầu sửa không ghi sổ", S, '        task_journal.append(db, task, kind="note", summary=f"Yêu cầu sửa kế hoạch', '        (lambda *a, **k: None)(db, task, kind="note", summary=f"Yêu cầu sửa kế hoạch'),
 ("M11 áp kế hoạch không giao phòng", S, '        if t["department_id"]:\n            routing.route_to_department', '        if t["department_id"]:\n            continue\n            routing.route_to_department'),
 ("M12 áp kế hoạch không tạo phụ thuộc", S, '            task_graph.add_dependency(db, made[t["key"]], made[k], actor_member_id=actor_member_id)', '            pass'),
 ("M13 áp kế hoạch hai lần", S, '    if payload.get("applied"):', '    if False:'),
 ("M14 việc bị chặn vẫn bị đánh thức", S, '        if member_id and not task_graph.open_blockers(db, task.id):', '        if member_id:'),
 ("M15 không tự chọn theo tải", S, '            member_id = pick.member_id', '            member_id = None'),
 ("M16 trưởng phòng lập kế hoạch được", S, '    seat_ok = (plan_task is not None and plan_task.assignee_member_id == actor.id) or actor.department_id is None', '    seat_ok = True'),
 ("M17 từ chối không đánh dấu goal", S, '        goal.status = "plan_rejected"', '        pass'),
 ("M18 gửi lại không báo lại người duyệt", "app/services/inbox.py", '                elif hist.has_changes() and obj.status == "pending":', '                elif False:'),
 ("M19 ai cũng duyệt được kế hoạch", "app/api/approvals.py", '    if plan and obj.approver_member_id and principal.member_id != obj.approver_member_id:', '    if False:'),
 ("M20 duyệt không áp kế hoạch", "app/api/approvals.py", '            strategy.on_resolved(db, obj, actor_member_id=principal.member_id)', '            pass'),
 ("M21 thừa hành dùng được tool", "app/services/tool_permissions.py", '"company_task_assign", "company_plan_submit"}', '"company_task_assign"}'),
]
red = 0
for name, f, old, new in M:
    p = B / f; src = p.read_text()
    assert old in src, name
    p.write_text(src.replace(old, new, 1))
    try:
        r = subprocess.run([str(B.parent / ".venv/bin/python"), "-m", "pytest", "-q", "-x", "-p", "no:warnings",
                            "tests/test_d33_strategy.py"], cwd=B, capture_output=True, text=True, timeout=300)
        ok = r.returncode != 0
        red += ok
        last = [l for l in r.stdout.splitlines() if "passed" in l or "failed" in l or "error" in l][-1:]
        print(f"{'ĐỎ ' if ok else 'XANH'} {name}: {last}", flush=True)
    finally:
        p.write_text(src)
print(f"{red}/{len(M)} đột biến bị bắt")
