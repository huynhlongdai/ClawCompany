<callout icon="🧭" color="blue_bg">
Thay kế hoạch D0–D4 bằng kế hoạch <b>theo module</b>: làm cho <b>lõi chạy ổn trên box</b> trước, sau đó tới các module quan trọng, phần còn lại ẩn đi và đóng băng. Số liệu dưới đây đo từ code nhánh <code>impl-plan</code> (a6d4512) và audit Playwright trên app local. <b>Cần anh duyệt 5 quyết định ở mục 7</b> rồi em mới tạo DB gói việc v2.
</callout>

## 1. Chẩn đoán

| Chỉ số | Hiện tại | Mục tiêu v2 |
| --- | --- | --- |
| Trang trong <code>/app</code> | 57 | ≤ 15 trang lõi, còn lại ẩn |
| Mục menu | 60 (riêng nhóm "Hệ thống" 41 mục) | 8 mục + ⌘K |
| Endpoint API | 570, rải trên ~30 tiền tố <code>/api/v9</code>…<code>/api/v36</code> | API lõi theo domain, ≤ 150 |
| Service backend | 115 | ~25 cho lõi |
| Khung giao diện | 11 bản AppShell (V8…V17), 7 họ class CSS (v8 dùng 468 lần, v9 104, v14 65…) trong 3 file CSS | 1 shell, 1 bộ token, ~20 component |
| Ngôn ngữ | 48/91 component còn chuỗi tiếng Anh ("Operating cycles", "Tick / reconcile"…) | 100% tiếng Việt, có bảng thuật ngữ |
| Lần đầu vào app | Không có onboarding, gặp ngay 60 mục menu | Wizard 4 bước |

### Lỗi thật tìm được (bấm nút tự động trên 32 trang)

1. <b>Phiên đang chạy → "Nối lại người theo dõi"</b>: <code>POST /api/v21/runtime/resume</code> trả 500 <code>RuntimeError: no running event loop</code> (<code>runtime_stream.follow</code> gọi asyncio trong endpoint sync). Response 500 không mang header CORS nên trình duyệt báo <b>lỗi CORS</b>. Hậu quả: mọi lỗi 500 trên app đều trông như "mất kết nối".
2. <b>Mục tiêu → "Plan"</b>: gọi <code>GET /api/tasks?goal_id=undefined</code> và nhận 422, do <code>GoalsConsole</code> gửi request khi chưa chọn mục tiêu.
3. <b>Trùng lặp và lạc đường</b>: không có <code>/app/tasks</code> hay <code>/app/org</code>. Công việc nằm rải ở <code>/app/flow</code> và <code>/app/os?tab=projects</code>. Mục tiêu có 3 trang (Mục tiêu / Kế hoạch mục tiêu / Nina lập kế hoạch), tổng quan có 3 (Tổng quan / Trung tâm điều hành / Buồng lái founder), tự động hoá có 2 (Tự động hoá / Việc định kỳ), agent có 2 (Nhân sự AI / Lực lượng AI).
4. <b>Nghi vấn chính cho lỗi anh gặp trên box</b>: box chưa chạy migration 0024–0027 (inbox, routines, <code>approvals.payload</code>). Khi đó trang mới gọi tới bảng hoặc cột chưa có → 500 → hiện ra thành lỗi CORS. Hiện app không tự migrate, <code>/health</code> cũng không báo lệch schema.

Trên DB seed mới, cả 63 route đều tải trang không lỗi. Vậy lỗi nằm ở <b>thao tác và triển khai</b>, không phải ở bước render.

## 2. Nguyên tắc v2

