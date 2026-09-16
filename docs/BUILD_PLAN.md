# Kế hoạch triển khai ClawCompany — chia theo gói việc

> Đọc `docs/ARCHITECTURE_TREE.md` trước: file đó là cây module và logic. File này là thứ
> tự làm, mỗi gói đủ nhỏ để làm xong trong 1–3 buổi, kèm **định nghĩa xong** và **cách
> kiểm chứng**. Không gói nào được coi là xong bằng cách đọc code rồi suy ra.

**Luật chung của mọi gói** (kế thừa mục 7 của `HANDOFF.md`):

1. Test bằng hành vi trên database thật (SQLite in-memory hoặc Postgres), không grep source,
   không test double bỏ qua `WHERE`.
2. Endpoint nào `await` thì phải `async def` — lỗi này đã làm `POST /api/v20/tasks/{id}/follow`
   trả 500 suốt nhiều version.
3. Mỗi gói xong thì commit riêng, conventional commit, và cập nhật `HANDOFF.md`.
4. Không thêm router `v37+` nếu việc đó nhét được vào module đã có. 45 router là quá nhiều rồi.

---

## Phase 1 — Mở bề mặt điều khiển (nền cho mọi thứ khác)

Không có phase này thì mọi màn hình cấu hình ở Phase 2 đều phải sửa file bằng tay.

### WP-1.1 Sửa mệnh đề sai về `agents.*` và mở rộng danh mục RPC — ✅ XONG 2026-09-16

- **Việc:** cập nhật `backend/app/runtime/openclaw_protocol.py`: bỏ khẳng định "There is no
  `agents.create`", thêm hằng số cho `agents.{list,create,update,delete}`,
  `agents.files.{list,get,set}`, `agents.workspace.{list,get}`,
  `config.{get,patch,apply,schema,schema.lookup}`, `models.list`, `usage.cost`,
  `tools.catalog`, `skills.status`.
- **Xong khi:** mỗi hằng số có comment trỏ tới file docs upstream đã xác nhận nó.
- **Kiểm chứng:** gọi thật `agents.list` và `config.schema.lookup` trên gateway local,
  lưu log vào `_reports/native-probe-agents.log`.
- **Rủi ro:** scope. `agents.workspace.*` cần `operator.read`, `config.patch` cần
  `operator.admin` — nếu token hiện tại thiếu thì phát hiện ngay ở bước này.
- **Kết quả đo được** (`_reports/native-probe-agents.log`): 8/8 method chỉ đọc
  gọi được trên gateway 2026.9.4 thật, gồm `agents.list`, `config.get`,
  `config.schema`, `models.list`, `tools.catalog`, `skills.status`,
  `usage.cost`, `agent.identity.get`. Mệnh đề *"There is no agents.create"* đã
  được thay, kèm `previous_claim` để đọc lại được vết sửa.
- **Lỗi phát sinh, đã sửa:** `config.schema` trả **2.213.528 byte**, vượt hạn
  mức frame mặc định 1 MiB của thư viện `websockets`, nên lời gọi chết với
  `1009 message too big`. Thêm `settings.openclaw_max_frame_bytes` = 16 MiB.
  Đây là loại lỗi chỉ lộ khi gọi thật.

### WP-1.2 Config Registry service — ✅ XONG 2026-09-16

- **Việc:** `backend/app/services/openclaw_config.py`: cache `config.schema`, đọc
  `reloadKind` theo path, ghi qua `config.patch` với `baseHash`, và **bắt buộc khai
  `replacePaths`** cho mọi path mảng (`agents.entries.*.skills`, `tools.allow`, …).
- **Xong khi:** một hàm `patch(paths_and_values)` trả về `{applied, reload_kind, requires_restart}`;
  từ chối ghi nếu `baseHash` lệch.
