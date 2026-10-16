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

- ~~Route cũ cấp tổ chức chưa lọc theo vai trò công ty~~ — **đã đóng ở P0 (2026-10-16, `app/core/company_guard.py`)**:
  với người bị giới hạn công ty, `/api/work`, `/api/tasks`, `/api/agents` (+ roster, hire/options), `/api/costs`,
  `/api/companies|members|projects|departments|approvals`, `/api/dashboard/summary`, `/v17/workspace/overview` và
  `/team/org-chart` chỉ trả công ty của họ; đối tượng theo id (task/agent/member/project/department/approval/budget)
  kiểm công ty (GET ≥ viewer, ghi ≥ manager); mọi module khác (v7–v36, a2a, routines, strategy, shared-memory,
  knowledge, jobs, realtime…) **mặc định đóng 403** `org_level_route`. Test `tests/test_p0_company_scope_legacy.py` quét
  mọi route GET không tham số.
- Còn lại: khách hàng (`customers`) chưa có `company_id` → không đếm cho người bị giới hạn; UI chưa ẩn mục menu cấp tổ
  chức với người bị giới hạn (bấm vào thấy thông báo 403 rõ ràng thay vì dữ liệu cả org).

---

## R2 — cho thuê agent theo ghế (`seat_leases`)

Commits `9192990` (backend + test), `af49ff7` (UI), `18d7f9d` (nhãn lớp bên thuê). Migration `0052_seat_leases`.

### Vòng đời

1. **Chào thuê** (bên cho thuê, admin công ty nguồn): `POST /leases {provider_agent_id, markup_pct, price_per_task_usd,
   price_per_hour_usd, price_per_month_usd, monthly_cost_cap_usd, allowed_tools, knowledge_doc_ids, data_handling, ends_at,
   offer_expires_at}` → `draft` + `offer_code` (mặc định hết hạn sau 14 ngày). Ghế đang là ghế đi thuê thì không cho thuê lại.
2. **Nhận lời** (bên thuê, admin công ty đích, tổ chức KHÁC): `GET /leases/offer/{code}` xem điều khoản →
   `POST /leases/accept {offer_code, company_id, position_id}` → hệ thống **tuyển một ghế agent MỚI** trong công ty bên thuê
   (workspace, MEMORY.md, phiên riêng; KHÔNG chép bộ nhớ nội bộ bên cho thuê), sinh lại AGENTS.md có sàn, đẩy luật lên guard
   plugin, ghi phí tháng đầu, Hộp việc hai bên → `active`.
3. **Chạy**: `suspended` khi chạm trần tháng (tự động) hoặc bên cho thuê tạm dừng; `resume` bị từ chối khi vẫn chạm trần.
4. **Kết thúc / hết hạn** (`POST /leases/{id}/end` hoặc beat `lease.tick` 300 s, `POST /leases/tick {now}` để kiểm tất
   định): retire ghế thuê (xoá agent + file + phiên trên gateway), xoá file chụp, khoá A2A, tài liệu riêng của ghế; **giữ**
   `lease_usage`, `usage_events`, `task_runs`. Chào thuê quá hạn chưa ai nhận → `ended`.

### Xếp lớp chính sách (đã cưỡng chế, có test)

| Lớp | Ở đâu | Cưỡng chế |
|---|---|---|
| Sàn bên cho thuê | AGENTS.md: ngay sau tiêu đề, mục `## Sàn của bên cho thuê (KHÔNG ĐƯỢC GHI ĐÈ)` (điều cấm hiến chương, luật cứng của công ty nguồn áp cho chức danh nguồn, quy tắc dữ liệu, công cụ, trần) → tri thức được cấp → `## Lớp của bên thuê` | `runtime_rules.rules_for` đặt luật sàn TRƯỚC luật bên thuê → cổng MCP + guard plugin; `tool_permissions.resolve` kiểm cổng thuê trước cả quyền riêng của ghế; bên thuê PUT AGENTS.md thiếu mục sàn → 422 |
| Công cụ | sàn = `allowed_tools` của hợp đồng, hoặc của chức danh nguồn; trống = không giới hạn thêm | công cụ hiệu lực = sàn ∩ chức danh bên thuê (AGENTS.md và `allowedCompanyTools` của plugin) |
| Tri thức | `knowledge_scope.doc_ids` (phải thuộc tổ chức bên cho thuê) | `knowledge_hub.visible_docs_query` + `company_mcp._doc_visible`; mất khi hợp đồng không `active` |
| Lớp bên thuê | hiến chương, phân quyền, luật cứng, hợp đồng dữ liệu, tri thức của công ty bên thuê | có sẵn vì ghế thuê là ghế của công ty bên thuê |

Bên thuê không nới được: đổi `model`/`model_policy` 403; cấu hình tab capability/permission/budget 403 (tab profile = tên/emoji
thì được); hạn mức ghế > trần hợp đồng 422; sửa điều khoản 403; luật sàn nằm ở công ty bên cho thuê → id luật 404 với bên thuê.
Giá (`price_*`, `markup_pct`) chỉ đổi khi còn `draft`.

### Ai duyệt / ai trả

