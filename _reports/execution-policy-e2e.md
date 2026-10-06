# D2.2 — Execution policy: kết quả đo thật

Ngày đo: 06/10/2026. Gateway OpenClaw 2026.9.8 thật, model giả có kịch bản, API với
`WAKEUP_DRAIN_SECONDS=5`. Migration `0022_execution_policy` (`tasks.execution_policy`,
`tasks.execution_state`, JSONB trên Postgres).

## Kết luận

| Tiêu chí "Xong khi" | Kết quả |
|---|---|
| Không đường API nào đưa task có policy sang `done` trước khi qua đủ chặng | **Đạt** — v18 `/workspace/tasks/{id}/move`, v20 `/board/tasks/{id}/move`, v27 `/tasks/{id}/move` đều **409 `execution_policy_pending`**; cả tool agent (`company_task_status` qua `lifecycle.transition`) và đường hệ thống (`system=True`) cũng bị chặn. Chốt duy nhất ở `task_lifecycle.transition`. |
| Chạy thật một vòng sửa → làm lại → duyệt | **Đạt** — task #38, 29,4 giây, không ai bấm dispatch (`evidence/d22/e2e_policy.txt`, 11/11 OK) |

## Vòng chạy thật (task #38)

| Bước | Thời điểm | Gì xảy ra |
|---|---|---|
| Đặt policy 1 chặng review (Long), giao cho Nina | 0,1 s | wakeup `assigned` |
| Vòng 1 | 15,7 s | drain → `chat.send` → exec (duyệt qua API) → **Nina tự ghi báo cáo** qua MCP `company_task_comment` → run `final` → task `review`, chặng 1 `in_review`, reviewer Long |
| Kéo thẳng sang done | 15,8 s | 409 `execution_policy_pending` |
| Long: SỬA "Ghi thêm múi giờ…" | 16,0 s | sổ: mục `review` "SỬA — chặng 1, vòng 1"; task → `in_progress`; wakeup `changes_requested` cho Nina |
| Vòng 2 | 27,1 s → 29,4 s | Nina tự chạy lại (run #25, `trigger_kind=changes_requested`), báo cáo lại, → `review` vòng 2 |
| Long: DUYỆT | 29,4 s | → `done`; lịch sử `[(1, revise), (2, approve)]` |

Chi phí: run #24 $0,150045 + run #25 $0,188505 = **$0,33855**; gateway `sessions.usage` cho
`agent:dev:company-task-38` = **$0,33855** (lệch 0,00%). 2 `chat.send`.

## Báo cáo bắt buộc — bắt được trên gateway thật

Lần chạy đầu (task #37) model giả **chưa** gọi được tool báo cáo: run xong → task sang `blocked`,
`execution_state.missing_report = 23`, event `task.report.missing`, không có chặng review nào
bắt đầu. Đúng thiết kế: việc không đi tiếp khi người làm không báo cáo.

Nguyên nhân, kiểm trên gateway: 2026.9.8 **giấu tool MCP sau Tool Search** — model chỉ thấy 11 tool
(`exec`, `read`, …, `tool_search`, `tool_describe`, `tool_call`); 23 tool `company_*` nằm trong
catalog (`tool-search: cataloged 77 tools`, trước khi gắn MCP là 41). Model phải `tool_search` →
`tool_call {id, args}`. Model giả đã làm đúng chuỗi đó ở task #38. Hệ quả cho model thật: skill
`clawcompany-heartbeat` phải dặn rõ tìm `company_task_comment` qua Tool Search.

Gắn MCP: `config.patch mcp.servers.clawcompany` (streamable-http, `X-API-Key` của seat Nina — API
key #3, chỉ scope `company.*`). Đây cũng là lần đầu xác nhận được phần D1.5 còn để ngỏ: gateway thật
gọi được máy chủ MCP của ClawCompany và ghi vào sổ việc dưới danh nghĩa seat.

## Cách làm

* `services/execution_policy.py`: chuẩn hoá policy, `on_submitted` (vào `review` từ mọi đường),
  `start_stage` (reviewer = participant đầu tiên **không phải người làm**; agent → wakeup
  `review_requested`; approval → hàng `approvals` `task_stage:t…:r…:s…`), `decide`, `guard_done`,
  `has_report` (chỉ comment **của người làm** trong khoảng run), `run_agent_review`.
* Reviewer là agent: drain gặp `review_requested` của đúng reviewer → phòng 2 người
  (`room_conductor`, `max_turns` 4, reviewer làm chủ toạ), đọc `QUYẾT ĐỊNH: DUYỆT|SỬA` từ biên bản
  (`room_turns`, loại `decision`), không từ bản xem trước 280 ký tự.
* Chặng approval: chỉ đúng `approver_member_id` được quyết (403 nếu khác); kết quả hàng đó là quyết định.
* API: `GET/PUT /api/tasks/{id}/execution-policy`, `POST /api/tasks/{id}/review`.
* UI TaskDetail: panel **Chặng duyệt** — stepper (đã qua / đang chờ / chưa tới), nút Duyệt / Yêu cầu
  sửa (bắt buộc nhận xét), lịch sử, trình soạn chặng. Playwright bấm thật trên task #39: thêm chặng →
  lưu → báo xong → "Yêu cầu sửa" → `in_progress` → báo xong → "Duyệt" → `done`; 0 lỗi console.
  Ảnh: `ui/d22-policy-*.png`.

## Kiểm chứng

* `tests/test_d22_execution_policy.py` — 13 test (ORM thật + TestClient): chốt done trên 3 endpoint +
  tool + system; vòng sửa → duyệt với người; review → approval 2 chặng; approval bị từ chối; loại người
  làm; policy sai → 422; reviewer agent trong phòng 2 người; missing_report; comment của người khác
  không tính.
* Mutation: M1 bỏ chốt done → 2 đỏ; M2 bỏ kiểm reviewer → đỏ; M3 không loại người làm → đỏ; M4 bỏ
  missing_report → đỏ; M5 bỏ kiểm người duyệt approval → đỏ; M6 `has_report` không lọc người làm →
  **xanh** lúc đầu → thêm test → đỏ; M7 bỏ `on_submitted` → 6 đỏ.
* `test_migration_chain` bắt được việc quên khai 2 cột mới ở `0001_baseline` — đã khai.

## Giới hạn

1. Reviewer agent chưa chạy trên gateway thật: dev chỉ có **một** agent (`dev`), seat Sophia/Mia gắn
   với agent id không tồn tại trên gateway. Đường phòng review đã test bằng runtime giả.
2. Trạng thái dùng `review` có sẵn thay cho `in_review` của kế hoạch (cùng nghĩa, không đổi từ vựng bảng).
3. Báo cáo bắt buộc áp cho task có policy; bật `REQUIRE_RUN_REPORT=true` để áp cho mọi task (mặc
   định tắt vì model thật chưa được dặn qua skill — xem D2.1 §4).
