# M2b — Nền công ty: hồ sơ pháp nhân + hiến chương, chức danh, ma trận phân quyền

Ba mục đầu của phần D trong `company-anatomy-and-agent-company.md`, anh duyệt 15/10/2026.
Nguyên tắc: biên dịch vào cơ chế đã có (AGENTS.md + tri thức cốt lõi, lưới quyền tool, approvals),
không dựng "bộ não" mới. Tiền: **chỉ USD**.

Migration: **`0038_company_foundation`** (bảng `company_profiles`, `positions`, `authority_rules`;
cột `members.position_id`, đã khai trong `0001_baseline.COLUMNS_OWNED_BY_LATER_MIGRATIONS`).
API: tiền tố của M2 là `/api/team`, nên ba mục nằm ở đó (không mở tiền tố mới).
UI: Đội ngũ → ba tab mới "Hồ sơ công ty", "Chức danh", "Phân quyền".

## 1. Hồ sơ pháp nhân + Hiến chương

**Dữ liệu** (`company_profiles`, một hàng / công ty): tên pháp nhân, loại hình (hộ kinh doanh —
NĐ 01/2021; DNTN, TNHH 1TV, TNHH 2TV+, cổ phần, hợp danh — Luật DN 2020), MST (10 số; chi nhánh
10-3; cá nhân/HKD 12 số), người đại diện theo pháp luật + chức vụ, địa chỉ trụ sở, vốn điều lệ
(số USD + ghi chú tự do), ngành nghề (danh sách), ngày thành lập. Hiến chương: sứ mệnh, giá trị,
giọng thương hiệu, điều cấm, cam kết với khách. `charter_version` tăng khi phần biên dịch đổi.

**Kiểm tra**: MST sai dạng / ngày sai / vốn âm → 422 tiếng Việt kèm cách sửa. Tên thiếu cụm loại
hình (Điều 37 Luật DN 2020), thiếu MST, thiếu người đại diện → *cảnh báo*, không chặn lưu.

**Biên dịch**: `company_foundation.charter_block` được `knowledge_hub.core_section` chèn ĐẦU phần
"## Kiến thức cốt lõi" (lớp công ty) của AGENTS.md — mọi đường đã sinh AGENTS.md (tuyển, sửa hồ sơ,
`sync_core`) tự mang hiến chương. Hạn mức ~3 000 ký tự; vượt → 422. Lưu mà phần biên dịch đổi →
`knowledge_hub.sync_core` chạy nền (cùng cơ chế auto-resync của f18630f), response có `core_sync: true`.

API: `GET /api/team/company-profile?company_id=` (member) · `PUT /api/team/company-profile` (admin).

## 2. Chức danh tách khỏi người

**Dữ liệu** (`positions`): công ty, phòng ban (NULL = Ban điều hành), tên, JD, trách nhiệm (danh
sách), KPI `[{name, target, unit, period∈day|week|month|quarter|year}]` (≤12), công cụ được phép
(tên tool `company_*`; rỗng = không giới hạn), kỹ năng, định biên, chức danh cấp trên (chống vòng).
`members.position_id` = ghế người/agent đang ngồi. Chỗ trống = định biên − số đang ngồi.

**Luật**: xếp ghế quá định biên → 409; hạ định biên dưới số đang ngồi → 409; lưu trữ chức danh còn
người → 409. Xếp ghế ghi `members.role = title` (và phòng ban theo chức danh); đổi tên chức danh ghi
lại `role` của người đang ngồi — nên lớp tri thức "nghề nghiệp" (khớp chữ trong chức danh) và bộ
eval theo vai (`role_keyword`) đọc đúng chức danh mà không phải đổi code đọc.

**Dữ liệu cũ**: migration gom `(công ty, phòng, members.role)` thành chức danh, định biên = số người,
cấp trên = chức danh của người quản lý. Mẫu công ty và nút "Tạo từ người đang có" dùng cùng luật
(`positions_from_members`); JD của chức danh mẫu = mô tả vai trong mẫu.

**Biên dịch vào agent**: `agent_hr.render_files(position=…)` → AGENTS.md có "Nhiệm vụ chính" = JD +
trách nhiệm của chức danh (JD riêng của seat thêm dưới "Riêng ghế này"), "## Chức danh", "## KPI của
chức danh", "## Công cụ & kỹ năng của chức danh". Sửa chức danh / xếp / gỡ ghế → sinh lại AGENTS.md
của agent liên quan (nền). Tuyển agent có `position_id` → nhận tên vai + phòng của chức danh, chặn
nếu hết định biên.

**Thực thi**: `allowed_tools` là cổng thật — `tool_permissions.resolve` trả `off` (nguồn
`position:<id>`) cho tool công ty ngoài danh sách. `allowed_skills` hiện chỉ biên dịch vào AGENTS.md
(*advisory*: chưa nối vào bước chọn seat theo kỹ năng của `dispatch_policy`).

