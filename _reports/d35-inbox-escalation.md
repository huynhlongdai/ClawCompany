# D3.5 — Hộp việc gộp & leo thang phê duyệt

## Đã làm
- **Migration `0025_inbox_escalation`**: `inbox_items` thêm `task_id`, `group_key`, `kinds`, `count`, `body`; `approvals` thêm `expires_at`, `escalate_to_member_id`, `escalated_at`. Khai ở `0001_baseline.COLUMNS_OWNED_BY_LATER_MIGRATIONS`.
- **`services/inbox.py`**
  - `notify()` gộp theo (người nhận, `task:<id>`): báo mới cùng việc → tăng `count`, thêm `kinds`, đặt lại *chưa đọc*. Chỉ người nhận inbox; agent → chuyển cho quản lý người.
  - 7 nguồn: `approval_pending`, `approval_escalated`, `run_failed` (runtime blocked / runtime_error), `task_review` (lifecycle → review), `mention` (@người trong sổ việc), `budget_warned`, `budget_exhausted`.
  - Hook ORM cho `Approval`: tạo mới → `expires_at` (mặc định 24h, `approval_ttl_hours`; approval gateway dùng `expires_at_ms`), `escalate_to_member_id` = quản lý; duyệt/từ chối → đóng dòng inbox.
  - `escalate_overdue(db, now)`: approval quá hạn → chuyển người duyệt lên cấp trên, audit `approval.escalated` (không có cấp trên → `approval.escalation_failed`, dời hạn, không spam), event + inbox ưu tiên cao; bỏ qua approval `openclaw:`; mỗi approval leo thang một lần mỗi cấp. Celery beat `approvals.escalate_overdue` 60s + chạy in-process (`approval_escalate_seconds`).
- **API v9**: `GET /inbox/mine`, `POST /inbox/{id}/status`, `GET /approvals/quick`, `POST /approvals/escalate-overdue` (manager). `ApprovalOut` thêm 3 trường.
- **UI**: `InboxConsole` hiển thị dòng gộp (×số lần, loại, Đã đọc/Xong), hạn và trạng thái leo thang trên approval; trang **`/app/approve`** (`QuickApprove`) — thẻ lớn, duyệt nhanh trên điện thoại.

## Kiểm chứng
- `tests/test_d35_inbox_escalation.py`: 9 test (gộp theo task, chỉ người, đặt lại chưa đọc, hạn 24h, leo thang + audit + không lặp, bỏ qua gateway, đóng khi duyệt, 4 hook nguồn, phân quyền `/inbox/mine`).
- `tools/mutate_d35.py`: **14/14** đột biến bị bắt.
- Full pytest: 918 passed, 2 skipped. `tsc --noEmit` sạch.
- Chưa e2e với gateway thật.