`approval_policy` mặc định `{business: renter, policy: provider, payer: renter}` — hiện CHỈ hỗ trợ đúng mặc định này (giá trị
khác → 422, nói thẳng thay vì im lặng bỏ qua). Thay đổi chính sách do bên thuê xin: `POST /leases/{id}/change-requests
{changes: {allowed_tools|monthly_cost_cap_usd|data_handling|knowledge_doc_ids|ends_at}, note}` → Hộp việc bên cho thuê
(`approval_pending`) → `POST …/{cr}/decide {approved|rejected}` (chỉ bên cho thuê) → áp dụng + sinh lại AGENTS.md + đẩy luật.

### Đo đếm (USD)

- Mỗi lượt model thật của ghế thuê (`cost_ledger.record_message_usage`) → `lease_usage kind=model`, `cost_usd` = chi phí
  thật, `billed_usd` = chi phí × (1 + markup/100); `task_runs.lease_id/billed_usd` cộng dồn.
- Lượt việc xong (`task_lifecycle.finish_run` succeeded) → `task_fee` + `hour_fee` (thời lượng lượt chạy), không tính hai lần.
- Phí tháng: lúc nhận lời + tick đầu mỗi tháng.
- A2A / cổng khách (không có task_run): kiểm hợp đồng TRƯỚC khi gửi (`seat_limits.check`), đo SAU khi trả lời bằng
  `sessions.usage` của phiên (ghi phần chênh), kênh `a2a|portal` + người gọi.
- Chạm `monthly_cost_cap_usd` (theo `billed_usd` tháng UTC) → `suspended` + Hộp việc `budget_exhausted` cả hai tổ chức.

### Bên nào thấy gì

`seat_leases.view`: bên cho thuê thấy điều khoản, trạng thái, số đo đếm, doanh thu, yêu cầu đổi — **không** có id ghế/agent,
việc, phiên của bên thuê (GET ghế bên thuê → 404). Bên thuê thấy ghế của mình + `block_reason`. Tổ chức thứ ba → 404.

### Kiểm chứng

- `tests/test_r2_leases.py` (12 test hành vi), suite đầy đủ xanh theo lát.
- VM (`work/vm_r2.py`): công ty 3 Tiệm Gốm Mộc cho tổ chức "Renter Test" / công ty 4 thuê agent CSKH; AGENTS.md trên gateway
  đúng thứ tự sàn → lớp bên thuê → vai trò; 5 lần bên thuê thử nới đều bị từ chối; `company_delegate_external` bị luật sàn chặn
  dù chức danh bên thuê cho dùng; đo đếm bằng usage tất định (`r2-synthetic-*`), trần 1 USD → tạm dừng + Hộp việc hai bên;
  yêu cầu đổi trần được duyệt; tick hết hạn → ghế bị gỡ khỏi gateway, 5 dòng đo đếm còn nguyên.

### Giới hạn (nói thẳng)

- Chưa có lượt model THẬT nào của ghế thuê (hết quota CometAPI): đo A2A/cổng khách chỉ kiểm bằng gateway giả.
- `approval_policy` chưa đảo vai được; chưa có hoá đơn/thu tiền thật — `lease_usage` là sổ đo đếm, không phải thanh toán.
- Chuỗi điều khoản (`terms.line`) sinh ở backend bằng tiếng Việt, giao diện EN vẫn hiện chữ Việt.
- Trần tháng tính theo tháng UTC; phí theo giờ lấy thời lượng lượt chạy (gồm cả thời gian chờ duyệt nếu lượt chạy chờ — suy ra từ code, chưa đo).
- `lease_of_member` chọn hợp đồng mới nhất của ghế; một ghế chỉ thuộc một hợp đồng (ghế được tuyển mới cho mỗi hợp đồng).

---

## R3 — mẫu công ty v2: xuất / nhập (thiết kế, chưa làm)

- `GET /team/companies/{id}/export` → JSON `clawcompany.template/v2`: hồ sơ + hiến chương, phòng ban, chức danh (JD, KPI,
  công cụ), ma trận phân quyền, quy trình + SOP + hợp đồng dữ liệu, luật cứng, SLA, lịch vận hành, tài liệu tri thức được
  đánh dấu "xuất được", hồ sơ agent (tính cách, model policy) — KHÔNG có dữ liệu khách, việc, phiên, bộ nhớ, khoá.
- `POST /team/companies/import {template, name}` → tạo công ty mới trong tổ chức đích, map id theo `key` ổn định, tuyển ghế
  agent mới theo chức danh; báo cáo phần không nhập được (công cụ/skill không có trên gateway đích).
- Bản xuất có `hash` + `source_version`; là đầu vào cho R4 và marketplace (`price_monthly`).

## R4 — cho thuê nguyên công ty có quản lý (thiết kế, chưa làm)

- `company_leases`: bên cho thuê vận hành một công ty (nhập từ mẫu R3) TRONG tổ chức bên thuê; mỗi ghế agent của công ty đó là
  một `seat_lease` con dùng chung điều khoản (sàn chung, trần chung, phí tháng có quản lý).
- Vai trò: bên cho thuê nhận vai trò công ty `manager` (R1) trên đúng công ty đó — không thấy công ty khác của bên thuê; bên thuê
  là `owner` công ty, duyệt việc kinh doanh.
- Hết hạn: tuỳ chọn "trả lại" (xoá như R2) hoặc "chuyển giao" (bên thuê giữ công ty, ghế được tách khỏi hợp đồng, sàn gỡ).
- Cần trước: R1 lọc vai trò công ty ở các route cấp tổ chức còn lại (`/api/work`, `/api/agents`, chi phí).
