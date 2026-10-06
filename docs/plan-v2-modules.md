<callout icon="🧭" color="blue_bg">
<b>v2.1 — triển khai từng module, chạy ổn định thật rồi mới sang module sau.</b> Thứ tự: Nền → Lõi OpenClaw → Công ty → Agent → Hoạt động → Đào tạo agent → Giao tiếp → Tổng quan. Một module chỉ được gọi là "ổn định" khi đã qua gate chạy trên box và gateway OpenClaw thật, không phải chạy mock. Số liệu đo từ code nhánh <code>impl-plan</code>.
<b>Đã chốt:</b> logo càng cua nắm 3 chấm, mascot <b>Bé Càng</b> (ốc mượn hồn mang vỏ toà nhà), font Be Vietnam Pro, bảng màu Càng / Mực / Kem, ẩn 27 trang ít dùng.
</callout>

## 1. Chẩn đoán

| Chỉ số | Hiện tại | Mục tiêu |
| --- | --- | --- |
| Trang trong <code>/app</code> | 57 | ≤ 15 trang lõi |
| Mục menu | 60 (nhóm "Hệ thống" có 41 mục) | 8 mục + ⌘K |
| Endpoint API | 570, rải trên \~30 tiền tố <code>/api/v9…v36</code> | gom theo module, ≤ 150 |
| Service backend | 114 | \~40 cho 7 module |
| Khung giao diện | 11 bản AppShell, 7 họ class CSS v8–v14 | 1 shell + <code>design/brand/tokens.css</code> |
| Ngôn ngữ | 48/91 component còn chuỗi tiếng Anh | 100% tiếng Việt |
| Lần đầu vào app | Không có hướng dẫn, gặp ngay 60 mục menu | Wizard 4 bước |

<b>Lỗi thật tìm được</b> khi cho script tự bấm nút trên 32 trang:

1. Nút "Nối lại người theo dõi" gọi <code>POST /api/v21/runtime/resume</code> và nhận 500 <code>no running event loop</code>. Response 500 không có header CORS, nên trình duyệt báo thành lỗi CORS và mọi lỗi 500 đều trông như mất kết nối.
2. Trang Mục tiêu, nút "Plan" gọi <code>/api/tasks?goal_id=undefined</code> và nhận 422.
3. Nhiều trang trùng nhau: mục tiêu có 3 trang, tổng quan 3, tự động hoá 2, agent 2. Không có trang danh sách công việc riêng.
4. <b>Nghi vấn chính cho lỗi anh gặp:</b> box chưa chạy migration 0024–0027. App hiện không tự migrate.

## 2. Ẩn 27 trang có đủ để vận hành không?

<b>Đủ.</b> Kết quả kiểm từ code:

- 12 service lõi không import service nào trong 25 service của nhóm bị ẩn. 12 service đó là: <code>agent_dispatch</code>, <code>runtime_stream</code>, <code>task_lifecycle</code>, <code>wakeup</code>, <code>budget</code>, <code>inbox</code>, <code>routines</code>, <code>strategy</code>, <code>execution_policy</code>, <code>dispatch_policy</code>, <code>work_context</code>, <code>approval_bridge</code>. Chỉ có một chỗ gọi sang là <code>routines → workspace_ops</code>, mà <code>workspace_ops</code> thuộc module Công ty nên vẫn được giữ.
- <b>Chỉ ẩn trang thì chưa đủ.</b> Trong 15 job nền, có 6 job vẫn chạy cho các module bị ẩn: <code>devcloud.cleanup_expired</code>, <code>v14.reap_runner_leases</code>, <code>v14.evaluate_slos</code>, <code>v14.review_portfolios</code>, <code>v15.control_plane_tick</code>, <code>v15.export_telemetry</code>. Riêng <code>control_plane_tick</code> chạy SRE recovery, có đọc và ghi vào bảng <code>approvals</code>, nên có thể đẩy phê duyệt lạ vào Hộp việc. Vì vậy cờ "Phòng thí nghiệm" phải <b>tắt luôn 6 job này</b>.
- Có 2 cặp job trùng việc: <code>operations.scan_recurring</code> làm trùng <code>routines.tick</code>, và <code>operations.tick_cycles</code> / <code>events.tick_decision_loops</code> làm trùng phần Nina lập kế hoạch. Hai cặp này được gộp trong module Hoạt động.

