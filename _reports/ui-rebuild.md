# Dựng lại UI theo design canvas v17

Ngày: 2026-09-15.

## Vấn đề

Dự án có **hai ngôn ngữ thị giác mâu thuẫn**:

- `design/clawcompany-ui-canvas.html` (v17) — giấy kem `#faf7f2`, mực ấm
  `#1b1a17`, điểm nhấn terracotta `#c2703d`, sidebar gần đen, tiêu đề serif
  biên tập. Đây là **spec của chính dự án**.
- `app/globals.css` đang chạy — tím `#715cff`, nền xanh xám, 378 selector viết
  dồn trên 77 dòng.

Và app không theo cái nào cho tới cùng: ảnh chụp trước khi sửa cho thấy bảng
HTML thô không viền, thẻ số lệch nhau, sơ đồ tổ chức là danh sách bullet, nút
"Làm mới" giãn hết chiều ngang cột.

## Cách làm

**Một file CSS, không sửa 66 component.** `app/globals.css` được viết lại thành
design system theo ngôn ngữ canvas, nhưng style theo **bộ tên class đang có**
(`v8Card`, `v14Table`, `v13Split`, `dataTable`, `tag`...). Nhờ vậy cả 49 route
đổi diện mạo cùng lúc. Selector nhóm theo *họ* thay vì theo version, vì
`v12Metrics` và `v14Metrics` vốn là cùng một thứ.

Kiểm chứng bằng headless chromium (playwright) chụp từng trang với dữ liệu
thật, không phải đọc code rồi tưởng tượng.

## Đã sửa

| # | Vấn đề | Cách xử lý |
| --- | --- | --- |
| 1 | Hai ngôn ngữ thị giác | Viết lại globals.css theo canvas; giữ tên class |
| 2 | Glyph Unicode (`⌂ ▤ ◫ ✦ ⛬ ◈`) render thành ô vuông tofu trên Linux | `components/Icon.tsx` — 20 icon SVG, ăn theo `currentColor` |
| 3 | Sidebar hở nền trắng khi trang dài hơn màn hình | Tô dải màu vào chính container grid |
| 4 | Chữ "ClawCompany" trắng trên thẻ đăng nhập nền trắng | Rule màu trắng chỉ còn áp trong sidebar |
| 5 | Sidebar hứa deep-link `?tab=agents` nhưng cockpit bỏ qua | Cockpit đọc `useSearchParams`, đổi tab thì đổi URL |
| 6 | "Trang chủ" luôn sáng dù đang ở tab khác | Trạng thái active so cả pathname và tab |
| 7 | **Hiển thị "9800%"** — API trả 98.0, component nhân 100 lần nữa | Hàm `percent()` đoán theo biên độ, chịu cả 0.98 và 98 |
| 8 | `next build` vỡ 4 trang: thiếu ranh giới Suspense cho `useSearchParams` | Tách `NavGroupsWithTab` / `WorkspaceCockpitInner`, bọc Suspense |
| 9 | Cửa đăng nhập dùng inline style gradient tím | Dùng `.portalLogin*` của design system, có nhãn và Enter-to-submit |
| 10 | Trang chủ trống nửa dưới cột trái | Thêm panel "Nhiệm vụ cần chú ý" |

## Thêm mới trên Trang chủ

Hiện thực hoá Screen 01 của canvas: hero có Nina và câu dẫn, dải 4 số liệu
chính + hàng phụ, cây tổ chức (node gốc tối + thẻ công ty có màu định danh),
bảng dự án có thanh tiến độ, **feed hoạt động đọc từ `/api/v10/events` thật**
(tên event dịch sang tiếng Việt, không có trong bảng thì giữ nguyên tên gốc),
và sơ đồ công ty → phòng ban → thành viên.

Bảng AI Agents thêm cột **Runtime**: hiện `runtime_agent_id` kèm trạng thái
`active` / `rời gateway`. Đây chính là trạng thái orphaned mà
`/api/v19/openclaw/reconcile` phát hiện — trước đây chỉ API biết, giao diện
không nói.

## Kiểm chứng

| Phép thử | Kết quả |
| --- | --- |
| `next build` | xanh, 51 route prerender |
| `tsc --noEmit` | không lỗi |
| Console trình duyệt trên 7 trang | **0 lỗi** |
| Ảnh chụp với dữ liệu thật | `_reports/ui/new-*.png` |

## Còn lại

