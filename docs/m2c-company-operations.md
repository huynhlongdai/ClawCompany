# M2c — Vận hành công ty: quy trình, KPI, nhịp vận hành, tuân thủ, sẵn sàng agent

Năm mục còn lại (D4–D8) của phần D trong `company-anatomy-and-agent-company.md`, anh duyệt 16/10/2026
("tiếp tục triển khai"). Nối tiếp M2b (`m2b-company-foundation.md`). Nguyên tắc như M2b: biên dịch vào
cơ chế đã có, không dựng động cơ thứ hai. API dưới `/api/team` (router `app/api/company_ops.py`).
UI: Đội ngũ → tab mới (`components/CompanyOperations.tsx`). Tiền: **chỉ USD**.

## D4. Bản đồ quy trình — migration `0039_process_map`

**Dữ liệu**: `processes` (công ty, nhóm APQC PCF 1–13, tên, mô tả, chức danh làm chủ, mẫu, trạng thái),
`process_steps` (thứ tự, tên, hướng dẫn, chức danh, SOP, thời lượng kỳ vọng phút, loại việc của ma trận
phân quyền + rủi ro), `process_instances` (lần chạy: tiêu đề, số tiền USD, dữ liệu vào, dự án, bắt đầu/kết
thúc, thời gian chu trình), `process_step_runs` (một bước của lần chạy = một task; tới lượt / bắt đầu /
xong, thời gian chu trình bước, người nhận, có cần duyệt, người duyệt, luật).

**Chạy** (`process_map.start`) — không có động cơ riêng:
- mỗi bước → `workspace_ops.create_task` trong dự án "Quy trình · <tên>", giao seat đang ngồi chức danh
  (ít việc mở nhất); chức danh trống → trưởng phòng của chức danh → chủ doanh nghiệp (ghi chú trên bước);
- bước sau chặn bởi bước trước bằng `task_dependencies` (D1.3) → `wake_unblocked` sẵn có đánh thức;
- bước có loại việc → `authority.decide` với số tiền của lần chạy; cần duyệt → task mang chặng `approval`
  của `execution_policy` (D2.2) với người duyệt theo luật → Hộp việc/duyệt đi đường cũ;
- bước 1 → "Cần làm" + wakeup `assigned`.

`task_lifecycle.transition` gọi `process_map.on_task_status`: Đang làm → `started_at`; Xong → `finished_at`,
chu trình bước = xong − tới lượt, mở bước sau ("Cần làm"); bước cuối xong → chu trình lần chạy. Huỷ một
bước → huỷ lần chạy và các bước còn chờ. Đang có lần chạy dở → không cho sửa các bước (409).

**Mẫu**: shop (Đơn hàng → giao hàng → hậu mãi; Hoàn tiền / đổi trả — bước "Hoàn tiền" có loại `refund`;
Đăng sản phẩm mới), agency (brief → sản xuất → báo cáo; chạy ads — `spend`), kế toán (khai thuế kỳ; lương
& BHXH). Bước gắn chức danh theo chữ trong tên chức danh; mỗi quy trình mẫu kèm một SOP. Gieo khi dựng
công ty từ mẫu và qua nút "Gieo mẫu".

API: `GET/POST /team/processes`, `PATCH/DELETE /team/processes/{id}`, `POST /team/processes/seed`,
`POST /team/processes/{id}/start {title, amount_usd, input}`, `GET /team/processes/{id}/instances`,
`GET /team/process-instances/{id}`, `POST /team/process-instances/{id}/cancel`.

Giới hạn tự khai: quy trình tuyến tính (chưa rẽ nhánh/song song); thời gian chu trình tính theo giờ đồng
hồ (không trừ ngoài giờ); chọn người theo số việc mở, không theo kỹ năng.

## D5. KPI chia tầng — migration `0040_kpi_cascade`

**Dữ liệu**: `kpi_definitions` (tầng `company | department | position | seat`, chủ thể của tầng, `parent_id`
nối tầng, `goal_id` → `executive_goals`, `objective_id` → `portfolio_objectives`, tên, đơn vị, mục tiêu, hướng
`up/down`, kỳ `week/month/quarter`, nguồn số `metric`, quy trình (cho chỉ số D4), trọng số, nguồn `custom |
position`), `kpi_measurements` (số nhập tay theo khoá kỳ `2026-10` / `2026-W42` / `2026-Q4`).

