# D1.2 — Đối chiếu hai nguồn chi phí

> **Kết luận: nguồn sự thật là `sessions.usage` của gateway OpenClaw; độ lệch của `usage_events` là 0,00% khi follower nghe đủ phiên (4/4 phiên, $0,267108 = $0,267108), 100% khi follower bám muộn hoặc trước D1.2.**
> D2.3 quyết toán ngân sách theo số gateway; `usage_events` dùng để gắn chi phí vào task/seat/khách hàng.

Môi trường: OpenClaw 2026.9.8 chạy thật (gateway, transcript, tính giá), model giả có kịch bản `scripted/approval-e2e`, đặt giá kiểu Sonnet (3 / 15 / 0,3 / 3,75 USD cho 1M token input / output / cacheRead / cacheWrite). Token do model giả ước lượng theo độ dài prompt thật (~4 ký tự/token) nên mỗi lượt khoảng 11k token.

## Trước D1.2
- `usage_events` chỉ có dòng `task_dispatch` (đơn giá 0) và dòng theo `usage_meter_rules` (đơn giá đặt tay). Không đường code nào ghi tiền model.
- `task_runs.cost_usd / tokens_in / tokens_out` luôn bằng 0.
- Đo trên 8 phiên cũ (task 12–19): gateway $0,0078 / 1.560 token, ClawCompany $0 → **lệch 100%**.

## Đã làm
- `services/cost_ledger.py` (một đường code):
  - `record_message_usage`: mỗi `session.message` của assistant có `message.usage` → một dòng `usage_events` loại `model_usage` (token, `cost.total`, model, `messageId`). Không ghi trùng theo `messageId`. Cộng luôn vào `task_runs` đang chạy.
  - `reconcile`: với từng task có phiên, so `usage_events` với `sessions.usage {key}` (chờ cache `fresh`), ra trạng thái `match` / `within_tolerance` (≤ 5%) / `drift`, số lượt model bị thiếu, và câu kết luận. Mỗi lần chạy ghi `company_events` `cost.reconciled`, có `reason` là câu kết luận.
- `runtime_stream.handle_event` gọi `record_message_usage`.
- `GET /api/tasks/cost-reconciliation?task_id=&limit=` (chỉ admin, lọc theo tổ chức).

## Số đo thật (gateway 2026.9.8)
| Phiên | Kịch bản | Gateway | usage_events | Lệch |
|---|---|---|---|---|
| task 20–22 | duyệt lệnh, follower nghe từ đầu | $0,066678 / 21.954 tok mỗi phiên | bằng nhau | 0,00% |
| task 23 | từ chối lệnh | $0,067074 / 21.998 tok | bằng nhau | 0,00% |
| task 24 | follower bám muộn 8 giây (`--late 8`) | $0,068649 / 2 lượt model | $0 / 0 lượt | 100% (thiếu 2 lượt) |
| task 12–19 | trước D1.2 | $0,0078 | $0 | 100% |

Tổng 13 phiên, đúng câu API trả về: *"Nguồn sự thật là gateway sessions.usage (gateway OpenClaw), độ lệch 22.25% so với usage_events (13 phiên). Lệch > 10%: chặn ngân sách theo số gateway, usage_events chỉ là số tham khảo."* Phần lệch đến hết từ các phiên không được nghe (task 12–19 và 24).

`task_runs` task 22 sau khi chạy: `cost_usd` 0,066678, `tokens_in` 21.886, `tokens_out` 68 (trước đây là 0).

**Gateway tự khớp:** `usage.cost` (30 ngày) = tổng `sessions.usage` = 239.124 token / $0,942036 (15 phiên). Tổng này gồm cả phiên không thuộc task (ví dụ `agent:dev:main`) → đối chiếu phải làm **theo từng phiên**, không theo tổng tổ chức.

## Vì sao chọn gateway
1. Gateway tính từ transcript nên không phụ thuộc việc ClawCompany có đang nghe hay không. Task 24 cho thấy follower bám muộn là mất trắng phần chi phí.
2. **Gateway giữ giá đã ghi:** đổi giá input 3 → 6 thì phiên task 20 (đã có `cost` lúc chạy) vẫn $0,066678. Riêng tin nhắn ghi lúc giá bằng 0 (task 16) thì gateway **tính lại theo giá hiện tại**: $0,0012 → $0,0018. Nghĩa là số của gateway cho phiên cũ có thể đổi khi bảng giá đổi, còn `usage_events` thì không. Cần biết điều này khi đối chiếu kỳ cũ.
3. Gateway có `missingCostEntries` để báo lượt chưa có giá; `usage_events` không có cách biết.

## Kiểm thử
- `tests/test_d12_cost_ledger.py`: 6 test, chạy trên `fixtures/d12_cost_frames.json` (frame `session.message` thật và kết quả `sessions.usage` thật của task 20).
- Mutation:
  - bỏ hook trong stream → 4 test fail
  - bỏ chống trùng → 1 fail
  - bỏ cộng vào `task_runs` → 1 fail
  - bỏ lọc tổ chức → 1 fail
- Bằng chứng trong `evidence/d12/`: frame log, JSON đối chiếu, so `usage.cost` với `sessions.usage`, log e2e.

## Giới hạn và việc cho gói sau
- Follower bám muộn thì mất cả tiền lẫn **quyền duyệt lệnh**: gateway từ chối exec ngay (`Headless runs cannot wait…`) vì lúc đó không có client duyệt nào kết nối. Task cũng kẹt `in_progress` vì đã lỡ frame `final`. Hướng sửa: theo dõi phiên trước khi gửi `chat.send`, hoặc khi gắn vào phiên thì đọc lại `chat.history`. Ghi vào D2.1.
- D2.3: giữ chỗ theo ước lượng, quyết toán theo `sessions.usage` khi run kết thúc. Lệch quá 5% thì ghi một dòng điều chỉnh vào `usage_events` để hai nguồn khớp.
- Model giả: số token là ước lượng theo độ dài, không phải tokenizer thật. Cơ chế giá và cộng dồn là của gateway thật.