- **Kiểm chứng:** test hành vi với gateway thật: đổi `agents.entries.dev.thinkingDefault`,
  đọc lại `config.get` thấy đúng; thử ghi mảng không khai `replacePaths` và xác nhận service
  chặn trước khi gửi.
- **Bẫy đã biết:** rate limit `config.patch` là `30 per 60s`. Service phải gộp thay đổi, UI
  không gọi theo từng lần gõ.
- **Kết quả đo được:** ghi thật `agents.entries.dev.identity.theme` →
  `changedPaths: ["agents.entries.dev.identity.theme"]`, đọc lại `config.get`
  khớp, rồi hoàn nguyên. Ghi lần hai bằng `baseHash` cũ bị gateway từ chối:
  `INVALID_REQUEST — config changed since last load; re-run config.get and
  retry`. **Optimistic concurrency có thật**, không phải lời hứa trong docs.
- **Tin tốt cho Phase 2:** cả 8 path mà màn hình hồ sơ seat cần
  (`agents.defaults.model`, `thinkingDefault`, `agents.entries`,
  `sandbox.mode`, `heartbeat.every`, `compaction.enabled`, `tools.exec.mode`,
  `mcp.servers`) đều là `reloadKind: "hot"` — sửa hồ sơ nhân sự AI **không cần
  khởi động lại gateway**.
- **Chốt đã dựng:** `replacePaths` bắt buộc khi patch làm mất phần tử mảng (chặn
  tại chỗ, trước khi gửi); wildcard bị từ chối theo bản docs nghiêm hơn;
  `allow_restart=False` mặc định; hạn mức ghi đếm theo từng method; `dry_run`
  cho màn hình xem trước. 37 test hành vi, và ba chốt chính đã được kiểm bằng
  mutation — bỏ chốt thì test đỏ.

### WP-1.3 Đóng cầu phê duyệt đầu-cuối

- **Việc:** chạy một lệnh exec thật cần duyệt, đi hết vòng
  `exec.approval.requested` → `approvals` row → UI duyệt → `exec.approval.resolve` →
  `exec.approval.resolved`.
- **Xong khi:** một lệnh bị chặn, rồi được duyệt, rồi chạy — và `audit_events` ghi đủ ba mốc.
- **Kiểm chứng:** `_reports/approval-e2e.md` kèm log frame thật của cả hai chiều.
- **Vì sao ưu tiên:** đây là module "kiểm soát" duy nhất có thật ở tầng runtime. Nếu nó
  không chạy, mọi lời hứa về quyền tự chủ có kiểm soát đều là giấy.

### WP-1.4 Đối chiếu hai nguồn chi phí

- **Việc:** đọc `usage.cost` và `sessions.usage` từ gateway, so với tổng `usage_events` của
  cùng khoảng thời gian, ghi độ lệch.
- **Xong khi:** có một bảng so sánh và một câu kết luận: dùng nguồn nào làm sự thật.
- **Kiểm chứng:** `_reports/cost-reconciliation.md` với số thật, không phải số mẫu.

---

## Phase 2 — Hồ sơ nhân sự AI (giá trị lõi, người dùng thấy ngay)

Đây là màn hình quan trọng nhất của sản phẩm: biến "cấu hình agent" thành "tuyển và huấn
luyện nhân viên".

### WP-2.1 Đọc hồ sơ seat — ✅ XONG 2026-09-16

- **Việc:** endpoint gộp trả về: hàng `agents`/`members`, entry từ `agents.list`, 5 file
  workspace qua `agents.files.get` (kèm `hash`), và `agent.identity.get`.
- **Xong khi:** một seat hiện đủ 7 bộ phận, và mỗi trường ghi rõ nguồn (`db` hay `gateway`).
- **Kiểm chứng:** test hành vi + ảnh màn hình trong `_reports/ui/`.
- **Chú ý:** trả luôn `hash` ra frontend — Phase 2.2 cần nó để ghi có điều kiện.
- **Đã làm:** `services/seat_profile.py` + `GET /api/agents/{id}/profile` (đặt ở
  router `agents`, không mở `/v37`). Mỗi khối mang `sources` nói rõ `db` hay
  `gateway`; `warnings` nói cái gì không đọc được.
