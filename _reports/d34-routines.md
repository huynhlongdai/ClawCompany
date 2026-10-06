# D3.4 — Routines (việc định kỳ / webhook)

## Đã làm
- **Migration `0026_routines`** (kế hoạch ghi `0022` — số đó đã dùng; chuỗi hiện tại …0025 → 0026): bảng `routines` (runbook, `assignee_member_id` | `department_id`, `mode` create_task|run_only, `timezone`, `catch_up`, `enabled`, `max_consecutive_failures`, `consecutive_failures`, `paused_reason`, `standing_task_id`), `routine_triggers` (`kind` cron|webhook, `cron`, `secret`, `next_run_at` UTC), `routine_runs` (`idempotency_key` **UNIQUE**, trạng thái queued/running/succeeded/failed/skipped, task/wakeup/task_run liên kết).
- **`services/routines.py`**
  - Cron 5 trường **theo múi giờ của routine** (dùng `recurring_ops.compute_next`, truyền giờ UTC có tzinfo). Ghi `routine_runs` TRƯỚC khi tạo việc → trùng key = IntegrityError = không có việc trùng (beat + API, hay webhook gửi lại).
  - `fire()`: `create_task` tạo việc mới trong dự án “Việc định kỳ” (hoặc dự án chỉ định) → seat: wakeup `routine` (dedupe `routine:rr<id>`), phòng: `routing.route_to_department` (D3.1). `run_only`: đánh thức trên một việc thường trực, tự mở lại nếu đã xong. Người (không phải agent) nhận → xong ngay.
  - **Đồng thời**: lần trước còn queued/running → lần này `skipped` (“concurrent”).
  - **Chạy bù** sau khi hệ thống tắt: cửa sổ trễ 5 phút vẫn là “đúng giờ”; `skip_missed` ghi mỗi giờ lỡ là run `skipped`; `run_once` chạy bù đúng 1 lần (`catch_up`, kèm số giờ lỡ). Giờ hẹn kế luôn tính từ *bây giờ*.
  - **Kết cục thật** (`reconcile`, mỗi nhịp tick): đọc `task_runs` (bỏ lượt định tuyến) → succeeded/failed; wakeup bị bỏ vì lý do không hoãn được → failed; seat bận / ngoài giờ → **chờ** (theo chuỗi `requeued_as` của D2.1); treo quá 12h → failed.
  - **Tự dừng**: lỗi liên tiếp ≥ N → `enabled=False`, `paused_reason`, audit `routine.paused`, event, Hộp việc loại mới `routine_paused` (ưu tiên cao, gửi chủ routine/quản lý). Thành công xoá chuỗi lỗi; bật lại xoá chuỗi lỗi và không chạy bù thời gian bị dừng.
  - **Webhook** `POST /api/routines/hooks/{trigger_id}`: `X-Routine-Secret` (so sánh hằng thời gian, sai → 403), `Idempotency-Key` bắt buộc (thiếu → 400); gửi lại cùng key → `duplicate: true`, trả đúng lần chạy/việc cũ. Payload webhook được ghi vào mô tả việc.
  - **3 mẫu**: *Báo cáo sáng của Nina* (`30 8 * * *`, Asia/Ho_Chi_Minh), *Rà soát SLA* (`0 10 * * 1-5`), *Tổng kết chi phí tuần* (`0 9 * * 1`). Mẫu gắn **bảng số liệu thật lúc tạo việc** (`snapshot`: việc theo trạng thái, quá hạn, bị chặn, phê duyệt chờ, SLA mở, Hộp việc chưa đọc, lượt chạy 24h, chi phí 24h/7 ngày) — thay phần chỉ-đếm của `decision_loop` (bản cũ để nguyên cho tương thích).
- **Lịch chạy**: Celery beat `routines.tick` 30s; dev không Celery: `ROUTINES_TICK_SECONDS` (mặc định 0 = tắt — bật là cho phép hệ thống tự tạo việc và đánh thức seat).
- **API** `/api/routines`: list, templates, create, from-template, get (kèm secret, manager), patch enabled, run, runs, tick (theo tổ chức), hooks.
- **UI `/app/routines`** (“Việc định kỳ”, nhóm Công việc): danh sách (người nhận, cron + múi giờ, lần tới giờ địa phương, lần cuối, lý do tự dừng), tạo từ mẫu, chi tiết + webhook (đường dẫn, secret, Idempotency-Key), bảng lần chạy, chạy ngay, tắt/bật lại, form tạo routine.

## Kiểm chứng
- `tests/test_d34_routines.py`: 11 test — routine 9:00 HCM (02:00 UTC) tạo việc + wakeup `routine` → drain → task_run `routine` → succeeded; key trùng không tạo lần hai; webhook 400/403/trùng không tạo việc trùng + concurrent; lỗi 2 lần → tự dừng + audit + inbox, bật lại; thành công xoá chuỗi lỗi; 2 chính sách chạy bù; cửa sổ trễ; seat bận không tính lỗi; routine giao phòng → trưởng phòng; run_only tái dùng + mở lại việc thường trực; mẫu + số liệu + API/validation.
- `tools/mutate_d34.py`: **18/18** đột biến bị bắt.
- Full pytest: **929 passed, 2 skipped**. `tsc --noEmit` sạch.
- Chưa e2e với gateway thật.
