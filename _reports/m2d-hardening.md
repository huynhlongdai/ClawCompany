# M2d — Gia cố M2c: báo cáo (16/10/2026)

Spec: `docs/m2d-hardening.md`. Năm gói làm theo thứ tự anh giao ("tiếp tục"), mỗi gói commit + deploy + kiểm chứng trên VM
(chỉ dữ liệu **Tiệm Gốm Mộc = company 3**; mọi script VM kiểm `company.name == "Tiệm Gốm Mộc"` trước khi ghi). Giữa chừng anh
đổi gói 3 ("agent mà nghỉ lễ gì") — đã làm theo bản đổi. Tiền: chỉ USD. Chuỗi UI mới: i18n vi + en (`tsc` bắt đủ khoá).

## 1. Quy trình v2 — rẽ nhánh + song song · migration `0044_process_branching` · commit `18920d3`

- `process_steps`/`process_step_runs` + `depends_on` (seq bước trước), `condition` `{field, op, value}`, `branch`; run + `outcome`,
  `skip_reason`. Migration chuyển quy trình tuyến tính cũ (seq>1 → `[seq-1]`); hàng NULL vẫn đọc là tuyến tính.
- Fan-out/fan-in = **`task_dependencies`** (mỗi cạnh một dòng). `_settle`: bước chờ được xét khi mọi bước trước xong/bỏ qua;
  mọi bước trước bị bỏ qua → bỏ qua (nhánh chết lan); điều kiện sai → bỏ qua (task Huỷ có lý do); gộp nhánh chạy khi ≥1 nhánh xong.
- Điều kiện: `amount_usd`, `input.<khoá>`, `step<N>.outcome` (ghi qua `POST /team/process-step-runs/{id}/outcome`).
- Chu trình theo nhánh (`stats.branches`) + theo đường đi (`stats.paths`); thời lượng kỳ vọng = đường găng.
- UI: "Chạy sau" (chip B1…), nhãn nhánh, điều kiện; đổi chỗ/xoá bước tự đánh số lại tham chiếu; lần chạy hiện "Bỏ qua" + lý do,
  ô "Ghi kết quả".