- **Đo được trên bản chạy thật** (Postgres + gateway 2026.9.4): seat Nina trả
  đủ 5 file kèm hash, `roster_match: true`, `config.inherited_keys` phân biệt
  giá trị riêng với giá trị thừa hưởng, tổng hồ sơ 9 722/60 000 ký tự.
- **Ba phát hiện chỉ có khi gọi thật:**
  1. `agents.files.list` **bỏ sót `IDENTITY.md`** — nhưng `agents.files.get`
     vẫn đọc được file đó (1 722 byte). Đừng lấy `files.list` làm danh sách
     file sửa được.
  2. `DREAMS.md` bị từ chối (`unsupported file`) — nó thuộc
     `agents.workspace.get`, tức WP-2.4, không thuộc namespace này. Đường dẫn
     vượt workspace (`../../etc/passwd`) cũng bị chặn: allowlist theo tên.
  3. **Cả 4 file của seat Nina vẫn là bản mẫu xuất xưởng của OpenClaw**
     (nội dung "C-3PO"), tức tính cách/JD của seat chưa từng được cấu hình.
     Hồ sơ nay gắn cờ `looks_like_shipped_sample` để UI nói ra.
- **Thêm một lệch nguồn đã phát hiện:** `agents.model` trong database ghi
  `GPT-4.1` còn gateway đang chạy `cometapi/gpt-4o-mini`. Hồ sơ trả
  `model_drift` và cảnh báo thay vì âm thầm chọn một bên.

### WP-2.2 Ghi hồ sơ seat (6 tab) — ✅ XONG 2026-09-16

- **Việc:** tab Hồ sơ / Tính cách / Công việc / Năng lực / Quyền / Hạn mức. Tab 1–3 ghi file
  bằng `agents.files.set` + `expectedHash`; tab 4–6 ghi config bằng WP-1.2.
- **Xong khi:** sửa `SOUL.md` trong UI rồi hỏi lại agent, giọng trả lời đổi theo.
- **Kiểm chứng:** một vòng thật, có ghi lại trước/sau. Và một test cho xung đột: hai lần
  ghi với `expectedHash` cũ → lần hai nhận `agent_file_conflict`, UI hiện "ai đó vừa sửa,
  tải lại".
- **Bắt buộc:** đếm ký tự trên UI theo `bootstrapMaxChars` (20 000/file) và
  `bootstrapTotalMaxChars` (60 000). Vượt thì OpenClaw **cắt âm thầm**.
- **Đã làm:** `PUT /api/agents/{id}/files/{name}` (tab 1-3, `expectedHash` bắt
  buộc; `force` là lựa chọn phải nói ra) và
  `PATCH /api/agents/{id}/config` (tab 4-6, đi qua ConfigRegistry của WP-1.2).
  Khoá ghi được giới hạn **theo tab ở tầng server** — frontend không đáng tin.
  UI: `components/SeatProfile.tsx`, sáu tab, đếm ký tự, khoá nút Lưu khi vượt.
- **Nghiệm thu "giọng có đổi" — đạt 4/4** (`_reports/seat-soul-e2e.md`):
  - trước: *"Tôi là C-3PO, một trợ lý ảo được tạo ra để giúp bạn trong quá
    trình phát triển phần mềm…"*
  - sau khi ghi SOUL.md mới: *"Báo cáo: Tôi là Nina, trưởng phòng chính của
    Nova Holding… — Nina, Nova Holding."*
  - Lưu ý cách đo: phải hỏi trong một **phiên mới**; file bootstrap chỉ được
    nạp lúc dựng prompt, nên hỏi lại trong phiên đang chạy sẽ thấy tính cách cũ
    và dẫn tới kết luận sai.
