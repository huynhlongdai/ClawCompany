# M2c — Vận hành công ty: báo cáo (16/10/2026)

Spec: `docs/m2c-company-operations.md`. Năm mục D4–D8 của `docs/company-anatomy-and-agent-company.md` mục D, làm
theo thứ tự, mỗi mục một gói (migration + API + UI + test), deploy + kiểm chứng trên VM trước khi sang mục sau.
API dưới `/api/team` (router mới `app/api/company_ops.py`). UI: Đội ngũ → 5 tab mới (`components/CompanyOperations.tsx`).
i18n namespace `ops` (298 khoá, vi + en, `tsc` bắt đủ khoá) + `nav.*` + `inbox.kind_*`. Tiền: chỉ USD.

## Đã làm

| Mục | Migration | Backend | UI |
|---|---|---|---|
| D4 Bản đồ quy trình | `0039_process_map` | `services/process_map.py`: quy trình theo 13 nhóm APQC, chủ = chức danh, bước = chức danh + SOP + phút kỳ vọng + loại việc của ma trận. **Chạy = task thường** (`workspace_ops.create_task`) giao người ngồi chức danh, chặn nối tiếp bằng `task_dependencies`, bước có loại việc → `authority.decide` với số tiền lần chạy → chặng `approval` của `execution_policy`. `task_lifecycle.transition` → `on_task_status` ghi chu trình bước/lần chạy, mở bước sau. Mẫu shop/agency/kế toán (kèm SOP), gieo khi dựng từ mẫu | tab **Quy trình**: nhóm APQC, bước + chức danh + SOP + loại duyệt, Chạy (số tiền USD), lần chạy với người nhận / người duyệt theo luật / chu trình, form sửa bước |
| D5 KPI chia tầng | `0040_kpi_cascade` | `services/kpi_cascade.py`: công ty (nối `executive_goals`/`portfolio_objectives`) → phòng → chức danh → seat; 8 nguồn số tự tính (việc xong, chu trình D4, % bước đúng hạn, lần chạy xong, chi phí/việc USD, % qua review lần đầu, phê duyệt chờ, thời gian duyệt) + nhập tay theo kỳ (giờ VN); tiến độ + cuộn lên có trọng số; `sync-positions` biến KPI chức danh (M2b) thành KPI chức danh + seat; `career.scorecard` có `kpis` + `kpi_attainment`, `recommend` thêm điều kiện KPI ≥ 90 % khi có số | tab **KPI**: cây KPI, thanh tiến độ, nhập số, form; thẻ Sự nghiệp trong hồ sơ agent hiện KPI seat |
| D6 Nhịp vận hành | `0041_operating_rhythm` | `services/operating_rhythm.py`: giao ban sáng / báo cáo tuần cho công ty + từng phòng từ việc, quy trình, KPI, phê duyệt, chi phí, ngoại lệ; bản xác định luôn có; trưởng phòng là agent → agent viết qua gateway (song song), lỗi → bản xác định + lý do; gửi Hộp việc người phụ trách là người; UNIQUE theo kỳ; beat `rhythm.tick` 300 s theo giờ công ty | tab **Giao ban**: lịch, gửi ngay, bản đã gửi (agent / tự động, số liệu gốc); Hộp việc có nhãn loại mới |
| D7 Lịch tuân thủ VN | `0042_compliance_calendar` | `services/compliance_calendar.py`: luật = dữ liệu sửa được, mỗi luật ghi căn cứ; GTGT/TNCN tháng-quý, quyết toán TNDN+BCTC, quyết toán TNCN, BHXH, HKD (cần kiểm tra), môn bài (đã bãi bỏ — TẮT), giấy phép tự thêm; hạn theo hồ sơ (loại hình, kỳ, có lao động), dời cuối tuần; nhắc trước N ngày → task cho chức danh kế toán + Hộp việc; task xong → đã nộp; beat `compliance.tick` mỗi giờ | tab **Tuân thủ**: dải "lịch tham khảo, không phải tư vấn pháp lý", cài đặt kê khai, hạn 120 ngày, luật + căn cứ, nhãn "Cần kiểm tra", thêm giấy phép |
| D8 Sẵn sàng agent | `0043_agent_readiness` | `services/agent_readiness.py`: 5 câu hỏi + 21 kiểm tra tự động trên 9 lớp, mỗi mục có `fix_href`; điểm có trọng số + mức; lighthouse (tần suất, SOP, có người, đo được, rủi ro tiền, ROI); chạy khi tạo công ty (mọi đường qua `provisioning.seed_authority`; dựng từ mẫu chấm lại cuối) và khi bấm | tab **Sẵn sàng agent**: điểm, từng lớp + link sửa, lighthouse + bước tiếp theo, checklist, bảng hỏi |

