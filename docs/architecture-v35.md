# v35 — Spend & Push

Service version `1.25.0`. Không thêm migration: migration head vẫn là
`0015_v32_department_status_not_null`. 192 tool contract cho OpenClaw.

v35 đóng hai món nợ mà bản bàn giao v34 đã nêu tên:

1. `max_cost_usd` trên delegation contract chỉ là chữ trang trí từ v16 — không ai
   đối chiếu nó với chi phí thật.
2. Cockpit theo dõi live run bằng cách poll `/app/live-runs` — mỗi client một
   nhịp request, độ trễ sàn bằng chu kỳ poll.

Cả hai đều được vá **kèm trần năng lực đọc được qua API**
(`GET /api/v35/coverage`), để người soát xét không phải tin vào giao diện.

---

## 1. Đối chiếu ngân sách delegation — `app/services/delegation_spend.py`

### Cách tính

- Chi phí lấy từ `usage_events` (bảng của v7, ghi bởi `metering.record_usage`).
- Quy về contract theo **`task_id` + khoảng thời gian** `[accepted_at hoặc
  created_at, closed_at hoặc now]`.
- Trạng thái: `within` → `warning` (từ `WARN_RATIO = 0.8`) → `over`;
  `unbudgeted` khi `max_cost_usd <= 0`; `unattributable` khi contract không có
  `task_id`.
- `MAX_SCAN = 200` cho mọi lượt quét.

### Chỗ yếu, nói thẳng

`attribution()` trả về đúng bốn lời thừa nhận, và mọi response đều mang theo nó:

| Khoá | Giá trị | Nghĩa |
| --- | --- | --- |
| `usage_rows_carry_delegation_id` | `false` | `usage_events` không có cột `delegation_id`. Hai contract trên cùng một task chỉ được tách bằng mốc thời gian. |
| `covers_contracts_without_task` | `false` | Contract không gắn task thì trả `0.0` nhưng **không** được gọi là phép đo. |
| `runner_reported_spend` | `false` | Số tiền là của metering nội bộ, không phải báo cáo chi phí từ runner OpenClaw. Metering ghi thiếu thì ở đây thiếu theo. |
| `enforced_before_dispatch` | `false` | Vượt trần không chặn việc. Muốn chặn thì phải kiểm tra trước trong đường dispatch. |

### Gắn cờ vượt trần

`flag_overruns()` phát `delegation.budget.overrun` lên event bus, mặc định
`dry_run=True`, và **chỉ một lần cho mỗi contract**: lượt sau tìm thấy event cũ
rồi báo `already_flagged` thay vì spam bus. Payload mang sẵn `"enforced": false`.

Module này không import `record_usage` và không chạm `budget.reserve` /
`settle_reserved` — đọc tiền thì không được phép tạo ra tiền.

---

## 2. Kênh live bằng SSE — `app/services/live_channel.py`

### Nó là gì, chính xác

- Transport là **SSE** (`text/event-stream`), **không phải WebSocket**. SSE một
  chiều server → client, đúng bằng nhu cầu của cockpit, và đi qua proxy HTTP
  thường mà không cần nâng cấp kết nối.
- Cursor là `RuntimeEvent.id`. Client mất kết nối rồi nối lại với cursor cũ sẽ
  nhận đủ phần đã bỏ lỡ — **miễn là hàng còn tồn tại**; retention của v32 xoá
  runtime event sau 14 ngày.
- Khung: `snapshot` (một frame render được ngay) → `events` → `heartbeat` mỗi 15s
  khi im lặng → `closed` kèm `reconnect_with_cursor`.
- Stream tự đóng sau `MAX_DURATION_SECONDS = 300` để một client biến mất không
  giữ mãi kết nối và session.

### Trần năng lực

`readiness()` báo `removes_client_polling: true` nhưng
`removes_server_polling: false`. Trình duyệt thôi poll; **server vẫn poll DB mỗi
2 giây**, vì `runtime_events` do tiến trình khác ghi và ở đây không có
LISTEN/NOTIFY hay pub/sub cho việc này. Đây là bỏ fan-out phía client, không
phải push thật từ gốc dữ liệu.

`observed_in_production: false` — chưa từng có client thật nối vào stream này.

### Hai quyết định kỹ thuật đáng ghi

