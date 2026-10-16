# Phase R — nhiều công ty + cho thuê agent

Ngày 2026-10-16 · nhánh `ui-v2`. Backlog gốc: `_reports/multi-company-and-rental-review.md`.

## Quyết định của anh (owner)

- Nền tảng tạo/quản lý **nhiều công ty trong một tổ chức** và **cho thuê agent (ghế)**; sau này cho thuê **nguyên công ty**.
- **Agent đi thuê tuân theo CẢ hai bên, xếp lớp:**
  - **Sàn của bên cho thuê (provider floor)** — điều cấm trong hiến chương, luật cứng, quy tắc xử lý dữ liệu, trần chi phí,
    công cụ được phép. Bên thuê **không bao giờ nới** được.
  - **Lớp bên thuê (renter layer)** — hiến chương, ma trận phân quyền, luật cứng, hợp đồng dữ liệu, tri thức của bên thuê.
    Chỉ **thêm / siết**.
- Mặc định (đổi được theo từng hợp đồng thuê): người duyệt của bên thuê duyệt hành động kinh doanh trong công ty bên thuê;
  bên cho thuê duyệt thay đổi chính sách / nền tảng của agent; bên thuê trả chi phí model theo đo đếm thật, bên cho thuê đặt
  biên lợi nhuận (markup) cho từng hợp đồng; thuê nguyên công ty = thuê tháng có quản lý (bên cho thuê vận hành), làm sau.

---

## R1 — cô lập + vai trò theo công ty

### Ma trận cô lập (test `tests/test_r1_isolation.py`)

2 tổ chức × 2 công ty, mỗi công ty gieo dữ liệu mang dấu riêng `MK-<org>-<co>` qua API thật (chức danh, ma trận, quy trình
+ SOP, KPI, luật cứng, hợp đồng dữ liệu, SLA, hồ sơ, agent, thẻ hộp việc, tài liệu). Quét **mọi** route của `/api/team`,
`/api/inbox`, `/api/learning`, `/api/agents`, `/api/approvals`, `/api/a2a/{external,expose}`:

| Kiểm | Kết quả trước R1 | Sửa |
|---|---|---|
| GET list với `company_id` của công ty kia (cùng org) không thấy dấu công ty này | **3 rò**: `/api/inbox` (cũ), `/api/team/rules/compiled`, `/api/learning/docs` trả cả org | thêm `company_id` + lọc theo vai trò công ty |
| GET list bằng người của org khác (có/không `company_id`) | sạch | — |
| Mọi route có id trong path, gọi bằng owner org khác → 4xx (không 2xx, không 500) | sạch | — |
| Tool MCP `company_*` của agent công ty A không trả dấu A2/B1/B2 | sạch | — |

### Vai trò theo công ty

- Bảng `company_access(user_id, organization_id, company_id, role ∈ owner|manager|approver|viewer, status)`.
- **Ai bị giới hạn:** user có ≥1 dòng `company_access` active **và** vai trò org dưới admin. Owner/admin org luôn thấy mọi
  công ty. User cũ không có dòng nào → giữ phạm vi cả tổ chức theo vai trò org (tương thích ngược).
- **Thực thi:** `CompanyScopeMiddleware` (ASGI) đặt một dict ngữ cảnh cho mỗi request; `get_principal` ghi người gọi
  (`Principal.company_roles`, `Principal.seats`); route thuộc công ty dùng `require_company_role(min)` (thay
  `require_role`) — qua cổng nếu vai trò công ty cao nhất đủ; service gọi `company_scope.check(company_id)` tại chỗ xác
  định công ty (`company_foundation._company` và mọi hàm lấy theo id: chức danh, luật phân quyền, quy trình, lần chạy, KPI,
  giao ban, tuân thủ, hợp đồng dữ liệu, ghế, ngày nghỉ, SLA, luật cứng) → 403 nếu công ty không thuộc người này hoặc vai trò
  không đủ. Đọc không `company_id` của người chỉ có một công ty → công ty đó. Ngoài request (beat/worker) không giới hạn.
- Mức: viewer = member (đọc), approver = member + quyết phê duyệt của công ty, manager = manager, owner = owner (trong công
  ty đó). Route cấp tổ chức (mời người, đổi vai trò org, dựng công ty từ mẫu) vẫn theo vai trò org.
- **Duyệt:** `authority.owner_member` ưu tiên **chủ công ty** (vai trò công ty owner có ghế ở công ty đó) trước owner org;
  loại người duyệt mới `company_approver` (người giữ vai trò approver, rồi owner, của công ty người xin). Hộp việc: vai trò
  approver/manager/owner của công ty quyết được phê duyệt chưa có người duyệt cụ thể.
- **Một người nhiều ghế:** bỏ unique `users.member_id` (Postgres; SQLite dev giữ unique cũ, không ảnh hưởng vì ghế mới đi qua
  bảng nối). Bảng `user_seats(user_id, member_id, company_id)` — mỗi công ty tối đa một ghế / user, mỗi ghế một user.
  Migration chép mọi `users.member_id` cũ sang. Hộp việc gộp mọi ghế; phê duyệt kiểm "người duyệt ∈ các ghế của tôi";
  hành động ghi theo ghế ở đúng công ty của phê duyệt (`Principal.seat_in`). Lời mời vào công ty khác tạo ghế mới thay vì
  dùng lại ghế cũ ở công ty khác.
- API: `GET /team/my-companies`, `GET|PUT /team/company-access`, `DELETE /team/company-access/{id}`, `POST /team/user-seats`,
  `DELETE /team/user-seats/{id}`. Chỉ owner/admin org hoặc **chủ công ty đó** đổi vai trò / gắn ghế.
- UI: tab Đội ngũ → "Vai trò công ty"; bộ chọn công ty ở sidebar chỉ hiện công ty của người bị giới hạn; `lib/api.ts` không
  còn ghim `organization_id=1` (lấy `org_id` trong JWT), Hộp việc cũ lọc theo công ty đang chọn.
- Migration `0051_company_roles`.

### Giới hạn còn lại (nói thẳng)

- Các trang/route cũ cấp tổ chức (`/api/work`, `/api/tasks`, chi phí, tổng quan, v7–v36) **chưa** lọc theo vai trò công ty:
  người bị giới hạn vẫn đọc được dữ liệu cả org ở đó nếu vai trò org cho phép. Cách an toàn hiện tại: cấp vai trò org
  `guest` cho người chỉ làm ở một công ty.
- Danh sách agent (`/api/agents`) chưa lọc theo vai trò công ty.
