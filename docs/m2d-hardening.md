# M2d — Gia cố M2c: quy trình v2, lịch sử KPI, lịch tuân thủ có ngày lễ, smoke A2A/deploy

Nối tiếp `m2c-company-operations.md`. Anh duyệt 16/10/2026 ("tiếp tục"). Nguyên tắc như M2b/M2c: biên dịch vào
cơ chế đã có, không dựng động cơ thứ hai; tiền **chỉ USD**; mọi chuỗi UI qua i18n (vi + en).

## 1. Quy trình v2 — rẽ nhánh + song song (migration `0044_process_branching`)

**Dữ liệu**: `process_steps` và `process_step_runs` thêm `depends_on` (JSON — seq các bước đứng trước), `condition`
(JSON `{field, op, value}`), `branch` (nhãn nhánh); step run thêm `outcome` (kết quả bước) và `skip_reason`.
Migration chuyển quy trình tuyến tính cũ: bước seq>1 phụ thuộc seq-1. Hàng `depends_on = NULL` vẫn đọc là tuyến tính.

**Đồ thị**: `depends_on` rỗng = chạy ngay khi bắt đầu; nhiều bước cùng phụ thuộc một bước = **song song (fan-out)**;
một bước phụ thuộc nhiều bước = **gộp nhánh (fan-in)**. Chỉ được trỏ về bước đứng trước → không có vòng.
API vắng `depends_on` → nối tiếp bước trước (client cũ không đổi hành vi). Mỗi cạnh = một `task_dependencies`.

**Điều kiện**: `field` = `amount_usd` | `input.<khoá>` (dữ liệu vào của lần chạy) | `step<N>.outcome` (kết quả bước
đứng trước, ghi qua `POST /team/process-step-runs/{id}/outcome`); `op` = `== != > >= < <= empty not_empty`. So sánh
chữ không phân biệt hoa thường; số so như số. Trường không có giá trị → chỉ `empty` đúng.

**Chạy** (`process_map._settle`): một bước chờ được xét khi MỌI bước trước đã xong/bỏ qua — mọi bước trước bị bỏ
qua → bỏ qua (nhánh chết lan xuống); điều kiện sai → bỏ qua; đúng → "Cần làm". Bước gộp chạy khi ít nhất một nhánh
trước đã xong. Bước bị bỏ qua → task "Huỷ" có lý do (task_dependencies coi huỷ là đóng). Lần chạy xong khi không
còn bước chờ/đang làm. Bước gốc được đánh thức lúc bắt đầu; bước sau do `wake_unblocked` sẵn có.

**Thời gian chu trình theo nhánh**: `stats.branches` (mỗi nhãn: số lần nhánh chạy trọn, TB từ lúc bước đầu nhánh tới
lượt tới lúc bước cuối nhánh xong) + `stats.paths` (lần chạy xong đi qua tập nhánh nào → chu trình TB, "—" = đường
chính). Thời lượng kỳ vọng của quy trình = **đường găng** (bước song song không cộng dồn).

**UI** (tab Quy trình): mỗi bước có "Chạy sau" (chip B1…), nhãn nhánh, điều kiện (trường / phép / giá trị); đổi
chỗ/xoá bước tự đánh số lại tham chiếu. Thẻ quy trình hiện "sau B1, B2", "chỉ khi Số tiền ≥ $50", nhánh; dòng thời
gian theo đường đi/nhánh. Lần chạy hiện bước "Bỏ qua" + lý do, ô "Ghi kết quả" cho bước đang tới lượt.

Giới hạn tự khai: kết quả bước do người ghi qua UI/API (agent chưa có tool MCP để ghi `outcome`; bước sau xét
lúc tới lượt nên phải ghi trước khi chuyển Xong); điều kiện một vế (chưa AND/OR); chu trình vẫn tính giờ đồng hồ.

## 2. Lịch sử KPI (migration `0045_kpi_history`)

**Mốc "xong"**: `tasks.completed_at` — listener ORM trên `Task.status` ghi lúc chuyển sang `done` (mọi đường đổi trạng
thái qua ORM, kể cả không qua `task_lifecycle`), mở lại thì xoá. Backfill: lần cuối có sự kiện `task.done` trong
`company_events.occurred_at`; không có → `updated_at`. KPI `tasks_done`, `cost_per_task_usd`, `first_pass_rate` và giao
ban D6 đếm theo `coalesce(completed_at, updated_at)` (sửa việc đã xong không còn dời nó sang kỳ khác).

**Snapshot**: `kpi_snapshots` (một hàng / KPI × kỳ, UNIQUE): giá trị, nguồn (auto/manual), mục tiêu, tiến độ, sức khoẻ,
`trigger` (beat | manual | close | backfill), `final`. `kpi_cascade.snapshot_company`: (1) kỳ trước đang có số "chạy" →
tính lại tại cuối kỳ đó, đóng băng (`close`); (2) tuỳ chọn `backfill` ≤ 12 kỳ cũ chưa có số → tính lại từ dữ liệu hiện
có, bỏ qua chỉ số tại một thời điểm (`approvals_pending` — không dựng lại được quá khứ) và KPI nhập tay của kỳ trước khi
KPI tồn tại; (3) upsert kỳ hiện tại. Beat `kpi.snapshot` mỗi giờ; `POST /team/kpis/snapshot {company_id, backfill}`
(manager). `GET /team/kpis` trả `history` (≤ 8 kỳ gần nhất cùng loại kỳ) mỗi KPI.