1. <b>Điều hành công ty, không phải dùng tool.</b> Mỗi khái niệm chỉ có 1 trang, 1 đường API, 1 service.
2. <b>Lõi chạy ổn trên box thật trước khi thêm tính năng.</b> Gate của mỗi module gồm: e2e Playwright theo luồng người dùng chạy trên box, pytest, mutation, và 0 lỗi console / HTTP ≥ 500.
3. <b>Không xoá code ngoài lõi.</b> Chỉ ẩn sau cờ <code>features.lab</code> ("Phòng thí nghiệm") và đóng băng (không sửa, không viết test mới) cho tới khi có nhu cầu thật.
4. <b>API theo domain</b> (<code>/api/tasks</code>, <code>/api/org</code>, <code>/api/runtime</code>…), không mở thêm vN. Route vN cũ thành alias có header <code>Deprecation</code> và bị xoá khi UI không còn gọi.
5. <b>Tiếng Việt 100%</b> theo một bảng thuật ngữ: seat → vị trí, run → lượt chạy, approval → phê duyệt, routine → việc định kỳ.

## 3. Bản đồ module

| Tầng | Module | Gộp từ (trang / khái niệm hiện có) | Việc chính |
| --- | --- | --- | --- |
| 0 · Nền | <b>M0 Ổn định & triển khai</b> | migrations, /health, xử lý lỗi, CI | Tự chạy <code>alembic upgrade head</code> khi boot. <code>/health</code> báo <code>schema: ok/behind</code>. Lỗi 500 trả JSON có CORS và mã lỗi. ErrorBoundary + toast tiếng Việt. Sửa 2 lỗi ở mục 1. Smoke e2e trong CI. |
| 0 · Nền | <b>M1 Danh tính & quyền</b> | đăng nhập, thành viên, vai trò, API key, bí mật | Mời thành viên, vai trò owner/manager/member, đổi mật khẩu, thu hồi key. |
| 1 · Lõi | <b>M2 Công ty & Đội ngũ</b> | os?tab=companies/people/agents, agents, routing, workspace-ops, company-factory | Một trang "Đội ngũ": sơ đồ tổ chức, phòng ban, vị trí người/agent, trưởng phòng, tuyển agent từ mẫu. |
| 1 · Lõi | <b>M3 Công việc</b> | flow, os?tab=projects, tasks/[id], quality, artifacts | List + board + side-peek kiểu Linear. Có checkout, blocker, bình luận, các bước review, tệp bàn giao. |
| 1 · Lõi | <b>M4 Runtime agent (OpenClaw)</b> | openclaw, live-runs, agent-tools | Trang "Kết nối OpenClaw" có doctor 1 nút. Trạng thái từng agent (đang làm / chờ / ngủ / lỗi), log lượt chạy, quyền tool 3 mức. |
| 1 · Lõi | <b>M5 Hộp việc & Phê duyệt</b> | inbox, approve, approvals, leo thang | Một hộp việc duy nhất, duyệt nhanh trên điện thoại, quá hạn thì leo thang. |
| 1 · Lõi | <b>M6 Ngân sách & Chi phí</b> | budgets, usage | Chi phí theo agent / phòng / mục tiêu. 3 nấc 80% / 100% / override. Đối soát với gateway ±5%. |
| 2 · Quan trọng | <b>M7 Mục tiêu & Kế hoạch</b> | goals + strategy + nina → 1 trang | Mục tiêu → Nina đề xuất plan → duyệt / yêu cầu sửa → sinh task con. Theo dõi tiến độ mục tiêu. |
| 2 · Quan trọng | <b>M8 Việc định kỳ</b> | routines + workflows | Cron / webhook, mẫu sẵn (báo cáo sáng…), tự dừng khi lỗi liên tiếp. |
| 2 · Quan trọng | <b>M9 Tri thức & Bộ nhớ</b> | os?tab=knowledge, memory, knowledge-mesh | Một kho tài liệu phân quyền theo phòng. Bài học được tự đề xuất rồi duyệt. |
| 2 · Quan trọng | <b>M10 Kỹ năng agent</b> | skills, agent-tools | Skill Studio: cài skill, đổi phiên bản, chạy thử input. |
| 2 · Quan trọng | <b>M11 Tổng quan & Báo cáo</b> | os, control-center, founder-cockpit, reports, events | Một trang Tổng quan, nhật ký hoạt động, báo cáo tuần. |
| 2 · Quan trọng | <b>M12 Phòng họp & Kênh</b> | collaboration, communications, portal/chat | Phòng họp agent, chat với Nina, kênh Telegram/Zalo. |
| 3 · Còn lại (ẩn) | Giao phần mềm | repositories, delivery, reviews, cicd, releases, release-manager, deployments, progressive-delivery, engineering, portfolio | Đóng băng. |
| 3 · Còn lại (ẩn) | Vận hành & tin cậy | sre-control, incidents, observability, telemetry-federation, trust, supply-chain, production-trust, secrets-federation | Đóng băng. |
| 3 · Còn lại (ẩn) | Runtime nâng cao | runners, sandboxes, workspaces, workspace-gateway, dev-cloud | Đóng băng. |
| 3 · Còn lại (ẩn) | Kinh doanh & khác | customers, marketplace, simulation; autonomy gộp vào cài đặt M4/M5 | Đóng băng. |

