"""M4b mutation: mỗi đột biến phải làm tests/test_m4b_inbox.py đỏ.

Chạy: .venv/bin/python tools/mutate_m4b.py            (tất cả)
      .venv/bin/python tools/mutate_m4b.py 1-5         (một đoạn, đánh số từ 1)
"""
import pathlib
import subprocess
import sys

B = pathlib.Path(__file__).resolve().parent.parent / "backend"
H = "app/services/inbox_hub.py"
S = "app/services/budget_scope.py"
C = "app/services/cost_board.py"
I = "app/services/inbox.py"
M = [
 ("M1 bỏ giành quyền quyết (UPDATE có điều kiện)", H, '    _claim(db, a, rev, values={"status": "deciding"})\n', "    pass\n"),
 ("M2 giành quyền không xét status=pending", H, '                     .where(Approval.id == a.id, Approval.status == "pending",\n', "                     .where(Approval.id == a.id,\n"),
 ("M3 bỏ kiểm revision", H, "    if expected_revision is not None and int(expected_revision) != int(a.revision or 1):", "    if False:"),
 ("M4 ai cũng là người duyệt", H, "        return principal.member_id is not None and principal.member_id in allowed", "        return True"),
 ("M5 không có người duyệt → ai cũng quyết", H, "    return is_manager(principal)\n\n\n# ----", "    return True\n\n\n# ----"),
 ("M6 từ chối không cần lý do", H, '    if decision == "reject" and not note:', "    if False:"),
 ("M7 seat agent là người duyệt → không chuyển cho quản lý", H, "        out |= set(inbox.human_recipients(db, a.approver_member_id))", "        out |= set()"),
 ("M8 không nói thẳng khi chưa gửi được gateway", H, '            msg += (" — nhưng CHƯA gửi được tới OpenClaw', '            msg += ("'),
 ("M9 thấy hộp việc của người khác", H, "                                       InboxItem.recipient_member_id == me)", "                                       InboxItem.recipient_member_id.isnot(None))"),
 ("M10 thiếu thẻ duyệt không có dòng hộp việc", H, "            if a.id in seen_approvals or me not in deciders(db, a):", "            if True:"),
 ("M11 thẻ quyết được không vào nhóm Cần anh duyệt", H, '    if actionable:\n        return "approvals"\n', ""),
 ("M12 tắt cổng dừng mềm", S, '        if (env.threshold_state or "ok") == "soft_stopped":\n            why = soft_gate', '        if False:\n            why = soft_gate'),
 ("M13 tạo phê duyệt trùng mỗi lần drain", S, '    if latest is None or latest.status != "pending":', "    if True:"),
 ("M14 từ chối không chặn", S, '    if latest is not None and latest.status in ("rejected", "denied"):', "    if False:"),
 ("M15 duyệt chi tiếp không đánh thức seat", S, "    for a in [approval] + [db.get(Approval, i) for i in covered]:", "    for a in []:"),
 ("M16 không có nấc dừng mềm", S, "    if env.soft_stop_pct and p >= float(env.soft_stop_pct) - EPS:", "    if False:"),
 ("M17 rời nấc mềm không huỷ phê duyệt", S, '        acted["expired_approvals"] = expire_soft_grants(db, env, "phong bì rời nấc dừng mềm")', '        acted["expired_approvals"] = []'),
 ("M18 cấp theo phòng không phủ phòng", S, '        return ev.get("department_id") is not None and ev.get("department_id") == member.department_id', "        return False"),
 ("M19 cấp rộng không duyệt theo yêu cầu đang chờ", S, '                s.status = "approved"\n', "                pass\n"),
 ("M20 ngân sách nhóm phủ mọi seat", S, "        return member is not None and sid is not None and sid in (teams or set())", "        return member is not None"),
 ("M21 leo thang không xuống trưởng phòng", I, "            target = department_head_for(db, a, exclude=prev)", "            target = None"),
 ("M22 route cũ quyết lại vẫn 200", "app/api/approvals.py", '    if obj.status != "pending" and payload.status in ("approved", "rejected"):', "    if False:"),
 ("M23 bỏ Deprecation cho đường cũ của hộp việc", "app/main.py", " or inbox_successor(request.url.path, request.method)", ""),
 ("M24 không kiểm thứ tự nấc", C, "    if soft is not None and not (w < int(soft) < 100):", "    if False:"),
 ("M25 cho trùng phạm vi", C, "    if dup:\n", "    if False:\n"),
 ("M26 sửa hạn mức khi đã dừng cứng không cần override", C, ' and (env.threshold_state or "ok") == "exhausted":', " and False:"),
 ("M27 tổng chi tính cả sự kiện không phải model", C, "                                        UsageEvent.event_type == EVENT_TYPE,\n", ""),
 ("M28 bài học không có nhóm riêng", H, '    if kinds & LESSON_KINDS:\n        return "lessons"\n', ""),
 ("M29 đánh dấu dòng của người khác", H, "    if item.recipient_member_id not in (None, principal.member_id):", "    if False:"),
]


def pick(argv):
    if len(argv) < 2:
        return list(enumerate(M, 1))
    lo, _, hi = argv[1].partition("-")
    lo, hi = int(lo), int(hi or lo)
    return [(i, m) for i, m in enumerate(M, 1) if lo <= i <= hi]


# Lần chạy trước bị giết giữa chừng → trả file gốc từ bản sao trước khi làm gì khác.
for bak in B.rglob("*.m4b-orig"):
    bak.replace(bak.with_suffix(""))

red = 0
chosen = pick(sys.argv)
for i, (name, f, old, new) in chosen:
    p = B / f
    src = p.read_text()
    (p.parent / (p.name + ".m4b-orig")).write_text(src)
    assert src.count(old) == 1, f"{name}: không tìm thấy đúng một chỗ để đột biến"
    p.write_text(src.replace(old, new, 1))
    try:
        r = subprocess.run([str(B.parent / ".venv/bin/python"), "-m", "pytest", "-q", "-x", "-p", "no:warnings",
                            "tests/test_m4b_inbox.py"], cwd=B, capture_output=True, text=True, timeout=600,
                           env={"DATABASE_URL": "sqlite:///./_test.db", "JWT_SECRET": "test",
                                "PATH": "/usr/bin:/bin"})
        ok = r.returncode != 0
        red += ok
        last = [l for l in r.stdout.splitlines() if "passed" in l or "failed" in l][-1:]
        print(f"{'ĐỎ ' if ok else 'XANH'} {name}: {last}", flush=True)
    finally:
        p.write_text(src)
        (p.parent / (p.name + ".m4b-orig")).unlink(missing_ok=True)
print(f"{red}/{len(chosen)} đột biến bị bắt")