**Số thực tế** (`kpi_cascade.compute`, kỳ hiện tại theo giờ Việt Nam, phạm vi theo tầng: cả công ty / thành
viên của phòng / người ngồi chức danh / một seat): `tasks_done`, `cycle_time_minutes` (lần chạy D4 xong; tầng
người = bước của họ), `on_time_rate` (bước D4 xong trong thời lượng kỳ vọng), `process_runs_done`,
`cost_per_task_usd` (chi phí lượt chạy / việc xong), `first_pass_rate` (cùng cách đếm scorecard M6),
`approvals_pending`, `approval_turnaround_hours`; `manual` = người nhập. Có số nhập tay cho kỳ → thắng số tự tính.

**Tiến độ** = thực tế/mục tiêu (hướng down: mục tiêu/thực tế), chặn 0–150 %; ≥90 đúng hướng, ≥60 cần chú ý,
dưới 60 chậm. **Cuộn lên**: mỗi nút có `rollup` = trung bình có trọng số tiến độ các con.

**Từ chức danh (M2b)**: `POST /team/kpis/sync-positions` — mỗi KPI trong `positions.kpis` → KPI tầng chức danh
(nguồn số đoán theo tên: "chu trình" → cycle time, "chi phí" → cost per task…, còn lại nhập tay; cha = KPI phòng
cùng nguồn số nếu có) + một KPI tầng seat cho mỗi người đang ngồi. Chạy lại không nhân đôi.

**Agent**: `career.scorecard` có `kpis` + `kpi_attainment` (KPI seat); `recommend` thêm điều kiện "KPI của seat
đạt ≥ 90 %" khi seat có KPI có số (không có KPI → luật cũ). UI: thẻ Sự nghiệp trong hồ sơ agent hiện KPI seat.

API: `GET/POST /team/kpis`, `PATCH/DELETE /team/kpis/{id}`, `POST /team/kpis/{id}/measurements {value, note,
period_key?}`, `POST /team/kpis/sync-positions`.

Giới hạn tự khai: "việc xong trong kỳ" dùng `tasks.updated_at` làm mốc xong (chưa có cột `done_at`); KPI tính
khi đọc (chưa lưu lịch sử số tự tính theo kỳ); AGENTS.md vẫn chỉ ghi mục tiêu KPI của chức danh (D2), số thực tế
nằm ở scorecard.

## D6. Nhịp vận hành — migration `0041_operating_rhythm`

**Dữ liệu**: `rhythm_configs` (một hàng / công ty: giao ban sáng bật + giờ, báo cáo tuần bật + thứ + giờ, múi giờ,
gửi riêng từng phòng, để agent trưởng phòng viết), `rhythm_reports` (bản đã gửi: phạm vi `c<id>`/`d<id>`, loại
`standup|weekly`, kỳ `2026-10-16`/`2026-W42`, nội dung, bản xác định, số liệu JSON, người viết, ghi chú, người nhận;
UNIQUE công ty × phạm vi × loại × kỳ).

**Số liệu** (`operating_rhythm.collect`, 24 giờ / 7 ngày): việc xong (tên 5 việc), đang làm/chờ duyệt, bị chặn,
trễ hạn, việc mới; quy trình D4 (lần chạy xong, đang chạy, chu trình TB, bước trễ so với thời lượng kỳ vọng); KPI
D5 chậm/cần chú ý của phạm vi; phê duyệt đang chờ (lâu nhất bao nhiêu giờ); chi phí lượt chạy (USD); lượt chạy lỗi.
`summarize` → bản tóm tắt **xác định** (không cần model).

**Người viết**: bật `agent_author` và trưởng phòng (cấp công ty: trưởng Ban điều hành) là seat agent còn hoạt động +
gateway thật → agent viết lại từ đúng số liệu (prompt cấm bịa số, phiên `agent:<rid>:rhythm-<phạm vi>-<loại>-<kỳ>`,
75 s, các phạm vi chạy song song); lỗi/không gateway/trưởng phòng là người → bản xác định, ghi lý do. Bản xác định
luôn lưu kèm (`fallback`).

**Gửi**: một `inbox_items` (loại `standup` / `weekly_report`, nhóm `rhythm:<id>`, thân = toàn văn) cho người phụ
trách là người: phòng → trưởng phòng (agent → người quản lý gần nhất là người, `inbox.human_recipients`); công ty →
chủ doanh nghiệp. **Lịch**: Celery beat `rhythm.tick` 300 s, gửi trong 2 giờ kể từ giờ hẹn theo múi giờ công ty
(khởi động muộn không gửi bù lúc nửa đêm). Công ty dựng từ mẫu được bật sẵn; công ty khác bật ở tab Giao ban.
(`operating_cycles` gắn với mục tiêu nên không dùng lại được cho giao ban; dùng chung beat + Hộp việc.)

API: `GET /team/rhythm`, `PUT /team/rhythm/config`, `POST /team/rhythm/run {kind, department_id? | all_departments}`,
`GET /team/rhythm/reports/{id}`.
