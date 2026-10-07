# M4a · Công việc & lượt chạy — báo cáo

**Gate (gateway thật):** giao việc cho agent A có review chéo bởi agent B → lượt chạy thật (beat drain → `chat.send` → follower)
→ câu trả lời cuối thành Kết quả → Chờ duyệt → B review trong phòng họp → DUYỆT/SỬA; chi phí lượt chạy và phòng review khớp
`sessions.usage` ±5%; tổng trên side-peek = lượt chạy + review và khớp danh sách; sai luồng / revision cũ / chạy khi chưa giao bị chặn bằng lời tiếng Việt.
**Kết quả:** `tools/gate_m4a.py` **18/18 PASS × 3 lần liên tiếp** trên VM (OpenClaw 2026.9.8) sau khi sửa lỗi bắt báo cáo (lần 2–4),
và **× 3 lần liên tiếp trên commit cuối** (lần 11–13). Lần 1: 16/18 (lỗi thật #2). Lần 7: 17/18 do chính gate so tổng chặt hơn
sai số làm tròn 6 số lẻ của từng phần (0.008170 vs 0.008171) — đã nới đúng bằng sai số làm tròn, số liệu app không đổi.
Lần 8: 16/18 — lộ lỗi thật #4 (hai tiến trình cùng chạy một review).
Ví dụ việc #14: lượt chạy $0.004003 (gateway $0.0040028), phòng review $0.004210 (gateway $0.004210), side-peek $0.008212.

## API gom về `/api/work` (spec từ code)
| Đường | Việc |
|---|---|
| `GET /meta` | trạng thái + nhãn VN, người nhận (agent/người, paused), phòng ban, dự án, quyền (`create`, `set_reviewers`) |
| `GET /tasks` | lọc `status`, `assignee=me\|none\|agent\|human\|<id>`, `department`, `project`, `company`, `priority`, `q` (`#id`); `counts` theo trạng thái; mỗi việc có `runs` {count, cost (gồm phòng review), tokens, running, failed, last_status}, `review`, `blocked_by` |
| `POST /tasks` | `start=true` → Cần làm + đánh thức người nhận; `start=false` → nháp; giao phòng → trưởng phòng định tuyến; review chéo (chặn tự review, agent tạm dừng/nghỉ) |
| `GET /tasks/{id}` | side-peek: dòng thời gian (thẻ lượt chạy kèm mục sổ theo runId, phòng review kèm từng lượt nói + chi phí, sự kiện nhãn VN), tổng chi phí/token, bước chuyển hợp lệ, người review gợi ý (trưởng phòng → đồng nghiệp agent → quản lý), lịch sử review |
| `PATCH /tasks/{id}` | sửa tên/mô tả/tiêu chí/ưu tiên/hạn/người nhận/phòng, có `expected_revision` |
| `POST /tasks/{id}/move` | kéo thẻ: kiểm bảng chuyển → chốt review → revision cũ = 409 `stale_revision` |
| `PUT /tasks/{id}/reviewers` | (quản lý) đặt/bỏ người review; đang review thì 409 |
| `POST /tasks/{id}/review` | người duyệt: DUYỆT → Xong, SỬA → Đang làm + đánh thức người làm |
| `POST /tasks/{id}/run` | Chạy ngay: wakeup `assigned` + drain ngay; giải thích khi bỏ qua (seat bận, chưa giao, là người…) |

Đường cũ vẫn chạy, trả `Deprecation: true` + `Link: <…>; rel="successor-version"`: `/v17/workspace/tasks`, `/v27|v18/…/move`, `/tasks/{id}/runs|execution-policy|review`.

## UI `/app/work` (thay "Bảng việc"; `/app/flow` → `?view=board`)
Danh sách nhóm theo trạng thái / Bảng kéo thả (menu chuyển bằng bàn phím), tìm `/`, tạo `C`, `j/k/Enter/Esc`, lọc người nhận/phòng/ưu tiên;
side-peek `?peek=id`: sửa tại chỗ, cảnh báo agent tạm dừng, tổng chi phí + Chạy ngay, tab Dòng thời gian / Review / Mô tả;
tạo việc gợi ý người review là trưởng phòng. Lỗi hiển thị bằng câu tiếng Việt (trước đây có chỗ hiện JSON thô).

## Lỗi thật tìm được khi chạy gateway thật (đã sửa)
1. **Mọi việc có review chéo kẹt "thiếu báo cáo".** Gateway chưa nối MCP `company_*` nên agent không có tool ghi sổ. Nay câu trả lời cuối của agent được ghi thành mục Kết quả của người làm.
2. **Câu trả lời cuối không bắt được** (gate lần 1: 16/18): lượt chạy xong *trước khi* follower kịp nghe nên không có `session.message` nào trên stream (việc #12: 0 sự kiện lưu). Nay bước bắt kịp (`stream_catchup`) lấy chữ assistant cuối thuộc chuỗi runId của lượt từ `chat.history`, không lấy câu trả lời của lượt khác cùng phiên.
3. **Phòng review chấm nhầm việc:** prompt neo vào "việc mở đầu tiên của dự án" (sắp theo chuỗi priority). Nay neo đúng việc `review-t{id}` + đưa nguyên văn kết quả người làm.
4. **Một review chạy hai lần.** Celery 4 tiến trình, beat drain mỗi 5 giây; phòng review mất ~40 giây mà wakeup vẫn `queued`, nên
   tiến trình khác bốc lại đúng wakeup ấy (việc #26: drain thứ hai chốt quyết định trước khi drain đầu ghi chi phí lượt nói → side-peek
   "0 lượt", drain đầu nhận 409 và đánh wakeup `failed`). Có thể gọi model hai lần cho cùng một việc. Nay mỗi drain giành wakeup bằng
   UPDATE có điều kiện (`processed_at` làm dấu giữ chỗ, hết hạn sau 15 phút nếu tiến trình chết), trả chỗ cho wakeup chưa đến lượt.
5. Lỗi có `detail` dạng object hiện JSON thô trên UI; kéo "Cần làm → Xong" báo "còn chặng review" thay vì "không có đường chuyển" (kiểm bảng chuyển trước chốt review); dòng thời gian hiện thẻ thô `task.journal.review` trùng với mục sổ; tab side-peek dùng `aria-pressed` thay vì `aria-selected`.

## Kiểm chứng
- `tests/test_m4a_work.py` 19 test + 2 test bắt kịp trong `test_m12_followers.py`; full pytest **1063 passed, 2 skipped** trên commit cuối; `tsc --noEmit` sạch.
- Mutation **18/18 bị bắt** (2 con sống sót lần đầu → siết test): bỏ ghi câu trả lời cuối, bắt kịp không lấy báo cáo, lấy nhầm câu trả lời lượt khác, stream không bắt chữ, phòng review neo sai, không cộng chi phí phòng review, cho tự review, đổi reviewer khi đang review, bỏ chặn agent tạm dừng, bỏ revision khi kéo / khi sửa, Chạy ngay không force, bỏ Deprecation, chốt review trước bảng chuyển, 409 revision không Việt hoá, thẻ `task.journal.*` trùng, drain không giành wakeup, không trả chỗ wakeup chưa chạy.
- UI (VM, 1440px + 390px): 0 lỗi console/HTTP, không tràn ngang; DOM side-peek việc #14: "1 lượt chạy $0.0082 chi phí 9.656 token 1 vòng review".

## Còn lại / ghi chú
- Gateway **chưa nối MCP company tools**: agent không tự ghi sổ / tự chuyển trạng thái; báo cáo hiện lấy từ câu trả lời cuối. Nối MCP sẽ cho báo cáo có cấu trúc hơn.
- Việc gate trên VM (#12 kẹt từ lần 1, #14…) nằm trong dự án Nina của Nova Fashion.

## Ảnh UI
`docs/screenshots/m4a/`: work-list, work-board, peek-timeline, peek-review, create (+ bản `-mobile`).
