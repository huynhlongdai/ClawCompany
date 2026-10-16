# Rà soát: nhiều công ty + cho thuê công ty/agent (đọc-only)

Ngày 2026-10-16 · nhánh `ui-v2` @ `80e2b50` · đã fetch và đọc `origin/main`, `master`, `impl-plan`, `ui-v5`, `ui-v6`: cả năm nhánh **đều là tổ tiên của `ui-v2`**, không có tài liệu hay code nào về multi-company/cho thuê mà `ui-v2` chưa có.
Không sửa code, không commit. Ghi chú: `(suy ra)` = kết luận rút ra từ đọc code, chưa chạy kiểm chứng.

---

## 1. Ý định của nền tảng (theo tài liệu)

**Thứ bậc.** Repo không có tài liệu tầm nhìn/PRD/mô hình kinh doanh riêng. Ghép từ các nguồn sau:

| Tầng | Bằng chứng | Ý nghĩa |
|---|---|---|
| Nền tảng | `README`, `HANDOFF §1` (control plane trên một gateway OpenClaw); `users.is_superuser` | Một bản triển khai phục vụ nhiều tổ chức. Chưa có bảng hay console nào cho cấp nền tảng. |
| Tổ chức (tenant) | `docs/security-model.md`: "`organization_id` is the top-level tenant scope"; `user_organization_access` | Khách trả tiền của nền tảng, đóng vai holding. |
| Công ty (nhiều công ty / tổ chức) | `docs/module-map.md`: "Công ty: **multi-company management**…"; `ARCHITECTURE_TREE.md §5` "L3 — Công ty & **Holding**"; `plan-v2-modules.md §5` "ClawCompany ▾ (**đổi công ty**)" | Một tổ chức sở hữu và vận hành nhiều công ty. |
| Phòng ban → chức danh → ghế | `entities.py` Department/Member; M2b `positions` | Ghế có thể là người hoặc agent. |
| **Khách hàng (bên thuê)** | `architecture-v5.md`: "Customer SaaS: **Customer → Subscription → Assigned Agent(s) → customer knowledge scope → portal**"; `architecture-v4.md` "Customer portal and tenant assignments"; `nav.ts`/`vi.json` "Khách hàng, **ghế đã bán**, chi phí AI theo khách" | Mô hình cho thuê **agent/ghế** cho khách ngoài, qua cổng riêng. |

**Các mô hình cho thuê tìm thấy trong tài liệu và code:**
1. **Thuê agent/ghế cho khách** (Customer + Subscription + `customer_agent_assignments` + portal chat). Có trong tài liệu v5/v7/v8.
2. **Kho mẫu (marketplace)**: mẫu nhân sự, team, công ty, skill, có `price_monthly` (`module-map.md`, `ARCHITECTURE_TREE §5`).
3. **A2A như dịch vụ**: "mở agent của công ty cho bên ngoài (inbound)" (`models/a2a.py`, commit `a474d45`). Hiện chỉ có một khoá cho mỗi ghế.
4. **Cho thuê nguyên công ty**: **không có trong tài liệu hay code nào**. Nguồn duy nhất là lời anh (owner). Phải coi đây là yêu cầu mới.

**Billing/metering trong ý định:** `architecture-v7.md §6` gồm UsageEvent, gộp usage theo khách, gán agent/task/run, hoá đơn nháp. `module-map.md` ghi "Billing: plans, subscriptions, usage, AI costs, margin".

## 2. Code hiện có

