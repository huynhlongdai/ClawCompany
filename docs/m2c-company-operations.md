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

## D7. Lịch tuân thủ Việt Nam — migration `0042_compliance_calendar`

**Dữ liệu**: `company_profiles.compliance` (kỳ khai GTGT, kỳ khai khấu trừ TNCN, có người lao động, chức danh kế
toán), `compliance_rules` (một nghĩa vụ là **dữ liệu sửa được** cho từng công ty: loại hình áp dụng, điều kiện, tần
suất, cách tính hạn, **căn cứ pháp lý**, ghi chú, nhắc trước N ngày, bật/tắt, `needs_review`, hiệu lực), 
`compliance_deadlines` (hạn theo kỳ: hạn theo luật, hạn sau khi dời cuối tuần, người nhận, việc, đã nhắc, đã nộp;
UNIQUE luật × kỳ).

**Luật mặc định** (đối chiếu web ngày 16/10/2026, nguồn trong báo cáo):

| Nghĩa vụ | Hạn | Căn cứ |
|---|---|---|
| GTGT tháng / khấu trừ TNCN tháng | ngày 20 tháng sau | Điều 44 khoản 1a Luật QLT 38/2019 (tới 30/6/2026); từ 1/7/2026 Luật QLT 2025 + Điều 10 khoản 2 NĐ 252/2026/NĐ-CP |
| GTGT quý / khấu trừ TNCN quý | ngày cuối tháng đầu quý sau | Điều 10 khoản 3 NĐ 252/2026 (trước đó Điều 44 khoản 1b) |
| Quyết toán TNDN + BCTC; quyết toán TNCN (tổ chức trả thu nhập) | ngày cuối tháng thứ 3 sau năm | Điều 10 khoản 5a NĐ 252/2026 |
| Đóng BHXH, BHYT, BHTN tháng | ngày cuối tháng tiếp theo | khoản 4 Điều 34 Luật BHXH 41/2024/QH15 (từ 1/7/2025) |
| Hộ kinh doanh khai quý (01/CNKD) | ngày cuối tháng đầu quý sau | khoản 6 Điều 10 NQ 198/2025/QH15 (bỏ khoán từ 2026) — **cần kiểm tra** |
| Lệ phí môn bài | **đã bãi bỏ từ 1/1/2026** — luật để TẮT, không sinh hạn | khoản 7 Điều 10 NQ 198/2025/QH15; NĐ 362/2025/NĐ-CP; CV 645/CT-CS |
| Giấy phép / hạn riêng | ngày hết hạn người dùng nhập | người dùng ghi; trống → "cần kiểm tra" |

Hạn rơi thứ Bảy/Chủ nhật → thứ Hai (Điều 86 TT 80/2021/TT-BTC; khoản 5 Điều 148 BLDS 2015); **ngày lễ chưa tính**.

**Sinh + nhắc** (`compliance_calendar.generate/remind`, beat `compliance.tick` mỗi giờ): hạn 120 ngày tới (chỉ từ hôm
nay — công ty mới bật không bị báo "quá hạn" cho kỳ cũ); tới ngưỡng nhắc → một việc trong dự án "Tuân thủ" giao người
ngồi chức danh kế toán (chọn trong cài đặt; không có → chức danh có chữ "kế toán/thuế" → chủ doanh nghiệp), hạn 17:00,
+ Hộp việc (loại `compliance_due`) cho người đó và chủ doanh nghiệp; mỗi hạn nhắc một lần. Việc xong → hạn "đã nộp".
Gieo luật mặc định khi dựng công ty từ mẫu, hoặc nút "Tạo lịch mặc định".

**UI** không khẳng định chắc chắn pháp lý: dải cảnh báo "lịch tham khảo, không phải tư vấn pháp lý", mỗi luật hiện
căn cứ, luật chưa chắc gắn nhãn "Cần kiểm tra".

API: `GET /team/compliance`, `PUT /team/compliance/settings` (admin), `POST /team/compliance/seed`, `POST/PATCH/DELETE
/team/compliance/rules[/{id}]`, `POST /team/compliance/generate`, `POST /team/compliance/deadlines/{id}/done`.