Bảng `operating_cycles` gắn với mục tiêu (goal_id bắt buộc) nên D6 không dùng lại nó; dùng chung beat + Hộp việc. D4 không
dùng `workflows/workflow_runs` (động cơ v7 cũ không giao người/không chặn) — dùng động cơ task D1–D3 đang chạy thật.

## Kiểm tra pháp lý D7 (web, 16/10/2026)

- Môn bài **đã bãi bỏ từ 1/1/2026**: khoản 7 Điều 10 NQ 198/2025/QH15 — https://xaydungchinhsach.chinhphu.vn/nghi-quyet-198-2025-qh15-ve-mot-so-co-che-chinh-sach-dac-biet-phat-trien-kinh-te-tu-nhan-119250517191622422.htm ; NĐ 362/2025 + CV 645/CT-CS — https://vov2.vov.vn/phap-luat/tu-01012026-khong-phai-nop-le-phi-mon-bai-56938.vov2
- Hạn khai từ 1/7/2026: Điều 10 NĐ 252/2026/NĐ-CP (tháng ngày 20; quý ngày cuối tháng đầu quý sau; quyết toán ngày cuối tháng thứ 3) — https://hethongphapluat.com/nghi-dinh-252-2026-nd-cp-huong-dan-luat-quan-ly-thue/dieu-10 , https://luatvietnam.vn/tin-van-ban-moi/thoi-han-nop-ho-so-khai-thue-theo-nghi-dinh-252-2026-nd-cp-186-110077-article.html
- BHXH: khoản 4 Điều 34 Luật BHXH 41/2024/QH15 — ngày cuối tháng tiếp theo — https://baohiemxahoi.gov.vn/tintuc/Pages/linh-vuc-bao-hiem-xa-hoi.aspx?itemID=25059
- Chưa chắc / để cấu hình: hộ kinh doanh (ngưỡng 50 tỷ, khai tháng/quý) gắn `needs_review`; **ngày lễ không được tính** (chỉ dời thứ Bảy/CN); quyết toán TNCN của cá nhân tự quyết toán (tháng thứ 4) không đưa vào vì là nghĩa vụ cá nhân.

## Test

- Mới: `test_m2c_process_map.py` 5, `test_m2c_kpi_cascade.py` 4, `test_m2c_operating_rhythm.py` 4, `test_m2c_compliance.py` 4,
  `test_m2c_readiness.py` 3 = **20 test hành vi** (ORM thật trên SQLite, gateway giả; không grep, không sửa test cũ).
- Toàn bộ backend theo lát (`work/run_chunk.sh`, 84 file; `test_wp37_work_memory_rooms.py` vượt 112 s nên chạy theo hai nhóm
  test id): **1239 passed, 2 skipped, 0 failed** (trước M2c: 1219).
- `tsc --noEmit` sạch; `next build` xanh (69 trang) cả sandbox lẫn VM.

## Kiểm chứng trên VM (Tiệm Gốm Mộc = company 3; mỗi script kiểm `company.name == "Tiệm Gốm Mộc"` trước khi ghi)

Migration chạy trên Postgres thật: `0038 → 0039 → 0040 → 0041 → 0042 → 0043`.

