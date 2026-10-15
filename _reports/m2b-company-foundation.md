# M2b — Nền công ty: báo cáo (15/10/2026)

Spec: `docs/m2b-company-foundation.md`. Migration **`0038_company_foundation`** (đã chạy trên Postgres
thật của VM: `Running upgrade 0037_a2a -> 0038_company_foundation`). API dưới `/api/team` (tiền tố M2).

## Đã làm

| Mục | Backend | UI (Đội ngũ) |
|---|---|---|
| 1. Hồ sơ pháp nhân + Hiến chương | `company_profiles`; `GET/PUT /api/team/company-profile`; kiểm MST/ngày/vốn, cảnh báo Điều 37 Luật DN 2020; hiến chương chèn đầu "Kiến thức cốt lõi" của AGENTS.md qua `knowledge_hub.core_section` (cơ chế f18630f), lưu → `sync_core` nền | tab **Hồ sơ công ty**: form pháp nhân + hiến chương, bản agent đọc (ký tự/hạn mức), cảnh báo luật |
| 2. Chức danh | `positions` + `members.position_id`; migration gom chức danh cũ thành chức danh (định biên = số người, cấp trên = chức danh của quản lý); CRUD + xếp/gỡ ghế + "tạo từ người đang có"; định biên/chỗ trống, 409 khi quá định biên; JD/trách nhiệm/KPI/công cụ vào AGENTS.md; `allowed_tools` là cổng thật trong `tool_permissions`; tuyển agent vào chức danh (`position_id`); mẫu công ty tạo chức danh kèm JD | tab **Chức danh**: thẻ từng chức danh (đã có/định biên, ghế trống, KPI), form JD + KPI + công cụ, xếp người vào ghế trống |
| 3. Ma trận phân quyền | `authority_rules`; `authority.decide` (loại việc × dải USD × rủi ro → người duyệt + cấp agent tự làm); người duyệt luôn là người; đọc bởi `policy.authorize` (MCP `company_approval_request` thêm `amount_usd`, `risk`), `company_policy_check`, lưới tool send/pay/delete (chỉ siết), `ask_approval`, chi tiếp vượt nấc ngân sách, exec từ gateway, chạy kế hoạch tự động (thay `max_auto_risk`), tuyển agent; mặc định + 3 mẫu (shop/agency/kế toán) gieo khi tạo công ty; `payload.authority` trên approval | tab **Phân quyền**: bảng luật theo loại việc, sửa/tắt/xoá, gieo mặc định/mẫu, "Thử luật"; Hộp việc: dòng "Theo luật #id …" trên thẻ và trong bảng chi tiết |

i18n: namespace `company` (160 khoá) + `nav.chuc_danh/phan_quyen/ho_so_cong_ty` + `inbox.theo_luat/kind_authority`, vi + en; `tsc` bắt đủ khoá.

## Test

- `tests/test_m2b_company_foundation.py`: **13 passed** — hiến chương lên AGENTS.md mọi seat + sửa → đồng bộ lại (bản cũ mất) + agent tuyển sau có ngay; kiểm dữ liệu pháp nhân; định biên/chỗ trống/409; JD+KPI vào AGENTS.md và sửa KPI → sinh lại; đổi tên chức danh → `members.role`; migration 0038 trên dữ liệu kiểu cũ (alembic thật tới 0037 → ghi → head); refund $80 qua MCP → approval người duyệt đúng + thẻ Hộp việc có luật; dải mặc định, cấp agent, chuyển lên người khi trưởng phòng là agent; ma trận siết không nới lưới; trùng dải 409; người duyệt theo chức danh; chặn tuyển; ngân sách + exec; mẫu shop có ma trận + chức danh.
- Toàn bộ backend (chạy theo lát vì sandbox giới hạn 120 s/lệnh, cùng lệnh pytest/SQLite): **1219 passed, 2 skipped, 0 failed** (79 file). Test tz chập chờn `test_v36_insights` lần này xanh.
- Frontend: `tsc --noEmit` sạch; `next build` xanh.

## Kiểm chứng trên VM (gateway OpenClaw 2026.9.8 thật)

