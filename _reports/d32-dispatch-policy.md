# D3.2 — Chọn seat theo tải

`backend/app/services/dispatch_policy.py`

- `choose(Need, [SeatState]) -> Decision` — **thuần**. Lọc theo thứ tự: phòng ban → kỹ năng (đủ tất cả, không phân biệt hoa thường; seat chưa đọc được kỹ năng bị loại khi việc có yêu cầu kỹ năng) → `members.status` + `agents.lifecycle` = active → số run mở (`task_runs` queued/dispatched/running) < `DISPATCH_MAX_OPEN_RUNS` (mặc định 2) → hạn mức còn lại (min các phong bì áp dụng; phong bì exhausted chặn luôn) ≥ số giữ chỗ của seat (`budget_scope.estimate`).
- Xếp hạng: ít run mở nhất → nhiều hạn mức còn lại nhất (không phong bì = vô hạn) → id nhỏ nhất.
- Không ai đủ điều kiện → `member_id=None`, `stage` = lớp loại hết, `reason` nêu tên từng seat và lý do; `rejected` giữ lý do loại sớm nhất cho mỗi seat. Không bao giờ chọn bừa.
- Phần đọc/ghi: `snapshot()` dựng trạng thái từ ORM; `seat_skills()` đọc kỹ năng hiệu dụng từ cấu hình gateway (`ConfigRegistry.agent_entry`); `decide()`; `record()` ghi `company_events` loại `task.dispatch_decided` (người quản lý đọc được "vì sao giao seat đó").

## Kiểm chứng
- `tests/test_d32_dispatch_policy.py`: 17 test — 6 tình huống thuần (ít tải thắng, phòng ban, kỹ năng, không active, đầy việc + thiếu hạn mức + hoà theo hạn mức, "không ai đủ điều kiện" ở cả 6 lớp), thứ tự lọc, và 5 test ORM thật (đếm run mở từ `task_runs`, đọc phong bì, định tuyến trong phòng theo tải + ghi event, phòng paused/exhausted → không ai, kỹ năng từ gateway).
- `tools/mutate_d32.py`: 10/10 đột biến bị bắt.
