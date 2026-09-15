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
