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

## M2e.2 — Luật cứng cưỡng chế lúc chạy

- Bảng `company_rules` (migration 0048): theo công ty, tuỳ chọn theo chức danh. Loại: `phrase` (cụm từ), `regex`,
  `tool` (công cụ cấm), `approval` (công cụ phải có người duyệt), `pii` (phone/email/cccd/card). Cách xử lý: `revise`,
  `block`, `scrub`, `approve`. `external_only` = chỉ áp khi gửi ra ngoài. `source=charter` + `source_ref` = chỉ số điều
  cấm trong hiến chương mà luật thực thi; màn hình chỉ ra điều cấm nào **mới chỉ là chữ**.
- Bảng `rule_violations`: mỗi lần bắt được (hook, hành động, trích đoạn đã che PII, run/session). Vi phạm → Hộp việc
  người quản lý của ghế (`rule_violation`, gộp theo ghế). Tỷ lệ tuân thủ ghế = lượt chạy không vi phạm / tổng lượt (30 ngày).
- Cưỡng chế ở **guard plugin** (OpenClaw 2026.9.8, đã đọc docs trong container `docs/plugins/hooks/*`):
  `before_agent_finalize` → `{action:"revise", retry}`; `message_sending` → `{cancel:true}` hoặc `{content}`;
  `before_tool_call` → `{block, blockReason}` / `{requireApproval}`. Plugin nhận luật qua `config.patch`
  chuỗi `plugins.entries.clawcompany-guard.config.rulesJson` (đổi `plugins.entries.*` chỉ nạp lại plugin runtime,
  không restart gateway). Plugin báo vi phạm về `POST /api/guard/violations` với `x-guard-token` (HMAC từ JWT_SECRET).
  Danh sách công cụ của chức danh (`allowedCompanyTools`) cũng được plugin chặn ở `before_tool_call`.
- Cưỡng chế ở **cổng MCP** (`/api/mcp` tools/call): luật tool/approval; luật chữ cho tool gửi ra ngoài
  (`company_delegate_external`) — chặn, hoặc che PII trong tham số rồi mới gửi.
- Regex chung một nguồn cho Python và JS (escape riêng, cấm cờ nội tuyến); test chạy node trên JSON do Python biên dịch.
- AGENTS.md của ghế có chức danh có mục "## Luật cứng (hệ thống cưỡng chế…)" — giữ chữ để model biết trước.
- API: `GET/POST /api/team/rules`, `PATCH/DELETE /api/team/rules/{id}`, `POST /api/team/rules/test`,
  `POST /api/team/rules/sync`, `GET /api/team/rules/compiled`. UI: Đội ngũ → tab "Luật cứng".
- Giới hạn thật: phát hiện bằng mẫu chữ, không hiểu nghĩa (câu hứa hoàn tiền viết khác mẫu sẽ lọt); `revise` tối đa 1
  lần mỗi lượt (sau đó plugin không chặn tiếp ở finalize — lớp `message_sending` vẫn chạy cho tin ra kênh).