API: `GET/POST /api/team/positions`, `PATCH/DELETE /api/team/positions/{id}`,
`POST /api/team/positions/{id}/seats {member_id}`, `DELETE /api/team/positions/{id}/seats/{member_id}`,
`POST /api/team/positions/from-members?company_id=`.

## 3. Ma trận phân quyền (DoA)

**Một luật** (`authority_rules`): loại việc × dải tiền USD `[min, max)` × rủi ro tối thiểu → người
duyệt (`none | manager | department_head | position | owner`) + cấp tự chủ tối thiểu để agent tự làm
(`probation < standard < trusted`; rỗng = không bao giờ). Dải trùng trong cùng loại + mức rủi ro → 409.

Loại việc: `spend, refund, external_message, contract, data_export, data_delete, exec, hire_agent,
budget_overrun, goal_execute` (+ từ đồng nghĩa: pay, discount, hoàn tiền, publish, delete…).

**Chọn luật**: luật bật của công ty, khớp dải tiền và rủi ro; nhiều luật khớp → dải cao nhất. Không có
số tiền → dải thấp nhất. **Người duyệt luôn là người**: người duyệt theo luật là agent → chuyển lên
người quản lý gần nhất; trống (chưa có trưởng phòng, chức danh trống) → chủ doanh nghiệp (owner của tổ
chức có member; không có → người đứng đầu sơ đồ). Người xin chính là người duyệt → lên một cấp.

**Ai đọc ma trận** (adapter `authority.decide`; không luật khớp → hành vi cũ):

| Đường cũ | Đọc ma trận thế nào |
|---|---|
| `policy.authorize` ← MCP `company_approval_request(action, amount_usd, risk)` | allow / approval_required, người duyệt, `policy_key=authority:r<id>` |
| MCP `company_policy_check(action, amount_usd)` | trả luật, người duyệt, có cần duyệt không |
| `tool_permissions.resolve` (action:send/pay/delete) | agent chưa đủ cấp → ít nhất "Hỏi trước". **Chỉ siết, không nới.** |
| `tool_permissions.ask_approval` | người duyệt + luật lưu vào approval |
| `budget_scope` chi tiếp khi chạm nấc dừng mềm | loại `budget_overrun` → người duyệt |
| `runtime_stream` lệnh exec từ gateway | loại `exec` → người duyệt |
| `orchestration.create_cycle` (autonomy) | loại `goal_execute` theo rủi ro → thay ngưỡng `max_auto_risk` |
| `agent_hr.hire` | loại `hire_agent` → vai trò tối thiểu của người tuyển (403 kèm cách xử lý) |

Approval sinh qua ma trận có `payload.authority = {rule_id, label, approver_kind, approver_name,
reason}`; thẻ Hộp việc hiện "Theo luật #id: …".

**Mặc định** (gieo khi tạo công ty qua `/companies`, `workspace_ops`, `provision_company`, mẫu): chi
<$20 quản lý (agent tin cậy tự làm) · $20–200 trưởng phòng · ≥$200 chủ; hoàn tiền <$20 quản lý
(agent chính thức tự làm) · $20–100 trưởng phòng · ≥$100 chủ; gửi ra ngoài: quản lý (tin cậy tự
làm); hợp đồng, xoá dữ liệu: chủ; xuất dữ liệu: trưởng phòng; exec: quản lý (tin cậy); tuyển agent:
trưởng phòng; chi tiếp vượt nấc: quản lý; kế hoạch tự động rủi ro cao trở lên: chủ. Mẫu: shop (CSKH
chính thức tự trả lời khách; hoàn tiền <$30), agency (ads <$500 trưởng phòng; mọi thứ gửi khách qua
trưởng account), kế toán (xuất dữ liệu: chủ; gửi tờ khai: trưởng phòng; chi chặt hơn). Với lưới tool
hiện có, ma trận mặc định không đổi hành vi nào của lưới — chỉ thêm người duyệt đúng và dải tiền.
Công ty có trước M2b chưa có luật (hành vi cũ) cho tới khi bấm "Dùng ma trận mặc định".

API: `GET /api/team/authority`, `POST/PATCH/DELETE /api/team/authority/rules[/{id}]` (admin),
`POST /api/team/authority/seed-defaults {company_id, template?, replace}`,
`POST /api/team/authority/evaluate {member_id, action_type, amount_usd, risk}` (thử, không tạo duyệt).

## Giới hạn tự khai

- Ma trận chỉ siết lưới tool, không mở được thứ lưới đã tắt; tool gọi qua lưới không mang số tiền.
- Số tiền chỉ được xét khi agent tự khai `amount_usd` qua `company_approval_request` — agent khai
  sai thì ma trận không biết (`enforced: false` cho số tiền do agent tự khai).
- Điều cấm trong hiến chương là chỉ dẫn trong AGENTS.md, chưa có guard runtime riêng (plugin
  `clawcompany-guard` hiện chỉ chặn lộ tên model).
- `allowed_skills` chưa nối vào chọn seat.