1. **D4** (`work/vm_m2c_d4.py`): gieo mẫu shop → 3 quy trình (APQC 3/4/6), bước gắn đúng chức danh hiện có. Chạy "Hoàn tiền /
   đổi trả" $80 (đơn GM-2026-1016-07) → instance #1, task #19–#22: B1/B2/B4 → Nhân viên CSKH (agent), B3 → Trưởng kho;
   B2 `approval_required` người duyệt **Long theo luật #17** (≥$50). Agent CSKH **thật** nhận B1 (wakeup), đọc chính sách
   (KB#2), gọi `company_approval_request(refund, 80)`, tạo artifact, tự chuyển review. Admin chốt B1 (chu trình **7.9 phút**)
   → B2 mở; review → approval #19 (chặng D2.2) → duyệt → B2 xong (**3.1 phút**) → B3 → B4 → **lần chạy xong, chu trình 11.1 phút**.
2. **D5** (`vm_m2c_d5.py`, `fix5`): sync-positions tạo 4 KPI (2 chức danh CSKH + 2 seat); KPI công ty "Ca hoàn tiền xong" 1/4 →
   25 % (tự tính từ D4), phòng Bán hàng "Việc xong" 3/20 → 15 %, "Chu trình hoàn tiền TB" 3.7 phút ≤ 120 → 150 %; công ty
   cuộn từ tầng dưới **82.5 %**; seat CSAT nhập tay 4.7/4.6 → 102.2 %, phản hồi 92/95 → 96.8 %; tóm tắt 7 KPI, 3 đúng hướng, 2 chậm.
3. **D6** (`vm_m2c_d6.py`): bật lịch 8 h / thứ Sáu 17 h; "Gửi giao ban" → 5 bản (công ty + 4 phòng) **vào Hộp việc của Long**.
   3 bản **do agent viết qua gateway thật** (Giám đốc cửa hàng cho công ty + Ban điều hành, Trưởng phòng marketing), dẫn đúng số
   (11.1 phút, $1.14/6 lượt, 8 chờ duyệt lâu nhất 10.1 giờ, KPI 15 % / 25 %). 2 bản (Bán hàng, Kho) **rơi về bản tự động** vì
   gateway trả `403 pre-consume quota failed` của CometAPI — đúng đường dự phòng, lý do ghi trên bản.
4. **D7** (`vm_m2c_d7.py`): TNHH 1TV, GTGT/TNCN quý, có lao động → 9 hạn 120 ngày: GTGT Q3 & TNCN Q3 & BHXH 09/2026 hạn luật
   31/10 (thứ Bảy) → **2/11/2026**; BHXH 10, 11/2026; Q4 → 1/2/2027; môn bài TẮT không sinh hạn; HKD không áp dụng. Giấy phép
   ATTP (demo) 10/11/2026 nhắc trước 30 ngày → **task #23 + thẻ Hộp việc "Hạn tuân thủ"**. Giao "chủ doanh nghiệp (chưa có
   chức danh kế toán)" vì shop không có chức danh kế toán.
5. **D8** (`vm_m2c_d8.py`): điểm **93/100 "Sẵn sàng thí điểm"**; việc cần sửa: định biên 6/7, JD 1/6 chức danh, 2 câu hỏi (quy
   trình viết một phần, dữ liệu bảng tính) — mỗi mục link `/app/team?tab=…&company=3`; lighthouse "Đơn hàng → giao hàng → hậu
   mãi" 84/100.
6. **Playwright trên VM** (`work/m2c_shot.cjs`, `mcr.microsoft.com/playwright:v1.48.0-noble`): 5 tab + Hộp việc + Sẵn sàng (en):
   **0 lỗi console, 0 HTTP 5xx**. Ảnh: `_reports/ui/m2c-processes.png`, `m2c-kpi.png`, `m2c-rhythm.png`, `m2c-compliance.png`,
   `m2c-readiness.png`, `m2c-readiness-en.png`, `m2c-inbox.png`.

## Commit (ui-v2, author Hark AI)

`8653e9a` D4 · `724a8f2` D5 · `4767e72` D6 · `a5bfe81` D7 · `44d99a9` D8 · + commit báo cáo (ngày theo locale, report).

## Còn mở / anh cần biết

- **Quota CometAPI gần cạn**: lượt agent cuối trả `403 pre-consume quota failed … remaining quota $0.0018` (model
  `custom/gemini-3.8-flash`). Agent nào chạy sau đó sẽ lỗi cho tới khi anh nạp thêm. Giao ban vẫn gửi (bản tự động).
- Dữ liệu demo trên VM (công ty 3): lần chạy quy trình #1 (khách Hạnh $80, admin chốt các bước thay người), KPI demo 5–7 +
  số nhập tay CSAT/phản hồi, giấy phép ATTP 10/11/2026 (demo, task #23), lịch giao ban đã bật (sẽ tự gửi 8 h sáng mỗi ngày
  + 17 h thứ Sáu vào Hộp việc của Long). Xoá/sửa ở các tab tương ứng nếu không muốn.
- Tiệm Gốm Mộc chưa có chức danh kế toán → việc tuân thủ đang giao chủ doanh nghiệp; chọn chức danh ở tab Tuân thủ.
- Approval #17 (hoàn $80 từ M2b) và 8 phê duyệt khác vẫn chờ anh.
- Giới hạn tự khai: quy trình tuyến tính (không rẽ nhánh/song song); chu trình tính giờ đồng hồ; "việc xong trong kỳ" dùng
  `tasks.updated_at` (chưa có cột `done_at`); KPI tính khi đọc (chưa lưu lịch sử số tự tính); ngày lễ chưa tính trong lịch
  tuân thủ; lighthouse/điểm là luật cố định (không model).
- Chưa push GitHub (theo yêu cầu, agent chính push).
