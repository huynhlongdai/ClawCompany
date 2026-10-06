# D3.3 — Nina phân rã mục tiêu

## Đã làm
- **Migration `0027_strategy_plans`**: `approvals.payload` (JSONB trên Postgres) + `approvals.revision` (mặc định 1); trạng thái mới `revision_requested` (cột String, không đổi kiểu). Khai ở `0001_baseline.COLUMNS_OWNED_BY_LATER_MIGRATIONS`. `ApprovalOut` thêm `payload`, `revision`.
- **`services/strategy.py`**
  - **Goal mới → Nina** (`orchestration.create_goal`, mọi đường tạo goal): tạo dự án “Mục tiêu #id · …” + việc **“Lập kế hoạch: …”** (`goal_id`, giao seat chiến lược = agent tên Nina, không có thì seat điều hành không thuộc phòng nào) + wakeup **`goal_created`**. Mô tả việc là bản giao: mục tiêu, ngân sách mục tiêu, **danh sách phòng + trưởng phòng + nhân sự kèm id**, giao thức gửi kế hoạch. Tắt được bằng `STRATEGY_PLAN_ON_GOAL=false`.
  - **Tool MCP `company_plan_submit(goal_id, summary, tasks[])`** — mỗi việc: key, title, description, **acceptance_criteria (bắt buộc)**, `department_id` | `member_id` (bỏ cả hai → chọn theo tải D3.2), `budget_usd`, `depends_on` [key], priority. Kiểm: phòng/người thuộc công ty, người thuộc đúng phòng, key trùng, phụ thuộc không tồn tại / tự phụ thuộc / **vòng**, **tổng ngân sách ≤ ngân sách mục tiêu**, tối đa 20 việc. Chỉ seat lập kế hoạch (hoặc seat điều hành) gửi được; thừa hành: tool `off` mặc định.
  - Kế hoạch → `approvals(action='strategy', policy_key='strategy:goal:<id>', payload, revision)`, người duyệt = người tạo goal (không có thì quản lý của Nina). Hạn 24h + leo thang + Hộp việc dùng lại D3.5. Mỗi goal chỉ một kế hoạch mở; gửi chồng khi đang chờ → `conflict`.
  - **Vòng sửa**: `POST /api/strategy/plans/{id}/request-revision` (chỉ người duyệt) → `revision_requested`, ghi chú vào **sổ của việc lập kế hoạch**, mở lại việc nếu cần, wakeup **`changes_requested`** cho Nina. Nina gửi lại → **cùng approval**, `revision+1`, `pending`, lịch sử các lần sửa trong `payload.history`, hạn mới và **báo lại người duyệt** (hook D3.5 bắt chuyển về `pending`).
  - **Duyệt** (`POST /api/approvals/{id}/resolve`, chỉ người duyệt) → **`plan_apply`**: việc con theo thứ tự topo (`goal_id`, `parent_task_id` = việc lập kế hoạch, `acceptance_criteria`, ngân sách ghi trong mô tả), **phụ thuộc** qua `task_graph.add_dependency`; giao **phòng** → `routing.route_to_department` (D3.1, trưởng phòng được đánh thức), giao **seat** → wakeup `assigned` (việc còn bị chặn thì không đánh thức — chờ `blocker_cleared`), không chỉ định → `dispatch_policy` (D3.2, event `task.dispatch_decided`). Idempotent (`payload.applied`): duyệt lại → 409, gọi lại → `already`. Goal → `active`, việc lập kế hoạch → `done`. Audit `strategy.plan_applied`, event `goal.plan_applied`.
  - **Từ chối** → goal `plan_rejected`, event `goal.plan_rejected`, không tạo việc.
- **API** `/api/strategy`: `GET /goals`, `GET /goals/{id}` (goal, việc lập kế hoạch, các kế hoạch + lịch sử, việc đã giao), `POST /plans/{id}/request-revision`.
- **UI `/app/strategy`** (“Kế hoạch mục tiêu”, nhóm Công việc): tạo mục tiêu (công ty, ngân sách), trạng thái lập kế hoạch, bảng việc của kế hoạch (phòng/người, tiêu chí, phụ thuộc, ngân sách), Duyệt / Yêu cầu sửa (ghi chú bắt buộc) / Từ chối, lịch sử sửa, danh sách việc đã giao.

## Kiểm chứng (“Xong khi”)
- `tests/test_d33_strategy.py` — 6 test, HTTP thật (goal qua API v9, Nina gọi MCP bằng API key của seat, duyệt qua Hộp việc):
  - goal → việc lập kế hoạch + wakeup `goal_created` → drain → gói của Nina có `company_plan_submit`, `goal_id`, đủ 3 phòng kèm id, ngân sách $20; task_run `goal_created`.
  - **Vòng đầy đủ**: gửi rev 1 (3 việc) → người duyệt được báo → gửi chồng bị chặn → **yêu cầu sửa** → ghi sổ + Nina được đánh thức (gói chứa ghi chú) → duyệt khi đang sửa = 409 → **gửi lại rev 2** (4 việc, cùng approval, người duyệt được báo lại, hạn mới) → **duyệt** → **4 việc con, đủ 3 phòng**, 3 phụ thuộc, 3 trưởng phòng được đánh thức `routed`, goal `active`, việc lập kế hoạch `done`; duyệt lại không sinh việc đôi.
  - Kiểm hợp lệ (ngân sách vượt, thiếu tiêu chí, phòng lạ, vòng, người sai phòng, summary ngắn, trưởng phòng không được lập kế hoạch).
  - Giao seat + tự chọn theo tải + việc bị chặn không bị đánh thức; từ chối; chỉ người duyệt được quyết; thừa hành không có tool.
- `tools/mutate_d33.py`: **21/21** đột biến bị bắt.
- Full pytest: **935 passed, 2 skipped** (test đếm tool MCP 24 → 25). `tsc --noEmit` sạch.
- Chưa chạy với Nina thật trên gateway (xem G5).