- **VM**: quy trình #4 "Hoàn tiền v2 (rẽ nhánh + song song)" (6 bước, kỳ vọng 145 phút = đường găng). Lần chạy #2 **$30** →
  B2 "Trưởng phòng duyệt" **bỏ qua** ("Điều kiện không thỏa: amount_usd >= 50", task #25 huỷ), B3 mở ngay; sau B3, **B4 kiểm kho
  và B5 báo khách cùng mở**; B6 chờ cả hai → xong, chu trình 0.5 phút. Lần chạy #3 **$80** → đi nhánh Duyệt, xong 2.1 phút.
  Thống kê: đường "Duyệt + Kho" 2.1 phút vs "Kho" 0.5 phút; nhánh Duyệt TB 0.4 phút. Admin chốt các bước thay người (quota
  CometAPI cạn). Playwright: `ui/m2d-process-branching.png`, `m2d-process-editor.png`, `m2d-process-branching-en.png`, 0 lỗi console.

## 2. Lịch sử KPI · migration `0045_kpi_history` · commits `f1eda18`, `d5c96dd`

- `tasks.completed_at`: listener ORM trên `Task.status` (mọi đường đổi trạng thái), mở lại thì xoá; backfill từ sự kiện
  `task.done` (`company_events.occurred_at`), không có → `updated_at`. KPI `tasks_done` / `cost_per_task_usd` / `first_pass_rate`
  và giao ban D6 đếm theo `coalesce(completed_at, updated_at)`.
- `kpi_snapshots` (KPI × kỳ, UNIQUE): beat `kpi.snapshot` mỗi giờ + `POST /team/kpis/snapshot {company_id, backfill ≤ 12}`;
  kỳ trước đóng băng tại cuối kỳ; backfill bỏ chỉ số tại một thời điểm (`approvals_pending`) và kỳ trước khi có công ty
  (lỗi tìm thấy trên VM: ghi số 0 cho tháng 5–9 khi công ty mới tạo 14/10 → sửa `d5c96dd`, đã xoá 15 hàng sai trên VM).
- UI: cột "Xu hướng" (sparkline theo kỳ, màu theo sức khoẻ, tooltip từng kỳ), nút "Chụp số ngay".
- **VM**: migration backfill `completed_at` cho 15/15 việc xong của công ty 3; snapshot 7 KPI kỳ hiện tại. Công ty mới có dữ liệu
  từ 14/10 nên mỗi KPI mới **1 kỳ** → UI hiện "1 kỳ — cần ≥ 2 kỳ" (`ui/m2d-kpi-trend.png`). Hình sparkline nhiều kỳ chụp bằng
  cách **sửa response trong trình duyệt** (không ghi DB): `ui/m2d-kpi-trend-mockdata.png` — chỉ để kiểm hiển thị.

## 3. Lịch tuân thủ: hạn theo lịch + hạn pháp lý · migration `0046_holiday_legal_due` · commits `b11c576`, `d7daba8`

Theo yêu cầu đổi của anh: agent làm mọi ngày; ngày lễ chỉ là dữ liệu tính hạn pháp lý.
- `due_date` = **hạn nội bộ = đúng ngày luật ghi** (nhắc trước N ngày, tiêu đề việc, `tasks.due_at` 17:00 VN đều theo ngày này)
  — áp dụng luôn cho việc dời cuối tuần cũ của D7. `legal_due_date` (mới) = ngày làm việc liền kề sau, hiển thị phụ kèm lý do.
- Căn cứ (đã tra web): Nghị định 252/2026/NĐ-CP, **Điều 3** (giải thích từ ngữ — "ngày cuối cùng của thời hạn … trùng với ngày
  nghỉ theo quy định thì … là ngày làm việc liền kề sau ngày nghỉ đó") — https://ketoananpha.vn/nghi-dinh-252-2026-nd-cp ,
  https://luatvietnam.vn/thue/nghi-dinh-252-2026-nd-cp-huong-dan-thi-hanh-luat-quan-ly-thue-chi-tiet-va-hieu-qua-439382-d1.html ;
  trước 1/7/2026: Điều 86 TT 80/2021/TT-BTC + khoản 5 Điều 148 BLDS 2015 —
  https://thuvienphapluat.vn/chinh-sach-phap-luat-moi/vn/ho-tro-phap-luat/tu-van-phap-luat/46053/han-nop-ho-so-khai-thue-han-nop-thue-trung-ngay-nghi-thi-xu-ly-the-nao .
  Số khoản trong Điều 3 các nguồn ghi khác nhau (khoản 7 / khoản 14) nên code chỉ ghi "Điều 3".
- `public_holidays` sửa được theo tổ chức × năm, gieo khi đọc lần đầu. **2026 (chính thức)**: TB 9441/TB-BNV (Tết 16–20/2; Quốc
  khánh 31/8 hoán đổi + 1–2/9; làm bù thứ Bảy 22/8) — https://cdn.thuvienphapluat.vn/phap-luat/2022-2/PH/151025/9441-TB-BNV.pdf ;
  CV 3383/BNV-CVL (nghỉ bù Giỗ Tổ 27/4; 30/4; 1/5); CV 10065/VPCP-KGVX (Ngày Văn hóa Việt Nam 24/11/2026). **2027**: TB 11483/TB-BNV
  (Tết 4–10/2 gồm 2 ngày nghỉ bù; Quốc khánh 2–3/9) — https://moha.gov.vn/tin-tuc/chinh-phu-chot-phuong-an-nghi-mot-so-dip-le-tet-nam-2026-va-nam-2027---id19707 .
  **Cần xác nhận**: Giỗ Tổ 2027 (16/4, tính âm lịch), nghỉ bù 1/5/2027 (3/5), Ngày Văn hóa 24/11/2027.
- API `GET/POST/PATCH/DELETE /team/compliance/holidays` (sửa = admin; tự tính lại hạn pháp lý). UI: thẻ "Lịch nghỉ lễ (chỉ để tính
  hạn pháp lý)" theo năm, nhãn Làm bù / Cần xác nhận; hạn hiện ngày theo lịch + dòng phụ "hạn pháp lý … — vẫn làm theo hạn trên".
- `test_m2c_compliance.py`: đổi 2 assertion **có chủ ý** (nghiệp vụ đổi, ghi lý do tại chỗ).
- **VM**: migration chuyển 9 hạn của công ty 3: GTGT Q3, TNCN Q3, BHXH 09/2026 → hạn **31/10/2026** (trước là 2/11), hạn pháp lý
  2/11 (cuối tuần); Q4 → 31/1/2027, pháp lý 1/2/2027. Lịch 2026: 14 ngày, 2027: 12 ngày (3 cần xác nhận). `ui/m2d-compliance.png`.

## 4. Smoke Playwright A2A + luồng deploy/install trên VM · commit `6604f8d`

Trang: Đội ngũ → Đào tạo → Agent ngoài (A2A), Kỹ năng, Dựng (build), `/app/marketplace`, `/app/company-factory`, `/app/deployments`.
Không bấm "Cài đặt"/"Dựng công ty" (sẽ tạo công ty mới ngoài company 3).
- **Lỗi tìm thấy + đã sửa**: "Gửi thử" tới agent ngoài #1 (seat CSKH công ty 3 tự gọi lại qua A2A) → API trả **502**, UI báo "Máy chủ
  gặp lỗi — thử lại sau ít giây", trong khi lý do thật là `-32003: budget: trần chi ngày của ghế: đã chi $1.12 / $1.00` (seat CSKH đã
  vượt trần $1/ngày). Sửa: lỗi từ agent bên kia → **424** + thông điệp "Agent bên kia không trả lời được … xử lý ở phía đó"; danh sách
  tải lại sau khi gửi lỗi (trước đó số lần gọi/lỗi gần nhất không hiện). Test mới trong `test_m6_a2a.py`.