- **Xung đột hash — đã chứng minh hai tầng:** gateway trả
  `details.type = agent_file_conflict` + `details.currentHash`; API trả **409**
  kèm `current_hash` để client rebase. `OpenClawProtocolError` nay giữ nguyên
  payload lỗi thay vì chuỗi hoá nó (trước đây `details` bị mất).
- **Kiểm chứng UI:** `tools/shot_seat.py` mở trang thật, chụp 6 tab, xác nhận
  0 lỗi console và **chốt hạn mức có hiệu lực trên UI** (vượt 20 050/20 000 thì
  hiện cảnh báo và nút Lưu bị khoá). Ảnh trong `_reports/ui/seat-*.png`.

### WP-2.3 Tuyển & cho thôi việc, có đối chiếu

- **Việc:** luồng 8 bước ở mục 3.3 của `ARCHITECTURE_TREE.md`, gồm bước đối chiếu
  `agents.list` và bước nghiệm thu "tự giới thiệu". Đổi `runtime_agent_id` sang quy ước
  `emp-<member_id>` (migration + backfill seat `dev` hiện có).
- **Xong khi:** tuyển một seat mới hoàn toàn từ UI, seat đó trả lời được, rồi cho thôi việc
  và không còn trong roster.
- **Kiểm chứng:** test hành vi cho provisioning (mock gateway) + một vòng thật ghi log.
- **Nợ phải đóng luôn:** v31 ghi nhận "un-archive một member không phục hồi trạng thái
  runtime" — làm luôn ở gói này.

### WP-2.4 Tab Bộ nhớ & Nhật ký học tập

- **Việc:** hiện 5 tầng bộ nhớ: `MEMORY.md`/`USER.md` (curated), danh sách
  `memory/YYYY-MM-DD.md`, standing intents, và `DREAMS.md` — đọc qua `agents.workspace.get`.
- **Xong khi:** người quản lý đọc được "nhân viên này đã học gì đêm qua" mà không cần SSH.
- **Kiểm chứng:** chạy `openclaw memory promote` (khô) trên seat thật, đối chiếu UI với đầu ra CLI.

### WP-2.5 Cửa duyệt trước khi thăng cấp ký ức

- **Việc:** chặn dreaming ghi thẳng `MEMORY.md`: chạy khô, đưa ứng viên vào `approvals`,
  duyệt xong mới `--apply`.
- **Xong khi:** một mục kiến thức chỉ vào `MEMORY.md` sau khi có người bấm duyệt, và có
  audit ghi ai duyệt.
- **Kiểm chứng:** test hành vi + một vòng thật.
- **Cân nhắc:** nếu `dreaming.enabled: false` để chặn thì mất luôn pha Light/REM. Đọc kỹ
  `concepts/dreaming.md` trước khi chọn cách chặn; đây là gói cần thử nghiệm, không phải gói
  làm theo công thức.

---

## Phase 3 — Cho agent đọc được dữ liệu công ty (bỏ chặn giá trị)

### WP-3.1 MCP endpoint + 24 tool

- **Việc:** `POST /mcp` (streamable-http) trên FastAPI, expose đúng 24 tool ở bảng mục 2.5
  của `ARCHITECTURE_TREE.md`, xác thực bằng API key gắn `Member`, mang `runtime_agent_id`
  mỗi lần gọi.
- **Xong khi:** `tools.catalog` từ gateway thấy đúng 24 tool `company_*`.
- **Kiểm chứng:** hỏi Nina "công ty đang có mấy dự án đang chạy" và nhận **con số đúng với
  database**, kèm log tool call. Đây là phép thử nghiệm thu của cả phase.
- **Ghi chú:** đổi `mcp.servers` **không cần restart gateway** (docs `config-extensions.md`).

### WP-3.2 Phân quyền tool theo seat

