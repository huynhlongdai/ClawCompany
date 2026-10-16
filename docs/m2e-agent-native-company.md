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

## M2e.3 — Hợp đồng dữ liệu vào/ra chuẩn

Bài toán: người làm mỗi lần một kiểu (thiếu trường, sai định dạng, quên lý do) → bước sau phải đọc văn bản và đoán.
Công ty agent: mỗi chức danh / bước quy trình có **hợp đồng dữ liệu**; kết quả sai schema bị trả về tự động.

- Bảng `io_contracts` (migration 0049): theo công ty, `position_id` tuỳ chọn (đầu ra chuẩn của ghế → AGENTS.md),
  gắn bước quy trình bằng `process_steps.contract_id`. `input_schema` / `output_schema` = **tập con JSON Schema**
  (type, properties, required, enum, minimum/maximum, minLength/maxLength, pattern, format email|date|date-time|uri,
  items, minItems/maxItems, additionalProperties, description) — khoá khác bị từ chối khi lưu (422) thay vì bỏ qua
  im lặng. `acceptance` = [{text, field?, op?, value?}]: có field/op thì máy kiểm (cùng phép so sánh với điều kiện bước),
  chỉ có text thì reviewer đọc. `max_attempts` (1–10, mặc định 3), `outcome_field` (trường thành kết quả bước),
  `version` tăng khi schema/tiêu chí/số lần đổi. Mẫu: Đơn hoàn tiền {order_id, amount_usd, reason, decision,
  customer_message}, Xác nhận đơn hàng, Bài đăng sản phẩm, Báo cáo ngày.
- `task_contracts`: hợp đồng của một việc — **ảnh chụp** schema/tiêu chí lúc giao (sửa hợp đồng không đổi luật của việc
  đang chạy), `input_json` + `input_errors`, `attempts`, `status` open|accepted|escalated. `task_outputs`: mỗi lần nộp
  (hợp lệ hay không, lỗi, via mcp|api|runtime). `process_step_runs.output_json`: kết quả đạt chuẩn của bước.
- Việc sinh từ bước có hợp đồng: bước gốc nhận ngay đầu vào lần chạy; bước sau nhận lúc **tới lượt** = đầu vào lần
  chạy + kết quả các bước đứng trước. Mô tả việc có mục "## Hợp đồng dữ liệu" (trường, tiêu chí, dữ liệu vào).
- MCP `company_task_submit_output(task_id, output)` (tool 32): sai → `{valid:false, status:rework, errors:[{path,
  message}], attempts_left}`; việc đang Chờ duyệt/Xong bị trả về Đang làm; nộp từ ngoài lượt chạy → đánh thức ghế
  (`changes_requested`). Hết lượt → `escalated`: việc Bị chặn + Hộp việc `output_escalated` cho **người** đầu tiên trong
  chuỗi `services/escalation.py` (chức danh cấp trên → quản lý → trưởng phòng → chủ). Đạt → ghi sổ `result`, ghi bước,
  `outcome_field` → `step<N>.outcome`.
- MCP `company_process_step_outcome(task_id, outcome)` (tool 33): agent ghi kết quả bước để rẽ nhánh.
- Cưỡng chế: agent gọi `company_task_status` sang review/done khi chưa đạt → `contract_output_required`. Lượt chạy kết
  thúc (complete → review) mà chưa đạt → một lần nộp hỏng "chưa nộp kết quả": còn lượt → việc về Cần làm + đánh thức
  lại; hết lượt → Bị chặn + leo thang. Người (UI/API) vẫn chuyển trạng thái được — quyết định của người thắng máy.
  Hai tool giao kết quả không bị danh sách công cụ của chức danh tắt (`tool_permissions.ALWAYS_ALLOWED`).
- Điều kiện bước: thêm `step<N>.output.<trường>` (UI: chọn trường của hợp đồng bước trước).
- Tỷ lệ đúng chuẩn = lần nộp hợp lệ / tổng lần nộp (gồm "chưa nộp") theo ghế / chức danh / hợp đồng + tỷ lệ đạt ngay
  lần đầu → KPI `output_conformance_rate` (%), scorecard (`output_conformance_rate`, `rule_compliance_rate`).
- AGENTS.md: mục "## Hợp đồng dữ liệu (đầu ra chuẩn…)" của chức danh (hợp đồng gắn chức danh + hợp đồng các bước do
  chức danh làm); sinh lại khi tạo/sửa/lưu trữ hợp đồng hoặc khi lưu quy trình có bước gắn hợp đồng.
