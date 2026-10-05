# D1.3 + D1.4 — Đồ thị công việc, vòng đời task, lượt chạy

Nhánh `impl-plan`. Migration `0018_task_graph`, `0019_task_runs`.

## Đã làm
| Phần | Ở đâu |
|---|---|
| Cột `tasks.parent_task_id, goal_id, due_at, acceptance_criteria, checkout_run_id`; bảng `task_dependencies`, `task_runs` | `models/entities.py`, `models/work_graph.py`, migration 0018/0019 (có downgrade) |
| Đồ thị: chặn vòng (phụ thuộc và cha), tổ tiên, blocker mở, dòng chuỗi mục tiêu ≤240 ký tự | `services/task_graph.py` |
| **Nơi duy nhất ghi `tasks.status`/`checkout_run_id`** | `services/task_lifecycle.py` (`transition`, `checkout`, `release`, `open_run`, `finish_run`) |
| 12 chỗ ghi status cũ chuyển sang lifecycle | workspace_ops.move_task, agent_dispatch (dispatch, abort), runtime_stream (kết thúc run), board_truth (lưu trữ), board_restore, member_reactivate, orchestration ×3, company_tools (API + workflow) |
| Lint CI | `tools/lint_task_status.py` — 0 chỗ ghi ngoài lifecycle |
| API | `GET /tasks/{id}/graph`, `POST/DELETE /tasks/{id}/dependencies`, `PATCH /tasks/{id}/links`, `GET /tasks/{id}/runs`, `GET /tasks?goal_id=` |
| Gói ngữ cảnh | khối 2 thêm `Chuỗi mục tiêu`, hạn, việc đang chờ, tiêu chí nghiệm thu |
| UI | Chi tiết việc: panel **Liên kết** + **Lượt chạy**; Mục tiêu: **Công việc phục vụ mục tiêu**; Bảng việc hiện đúng lý do khi không chuyển được |

## Luật mới (đã kiểm bằng test hành vi)
- Thêm phụ thuộc tạo vòng → **422**; task tenant khác → **404**.
- Còn blocker chưa xong → không vào `in_progress/review/done` (409) và không dispatch được.
- Mỗi dispatch = 1 hàng `task_runs`; lượt phải `checkout` bằng UPDATE có điều kiện. Lượt thứ hai thua → **409**, ghi `skipped`, không thử lại.
- Run kết thúc (complete/error/abort) → hàng run đóng (`completed/failed/cancelled`, `ended_at`, `error_reason`) và task được thả. Gọi runtime lỗi → run `failed`, task được thả.
- Bàn giao cho người khác → lượt của chủ cũ `cancelled` ("handed off").
- Công cụ `company/tasks/{id}/status` của agent trước nhận **bất kỳ chuỗi nào**; giờ theo cùng bảng chuyển với người.
- Chuyển do hệ thống (`system=True`) bắt buộc có lý do; sự kiện `task.{to}` mang `reason`, `via`.

## Bằng chứng
- `pytest`: **793 passed, 2 skipped** (trước: 780/1). File mới `tests/test_d13_d14_task_graph_lifecycle.py` (14 test).
- **Postgres 16 thật**: 20 luồng cùng checkout một task → đúng **1 thắng, 19 thua** (`pytest -m postgres`).
- Mutation: bỏ điều kiện `checkout_run_id IS NULL` → 2 test đỏ (SQLite + Postgres); tắt chặn blocker → test blocker đỏ; bỏ đăng ký cột ở baseline → test migration đỏ.
- Alembic `upgrade head → downgrade -2 → upgrade head` xanh trên SQLite sạch và Postgres; `upgrade head` từ DB Postgres trống xanh.
- UI: `/app/tasks/2`, `/app/tasks/9`, `/app/goals` — 0 lỗi console; kiểm tương tác: tạo vòng hiện lỗi 422 đúng câu, thêm blocker hiện cảnh báo, gỡ blocker hết cảnh báo, chọn mục tiêu liệt kê đúng task.

## Sửa phát sinh
- `0001_baseline` dựng bảng từ bản sao **đã cắt cột tương lai** thay vì tạo rồi bóc: `tasks.goal_id` trỏ `executive_goals` (0004) làm Postgres từ chối CREATE TABLE và SQLite vỡ ở batch. Test đăng ký cột nay nhận cả dạng `batch.add_column`.
- `POST /tasks` từ chối `status` ngoài từ vựng (trước tạo được task với trạng thái tuỳ ý).
- `/api/v18/workspace/tasks/{id}/move` gắn `Deprecation` + `Link` tới v27.

## Chưa làm / giới hạn
- `task_runs.cost_usd/tokens` chưa được điền từ metering (D1.2/D2.3 sẽ nối).
- Không có job dọn checkout treo: checkout tự lành khi lượt giữ đã kết thúc; lượt `running` mãi không có sự kiện kết thúc thì phải abort tay.