- **Việc:** `toolFilter.include` theo vai: seat thừa hành không thấy `company_budget_check`;
  chỉ seat quản lý có `company_approval_request`. Kiểm quyền **hai lớp**: lọc ở gateway và
  kiểm scope ở API.
- **Xong khi:** một seat gọi tool ngoài quyền → API trả 403 kể cả khi gateway đã cho gọi.
- **Kiểm chứng:** test hành vi cho từng vai, không grep config.

### WP-3.3 Kiểm chứng `knowledge_grants` thực sự chặn

- **Việc:** test hành vi trên database thật: seat phòng A tìm tài liệu phòng B → không ra kết quả.
- **Xong khi:** có test đỏ trước khi sửa, xanh sau khi sửa (nếu hoá ra chưa chặn).
- **Vì sao tách riêng:** dạng lỗi "bảng có nhưng không chặn" đã gặp ba lần trong repo.

---

## Phase 4 — Điều phối việc thật

> **Viết lại 2026-09-16** sau hai phép đo: `_reports/work-memory-gap.md` (agent
> nhận prompt 358 ký tự, thiếu 10/12 dữ kiện công ty đã biết) và
> `_reports/room-conductor-e2e.md` (phòng họp là bảng dữ liệu không ai gọi).
> Bản cũ của phase này chỉ có "chọn seat", như thế là quá mỏng để gọi là điều
> phối. Phân tích đầy đủ: `docs/AGENT_WORK_MEMORY.md` và `docs/AGENT_TEAMWORK.md`.

### WP-4.0 Tầng bộ nhớ công việc — ✅ XONG 2026-09-16

- **Việc:** gói ngữ cảnh bảy khối (`services/work_context.py`) + sổ ghi task
  (`services/task_journal.py`, bảng `task_journal_entries`), nối vào
  `agent_dispatch` thay cho `task_brief` bốn dòng.
- **Ranh giới đã chốt:** kinh nghiệm cá nhân ở OpenClaw (`MEMORY.md`, dreaming),
  sự thật về công việc ở ClawCompany. Lý do không phải sở thích: cả năm tầng bộ
  nhớ của OpenClaw đều per-agent hoặc per-session, và tìm kiếm bộ nhớ chéo agent
  **đã bị xoá** ở upstream v2026.8.1.
- **Đo được:** brief cũ 358 ký tự → gói mới 1 310 ký tự trên cùng task. Hỏi lại
  ba câu cần bối cảnh: trước là "không có thông tin" cả ba, sau trả lời được
  "dự án Summer Dress Campaign, tiến độ 68%, còn 14 ngày, hạn 30/09/2026".
- **Chốt thiết kế:** khi vượt ngân sách thì cắt khối 4 → 3 → 5 → 1; **khối 2
  (việc) và 6 (luật) không bao giờ bị cắt** — thiếu bối cảnh thì agent làm kém,
  thiếu luật thì agent làm sai.
- **Một câu trả lời sai đã ghi lại trung thực:** phép đo gửi gói của Mia vào
  seat của Nina nên agent nhầm vai. Bài học: gói phải tới đúng seat của người mà
  khối 1 đang nói về.

### WP-4.1 Phòng họp có chủ toạ chạy thật — ✅ XONG 2026-09-16

- **Việc:** `services/room_conductor.py` — vòng lặp chín bước khiến agent thật
  nói trong phòng của v16, cộng `POST /api/v16/rooms/{id}/chair` và
  `/conduct`, cộng bảng `room_conductor_runs`.
- **Không xây lại máy trạng thái phòng:** v16 đã có thứ tự lượt, quyền chốt, năm
  loại lượt, trần lượt. Nó thiếu đúng một thứ — **không ai gọi agent**. Trong 93
  service chỉ ba chỗ từng gọi `run_agent`.
