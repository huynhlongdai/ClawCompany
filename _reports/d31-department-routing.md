# D3.1 — Trưởng phòng định tuyến

## Đã làm
- **Migration `0024_department_routing`**: `tasks.assignee_department_id` (FK `departments`, index) và `departments.guide` (hướng dẫn phòng). Khai ở `0001_baseline.COLUMNS_OWNED_BY_LATER_MIGRATIONS`; chuỗi migration lên head trên DB sạch vẫn chạy được.
- **`services/routing.py`**
  - `should_wake_head(HeadEvent)` — **thuần**, 5 luật xét theo thứ tự: tự kích hoạt → không (`self_triggered`); đã có lượt chờ → không (`dedup_pending`); comment có @ → không (`mention_routes_directly`, người được @ nhận wakeup `mentioned`); comment không @ → đánh thức; sự kiện chỉ tham chiếu tới việc (giao cho phòng…) → đánh thức (`task_reference`).
  - `route_to_department` — phòng giữ việc (bỏ người nhận), đánh thức `departments.head_member_id` với lý do `routed`. Việc đang `in_progress/review/done` → 409.
  - **Lượt định tuyến**: wakeup `routed` → `wakeup._route` (vẫn qua cổng ngân sách D2.3) → phiên riêng `agent:<id>:company-route-<task>`, `task_runs.trigger_kind='routed'`, **không checkout, không đổi trạng thái task**. Kết thúc phiên → `finish_routing_run` (đóng run, quyết toán + true-up, xếp lại lý do bị hoãn); chi phí `session.message` tính vào lượt định tuyến.
  - **Gói ngữ cảnh trưởng phòng** (7 khối): bạn là ai (+ là trưởng phòng), việc + người nhận hiện tại, dự án, **nhân sự phòng** (vai, loại, trạng thái, việc mở, lượt đang chạy), **hướng dẫn phòng**, luật (ngân sách), **giao thức định tuyến** (chỉ giao việc, ghi đánh giá, dừng).
  - Comment trên việc của phòng (`task_journal.append`) → `on_journal_entry`: áp luật khi phòng giữ việc chưa có người nhận, hoặc comment `blocker` (người nhận vướng → trưởng phòng có thể giao lại). Comment báo cáo cuối lượt của người nhận không đánh thức.
- **Tool MCP `company_task_assign(task_id, member_id?, reason)`** — chỉ trưởng phòng đang giữ việc (hoặc seat điều hành không thuộc phòng nào); người nhận phải trong phòng; bắt buộc lý do; bỏ `member_id` → chọn theo tải bằng D3.2 (`task.dispatch_decided`). Ghi `company_events` **`task.routed`** (`reason`, `by_member_id`, `run_id`, `auto_pick`) + dòng sổ `decision` mang actor = trưởng phòng (luật tự kích hoạt chặn vòng tự gọi). Seat thừa hành: tool `off` mặc định (D1.6). Việc của phòng nhìn thấy được với người trong phòng.
- **API v18**: `POST /workspace/tasks/{id}/route`, `TaskIn.assignee_department_id`, `GET /workspace/departments/{id}/routing` (trưởng phòng, hướng dẫn, nhân sự, việc phòng giữ, sự kiện định tuyến), `PUT /workspace/departments/{id}/guide` (manager).
- **UI `/app/routing`** (“Định tuyến phòng ban”, nhóm Đội ngũ): chọn phòng, nhân sự + tải, sửa hướng dẫn, việc phòng đang giữ kèm dòng thời gian (giao cho phòng → đánh thức theo luật nào → trưởng phòng giao cho ai, lý do gì), form giao việc cho phòng.

## Kiểm chứng
- `tests/test_d31_routing.py`: 15 test — 5 luật + thứ tự luật; HTTP thật (API v18, MCP bằng API key seat): giao cho phòng → wakeup `routed`; drain → gói định tuyến đúng nội dung, run `routed` không giữ task; trưởng phòng gọi `company_task_assign` → `task.routed` có lý do, chỉ 1 wakeup `routed` (không vòng), người được giao chạy lượt thường, trưởng phòng không bị gọi lại; luật comment trên việc của phòng; chỉ `blocker` của người nhận mới đánh thức; chặn thừa hành / người ngoài phòng / thiếu lý do; tự chọn theo tải; chi phí phiên định tuyến vào đúng run; API routing + hướng dẫn + 409.
- `tools/mutate_d31.py`: **13/13** đột biến bị bắt.
- Full pytest: 906 passed (+ 3 test cũ cập nhật: số tool MCP 23→24, baseline khai cột 0024) — chạy lại sau sửa.
- Chưa chạy e2e với gateway thật (agent `dev` local hỏng do đổi đường dẫn workspace — xem phần cuối báo cáo D2.3).