## 3. Cách làm một module

1. <b>Kiểm kê từ code:</b> liệt kê endpoint, bảng, job nền, trang UI rồi viết spec 1 trang. Chỉ ghi những gì đã kiểm, không suy đoán.
2. <b>Gom API</b> về <code>/api/<module></code>. Route vN cũ giữ làm alias có header <code>Deprecation</code>.
3. <b>Test:</b> hành vi đúng, các tình huống lỗi (mất mạng, timeout, gateway khởi động lại, dữ liệu trùng) và mutation.
4. <b>UI của module</b> làm trên khung mới: tiếng Việt, mọi lỗi đều có câu giải thích kèm cách xử lý, Bé Càng xuất hiện ở trạng thái rỗng và trạng thái lỗi.
5. <b>Chạy thật</b> trên box với gateway OpenClaw thật: kịch bản e2e Playwright và chaos test (tắt gateway giữa chừng).
6. <b>Báo cáo</b> <code>_reports/<module>.md</code>, anh nghiệm thu. Sau đó module được đánh dấu "Ổn định" và API của nó bị khoá.

Một module được coi là <b>ổn định</b> khi: e2e chạy 3 lần liên tiếp đều xanh, 0 lỗi 500 và 0 lỗi console, và có hướng dẫn vận hành ngắn.

## 4. Các module theo thứ tự

<b>M0 · Nền & khung (1,5 tuần)</b>

- Tự chạy <code>alembic upgrade head</code> khi khởi động. <code>/health</code> báo <code>schema: ok/behind</code> và phiên bản OpenClaw.
- Lỗi 500 trả JSON có header CORS và mã lỗi. Thêm ErrorBoundary và toast tiếng Việt. Sửa 2 lỗi ở mục 1.
- Cờ "Phòng thí nghiệm" ẩn 27 trang và tắt 6 job nền ở mục 2.
- Shell mới với menu 8 mục, ⌘K, giao diện điện thoại, tokens và Bé Càng. Có CI và branch protection.
- <i>Gate:</i> deploy box mới, smoke e2e các trang lõi 0 lỗi. Anh đăng nhập và đi hết menu không gặp lỗi.

<b>M1 · Lõi OpenClaw (1,5 tuần)</b>

- <i>Hiện trạng:</i>
  - Phần kết nối gateway (<code>runtime/openclaw_native.py</code> và <code>openclaw_protocol.py</code>) khoảng 960 dòng. Thêm <code>runtime_stream.py</code> 558 dòng và <code>openclaw_config.py</code> 473 dòng.
  - App gọi 29 lệnh RPC của gateway. Em đã đối chiếu: cả 29 lệnh đều có trong OpenClaw 2026.9.8.
  - Có 3 chế độ: mock, native và <code>gateway</code>. Chế độ <code>gateway</code> là kiểu cũ, viết theo hợp đồng đoán chứ chưa kiểm chứng.
  - <b>Chưa từng chạy e2e trên gateway thật.</b>
- <i>Việc:</i>
  - Bỏ chế độ <code>gateway</code> kiểu cũ.
  - Trang "Kết nối OpenClaw" có doctor 1 nút, kiểm: phiên bản, xác thực, model, skill heartbeat.
  - Tự nối lại khi mất kết nối và resume lượt đang chạy; sửa luôn lỗi 500 ở mục 1.
  - Đổi lỗi runtime thành lý do tiếng Việt.
  - Đối soát chi phí với <code>usage.cost</code>.
- <i>Gate (gateway thật):</i> kết nối được, gửi và nhận stream, huỷ giữa chừng, duyệt lệnh exec. Khởi động lại gateway khi đang có lượt chạy thì hệ thống tự nối lại và task không mất. Chi phí khớp ±5%.

<b>M2 · Công ty & tổ chức (1 tuần)</b>. Làm trước Agent vì agent phải gắn vào phòng ban và có người quản lý.

- <i>Hiện trạng:</i> đã có <code>Company</code>, <code>Department</code>, <code>Member</code>, <code>workspace_ops</code>, <code>provisioning.provision_company</code>, mẫu công ty (<code>company_factory</code>) và định tuyến cho trưởng phòng.
- <i>Việc:</i> một trang "Đội ngũ" có sơ đồ tổ chức. Mời người, phân vai trò owner/manager/member. Chọn trưởng phòng. Có 3 mẫu công ty (shop, agency, kế toán) và cho nhập sơ đồ từ CSV.
- <i>Gate:</i> tạo công ty từ mẫu thì đủ phòng ban và sơ đồ đúng. Người được mời đăng nhập thấy đúng quyền của mình.