- 40 console hạ tầng (v9→v35) thừa hưởng ngôn ngữ mới nhưng **chưa được xem
  lại từng trang**; chúng đúng tông nhưng bố cục có thể còn chỗ chưa tối ưu.
- Chưa có chế độ tối, chưa có trang cho khổ điện thoại thật (chỉ có breakpoint).
- Command palette (`.overlay/.command`) đã có style nhưng chưa nối vào phím tắt.
- Canvas còn Screen 03/04 (Collaboration Room, Knowledge Mesh) với bố cục ba
  cột riêng; hai trang đó hiện chỉ thừa hưởng style chung.

---

# Vòng hai: chuyển sang mockup indigo/pastel của người dùng

Người dùng gửi một ảnh mockup dashboard và nói: thích **logo** trên đó, và
muốn tham khảo UI. Ảnh đó khác canvas v17 ở hai điểm nền tảng:

| | Canvas v17 | Mockup người dùng |
| --- | --- | --- |
| Bảng màu | giấy kem, mực ấm, terracotta | nền lavender nhạt, indigo `#5b5be6`, men pastel |
| Bố cục | hai cột | **ba cột** — sidebar, nội dung, rail phải |
| Chrome | header đơn giản | topbar có ô tìm kiếm ⌘K, nút "Tạo mới", chuông, đồng hồ |
| Sidebar | nhãn nhóm | có **số đếm** cạnh mục |

Người dùng xem cả hai và chọn hướng này, nên palette đổi theo. Việc đổi nằm
gọn trong khối token + vài rule nền, nên 49 route vẫn đổi theo cùng lúc.

## Logo

`components/Logo.tsx` — dựng lại bằng **SVG**: khối "gem" bốn cạnh với hai góc
đối diện vê mạnh, gradient xanh dương → tím, khoét lỗ lục giác giữa. Tham số
`hole` nhận màu nền chỗ đặt logo, vì đây là lỗ thật chứ không phải hình tròn
màu — nhờ vậy logo dùng được cả trên sidebar tối và thẻ trắng.

## Đã dựng theo mockup

- **Vỏ ba cột** (`.shell3`), rail 360px dính theo cuộn.
- **Topbar**: ô tìm kiếm rộng có `⌘K`, nút "Tạo mới" gradient indigo, chuông
  có dấu đỏ, ngày + giờ thật (render phía client để không lệch hydration).
- **Rail phải** (`components/HomeRail.tsx`): "Nhiệm vụ của bạn" với ba pill tab
  và nhãn ưu tiên Cao/Trung bình/Thấp, dòng diễn biến, panel Nina.
- **Hero**: ảnh chân dung Nina thật (`public/nina.jpg`, sinh bằng
  GenerateImage), tiêu đề sans đậm (mockup không dùng serif cho dòng này),
  câu trích dẫn giữ serif để hero có nhịp biên tập.
- **Ô icon pastel** cho KPI và từng dòng trong rail, phân biệt bằng men màu.
- **Chồng avatar** trên thẻ công ty, chữ đầu tên thành viên thật từ org-chart.
- **Danh sách AI Agents** có nhãn trạng thái runtime.
- **Số đếm sidebar** lấy từ `/api/v17/workspace/overview`.

## Ba chỗ mockup có mà hệ thống không có — xử lý bằng sự thật, không bịa

| Mockup | Hệ thống | Cách làm |
| --- | --- | --- |
| "Doanh thu (tháng) $42,380 +12%" | không có thực thể doanh thu | bỏ ô này; KPI chỉ hiện số đo được |
| "Lịch hôm nay" với 5 buổi họp | không có thực thể lịch | thay bằng **event bus thật**, kèm một dòng nói rõ vì sao |
| Chat Nina trả lời được | gateway dev không có credential model | panel giữ nguyên, ô nhập **bị khoá kèm lý do**, chips điều hướng vẫn dùng được |
| "Hạn chót 30/09/2026" trên bảng dự án | `projects` không có cột hạn | cột đó không tồn tại; thay bằng số việc done/total |

Một dashboard bịa số thì đẹp ảnh nhưng vô dụng khi vận hành — và dự án này
vừa mất một lượt tiếp nhận chỉ để tìm ra những chỗ tài liệu tự tin hơn thực tế.

## Kiểm chứng vòng hai

`next build` xanh 51 route · `tsc` sạch · 0 lỗi console trên 7 trang · ảnh
chụp ở `_reports/ui/new-*.png`.