| Hạng mục | Có gì | Thiếu / stub |
|---|---|---|
| Tổ chức | `organizations`; `user_organization_access` (role cho từng org, thu hồi được); token mang **1 org**; đổi org = đăng nhập lại với `organization_id` (`api/auth.py`) | Không có endpoint đổi org. `GET /organizations` chỉ trả org đang dùng. Không có gói hay hạn mức cho org (số công ty, số agent). Không có console nền tảng. |
| Nhiều công ty | `companies.organization_id`; bộ chọn công ty `CompanySwitcher` (`Shell.tsx`, lưu `cc_company` trong localStorage) | Chỉ tab **Đội ngũ** đọc lựa chọn này. Công việc, Hộp việc, Chi phí, Tổng quan vẫn gộp cả org. |
| Vai trò | `ROLE_ORDER` cấp org (`core/authz.py`) | **Không có vai trò theo công ty.** `RoleBinding.scope_type` có cột nhưng chỉ `policy.py` đọc; `require_role` không dùng tới. **`users.member_id` là unique**: một người chỉ có một ghế, ở một công ty. |
| Khách thuê agent | `customers` (org, `tenant_key`, mrr), `customer_agent_assignments` (`knowledge_scope`), `customer_portal_users`, `/portal/*` chat (`api/v8.py`), `CustomersConsole` | `knowledge_scope` **không được dùng ở đâu** (grep = 0). Không có thời hạn thuê, giá theo ghế, hay thu hồi gắn với phiên. Agent chạy bằng AGENTS.md, tri thức và tool MCP **của công ty chủ** (suy ra). `record_usage(unit_cost=0)` nên chi phí thật không được tính. |
| Subscription / hoá đơn | `subscriptions` (theo customer), `billing_invoices`, `metering.generate_invoice` (dòng usage = 0), `usage_meter_rules` | Không có subscription của **org** với nền tảng. Không có cổng thanh toán. Hoá đơn không lấy chi phí thật. |
| Marketplace | `marketplace_templates` **gắn org** (`organization_id`), `manifest_json`, `price_monthly`, `installs`; `provisioning.resolve_manifest` chỉ dùng mẫu cùng org | Không có catalog toàn nền tảng, không publish hay cài chéo org, không mua. `UI` chỉ liệt kê. |
| Mẫu công ty | `team_templates.TEMPLATES` (shop/agency/kế toán, **cứng trong code**) → seed M2b/M2c (ma trận, chức danh, quy trình, giao ban, tuân thủ, readiness) | **Không có "lưu công ty thành mẫu", clone hay export/import.** Manifest marketplace (v8) chỉ chứa phòng ban và agent, không có lớp M2b/M2c. |
| A2A | Outbound `external_agents` (cấp org); inbound `a2a_exposures` (1 khoá cho mỗi ghế, đếm `calls`) | Không định danh người gọi, không hạn mức hay hợp đồng cho từng người gọi, không UsageEvent. Phiên `agent:<rid>:a2a-*` chạy với toàn bộ tool MCP công ty của ghế (suy ra). Chi phí A2A và portal **không vào `task_runs`**, nên `seat_limits` (trần $/ghế) không thấy (suy ra). |
| Cô lập org | `enforce_org`/`active_org` có mặt khắp nơi; test hai tenant (HANDOFF) | `lib/api.ts` để mặc định `organizationId=1` cho `customers`/`marketplace`/`inbox`…, nên người dùng org ≠ 1 nhận **403** trên các trang cũ. Có **một gateway OpenClaw và một provider key chung** cho mọi org (`config.openclaw_gateway_ws`). |

## 3. Audit M2b/M2c theo nhiều công ty và cho thuê

**Phần đúng:**
- Mọi bảng mới (`company_profiles`, `positions`, `authority_rules`, `processes`, `process_instances`, `kpi_definitions`, `rhythm_configs/reports`, `compliance_rules/deadlines`, `readiness_assessments`) đều có `organization_id` và `company_id`. Bảng con (`process_steps`, `kpi_measurements`, `process_step_runs`) đi theo cha.
- Kiểm tra tham chiếu cùng công ty đã có ở hầu hết chỗ cần: phòng ban của chức danh, chức danh cấp trên, gán ghế (`assign_seat`), chức danh duyệt (`authority._apply`), chức danh trong bước quy trình (`_check_position`), KPI cha, phòng ban, chức danh, seat, quy trình (`kpi_cascade`).
- Mọi thao tác theo id đều kiểm `organization_id` (cùng org).
- Ma trận phân quyền chọn luật theo `requester.company_id`. Charter biên dịch theo `member.company_id`.
- UI Đội ngũ truyền `companyId` vào mọi lời gọi.