- **Năm điều kiện dừng:** `chair_closed`, `budget`, `stalled`, `max_turns`,
  `waiting_for_human`. Bộ điều phối **từ chối chạy** nếu phòng chưa đặt
  `cost_budget_usd` — phòng toàn agent không trần tiền là hoá đơn mở.
- **Nghiệm thu thật** (`_reports/room-conductor-e2e.md`): ba lượt, Nina mở đầu →
  Mia đề xuất 5 hook (`proposal`) → Nina chốt bằng `QUYẾT ĐỊNH:` (`decision`) →
  phòng đóng vì `chair_closed`. Seat thứ hai được tạo **qua wire** bằng
  `agents.create`. Mỗi agent dùng phiên riêng của phòng, không lượt nào chạm
  `agent:<id>:main`.
- **Ba lỗi chỉ lần chạy thật phát hiện, đã sửa, đều có test hồi quy:**
  1. "chúng ta **sẽ quyết định**" bị đọc thành "tôi chốt" → nay chỉ dòng bắt đầu
     bằng `QUYẾT ĐỊNH:` mới kết thúc họp. Nguyên tắc: *đừng suy diễn cái có thể
     yêu cầu.*
  2. Chốt chống treo so với lượt **liền trước**, nên vòng lặp luân phiên
     `A B A B` không bao giờ bị bắt → nay so với lượt gần nhất của **chính người
     nói**.
  3. **Nguyên nhân gốc:** `_ask` đọc "message trợ lý cuối cùng" trong một session
     dài, nên khi model chưa kịp trả lời thì nó đọc lại câu cũ. Bằng chứng nằm
     trong số đo: lượt 1 mất 10,09s (hai nhịp poll), lượt 3 chỉ 5,06s và trả về
     đúng từng ký tự câu của lượt 1 → nay chụp vân tay message **trước khi gửi**.
- **Lỗi có sẵn của v16 đã sửa kèm:** `POST /api/v16/rooms` trả về `{}` vì
  `emit_event` commit sau `db.refresh()` làm instance bị expire. Nghĩa là suốt
  từ v16, chưa ai tạo phòng qua API rồi dùng kết quả.

### WP-4.2 Chọn seat theo năng lực và tải

- **Việc:** `services/dispatch_policy.py` **thuần**: `(task, seats, tải, ngân
  sách) → (seat, lý do chọn)`. Lọc theo phòng ban → kỹ năng → `lifecycle='active'`
  → tải → hạn mức còn lại.
- **Xong khi:** lý do chọn được lưu vào `company_events`; quản lý đọc được "vì
  sao việc này giao cho seat đó".
- **Cảnh báo phạm vi:** OpenClaw không có metric hiệu suất per-agent.
  `agent_daily_stats` của v36 trả `success_rate: null` khi chưa đo được, và một
  thuật toán phân việc dựa trên `null` chỉ là phân việc theo thứ tự id. Làm
  phần "theo tải" trước, phần "theo năng lực" sau khi có dữ liệu thật.
- **Kiểm chứng:** test hành vi cho 6 tình huống, gồm "không seat nào đủ điều
  kiện" — phải trả lời rõ, không được chọn bừa.

### WP-4.3 Bàn giao gọi được agent — ✅ XONG 2026-09-16

- **Việc:** `services/handoff_dispatch.py` — khi `artifact_handoffs` được tạo với
  `to_member_id` là agent đang hoạt động thì ghi mục `handoff` vào sổ ghi task,
  chuyển chủ việc, tự nhận bàn giao, rồi dispatch.
  `POST /api/v10/artifacts/{id}/handoff` thành `async def` và nhận thêm cờ
  `dispatch`.