<b>M3 · Agent / Nhân sự AI (1,5 tuần)</b>

- <i>Hiện trạng:</i>
  - Mỗi agent gồm <b>3 nguồn phải khớp nhau</b>: hàng trong DB (<code>members</code> + <code>agents</code>), mục <code>agents.entries</code> trong <code>openclaw.json</code>, và 5 file workspace (IDENTITY, SOUL, AGENTS, USER, MEMORY). <code>seat_profile.py</code> gộp 3 nguồn này thành một hồ sơ.
  - Tạo agent qua <code>provision_agent</code> (gọi <code>agents.create</code>).
  - <code>openclaw_alignment</code> phát hiện khi các nguồn lệch nhau.
  - Đã có quyền tool 3 mức (<code>tool_permissions</code>) và <code>heartbeat_policy</code>.
- <i>Việc:</i>
  - Wizard tuyển agent: vai trò, phòng ban, model, ngân sách, tính cách.
  - Sửa hồ sơ thì ghi cả 2 chiều (DB và gateway).
  - Vòng đời agent: đang làm, tạm dừng, nghỉ việc.
  - Màn hình quyền tool.
  - Nút "Đồng bộ lại" khi các nguồn bị lệch.
- <i>Gate (gateway thật):</i> tạo agent trên UI thì agent có trong <code>agents.list</code> và đủ 5 file. Sửa SOUL trên UI thì file trên gateway đổi theo. Sửa tay trên gateway thì UI báo lệch. Cho agent nghỉ thì session được dọn sạch.

<b>M4 · Hoạt động (3 tuần, chia 3 gói)</b>

- <i>Hiện trạng:</i> phần backend D1–D3 đã xong (task lifecycle, checkout, wakeup, execution policy, chọn seat theo tải, định tuyến phòng ban, ngân sách, hộp việc, việc định kỳ, Nina lập plan). Có 936 test xanh, <b>nhưng mới chạy với mock</b>.
- <i>4a · Công việc & lượt chạy:</i> list, board và side-peek kiểu Linear. Có dòng thời gian lượt chạy kèm chi phí, review chéo.
- <i>4b · Hộp việc, phê duyệt, chi phí:</i> duyệt 1 chạm trên điện thoại, leo thang khi quá hạn, ngân sách 3 nấc.
- <i>4c · Mục tiêu & việc định kỳ:</i> gộp 3 trang mục tiêu thành 1 và 2 trang tự động hoá thành 1. Gộp các job trùng ở mục 2.
- <i>Gate (= G5 thật):</i> kịch bản "Ra mắt bộ sưu tập hè, \$20" chạy trên gateway thật: plan được duyệt → 3 phòng làm việc → review chéo → người chỉ bị ping 2 lần → chi phí khớp ±5%.

<b>M5 · Đào tạo agent (2,5 tuần)</b>

- <i>Hiện trạng (phần này còn thiếu nhiều nhất):</i>
  - Bảng <code>skills</code> mới chỉ có metadata (tên, version, scope), chưa lưu nội dung skill và chưa có lịch sử phiên bản.
  - Việc đẩy skill lên gateway (<code>skills.upload.*</code>, <code>skills.install</code>) mới chỉ dùng cho skill heartbeat.
  - Tri thức nằm rải 3 nơi: <code>knowledge_mesh</code>, <code>vector_search</code>, <code>org_memory</code>.
  - Đã có bảng <code>agent_daily_stats</code> nhưng chưa có phần chấm điểm.
- <i>Việc:</i>
  - <b>Skill Studio:</b> soạn nội dung skill, quản lý phiên bản, cài và gỡ cho từng agent.
  - <b>Bộ bài thử (eval):</b> input mẫu kèm tiêu chí, chạy rồi chấm điểm.
  - <b>Scorecard:</b> tỉ lệ qua review ngay lần đầu, số vòng sửa, chi phí trên mỗi việc.
  - <b>Kho tri thức:</b> gộp về 1 kho, phân quyền theo phòng.
  - <b>Bài học:</b> việc xong thì đề xuất bài học → duyệt → ghi vào <code>MEMORY.md</code> của agent.