**Lỗi và rủi ro (nhiều công ty):**
1. **Rơi về "công ty đầu tiên"**: `_company()` trong `company_foundation.py`, `authority.py`, `process_map.py` lấy `order_by(Company.id).first()` khi thiếu `company_id`. Một lời gọi ghi thiếu tham số (agent, MCP hay script) sẽ ghi nhầm vào công ty #1 mà không báo lỗi.
2. **SOP không có `company_id`** (`extended.py: SOP`). `process_map.seed_templates` tạo SOP với `department_id=None`, nên `company_sop_get` (MCP) cho agent của **mọi công ty trong org** thấy SOP của nhau. Ba shop cùng org sẽ có ba "SOP: Hoàn tiền" trùng tên, lẫn lộn.
3. **InboxItem không có `company_id`**: báo cáo giao ban, nhắc tuân thủ, phê duyệt của mọi công ty đổ chung một hộp và không lọc theo công ty được.
4. **Tick nền bỏ qua trạng thái công ty**: `operating_rhythm.tick` vẫn chạy cho công ty đã archive (agent vẫn viết giao ban, tốn tiền). `compliance_calendar.tick` gặp 404 với công ty archived ở mỗi lượt (lỗi được nuốt).
5. `kpi_cascade._apply` không kiểm `goal_id`/`objective_id` (có thể trỏ sang mục tiêu của công ty hoặc org khác).
6. **Người duyệt "chủ"** = owner của **org** (`authority.owner_member`). Không có khái niệm chủ hoặc giám đốc riêng cho từng công ty. Vì `users.member_id` là 1:1, một người làm giám đốc 3 công ty không thể ngồi chức danh ở cả 3.
7. Vai trò chỉ ở cấp org: manager ở org thì là manager ở mọi công ty, kể cả sửa ma trận phân quyền của công ty khác.

**Khi cho thuê** (hiện code chưa trả lời câu nào trong số này):

| Câu hỏi | Hiện trạng |
|---|---|
| Agent cho thuê theo charter, ma trận, tri thức của ai? | Luôn của công ty chủ (`member.company_id`). Bên thuê không có lớp charter hay tri thức riêng. `knowledge_scope` không có hiệu lực. |
| Ai duyệt hành động của agent khi làm cho bên thuê? | Người duyệt của công ty chủ: hoàn tiền cho khách của bên thuê lại do trưởng phòng bên cho thuê duyệt. Bên thuê không có tầng duyệt. |
| Ai trả tiền? | `UsageEvent.customer_id` có cột nhưng `unit_cost=0`. Chi phí thật nằm ở `task_runs.cost_usd` của ghế, tức bên cho thuê gánh. Trần ghế không tính A2A/portal (suy ra). |
| Cô lập dữ liệu | Phiên portal/A2A dùng chung agent và workspace (MEMORY.md, tool MCP công ty) nên có thể lộ việc hay tri thức nội bộ, và nhớ chéo giữa các khách (suy ra). |
| Trả lại (kết thúc thuê) | Chỉ có cờ `status`/`enabled`. Không dọn phiên, không xoá bộ nhớ của bên thuê, không bàn giao dữ liệu. |
| Clone hoặc mẫu cả công ty, gồm lớp M2b/M2c | Không có. Mẫu chỉ có 3 bộ cứng trong code. |

## 4. Đề xuất ưu tiên

