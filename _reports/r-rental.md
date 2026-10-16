# Báo cáo Phase R — nhiều công ty + cho thuê agent (R1 + R2)

Ngày 2026-10-16 · nhánh `ui-v2` · spec `docs/r-rental-and-multi-company.md` · backlog `_reports/multi-company-and-rental-review.md`.
Chưa push.

## Tóm tắt

| | R1 cô lập + vai trò công ty | R2 cho thuê agent theo ghế |
|---|---|---|
| Commit | `e914a07` | `9192990`, `af49ff7`, `18d7f9d` |
| Migration | `0051_company_roles` | `0052_seat_leases` |
| Test | `tests/test_r1_isolation.py` (7) | `tests/test_r2_leases.py` (12) |
| Suite | xanh theo lát (93 file) | xanh theo lát (94 file) |
| VM | đã deploy + kiểm (`work/vm_r1.py`) | đã deploy + kiểm (`work/vm_r2.py`), 6 ảnh `_reports/ui/r2-*.png`, 0 lỗi console |

## R1 — đã làm

- Ma trận cô lập 2 tổ chức × 2 công ty bằng API thật, quét mọi GET của `/api/team|inbox|learning|agents|approvals|a2a|leases`,
  mọi route có id gọi chéo tổ chức, mọi tool MCP `company_*` → tìm và sửa 3 chỗ rò (`/api/inbox` cũ, `/team/rules/compiled`,
  `/learning/docs`).
- Vai trò theo công ty (chủ / quản lý / người duyệt / người xem), một người nhiều ghế (mỗi công ty một ghế), cổng
  `require_company_role` + `company_scope.check`. UI tab "Vai trò công ty".
- VM: người xem công ty 3 đọc 200 / ghi 403 / công ty khác 403; tổ chức Renter Test không đọc được công ty 3.

## R2 — đã làm

- Hợp đồng thuê ghế: chào thuê có mã → bên thuê (tổ chức khác) nhận → **ghế agent mới** trong công ty bên thuê.
- **Xếp lớp**: AGENTS.md của ghế thuê = tiêu đề → *Sàn của bên cho thuê (KHÔNG ĐƯỢC GHI ĐÈ)* → tri thức được cấp →
  *Lớp của bên thuê* → vai trò/chức danh/hiến chương bên thuê. Luật sàn đi trước luật bên thuê ở cổng MCP và guard plugin;
  công cụ = sàn ∩ chức danh bên thuê; cổng thuê đứng trên quyền riêng của ghế.
- **Bên thuê không nới được**: model / cấu hình năng lực-quyền-hạn mức 403, bỏ mục sàn khỏi AGENTS.md 422, hạn mức > trần 422,
  sửa điều khoản 403, đụng luật sàn 404. Đổi chính sách → yêu cầu thay đổi, bên cho thuê duyệt.
- **Đo đếm USD**: chi phí model thật × (1 + markup), phí theo việc, theo giờ, theo tháng; A2A và cổng khách đo theo
  `sessions.usage`; chạm trần → tạm dừng + Hộp việc hai bên.
- **Hết hạn**: ghế bị gỡ khỏi gateway, dữ liệu bên thuê trong ghế bị xoá, sổ đo đếm giữ nguyên.
- **Riêng tư**: bên cho thuê chỉ thấy điều khoản + số đo đếm + doanh thu; ghế bên thuê → 404 với bên cho thuê.
- UI: Đội ngũ → "Cho thuê agent" (chào thuê, mã, trạng thái, đo đếm tháng so với trần, doanh thu/lãi gộp, duyệt yêu cầu đổi,
  tạm dừng/kết thúc) và "Agent đi thuê" (nhập mã, xem điều khoản, chọn chức danh, chi phí so với trần, xin đổi). vi + en.

## Bằng chứng trên VM (R2)

| Bước | Kết quả |
|---|---|
| Chào thuê agent CSKH (#6) của Tiệm Gốm Mộc, markup 20%, 0.05 USD/việc, 0.5 USD/giờ, trần 1 USD | lease #1, mã dùng một lần |
| Renter Test Co nhận vào chức danh "CSKH thuê" | ghế mới agent #10 `nhan-vien-cskh-f83c`, luật đẩy cho 7 agent |
| AGENTS.md trên gateway | sàn @44 < lớp bên thuê @1430 < vai trò @1486; 3 điều cấm + 3 luật cứng của bên cho thuê |
| Bên thuê thử nới (model, cấu hình quyền, AGENTS.md thiếu sàn, hạn mức 50 > trần, tắt luật sàn, sửa điều khoản) | 403 / 403 / 422 / 422 / 404 / 403 |
| `company_delegate_external` (chức danh bên thuê cho dùng) | **bị chặn** bởi luật sàn "Không giao việc cho agent ngoài" |
| Usage tất định 0.30 + 0.60 USD | tính 0.36 + 0.72 → chạm trần 1 USD → `suspended`, Hộp việc #37 (bên cho thuê) #38 (bên thuê) |
| Yêu cầu đổi trần → 3 USD | bên thuê tự duyệt 403; bên cho thuê duyệt → áp dụng, AGENTS.md sinh lại có "3 USD/tháng"; resume |
| Lượt việc 30 phút, model 0.10 | 0.12 + phí việc 0.05 + phí giờ 0.25 |
| Tick tại hạn + 1 phút | `ended`, agent bị gỡ khỏi gateway, 5 file chụp xoá, 5 dòng đo đếm giữ |

Ảnh: `r2-lease-out.png`, `r2-lease-out-en.png`, `r2-offer-form.png`, `r2-leased.png`, `r2-leased-en.png`, `r2-accept-preview.png`.

## Chưa kiểm chứng / cần chạy lại bằng agent thật (khi có quota CometAPI)

1. Một lượt việc thật của ghế thuê: usage thật từ `session.message` → dòng `lease_usage` model + phí việc/giờ.
2. Gọi A2A thật vào ghế thuê (mở A2A ở công ty bên thuê) → dòng `channel=a2a` từ `sessions.usage` thật.
3. Cổng khách thật gắn ghế thuê → dòng `channel=portal`.
4. Model thật bị guard plugin chặn khi ghế thuê định gọi `company_delegate_external` / hứa hoàn tiền 100% (luật sàn ở hook).
(R1 không cần chạy lại bằng agent thật.)

## Việc còn mở

- R1: các route cấp tổ chức cũ (`/api/work`, `/api/tasks`, chi phí, v7–v36, `/api/agents`) chưa lọc theo vai trò công ty.
- R2: `approval_policy` chỉ hỗ trợ mặc định; chưa có hoá đơn/thu tiền; chuỗi điều khoản tiếng Việt trong giao diện EN;
  trần theo tháng UTC.
- R3 (xuất/nhập mẫu công ty v2) và R4 (thuê nguyên công ty có quản lý): mới có thiết kế trong spec.
- Dữ liệu thử để lại trên VM: lease #2 (mã chào thuê `CHjZDLtccPsG`, hết hạn 2026-12-15), project "R2 probe (synthetic)" ở
  công ty 4, chức danh #10 "CSKH thuê", usage tổng hợp ≈ 1 USD ở tổ chức 2 (message id `r2-synthetic-*`).