**UI**: cột "Xu hướng" — sparkline SVG theo kỳ, màu theo sức khoẻ kỳ cuối, tooltip từng kỳ (đánh dấu kỳ đang chạy);
nút "Chụp số ngay" (lưu kỳ này + tính lại 5 kỳ trước).

Giới hạn tự khai: số backfill là "tính lại hôm nay cho kỳ cũ" — việc bị xoá/sửa từ đó tới nay làm lệch; không có
snapshot theo ngày (chỉ theo kỳ của KPI).

## 3. Lịch tuân thủ: hạn theo lịch + hạn pháp lý, ngày lễ là dữ liệu (migration `0046_holiday_legal_due`)

**Đổi nghiệp vụ theo anh (16/10/2026, "agent mà nghỉ lễ gì")**: agent làm mọi ngày — không có ngày nghỉ ở giao việc,
giao ban, nhắc hạn. Ngày lễ CHỈ là dữ liệu để tính **hạn pháp lý**.

- `compliance_deadlines.due_date` = **hạn nội bộ = đúng ngày luật ghi** (không dời). Nhắc trước N ngày, tiêu đề việc,
  `tasks.due_at` (17:00 giờ VN) đều theo ngày này → agent nộp sớm. Áp dụng luôn cho việc dời cuối tuần của D7 (trước
  đây `due_date` là ngày đã dời).
- `legal_due_date` (mới) = ngày làm việc liền kề sau nếu hạn rơi vào thứ Bảy/CN/lễ/Tết — trường phụ "hạn pháp lý" kèm lý do.
  Căn cứ: Điều 3 (giải thích từ ngữ) **Nghị định 252/2026/NĐ-CP** (hướng dẫn Luật Quản lý thuế 108/2025/QH15, từ 1/7/2026): "Trường
  hợp ngày cuối cùng của thời hạn … trùng với ngày nghỉ theo quy định thì ngày cuối cùng của thời hạn được tính là ngày
  làm việc liền kề sau ngày nghỉ đó"; trước 1/7/2026: Điều 86 Thông tư 80/2021/TT-BTC + khoản 5 Điều 148 BLDS 2015.
- Migration chuyển dữ liệu D7: `legal_due_date` ← `due_date` cũ (đã dời), `due_date` ← `statutory_date`.

**Lịch nghỉ** `public_holidays` (tổ chức × ngày, UNIQUE): tên, loại `holiday | makeup_workday` (thứ Bảy làm bù là ngày làm
việc), trạng thái `official | needs_confirmation`, nguồn. Lần đầu đọc một năm → gieo mặc định (lịch khu vực hành chính —
cơ quan thuế theo lịch này): 2026 theo TB 9441/TB-BNV (Tết 16–20/2; Quốc khánh 31/8 hoán đổi + 1–2/9, làm bù 22/8), CV
3383/BNV-CVL (nghỉ bù Giỗ Tổ 27/4; 30/4, 1/5), CV 10065/VPCP-KGVX (Ngày Văn hóa Việt Nam 24/11/2026); 2027 theo TB
11483/TB-BNV (Tết 4–10/2 gồm 2 ngày nghỉ bù; Quốc khánh 2–3/9). **Cần xác nhận**: Giỗ Tổ 2027 (16/4, tính âm lịch), nghỉ
bù 1/5/2027 (3/5), Ngày Văn hóa 24/11/2027. Sửa lịch → tính lại hạn pháp lý các hạn chưa nộp (hạn nội bộ không đổi).

API: `GET /team/compliance/holidays?year=` (member), `POST/PATCH/DELETE /team/compliance/holidays[/{id}]` (admin; trả
`legal_due_updated`). `GET /team/compliance` thêm `legal_due_date`, `legal_shift_reason`, `legal_overdue`, `holidays`
(năm nay + năm sau). UI tab Tuân thủ: ngày đậm = hạn theo lịch, dòng phụ "hạn pháp lý … — vẫn làm theo hạn trên"; thẻ
"Lịch nghỉ lễ (chỉ để tính hạn pháp lý)" theo năm, nhãn Làm bù / Cần xác nhận, nút Xác nhận / thêm / xoá.

Giới hạn tự khai: lịch nghỉ là của khu vực hành chính (doanh nghiệp có thể nghỉ Tết khác — không ảnh hưởng hạn thuế);
năm ngoài 2026/2027 không có mặc định (nhập tay); BHXH dùng cùng quy tắc ngày nghỉ (luật BHXH không nói riêng — cần kiểm tra).