| # | Việc | Cỡ |
|---|---|---|
| **P0-1** | **ADR mô hình tenancy và cho thuê**: Nền tảng → Tổ chức (holding, khách trả tiền) → Công ty → Phòng → Chức danh → Ghế. Bên thuê = `Customer` (ngoài) hoặc tổ chức khác. Chốt ba dạng thuê: *ghế/agent*, *nguyên công ty*, *A2A theo hợp đồng*. Mỗi dạng ghi rõ: charter/ma trận/tri thức nào áp dụng, ai duyệt, ai trả, cô lập ra sao, trả lại thế nào. Cần anh duyệt trước khi code. | S (1–2 ngày) |
| **P0-2** | **Siết phạm vi công ty trong module Công ty**: bắt buộc `company_id` cho mọi thao tác ghi (bỏ fallback "công ty đầu"; đọc thì vẫn tiện nhưng trả `company_id`). Thêm `sops.company_id` (migration, backfill từ `process_steps`) và lọc trong MCP. Thêm `inbox_items.company_id` và bộ lọc. Tick giao ban/tuân thủ bỏ qua công ty archived/suspended. Kiểm `goal_id`/`objective_id`. Bỏ mặc định `organizationId=1` trong `lib/api.ts`. | M (2–3 ngày) |
| **P0-3** | **Bộ test cô lập 2 công ty × 2 org** cho mọi `/api/team/*`, `/api/ops/*` và các tool MCP (SOP, quyết định, ngân sách, metric, tri thức), cộng một kịch bản trên VM. | M (2 ngày) |
| **P1-4** | **Quyền theo công ty**: thực thi `RoleBinding(scope_type=company)` hoặc thêm `user_company_access`. Bỏ ràng buộc unique `users.member_id` (một người, nhiều ghế, mỗi công ty một ghế). Thêm "chủ/giám đốc công ty" làm người duyệt cuối thay cho owner org. Đây là điều kiện bắt buộc cho thuê nguyên công ty. | L (4–6 ngày) |
| **P1-5** | **Vá an toàn và đo đếm cho portal/A2A hiện có**: phiên khách/A2A dùng bộ tool MCP rút gọn (không đọc việc, tri thức nội bộ) và session/bộ nhớ riêng cho từng khách. Ghi chi phí thật (từ `usage` gateway) vào `UsageEvent` + `task_runs` để trần ghế chặn được. Thêm `company_id`/`lease_id` vào `usage_events`. Hoá đơn lấy usage thật cộng biên lợi nhuận. | M (3–4 ngày) |
| **P2-6** | **Hợp đồng thuê ghế (`seat_leases`)** gộp `customer_agent_assignments` + `a2a_exposures` + portal: bên thuê, thời hạn, giá, phạm vi tri thức, allowlist tool, lớp charter bên thuê (ghép sau charter chủ). Ma trận: luật bên chủ là trần khoá, bên thuê duyệt trong trần. Metering theo lease. Kết thúc thuê: thu hồi khoá, đóng phiên, xoá bộ nhớ và tri thức của bên thuê, xuất dữ liệu bàn giao. | L (6–8 ngày) |
| **P2-7** | **Snapshot/clone/mẫu công ty v2**: xuất một công ty ra manifest có phiên bản, gồm phòng ban, chức danh + JD, ma trận, quy trình + SOP, định nghĩa KPI, nhịp giao ban, bộ luật tuân thủ, spec agent (soul, skill, model), tri thức được đánh dấu "được xuất". **Không** xuất hồ sơ pháp lý, MST, dữ liệu vận hành hay bộ nhớ. Cài vào cùng org hoặc org khác. Marketplace có thêm `visibility` (riêng/org/nền tảng) và giá. | L (5–7 ngày) |
| **P2-8** | **Cho thuê nguyên công ty** (sau P1-4, P2-6): `company_leases` gắn công ty với bên thuê. Bên thuê nhận vai trò theo công ty, sửa charter/ma trận trong khung bên chủ khoá. Người duyệt là người của bên thuê. Subscription theo lease. Trả lại thì archive, bàn giao dữ liệu cho bên thuê, rồi xoá. Một phương án khác là "bán bản sao" qua P2-7 (chuyển hẳn sang org bên mua). | L (5–8 ngày) |

**Thứ tự gợi ý:** P0-1 → P0-2 + P0-3 (làm ngay, không phụ thuộc quyết định kinh doanh) → P1-5 (đang có rủi ro lộ dữ liệu thật qua portal/A2A) → P1-4 → P2-6 → P2-7 → P2-8.