- <i>Gate:</i> nâng skill của 1 agent từ v1 lên v2, chạy 5 bài thử, so scorecard trước và sau. Bài học đã duyệt xuất hiện trong <code>MEMORY.md</code> trên gateway. Phòng A không đọc được tài liệu của phòng B.

<b>M6 · Giao tiếp & kênh (1,5 tuần)</b>

- Phòng họp agent và chat với Nina.
- Telegram trước, Zalo OA sau: tạo việc từ tin nhắn và duyệt ngay trong chat.
- <i>Gate:</i> giao một việc qua Telegram, duyệt trong chat, kết quả trên app khớp.

<b>M7 · Tổng quan & báo cáo (1 tuần)</b>

- Trang Tổng quan "Hôm nay công ty làm gì". Nhật ký hoạt động. Báo cáo tuần và báo cáo chi phí.
- <i>Gate (= G6):</i> 1 công ty tự vận hành 1 tuần bằng việc định kỳ. Có báo cáo chi phí theo ngày và scorecard từng agent.

Tổng cộng khoảng 13–14 tuần. 27 trang bị ẩn chỉ được xét lại sau M7: giữ lại dưới dạng plugin hoặc xoá.

## 5. UI/UX

<b>Tham chiếu:</b>

- <b>Paperclip:</b> "điều hành công ty, không phải dùng tool", sơ đồ tổ chức cho agent, duyệt từ điện thoại.
- <b>Linear:</b> list nhanh, ⌘K, side-peek, ít màu.

<b>Menu 8 mục:</b>

```plain text
┌ ClawCompany ▾ (đổi công ty)      ⌘K
│ 📥 Hộp việc
│ 🏠 Tổng quan
│ ✅ Công việc           (list · board · dự án)
│ 🎯 Mục tiêu & Kế hoạch (Nina)
│ 👥 Đội ngũ             (sơ đồ · agent · người · đào tạo)
│ 🔁 Việc định kỳ
│ 💰 Chi phí
│ ⚙️ Cài đặt             (OpenClaw · kỹ năng · bí mật · thành viên · 🧪 Phòng thí nghiệm)
```

<b>Onboarding 4 bước:</b> đặt tên công ty → chọn mẫu → kết nối OpenClaw (chạy doctor) → giao việc đầu tiên cho Nina.

## 6. Thương hiệu (đã chốt)

- <b>Logo:</b> chữ C hình chiếc càng nắm 3 chấm (agent / người / việc). File nằm ở <code>design/brand/</code>: bản nền tối, nền sáng, đơn sắc, PNG 512/192/32.
- <b>Mascot Bé Càng:</b> ốc mượn hồn mang vỏ là toà nhà văn phòng. Cửa sổ sáng nghĩa là agent đang làm. Có 5 trạng thái: chào, làm việc, duyệt xong, lỗi, ngủ. Bản phác ở <code>design/mascot/</code>, sẽ vẽ lại dạng SVG trong M0.
- <b>Font:</b> Be Vietnam Pro cho giao diện, JetBrains Mono cho log.
- <b>Màu:</b> định nghĩa trong <code>design/brand/tokens.css</code>, có bản sáng và tối. Mọi màu chữ đều đạt tương phản ≥ 4,5:1.

| Màu | Mã | Dùng cho |
| --- | --- | --- |
| Càng | #FF5A4E | mascot, điểm nhấn (không dùng làm nền cho chữ) |
| Càng đậm | #D63A2F | nút chính, chữ trắng 4,7:1 |
| Mực | #1A1C2B | chữ chính, 15,9:1 |
| Kem | #FFF7F0 | nền |
| Rong | #0B7A6D | OK, agent đang làm, 4,9:1 |
| Đèn | #FFD36B / #8A5A00 | chờ duyệt |

## 7. Còn chờ anh duyệt

1. Thứ tự module M0 → M7, trong đó Công ty làm trước Agent.
2. Menu 8 mục.
3. Dừng series D cũ: D0.1 chuyển vào M0, D2.3 chuyển vào gate M4.
4. <b>Gateway thật cho các gate M1, M3, M4</b>: hoặc box chạy <code>OPENCLAW_MODE=native</code> có 1 API key model, hoặc em dựng gateway OpenClaw trong sandbox (cũng cần key; anh nhập qua ô bảo mật).
