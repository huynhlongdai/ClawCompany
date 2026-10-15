# M2e — Công ty agent-native

Hướng của anh (16/10/2026): làm xong module Công ty trước khi cho thuê / nhiều công ty. Công ty agent phải giải
được ba bài toán nhân sự mà công ty truyền thống không giải được:

1. **Cảm xúc, thất thường** → agent làm theo **luật cứng** được cưỡng chế lúc chạy (không chỉ là chữ trong AGENTS.md).
2. **Dữ liệu vào ra không chuẩn** → mỗi chức danh / bước quy trình có **hợp đồng dữ liệu** (schema vào, schema ra,
   tiêu chí nghiệm thu); kết quả sai schema tự trả về làm lại.
3. **Giờ làm việc** → ghế agent chạy 24/7; ghế người có giờ làm + nghỉ phép; SLA có đồng hồ, quá hạn tự leo thang;
   việc tới ngoài giờ của người được chuyển cho agent cùng chức danh.

Thứ tự gói: M2e.1 phạm vi công ty → M2e.2 luật cứng → M2e.3 hợp đồng dữ liệu → M2e.4 vận hành 24/7 → M2e.5 HR agent.
Mỗi gói: migration riêng (0047…), test hành vi, i18n vi+en, deploy + kiểm trên VM (công ty 3 Tiệm Gốm Mộc).

## M2e.1 — Phạm vi công ty (tiền đề)

- `_company(..., write=True)`: thao tác ghi bắt buộc `company_id` (422), không còn rơi về "công ty đầu tiên".
  Đọc không có `company_id` chỉ được khi tổ chức có đúng 1 công ty đang hoạt động (nhiều công ty → 422, không đoán).
- `sops.company_id`, `inbox_items.company_id` (migration 0047, backfill). Hai hàm `before_insert` tự điền
  khi code cũ không truyền: hộp việc theo task → dự án → công ty, phê duyệt → công ty người xin, cuối cùng công ty
  người nhận; SOP theo phòng ban hoặc người sở hữu. SOP mẫu quy trình gắn công ty.
- `company_sop_get` (MCP) chỉ trả SOP công ty của agent (+ SOP cũ dùng chung NULL). Bước quy trình không trỏ được
  SOP của công ty khác.
- `GET /api/inbox/items?company_id=` lọc theo công ty; UI hộp việc có ô chọn công ty khi tổ chức có ≥ 2 công ty.
- Tick nền `rhythm.tick`, `compliance.tick`, `kpi.snapshot` bỏ qua công ty đã lưu trữ.
- KPI: `goal_id` / `objective_id` phải cùng tổ chức và (NULL hoặc cùng công ty).
- Chưa làm (để gói cho thuê): người duyệt "chủ" theo từng công ty, vai trò theo công ty (mục 6–7 báo cáo review).