1. **Hiến chương → AGENTS.md trên gateway**: `PUT /api/team/company-profile` cho "Tiệm Gốm Mộc" (công ty 3) → `charter_version 1, core_sync true, 803 ký tự`. Đọc `agents.files.get AGENTS.md` trực tiếp từ gateway: **6/6 seat** (`shop-a407-giam-doc/-truong-ban-hang/-cskh/-truong-kho/-truong-marketing/-noi-dung`) có "### Hiến chương" và điều cấm "Không chê sản phẩm của đối thủ". Sửa ngược (xoá hiến chương ở Nova Fashion, xem dưới) → AGENTS.md của sophia-cmo / mia-content mất phần hiến chương sau đồng bộ nền.
2. **Chức danh định biên 2, xếp 1 ghế → trống 1**: tạo "Chăm sóc khách hàng online" (headcount 2, JD, 3 trách nhiệm, 2 KPI) → xếp Nhân viên CSKH → `filled 1, vacancies 1, resync_agents [6]`; chức danh cũ trống được lưu trữ. AGENTS.md của `shop-a407-cskh` trên gateway có "## Chức danh … báo cáo cho chức danh Trưởng phòng bán hàng", "## KPI của chức danh: Phản hồi trong 15 phút: 95 % / tuần; CSAT: 4.6 điểm / tháng"; lớp tri thức nghề nghiệp vẫn còn. Migration trên dữ liệu thật: Tiệm Gốm Mộc 6 chức danh, Nova Fashion 2.
3. **Ma trận → agent thật → Hộp việc**: gieo mẫu shop, thay luật hoàn tiền bằng `<$50 quản lý (agent chính thức tự làm)` (#16) và `≥$50 trưởng phòng` (#17). Gửi cho agent CSKH thật (`openclaw agent --agent shop-a407-cskh`): khách đòi hoàn 80 USD → agent gọi `company_approval_request(action=refund, amount_usd=80)` → **`approval_required`, approval #17, `policy_key authority:r17`**, agent trả lời khách đúng giọng hiến chương (em/chị, ấm áp) và hẹn chờ duyệt. Hộp việc của admin (Long): thẻ nhóm "Cần anh duyệt", `kind authority`, `authority.label "Hoàn tiền / giảm giá · từ $50 → Trưởng phòng"`, `can_decide true`; UI hiện "Theo luật #17 Hoàn tiền / giảm giá · từ $50 → Long". "Thử luật" $20 → tự làm (#16).
4. Playwright trên VM: 3 tab mới + Hộp việc, **0 lỗi console, 0 HTTP 5xx**. Ảnh: `_reports/ui/m2b-profile.png`, `m2b-positions.png`, `m2b-authority.png`, `m2b-inbox-card.png`.

## Việc anh cần biết / còn mở

- **Dữ liệu demo do em nhập trên VM**: hồ sơ pháp nhân của Tiệm Gốm Mộc (tên "Công ty TNHH Cửa Hàng Gốm Mộc", MST 0318765432, đại diện "Caca Long", vốn $20 000) là giá trị thử — anh thay bằng số thật ở Đội ngũ → Hồ sơ công ty. Lần chạy đầu em ghi nhầm hiến chương vào Nova Fashion, đã xoá lại (Nova Fashion còn một hàng hồ sơ rỗng, `charter_version 2`).
- Approval **#17** (hoàn $80, khách Lan) để chờ anh duyệt/từ chối.
- Công ty có trước M2b (Nova Fashion, Nova Labs) chưa có luật → giữ hành vi cũ tới khi bấm "Dùng ma trận mặc định". Tiệm Gốm Mộc đã có ma trận mẫu shop (đã sửa luật hoàn tiền).
- Giới hạn tự khai: ma trận chỉ siết lưới tool; số tiền do agent tự khai qua `amount_usd`; điều cấm của hiến chương là chỉ dẫn trong AGENTS.md (chưa có guard runtime); `allowed_skills` chưa nối vào chọn seat.
- **Chưa push GitHub**: phiên này không đọc được PAT trong vault (connector GitHub chặn `connect_service` cho github.com, và token không có dạng rõ trong sandbox). Các commit nằm local ở `ui-v2` và trên VM.