- API: `GET/POST /api/team/contracts`, `PATCH/DELETE /api/team/contracts/{id}`, `POST /api/team/contracts/{id}/validate`,
  `GET/POST /api/team/tasks/{id}/contract`, `POST /api/team/tasks/{id}/output`. UI: Đội ngũ → tab "Hợp đồng dữ liệu"
  (bảng trường ↔ JSON, tiêu chí, thử kết quả, tỷ lệ theo ghế/chức danh, lần nộp gần đây); Quy trình: chọn hợp đồng cho bước,
  điều kiện theo trường kết quả, lần chạy hiện kết quả + trạng thái hợp đồng.
- Giới hạn thật: kiểm cấu trúc + tiêu chí có field; chất lượng câu chữ (lịch sự, đúng chính sách) vẫn do review đọc.

## M2e.4 — Vận hành 24/7

- Ghế **agent** luôn trực: không giờ làm, không nghỉ phép, không lễ (không có hàng lịch; API sửa lịch/nghỉ của agent → 422).
- Ghế **người** (migration 0050): `seat_schedules` (giờ theo tuần `{"0": [["08:00","17:30"]], …}` 0 = thứ Hai, múi giờ
  mặc định Asia/Ho_Chi_Minh, `observe_holidays`), mặc định T2–T6 08:00–17:30, T7 08:00–12:00; `seat_leaves` (nghỉ theo
  ngày: phép năm / ốm / khác); lễ lấy `public_holidays` của tổ chức (ngày làm bù = làm như thứ Hai).
- **SLA** `sla_policies`: gắn đúng một nơi — bước quy trình (thắng) hoặc chức danh; `first_response_minutes`
  (việc chuyển Đang làm) và/hoặc `resolution_minutes` (Xong). `sla_timers`: hạn = phút **trực** của ghế nhận việc
  (`add_working_minutes`: agent = đồng hồ thật, người = chỉ phút trong giờ làm, bỏ nghỉ phép/lễ). Đồng hồ bật khi bước
  tới lượt (process_map) hoặc beat thấy việc mở của ghế có SLA chức danh; `task_lifecycle.transition` đóng đồng hồ.
- Beat `sla.tick` mỗi 60 giây: bật đồng hồ còn thiếu; quá hạn → `breached` + leo thang một lần tới NGƯỜI đầu tiên của
  `escalation.chain` + Hộp việc `sla_breach` (ưu tiên cao) + ghi sổ; việc chưa bắt tay mà người nhận ngoài giờ → chuyển
  agent cùng chức danh. `POST /api/team/sla/tick` chạy ngay một nhịp.
- **Ngoài giờ** (`after_hours_routes`): việc bước quy trình / có SLA, trạng thái Cần làm, giao người đang ngoài giờ →
  có agent cùng chức danh: chuyển (`rerouted`, đồng hồ SLA tính lại theo agent, Hộp việc `after_hours` báo người, đánh thức
  agent); không có: giữ người, `queued` + "người xử lý lúc HH:MM" (sổ việc + Hộp việc); người trực lại → hàng chờ đóng.
  Chọn ghế cho bước quy trình: ghế đang trực trước, rồi ít việc mở nhất.
- **Độ phủ** `GET /api/team/coverage`: lưới 7×24 mỗi chức danh (ô = số agent / số người trực ≥ 30 phút trong giờ đó),
  giờ có người trực / 168, ghế (trong giờ / ngoài giờ / trực lại lúc), hàng chờ (việc chưa bắt tay + việc xếp hàng ngoài
  giờ), tỷ lệ đạt SLA 30 ngày (tách agent / người), đồng hồ gần đây, việc tới ngoài giờ.
- KPI `sla_attainment_rate` (% đồng hồ đóng đúng hạn; quá hạn rồi mới xong vẫn tính trễ).
- **Giao ban sáng** có mục "Ca đêm của agent (18:00 hôm trước → 08:00)": việc agent xong, lượt chạy, chi phí USD, số việc
  ngoài giờ đã chuyển cho agent, số việc đang chờ người.
- API: `GET /api/team/coverage`, `GET/PUT /api/team/seats/{id}/schedule`, `POST /api/team/seats/{id}/leaves`,
  `DELETE /api/team/leaves/{id}`, `GET/POST /api/team/sla-policies`, `PATCH/DELETE /api/team/sla-policies/{id}`,
  `POST /api/team/sla/tick`. UI: Đội ngũ → tab "Vận hành 24/7".
- Giới hạn thật: lưới độ phủ dựa trên lịch tuần mẫu (nghỉ phép/lễ hiện ở danh sách ghế, không trừ vào lưới); "phản hồi
  đầu" đo bằng trạng thái việc, không đo tin nhắn đầu tiên gửi khách trên kênh chat; `sla/tick` thủ công chạy cho mọi công
  ty trên máy (giống beat).