Phần backend của D1–D3 (task lifecycle, wakeup, execution policy, budget, routing, routines, inbox, strategy) <b>giữ nguyên và dùng lại</b> cho M3–M8. Phần phải làm lại là gom API và UI. Các gói D4.x được chuyển vào M2 (gói công ty), M9 (tự học, tìm kiếm), M10 (Skill Studio) và M12 (kênh).

## 4. Lộ trình theo đợt

| Đợt | Nội dung | Thời lượng | Gate |
| --- | --- | --- | --- |
| <b>A · Ổn định</b> | A0 thu lỗi anh gặp và kiểm box (<code>alembic current</code>). A1 làm M0. A2 thêm cờ lab, rút menu tạm còn 12 mục (chưa đổi giao diện). A3 chạy smoke e2e trên box. | 1–1,5 tuần | <b>GA</b>: box deploy mới, e2e 15 luồng 0 lỗi. Anh tự chạy được "tạo công ty → thêm agent → giao việc → agent làm → duyệt" không lỗi. |
| <b>B · Khung mới</b> | Design system (token, font, ~20 component), shell mới (8 mục, ⌘K, mobile), mascot, onboarding 4 bước. | 1,5 tuần | <b>GB</b>: trang lõi không còn class v8–v14. Lighthouse a11y ≥ 90. Dùng được ở 390px. |
| <b>C · Lõi</b> | M2 → M3 → M4 → M5 → M6, mỗi module một gói gồm API domain + UI mới + e2e. M1 làm song song. | 3–4 tuần | <b>GC</b> (= G5 thật): kịch bản "Ra mắt bộ sưu tập hè, \$20" chạy trên gateway thật, người chỉ nhận 2 ping, chi phí khớp ±5%. |
| <b>D · Quan trọng</b> | M7 → M8 → M11 → M9 → M10 → M12. | 3–4 tuần | <b>GD</b> (= G6 cũ): 1 công ty tự chạy 1 tuần bằng việc định kỳ, có scorecard. |
| <b>E · Còn lại</b> | Xét từng module tầng 3: chuyển thành plugin hoặc xoá. | theo nhu cầu | Không còn route vN, ≤ 200 endpoint. |

## 5. UI/UX

<b>Tham chiếu.</b> Paperclip: mental model "điều hành công ty, không phải dùng tool", sơ đồ tổ chức cho agent, heartbeat, duyệt từ điện thoại. Linear: list nhanh, phím tắt, ⌘K, side-peek, ít màu, trạng thái rõ. Notion: empty state thân thiện, trang chính là tài liệu.

<b>IA mới, 8 mục:</b>

```plain text
┌ ClawCompany ▾ (đổi công ty)      ⌘K
│ 📥 Hộp việc            3
│ 🏠 Tổng quan
│ ✅ Công việc           (list · board · dự án)
│ 🎯 Mục tiêu & Kế hoạch (Nina)
│ 👥 Đội ngũ             (sơ đồ · agent · người)
│ 🔁 Việc định kỳ
│ 💰 Chi phí
│ ⚙️ Cài đặt             (OpenClaw · kỹ năng · bí mật · thành viên · 🧪 Phòng thí nghiệm)
```

