"""D3.5 mutation: mỗi đột biến phải làm test_d35 đỏ. Chạy: .venv/bin/python tools/mutate_d35.py"""
import subprocess, pathlib
B = pathlib.Path("/data/cc/backend")
I = "app/services/inbox.py"
M = [
 ("M1 agent cũng nhận inbox", I, "        if m.member_type == \"human\":", "        if True:"),
 ("M2 không gộp theo task", I, "    group = f\"task:{task_id}\" if task_id else", "    group = f\"x:{datetime.utcnow().timestamp()}\" if task_id else"),
 ("M3 báo mới không đặt lại chưa đọc", I, "                item.title, item.item_type, item.status = title[:220], kind, \"unread\"", "                item.title, item.item_type = title[:220], kind"),
 ("M4 không đặt hạn 24h", I, "        a.expires_at = _gateway_expiry(a) if gateway else now + timedelta(hours=float(settings.approval_ttl_hours))", "        a.expires_at = _gateway_expiry(a) if gateway else None"),
 ("M5 leo thang không đổi người duyệt", I, "        a.approver_member_id = target\n", "        pass\n"),
 ("M6 leo thang không ghi audit", I, "        log_event(db, a.organization_id, \"approval.escalated\"", "        (lambda *x, **k: None)(db, a.organization_id, \"approval.escalated\""),
 ("M7 leo thang hai lần", I, "        a.expires_at = now + ttl\n        a.escalate_to_member_id", "        a.expires_at = now\n        a.escalate_to_member_id"),
 ("M8 leo thang cả approval gateway", I, "        if (a.policy_key or \"\").startswith(\"openclaw:\"):\n            continue", "        if False:\n            continue"),
 ("M9 duyệt xong không đóng inbox", I, "                item.status = \"done\"", "                pass"),
 ("M10 không báo khi vào review", "app/services/task_lifecycle.py", "        inbox.task_review(db, task)", "        pass"),
 ("M11 run lỗi không báo", "app/services/runtime_stream.py", "        inbox.run_failed(db, task, str(event.get(\"errorMessage\") or reason),", "        (lambda *a, **k: None)(db, task, str(event.get(\"errorMessage\") or reason),"),
 ("M12 @người không báo", "app/services/task_journal.py", "        inbox.mention(db, task, entry, organization_id)", "        pass"),
 ("M13 xem hộp việc của người khác", "app/api/v9.py", "                                   InboxItem.recipient_member_id == principal.member_id)", "                                   InboxItem.recipient_member_id.isnot(-1))"),
 ("M14 đỉnh cây không dời hạn (spam audit)", I, "            a.expires_at = now + ttl            # thử lại", "            pass            # thử lại"),
]
red = 0
for name, f, old, new in M:
    p = B / f; src = p.read_text()
    assert old in src, name
    p.write_text(src.replace(old, new, 1))
    try:
        r = subprocess.run([str(B.parent / ".venv/bin/python"), "-m", "pytest", "-q", "-x", "-p", "no:warnings",
                            "tests/test_d35_inbox_escalation.py"], cwd=B, capture_output=True, text=True, timeout=300)
        ok = r.returncode != 0
        red += ok
        last = [l for l in r.stdout.splitlines() if "passed" in l or "failed" in l][-1:]
        print(f"{'ĐỎ ' if ok else 'XANH'} {name}: {last}", flush=True)
    finally:
        p.write_text(src)
print(f"{red}/{len(M)} đột biến bị bắt")