- Sau sửa (VM): banner đúng, danh sách hiện "5 lần gọi · -32003 …"; 5 trang còn lại **0 lỗi console, 0 HTTP 5xx**. Exposure CSKH đang
  mở, card `…/api/a2a/agents/shop-a407-cskh/.well-known/agent-card.json`. Ảnh `ui/m2d-a2a.png`, `ui/m2d-smoke-*.png`.
- Ghi nhận chưa sửa: Kho mẫu (`/app/marketplace`) còn chuỗi tiếng Việt cứng + dính chữ "0 lượt càiMiễn phí" (thuộc nợ ~566 chuỗi Lab).

## 5. So sánh nhánh ui-v5 / ui-v6 (chỉ đọc) — `_reports/branches-ui-v5-v6.md`

Cả hai **đã là tổ tiên của ui-v2** (0 commit ui-v2 chưa có; ui-v2 đi trước 159 / 151 commit) → không có gì để port, không xung
đột. ui-v5 đầu `aabb93f` (Rudi, 23/9, theme Elera + WorkFlowBoard); ui-v6 đầu `a3dfc4f` ("Notion AI", 5/10, AppShell/⌘K/Hộp việc v6)
— shell v6 đã bị UI v2 thay. Còn `components/WorkFlowBoard.tsx`, `V17AppShell.tsx` không ai import (code chết). Không merge/push gì.

## Test

- Mới: `test_m2d_process_branching.py` 5, `test_m2d_kpi_history.py` 5, `test_m2d_holidays.py` 3, + 1 trong `test_m6_a2a.py` = **14**.
- Toàn bộ backend theo lát (`work/run_chunk.sh`, 87 file; `test_wp37_work_memory_rooms.py` chạy 3 nhóm test id):
  **1253 passed, 2 skipped, 0 failed** (trước M2d: 1239). `test_migration_chain` xanh (bắt được lỗi cột `occurred_at` của 0045).
- `tsc --noEmit` sạch; `next build` xanh (sandbox + VM build image).

## Deploy

VM ở `6604f8d` (code đủ 4 gói); migration Postgres `0043 → 0044 → 0045 → 0046`. Tunnel cũ không còn trả lời →
`tools/oc_compose.sh restart tunnel` → **https://peripheral-administrative-oak-weapon.trycloudflare.com** (HTTP 307 → đăng nhập).
Commit `d7daba8` (sửa trích dẫn + disclaimer) đã vào bản deploy. Commit báo cáo này chỉ thêm file `_reports/`.

## Còn mở / anh cần biết

- **Quota CometAPI cạn + seat CSKH vượt trần $1/ngày** → mọi lượt agent thật đang lỗi. Cần chạy lại sau khi nạp: (1) một lần chạy quy
  trình v2 để agent thật tự làm B1/B3 (thay vì admin chốt); (2) A2A "Gửi thử" có câu trả lời thật; (3) giao ban do agent viết
  (đang rơi bản tự động); (4) agent tự ghi `outcome` — **chưa có tool MCP** cho việc này, hiện người ghi qua UI/API.
- Dữ liệu demo mới trên VM (công ty 3): quy trình #4 + lần chạy #2 ($30) #3 ($80), task #24–#35 (admin chốt). Xoá ở tab Quy trình nếu không cần.
- Lịch nghỉ: xác nhận Giỗ Tổ 2027, nghỉ bù 1/5/2027, Ngày Văn hóa 2027 khi Bộ Nội vụ công bố (nút "Xác nhận" trong tab Tuân thủ).
- Lịch sử KPI ở công ty 3 mới 1 kỳ; đường xu hướng sẽ có từ tháng/tuần sau (beat chụp mỗi giờ, tự đóng băng kỳ cũ).
- Chưa push GitHub (theo yêu cầu, agent chính push).