<b>Màn hình chủ chốt:</b>

- <b>Onboarding 4 bước:</b> đặt tên công ty → chọn mẫu (shop / agency / kế toán) → kết nối OpenClaw (doctor) → giao việc đầu tiên cho Nina.
- <b>Hộp việc:</b> thẻ hành động 1 chạm (Duyệt / Yêu cầu sửa / Mở), gộp theo task, vuốt được trên điện thoại.
- <b>Công việc:</b> list/board, side-peek, dòng thời gian lượt chạy kèm chi phí từng lượt.
- <b>Đội ngũ:</b> sơ đồ tổ chức. Thẻ agent hiện trạng thái bằng mascot: đang làm / chờ / ngủ / lỗi.
- <b>Tổng quan:</b> "Hôm nay công ty làm gì", gồm 3 con số (việc xong, chờ anh duyệt, chi phí hôm nay so với ngân sách) và feed hoạt động.

<b>Design system:</b>

- Token: spacing theo bội 4, radius 8/12/20, 2 mức shadow, cỡ chữ 12/14/16/20/28. Dark mode dùng token kép ngay từ đầu.
- Font: <b>Be Vietnam Pro</b> cho UI (thiết kế cho dấu tiếng Việt), <b>JetBrains Mono</b> cho log.
- CSS: 1 file token + component. Xoá dần các họ class v8–v14, gom 11 AppShell còn 1.

| Màu | Mã | Dùng cho | Tương phản (đã đo) |
| --- | --- | --- | --- |
| Càng | #FF5A4E | mascot, điểm nhấn | chữ trắng chỉ đạt 3,1:1, không dùng cho chữ |
| Càng đậm | #D63A2F | nút chính, chữ trắng | 4,7:1 ✅ |
| Mực | #1A1C2B | chữ chính | 15,9:1 trên nền Kem ✅ |
| Kem | #FFF7F0 | nền | — |
| Rong | #16B3A3 / #0E8577 | agent đang làm, OK | chữ dùng #0E8577 4,5:1 ✅ |
| Đèn | #FFD36B | chờ duyệt, cảnh báo nhẹ | chữ Mực trên nền Đèn 11,9:1 ✅ |

## 6. Mascot

Đã phác 3 hướng, file nằm ở <code>design/mascot/</code> trong repo:

- <b>A. "Ốc" — ốc mượn hồn mang vỏ là toà nhà văn phòng (em đề xuất chọn).</b> Ý nghĩa: công ty là ngôi nhà, agent dọn vào làm việc. Cửa sổ sáng nghĩa là agent đang làm, nên mascot dùng luôn làm chỉ báo hoạt động. Đã có 5 trạng thái: chào, làm việc, duyệt xong, lỗi, ngủ. Cùng họ "càng" với tôm hùm OpenClaw nhưng không bị trùng.
- <b>B. "Sếp Càng" — tôm hùm quản lý đeo cà vạt, cầm checklist.</b> Dễ nhận diện, nhưng dễ bị coi là bản sao mascot tôm hùm của OpenClaw.
- <b>C. Biểu tượng chữ C hình chiếc càng nắm 3 chấm</b> (agent / người / việc). Dùng làm app icon và favicon, đi kèm A.

Mascot xuất hiện ở onboarding, empty state, loading (cửa sổ sáng dần), trang lỗi và thông báo. Không đặt trong bảng dữ liệu.

## 7. Cần anh duyệt

1. Ẩn 27 trang tầng 3 sau "Phòng thí nghiệm" và gộp ~12 trang trùng (không xoá code).
2. IA 8 mục như mục 5.
3. Mascot A + logo C (hay chọn B), và tên mascot: "Ốc" hay "Bé Càng".
4. Font Be Vietnam Pro + bảng màu Càng / Mực / Kem.
5. Dừng series D cũ: D0.1 (branch protection) chuyển vào M0, D2.3 (e2e gateway) chuyển vào gate GC. Anh duyệt xong em tạo DB "Gói việc v2" và bắt đầu Đợt A.
