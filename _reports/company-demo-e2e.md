# G5 — Kịch bản demo công ty (Gate ra Đợt 3)

> Trạng thái: **đã chạy giả lập toàn đường ống — chưa chạy với gateway thật.** G5 chưa đóng.

## Kịch bản (trang kế hoạch)
Mục tiêu *“Ra mắt bộ sưu tập hè, $20”* → plan được duyệt → 3 phòng nhận việc → review chéo → người chỉ nhận 2 lần ping → chi phí khớp ±5%.

## Kết quả chạy giả lập — `tests/test_g5_company_demo.py`
Runtime giả (chỉ ghi `run_agent`); mọi thứ khác thật: ORM, API v9/approvals, MCP bằng API key của từng seat, hàng đợi wakeup + drain, lifecycle, execution policy, Hộp việc.

| Bước | Đường đi trong code | Kết quả |
| --- | --- | --- |
| Người tạo mục tiêu ($20) | `POST /api/v9/goals` → `strategy.on_goal_created` | việc “Lập kế hoạch” + wakeup `goal_created` cho Nina |
| Nina lập kế hoạch | drain → 1 lượt Nina → `company_plan_submit` (3 việc, phụ thuộc chuỗi, mỗi việc 1 reviewer ở phòng khác, tổng $20) | approval `strategy` rev 1 |
| **Ping #1** | Hộp việc `approval_pending` → người duyệt | duyệt → `plan_apply` |
| 3 phòng nhận việc | `route_to_department` ×3 → drain → 3 lượt định tuyến → `company_task_assign` ×3 (kèm lý do) | mỗi phòng giao 1 nhân viên |
| Làm theo phụ thuộc | việc 2, 3 bị chặn tới khi việc trước `done` (`blocker_cleared`) | đúng thứ tự Sản xuất → Marketing → Bán hàng |
| Review chéo | việc vào `review` → chặng review (D2.2) → wakeup `review_requested` cho trưởng phòng **khác** → DUYỆT → `done` | 3/3 qua review, **không ping người** |
| Mục tiêu hoàn thành | `strategy.on_task_closed` → goal `completed`, progress 100 | event `goal.completed` |
| **Ping #2** | Hộp việc `goal_completed` → người duyệt kế hoạch | — |

**Số ping người nhận: đúng 2** (`approval_pending`, `goal_completed`). Lượt chạy: Nina 1, trưởng phòng 3, nhân viên 3.

### Thay đổi phải làm để đạt kịch bản (phát hiện khi chạy giả lập)
1. Việc vào `review` trước đây luôn báo người quản lý, kể cả khi reviewer là agent → 3 ping thừa. Nay reviewer của chặng là agent thì không ping người.
2. Kế hoạch chưa mang được review chéo → thêm `reviewer_member_id` cho từng việc trong `company_plan_submit` (tạo policy review D2.2).
3. Chưa có “mục tiêu hoàn thành” → `on_task_closed` cập nhật tiến độ; xong hết thì goal `completed` + một ping `goal_completed`.

## Chưa kiểm được (cần gateway thật)
- **Chi phí khớp ±5%**: cần usage/giá model thật từ OpenClaw (`sessions.usage`) đối chiếu `usage_events`/`budget_ledger` (D1.2/D2.3). Runtime giả không sinh chi phí.
- Nina/trưởng phòng **thật** có gọi đúng tool hay không (chất lượng gói ngữ cảnh); phòng họp review 2 người (`room_conductor`) chạy thật — giả lập quyết định review trực tiếp qua `execution_policy.decide`.

## Cần để chạy G5 thật
Gateway OpenClaw chạy được agent thật, một trong hai:
- local: sửa agent `dev` (`openclaw doctor --force` — cần anh đồng ý), hoặc
- box Prized: chuyển `OPENCLAW_MODE` khỏi `mock`, cấp API key model, bind 7 seat (Nina, 3 trưởng phòng, 3 nhân viên), bật `WAKEUP_DRAIN_SECONDS`.
Ước tính ~10 lượt agent (+ vòng sửa/review) trong trần $20 của mục tiêu.
