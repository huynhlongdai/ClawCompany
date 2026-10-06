# D1.5 + D1.6 — Máy chủ MCP `company_*` và quyền tool ba mức

Nhánh `impl-plan`. Migration `0020_tool_permissions`.

## Đã làm
| Phần | Ở đâu |
|---|---|
| 23 tool `company_*` (22 tool trong bảng L2.5 + `company_task_checkout`) | `services/company_mcp.py` |
| Máy chủ MCP streamable-HTTP: `initialize`, `ping`, `tools/list`, `tools/call`, notification → 202, `Mcp-Session-Id`; `GET /api/mcp` → 405 | `api/mcp.py` |
| Seat lấy từ API key gắn `member_id` (hoặc `X-ClawCompany-Seat`); lượt chạy lấy từ `X-OpenClaw-Session-Key: company-task-<id>` | `api/mcp.py::_seat`, `_run_for_session` |
| Bảng quyền `tool_permissions` (member > bậc ghế lead/executor > mặc định; tool lạ → off) | `models/tool_access.py`, `services/tool_permissions.py` |
| Ba mức: `allowed`; `ask` → tạo Approval `tool:<tên>`, duyệt xong cấp 24h; `off` → HTTP 403, JSON-RPC `-32003` | `api/mcp.py::_handle` |
| REST `/api/company-tools/*` kiểm cùng bảng quyền | `api/company_tools.py` |
| `policy.authorize`: agent không có policy → **deny** (`default_deny`); người giữ allow | `services/policy.py` |
| Nhật ký: mỗi lượt gọi ghi `mcp.tool.called` (tool, ok, ms, run_id, arg_keys — không ghi giá trị), từ chối ghi `mcp.tool.denied` | event bus v10 |
| UI **Kiểm soát → Công cụ của agent** (`/app/agent-tools`): tóm tắt theo bậc, ma trận tool × bậc (admin chỉnh), đoạn cấu hình OpenClaw, nhật ký gọi tool | `components/AgentToolsConsole.tsx`, `lib/api.ts::apiMcp` |

## Kiểm chứng
- `tests/test_d15_mcp_company_tools.py` — 12 test qua TestClient + API key thật; đã kiểm mutation: bỏ chốt chính thì test đỏ.
- Full pytest: 805 passed, 2 skipped. Alembic 0018→0020 up/down/up trên Postgres 16 sạch.
- Dev server, seat **Nina** gọi qua `POST /api/mcp`: `company_project_get` → `running_count: 1` (dữ liệu công ty thật, không còn đoán). Đổi `company_budget_check`=off cho bậc lead → 403 `-32003`; `company_event_emit`=ask → `pending_approval`, approval #2.
- UI (Playwright): chọn "Tắt" cho `company_report_submit`/Thực thi → API trả `off/override`, tải lại vẫn giữ; đặt lại "Được dùng" → lưu đúng. 0 lỗi console. Ảnh: `ui/d15-agent-tools.png`.

## Chưa kiểm được (ghi thẳng)
- **Header theo session của OpenClaw**: sandbox không có gateway OpenClaw thật, nên chưa xác nhận OpenClaw gửi `X-OpenClaw-Session-Key` cho MCP server. Hiện dựa vào API key theo seat (đủ để định danh); nếu OpenClaw không gửi header, tool vẫn chạy nhưng `run_id` trong log là trống và `company_task_checkout` cần `task_id`.
- Nina trả lời bằng **model thật** chưa chạy — mới kiểm bằng client MCP gọi đúng tool.