- **Bốn câu hỏi mà "chỉ gọi dispatch" không trả lời được, và cách xử lý:**
  1. **Ai là chủ việc sau bàn giao?** Phải gán lại `task.assignee_member_id`.
     Khối 1 của gói ngữ cảnh mở đầu bằng "Bạn là <người được giao>", nên không
     gán lại thì người nhận đọc hồ sơ của người khác — **đúng lỗi đã đo được** ở
     `_reports/work-memory-gap.md`. Đây là chỗ thi hành bài học đó.
  2. **Agent có cần bấm "accept"?** Không, nhưng trạng thái vẫn đi qua
     `accept_handoff` của v10 thay vì tự đặt `status`, để không sinh định nghĩa
     thứ hai của "đã nhận" (lớp lỗi `row_guard.kind` ở v28, `next_speaker` ở v37).
  3. **Bàn giao nào cũng tự tiêu tiền?** Không: cờ của lời gọi → cấu hình
     `openclaw_auto_dispatch` → không chạy. Mọi nhánh **đều trả về `reason`**.
  4. **Không dispatch được thì bàn giao có mất?** Không. Ghi sổ xảy ra **trước**
     khi gọi runtime, nên lịch sử công việc không phụ thuộc vào việc có tiêu
     tiền hay không.
- **Nghiệm thu thật** (`_reports/handoff-dispatch-e2e.md`): một lời gọi API →
  sổ ghi seq 1 (`handoff` từ Nina) + seq 2 (`attempt` của Mia), chủ việc chuyển
  2→4, tự nhận, dispatch vào `agent:mia:company-task-14`. Bốn kiểm tra gói ngữ
  cảnh đều đạt. Rồi hỏi chính Mia: *"Hạn nội bộ là ngày **18/09**. Hook về
  **giảm giá sốc** đã bị loại."* — hai chi tiết **chỉ tồn tại trong
  `instructions` của bàn giao**, không ở tiêu đề task, mô tả hay dự án.
- **Lỗi có sẵn sửa kèm:** `POST /api/v10/artifacts` (và `/messages`,
  `/handoffs/{id}/accept`, `/evaluations`) trả về thiếu `id` — cùng lớp lỗi
  expire-after-commit đã sửa ở `POST /api/v16/rooms`. Nghĩa là chưa ai tạo
  artifact qua API rồi dùng id đó để bàn giao. Đã gộp thành helper `_fresh`.
- 17 test hành vi; ba chốt chính (gán lại chủ việc, ghi sổ, kiểm `lifecycle`)
  đều kiểm bằng mutation — bỏ chốt thì test đỏ.

### WP-4.4 Review hai vòng dùng lại bộ điều phối

- **Việc:** một review là một phòng hai người, `max_turns` nhỏ, chủ toạ là người
  duyệt. Dùng lại `room_conductor` thay vì viết vòng lặp thứ hai.
- **Xong khi:** một artifact đi qua vòng review có agent reviewer thật phát biểu,
  và kết quả vào `repository_reviews`.

### WP-4.5 Vòng đời task đủ trạng thái

- **Việc:** chạy một task có follower từ đầu để `runtime_stream` chuyển
  `complete → review` và `error → blocked`.
- **Xong khi:** cả hai đường chuyển trạng thái được chứng minh bằng event thật.

### WP-4.6 Ngân sách chặn được thật

- **Việc:** nối `budget_envelopes` vào đúng lúc gửi lệnh; seat hết hạn mức thì
  `chat.send` không được gửi, task chuyển `blocked` kèm lý do.
- **Phụ thuộc:** WP-1.4 — phải biết số tiền nào là thật trước khi chặn theo nó.
  Hiện `cost_per_turn_usd` của phòng họp là **ước lượng do caller đưa vào**, và
  hai nguồn tiền chưa từng được đối chiếu.

## Phase 5 — Đóng nợ đo lường (P1 trong HANDOFF)

### WP-5.1 Thay các test dùng double bỏ qua WHERE

- **Việc:** chuyển `test_v27_board_truth.py` (`FakeDb` trả mọi task cho mọi truy vấn) và các
  file cùng dạng sang model ORM thật + SQLite in-memory, theo mẫu `test_v28`/`test_v30`.