1. **Một session cho mỗi nhịp.** Generator mở `SessionLocal()` rồi đóng ngay
   trong `finally` ở từng vòng, không giữ session của request. Session sống
   hàng phút sẽ ghim một snapshot DB và không bao giờ thấy hàng do worker khác
   ghi.
2. **Phạm vi tenant đi qua `tasks`.** `runtime_events` không có
   `organization_id`, nên `_run_ids()` lấy `runtime_run_id` từ `tasks` của
   organization (giới hạn 500 run gần nhất). Run mà task đã bị xoá trở thành
   vô hình ở đây, thay vì rò rỉ sang tenant khác.

---

## 3. Bề mặt API — `app/api/v35.py`

Prefix `/api/v35`, tag `v35-spend-push`. Đọc cần `company.context:read`, ghi cần
`company.workspace:write`.

| Method | Endpoint | Quyền tối thiểu |
| --- | --- | --- |
| GET | `/coverage` | read |
| GET | `/spend/report` | read |
| GET | `/spend/rollup` | read |
| GET | `/spend/overruns` | read |
| GET | `/spend/delegations/{delegation_id}` | read |
| POST | `/spend/flag-overruns` | admin |
| GET | `/live/readiness` | read |
| GET | `/live/snapshot` | read |
| GET | `/live/events` | read |
| GET | `/live/tasks` | read |
| GET | `/live/stream` | read |

Một endpoint ghi duy nhất, và nó chỉ ghi event. `/live/events` được giữ lại cho
client không thể mở SSE — và cho test, vì test không chạy vòng lặp vô hạn được.

11 tool contract mới, tổng **192**: `company.spend.coverage`,
`company.spend.report`, `company.spend.rollup`, `company.spend.overruns`,
`company.spend.detail`, `company.spend.flag_overruns`,
`company.live.readiness`, `company.live.snapshot`, `company.live.events`,
`company.live.tasks`, `company.live.stream`.

---

## 4. Frontend

- `lib/api.ts`: `apiV35`.
- `components/SpendPushPanel.tsx`: bảng ngân sách vs chi phí, danh sách vượt
  trần, và một ô live dùng `EventSource` với cursor nối lại. Panel in thẳng cả
  hai trần năng lực ra màn hình thay vì chỉ hiện số.
- Nhúng vào `WorkspaceOpsConsole`. Nhãn shell đổi thành `AI Organization OS · v35`.

---

## 5. Kiểm thử

`backend/tests/test_v35_spend_push.py`: 82 test, nâng tổng lên khoảng 544.

Tất cả **chỉ được biên dịch, chưa bao giờ chạy** — sandbox không có mạng nên
không cài được `pytest`, `fastapi`, `sqlalchemy`, `alembic`.

## 6. Chưa chứng minh được

1. Chạy `alembic upgrade head` (`0013`, `0014`, `0015` chưa từng apply) rồi chạy
   toàn bộ test suite.
2. Mở `/api/v35/live/stream` bằng một trình duyệt thật qua proxy thật: kiểm tra
   frame tới liên tục, `X-Accel-Buffering: no` có tác dụng, và nối lại bằng
   cursor không mất event.
3. Tạo `usage_events` thật từ một run OpenClaw rồi đối chiếu `spend/report` với
   hoá đơn runner — để biết sai số của cách quy theo `task_id`.
4. Hai contract trên cùng một task, chồng thời gian: xác nhận phép tách bằng
   mốc thời gian sai đến mức nào.

## 7. Cố tình không làm

- **Không chặn dispatch khi vượt trần.** Chặn dựa trên một con số suy ra từ
  `task_id` sẽ dừng việc đúng vì một phép đo sai.
- **Không thêm cột `delegation_id` vào `usage_events`.** Đó là migration đúng
  đắn cho v36, nhưng nó phải đi kèm việc sửa đường ghi metering, không chỉ thêm
  cột rỗng.
- **Không làm WebSocket.** Cockpit chỉ cần một chiều; WebSocket thêm trạng thái
  kết nối, heartbeat hai phía và đường nâng cấp proxy mà chưa ai cần.
- **Không dùng Redis pub/sub để bỏ poll phía server.** Làm được, nhưng sẽ khiến
  kênh live phụ thuộc Redis, còn hiện tại Redis vẫn là tuỳ chọn và có thể rơi
  (v32 backoff).