- **Xong khi:** không còn file test nào dùng double bỏ qua điều kiện lọc.
- **Kiểm chứng:** mỗi test chuyển đổi phải **đỏ trước** nếu cố tình bỏ mệnh đề `WHERE` trong
  code thật. Test không đỏ được là test không kiểm gì.

### WP-5.2 Xoá các assertion grep source và ghim version

- **Việc:** bỏ mọi assertion đọc source hoặc ghim số cứng theo version. Dạng lỗi này đã
  *bảo tồn* một lỗi P0 thật và đã tái xuất ba lần.
- **Xong khi:** `grep -rn "read_text()" backend/tests/` không còn dòng nào dùng để xác nhận
  hành vi.

### WP-5.3 CI tối thiểu

- **Việc:** pytest, `test_migration_chain`, `next build`, và một job devstack chạy
  `alembic upgrade head` trên Postgres thật.
- **Xong khi:** mỗi push đều chạy, và PR đỏ thì không merge được.

### WP-5.4 Vệ sinh

`conftest.py` + `pyproject.toml`; thay ~2900 `datetime.utcnow()`; retention cho
`company_events`; bỏ shim `services/tasks.py`.

---

## Phase 6 — Vận hành một công ty thật

### WP-6.1 Bật sandbox mặc định cho mọi seat

`mode: "all"`, `scope: "agent"`, `workspaceAccess: "rw"`, `docker.network: "none"`,
`tools.exec.mode: "ask"`. **Xong khi:** một seat thử đọc file ngoài workspace và thất bại.
**Cần:** Docker trong môi trường chạy — hiện sandbox tiếp nhận không có.

### WP-6.2 Chính sách heartbeat theo vai

Tắt heartbeat cho seat thừa hành; bật cho duy nhất seat chief-of-staff kèm `activeHours`.
**Xong khi:** có con số chi phí một ngày trước và sau khi đổi.

### WP-6.3 Chạy thật bằng Docker

`docker compose up` + `alembic upgrade head` + `seed.py`, ghi lại kết quả. Việc số 1 trong
mục "Việc tiếp theo" của `HANDOFF.md`, còn nợ vì sandbox không có Docker.

### WP-6.4 Nhập sơ đồ tổ chức thật

Nhập công ty thật (CSV hoặc form) → sinh phòng ban → sinh seat → gán manager. Đây là lời hứa
gốc của dự án: "build company từ đời thật lên thành các agent". Đặt cuối vì nó cần Phase 2
(hồ sơ seat) và Phase 3 (agent đọc được dữ liệu) đã xong.

---

## Thứ tự và phụ thuộc

```
WP-1.1 ─┬─► WP-1.2 ─────────────► WP-2.2 ─┐
        ├─► WP-1.3                WP-2.1 ─┼─► WP-2.3 ─► WP-2.4 ─► WP-2.5
        └─► WP-1.4 ──────────────────────┐ │
                                         │ │
WP-3.1 ─► WP-3.2 ─► WP-3.3               │ │
   │                                     │ │
   └────────────────► WP-4.1 ─► WP-4.2 ─► WP-4.3
                        │                 │
                        └─► WP-4.4 ◄──────┘  (cần WP-1.4)

Phase 5 chạy song song từ đầu (không phụ thuộc gói nào)
Phase 6 sau Phase 2 + 3
```

**Đường tới hạn:** `WP-1.1 → WP-1.2 → WP-2.1/2.2 → WP-3.1 → WP-4.1`. Năm gói này biến dự
án từ "hạ tầng đã chứng minh chạy được" thành "một công ty số hoá dùng được".

**Nếu chỉ làm được ba gói:** WP-1.1, WP-3.1, WP-2.2. Sau ba gói đó, một người dùng thật
tuyển được nhân viên AI, sửa được tính cách và mô tả công việc của nó, và nó trả lời bằng
số liệu công ty thật chứ không phải kiến thức chung.
