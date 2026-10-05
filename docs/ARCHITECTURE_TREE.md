# Cây kiến trúc ClawCompany — module, chức năng, logic

> Tài liệu này trả lời đúng một câu hỏi: **để "số hoá một công ty thật thành các agent
> phối hợp làm việc", cần những module nào, mỗi module làm gì, logic ra sao, và phần nào
> OpenClaw đã làm sẵn còn phần nào ClawCompany phải tự làm.**
>
> Khác với 25 file `architecture-v*.md` trong cùng thư mục: những file đó mô tả *đã xây
> gì theo từng version*. File này mô tả *hệ thống nên có hình gì*, rồi đối chiếu với hiện
> trạng. Nơi nào tôi chưa kiểm chứng, tôi ghi `CHƯA KIỂM CHỨNG` thay vì viết trôi chảy.

**Nguồn chứng cứ cho phần OpenClaw:** docs chính thức trong package
`openclaw@2026.9.4` (`/tmp/oc/node_modules/openclaw/docs/`, 1252 file md) — cụ thể
`concepts/{agent,agent-loop,soul,system-prompt,memory-architecture,dreaming,multi-agent,delegate-architecture,queue,context}.md`,
`gateway/protocol/rpc-*.md`, `gateway/config-agents/*.md`, `tools/{skills,creating-skills,exec-approvals}.md`,
`gateway/config-extensions.md`. Mọi định danh viết trong backtick là trích nguyên văn.

---

## 0. Sửa một mệnh đề sai đang nằm trong code

`backend/app/runtime/openclaw_protocol.py` (dòng 12) ghi:

> "There is no `agents.create` / `agents.run` RPC pair. Agents are config…"

Nửa sau đúng, nửa đầu **sai với 2026.9.4**. Docs `gateway/protocol/rpc-talk-config-and-agents.md`
liệt kê rõ:

| RPC | Làm gì | Ghi chú từ docs |
| --- | --- | --- |
| `agents.create` / `agents.update` / `agents.delete` | "manage agent records and workspace wiring" | tạo seat từ xa, không cần sửa file |
| `agents.list` | liệt kê agent entries gateway thấy | có filter `kind` |
| `agents.files.list` / `agents.files.get` / `agents.files.set` | đọc/ghi **bootstrap workspace files** (`AGENTS.md`, `SOUL.md`, `IDENTITY.md`, `USER.md`, `MEMORY.md`) | `agents.files.set` nhận `expectedHash`; lệch hash thì từ chối với `details.type = agent_file_conflict` và trả `details.currentHash` |
| `agents.workspace.list` / `agents.workspace.get` | duyệt workspace read-only, phân trang | `operator.read`; chặn symlink escape; không lộ path host |
| `agent.identity.get` | identity hiệu dụng của agent/session | |
| `config.get` / `config.patch` / `config.apply` / `config.schema` / `config.schema.lookup` | đọc & ghi `openclaw.json` qua API | `config.schema.lookup` trả `reloadKind` ∈ `restart` \| `hot` \| `none` |

**Hệ quả kiến trúc, và đây là góp ý số một của tôi:** toàn bộ màn hình "cấu hình AI employee"
trong ClawCompany **không cần** SSH hay sửa `openclaw.json` bằng tay. Nó là một form gọi
`config.patch` + `agents.files.set`. `expectedHash` cho ta optimistic concurrency y hệt
`row_revision` mà v28→v30 đã dựng cho phía database — hai cơ chế cùng triết lý, ghép được.

`agents.run` thì đúng là không có: chạy việc vẫn là `sessions.create` → `chat.send` →
`sessions.messages.subscribe`, đúng như adapter hiện tại đang làm.

---

## 1. Đường ranh: OpenClaw sở hữu gì, ClawCompany sở hữu gì

Đây là quyết định kiến trúc quan trọng nhất của cả dự án. Chọn sai ranh giới thì hoặc ta
xây lại thứ đã có (tốn công vô ích), hoặc ta tưởng OpenClaw lo rồi mà thật ra không ai lo
(lỗ hổng sản phẩm).

| Năng lực | Chủ sở hữu | Bằng chứng / lý do |
| --- | --- | --- |
| Vòng lặp suy nghĩ, gọi tool, stream | **OpenClaw** | `concepts/agent-loop.md` |
| Danh tính & tính cách một agent | **OpenClaw** (file) + ClawCompany (UI ghi file) | `SOUL.md`, `IDENTITY.md` |
| Bộ nhớ **cá nhân** của agent | **OpenClaw** | 5 tầng, SQLite riêng từng agent |
| Học tập / hợp nhất kiến thức cá nhân | **OpenClaw** (dreaming, cron `0 3 * * *`) | `concepts/dreaming.md` |
| Nén ngữ cảnh, quản context window | **OpenClaw** | `concepts/compaction.md` |
| Phê duyệt việc chạy lệnh nguy hiểm | **OpenClaw** (engine) + ClawCompany (UI/chính sách) | `exec.approval.*`, `approval.resolve` |
| Sandbox, giới hạn tool | **OpenClaw** | `agents.defaults.sandbox.*`, `tools.allow/deny` |
| **Sơ đồ tổ chức** (công ty→phòng ban→người) | **ClawCompany** | `agents.entries` là registry *phẳng*: không có `reportsTo`, không có `department` |
| **Điều phối việc** (ai làm task nào) | **ClawCompany** | `subagents.delegationMode: "prefer"` chỉ là *"prompt guidance only"* |
| **Cân bằng tải, xếp hàng theo năng lực** | **ClawCompany** | OpenClaw chỉ có cap `maxConcurrent`, không có balancer |
| **Tri thức dùng chung của team/công ty** | **ClawCompany** | cross-agent memory search **đã bị xoá** ở v2026.8.1; mỗi agent chỉ search chỉ mục của chính nó |
| **Phân quyền tri thức** (ai đọc được gì) | **ClawCompany** | provenance của OpenClaw chỉ phân loại `owner/agent/untrusted/system`, không có role |
| **Đo hiệu suất, chi phí, KPI** | **ClawCompany** | OpenClaw không có metric per-agent nào ngoài diagnostics hàng đợi |
| **Lưu vết kiểm toán cấp tổ chức** | **ClawCompany** | `audit.activity.list` chỉ là metadata ledger của gateway |
| **Retention / quyền được lãng quên** | **ClawCompany** | `memory forget` là per-agent, per-session; docs nói thẳng "not a certificate that no related information remains" |

Đọc bảng này theo một câu: **OpenClaw là "bộ não và đôi tay của một cá nhân". Tất cả những
gì biến nhiều cá nhân thành một *công ty* — sơ đồ, quyền, điều phối, tri thức chung, đo
lường, kiểm toán — là phần của ClawCompany.** Repo hiện có 163 bảng phần lớn đang đứng ở
đúng phía này, nên tin tốt là ranh giới đã chọn đúng; vấn đề là nhiều chỗ chưa nối dây.

---

## 2. L0 — Lõi runtime: cấu hình OpenClaw và đưa vào UI

### L0.1 Kết nối gateway (`ClawCompany ↔ OpenClaw`)

**Chức năng.** Một client WebSocket dài hạn, role `operator`, giữ scope tối thiểu cần dùng.

**Logic.** Handshake `ConnectParamsSchema` (`minProtocol`/`maxProtocol`, `client.id` thuộc
enum đóng, `auth.token`) → `hello-ok` → subscribe. Mọi frame `type: "req"`, đọc `ok` +
`payload`. Đã kiểm chứng với gateway thật, 16 test pin hình dạng frame.

**Trạng thái:** VERIFIED (`backend/app/runtime/openclaw_native.py`, `_reports/openclaw-protocol-audit.md`).

**Việc còn thiếu:** mới dùng ~10 RPC (`sessions.*`, `chat.*`, `exec.approval.*`). Nhóm
`agents.*`, `config.*`, `tools.catalog`, `skills.*`, `usage.cost`, `cron.*` chưa dùng —
tức 9/10 bề mặt điều khiển đang bỏ trống.

### L0.2 Sổ đăng ký cấu hình (Config Registry)

**Chức năng.** Đọc schema sống từ gateway, sinh form, ghi lại có kiểm soát phiên bản.

**Logic đề xuất.**
1. `config.schema` → cache schema (có `title`, `description`, `enum`, `deprecated`, `readOnly`).
2. Render form theo schema, **không** hard-code danh sách field (OpenClaw lên version là schema đổi).
3. Trước khi ghi: `config.schema.lookup` từng path → đọc `reloadKind`. `hot`/`none` thì
   ghi xong dùng ngay; `restart` thì UI phải cảnh báo "cần khởi động lại gateway" **trước**
   khi người dùng bấm Lưu, không phải sau.
4. Ghi bằng `config.patch` + `baseHash` (docs: nhận `raw`, `baseHash`, `sessionKey`).
   Mảng muốn *thay* chứ không *trộn* thì phải khai trong `replacePaths` — ví dụ
   `agents.entries.*.skills`. Đây là cái bẫy dễ mất dữ liệu nhất của cả nhóm này.
5. Rate limit thật: `config.patch` bị chặn `30 per 60s`. UI không được gọi mỗi lần gõ phím.

**Trạng thái:** MISSING toàn bộ. Đây là module nền cho mọi màn hình cấu hình ở L1.

### L0.3 Nhà cung cấp model & chi phí

**Chức năng.** Khai báo provider, danh mục model, hạn mức, và quy model về tiền.

**Logic.** `models.providers.<id>` (đã chạy thật với CometAPI, key qua SecretRef
`{source:"file"}` nên không nằm trong `openclaw.json`). Đọc `models.list` để UI có danh
mục thật; `usage.cost` + `sessions.usage` để lấy chi phí theo agent/session.

**Trạng thái:** provider VERIFIED; đọc `models.list`/`usage.cost` MISSING — hiện
`agents.cost_30d` và `agent_daily_stats.cost` tính từ `usage_events` do ClawCompany tự
ghi, tức **hai nguồn số tiền song song chưa đối chiếu nhau lần nào**.

### L0.4 Bí mật (Secrets)

`secrets.providers.local` + SecretRef đã chạy. Còn `secrets.store.*` (`operator.admin`)
chưa dùng; ClawCompany có bảng `secret_references`/`secret_grants` riêng. Cần một quyết
định: **ai là nguồn sự thật cho secret** — hiện tại là hai kho không nói chuyện với nhau.

### L0.5 Cầu phê duyệt (Approval Bridge)

**Chức năng.** Một quản lý người bấm "Duyệt" trong ClawCompany thì lệnh thật trên gateway
được chạy — không phải hai hàng đợi rời nhau.

**Logic.** Sự kiện `exec.approval.requested` → tạo `approvals` row (kèm `policy_key`,
`risk`, evidence) → người duyệt trong UI → gọi `exec.approval.resolve`
(scope `operator.approvals`, first-answer-wins) → nhận `exec.approval.resolved` đối chiếu
lại. Backfill `exec.approval.list` khi vừa kết nối để không mất yêu cầu phát sinh lúc mất mạng.

**Trạng thái:** CODED (`services/approval_bridge.py`, `approval_backfill.py`,
`grant_ledger.py`) nhưng **chưa từng chạy trọn một vòng với một lệnh exec thật** — đây là
một trong hai lỗ hổng nghiêm trọng nhất còn lại.

### L0.6 UI cho L0 — "OpenClaw Runtime"

Một trang, bốn tab: Kết nối (health/`status`/protocol), Model & chi phí, Bí mật, Phê duyệt.
Trang `/app/openclaw` đã tồn tại nhưng chỉ hiển thị trạng thái; chưa ghi được gì.

---

## 3. L1 — Agent: một "nhân sự AI" gồm những gì

Đây là phần user hỏi kỹ nhất: *"agent sẽ như nào, có những gì và kết nối với lõi ra sao,
học tập rồi kiến thức, tư duy, soul, bộ nhớ"*. Câu trả lời ngắn: **một AI employee =
một `agents.entries.<id>` + 5 file trong workspace + một hàng `agents` trong Postgres.**
Ba thứ đó phải đồng bộ, và ClawCompany là bên chịu trách nhiệm đồng bộ.

### 3.1 Bảy bộ phận của một agent, ánh xạ sang thuật ngữ nhân sự

| # | Bộ phận | Nằm ở đâu trong OpenClaw | Tương đương nhân sự | UI ClawCompany |
| --- | --- | --- | --- | --- |
| 1 | **Danh tính** | `agents.entries.<id>.identity.{name,theme,emoji,avatar}` + `IDENTITY.md` | Tên, chức danh, ảnh thẻ | Tab "Hồ sơ" |
| 2 | **Soul (tính cách)** | `<workspace>/SOUL.md` | Phong cách làm việc, giọng điệu | Tab "Tính cách" |
| 3 | **Bản mô tả công việc** | `<workspace>/AGENTS.md` | JD + SOP + quy tắc nội bộ | Tab "Công việc" |
| 4 | **Tư duy (cách nghĩ)** | `thinkingDefault`, `model`/`fallbacks`, `fastModeDefault`, `compaction.*`, `contextLimits.*` | Trình độ, tốc độ vs độ sâu | Tab "Năng lực" |
| 5 | **Bộ nhớ** | `MEMORY.md`, `USER.md`, `memory/YYYY-MM-DD.md`, standing intents, `openclaw-agent.sqlite` | Kinh nghiệm tích luỹ | Tab "Bộ nhớ" |
| 6 | **Công cụ & quyền** | `tools.{profile,allow,deny}`, `skills`, `sandbox.*`, `tools.exec.mode` | Quyền truy cập hệ thống | Tab "Quyền" |
| 7 | **Hạn mức** | `timeoutSeconds`, `modelPolicy.allow`, `heartbeat.*`, `subagents.*` | Ngân sách & khối lượng việc | Tab "Hạn mức" |

Sáu tab này là **một màn hình duy nhất** cần xây, và nó là màn hình quan trọng nhất của
sản phẩm: nó biến "cấu hình một agent" thành "tuyển và huấn luyện một nhân viên".

### 3.2 Chi tiết từng bộ phận, kèm logic và cạm bẫy

**(1) Danh tính.** `identity.mentionPatterns` và `identity.ackReaction` **tự suy ra** từ
`name`/`emoji`, nên UI chỉ cần 4 field. `agentId` thì bất biến: tôi đề nghị quy ước
`emp-<member_id>` để luôn suy được từ database, không bao giờ trùng, và đọc log là biết
ngay seat của ai. Hiện `agents.runtime_agent_id` là chuỗi tự do (`"dev"`) — đúng cho một
seat thí nghiệm, sai khi có 50 seat.

**(2) Soul.** Inject vào Project Context **mọi session**, trừ subagent session (bị lọc để
tiết kiệm context). Giới hạn: `bootstrapMaxChars` 20 000/file và `bootstrapTotalMaxChars`
60 000 tổng — vượt thì **bị cắt âm thầm**. UI phải đếm ký tự và cảnh báo, nếu không thì
tính cách nhân viên bị cắt mất nửa mà không ai biết. Docs khuyên thẳng: *"Short beats long.
Sharp beats vague."*

**(3) AGENTS.md.** Đây là chỗ đặt SOP thật của công ty. Một cạm bẫy đã ghi trong docs:
mục `## Tools` trong `AGENTS.md` **không** kiểm soát quyền dùng tool, nó chỉ là lời khuyên.
Quyền thật nằm ở `tools.allow/deny`. Viết "không được xoá file" trong AGENTS.md mà không
chặn ở policy thì đó là **hàng rào sơn vẽ**. Nguyên tắc chung của OpenClaw, trích
`system-prompt.md`: *"Safety guardrails in the system prompt are advisory, not enforcement."*

**(4) Tư duy.** `thinkingDefault` có thang 8 mức
(`off|minimal|low|medium|high|xhigh|adaptive|max`). `model` khai bằng **string** là chế độ
nghiêm (không fallback); khai `{primary, fallbacks}` mới có dây chuyền dự phòng. Với một
công ty, tôi đề nghị: seat cấp quản lý (`Nina`) dùng model mạnh + `thinkingDefault: high`;
seat thừa hành dùng model rẻ + `medium`; và **mọi seat đều phải có `modelPolicy.allow`**
để một prompt injection không đổi được sang model đắt gấp 20 lần.

**(5) Bộ nhớ — 5 tầng, trích nguyên văn `memory-architecture.md`:**

| Tầng | Bề mặt | Ai ghi | Khi nào vào prompt |
| --- | --- | --- | --- |
| Instructions | `AGENTS.md` | **chỉ người** | luôn luôn, đầu session |
| Curated core | `MEMORY.md`, `USER.md` | dreaming, hoặc người yêu cầu trực tiếp | đầu session, có hạn mức |
| Episodic | `memory/YYYY-MM-DD.md`, transcript | agent trong lúc làm việc | **không bao giờ**; chỉ tìm khi cần |
| Prospective | standing intents (SQLite) | tool `intent` | chỉ khi trigger khớp |
| Review | `DREAMS.md` | các pha dreaming | không bao giờ; để **người** đọc |

Ba con số cần biết: standing intent mặc định cooldown 24h, tối đa 3 lần bắn, hết hạn sau
90 ngày. `USER.md` có hạn mức riêng 4 000 ký tự, nhỏ hơn các file khác.

**(6) Học tập (dreaming).** Bật sẵn (`plugins.entries.memory-core.config.dreaming.enabled`
mặc định `true`), chạy cron `"0 3 * * *"`, ba pha Light → REM → Deep. **Chỉ pha Deep mới
ghi vào `MEMORY.md`.** Xếp hạng bằng 6 tín hiệu có trọng số: relevance 0.30, frequency 0.24,
query diversity 0.15, recency 0.15, consolidation 0.10, conceptual richness 0.06 — và phải
vượt cả ba ngưỡng `minScore`, `minRecallCount`, `minUniqueQueries`. Chốt an toàn:
`maxPriorEntryLossFraction` 0.25 (một lần viết lại xoá hơn 25% mục cũ thì bị từ chối) và
`maxPromotedSnippetTokens` 160. Có taint gate cấu trúc: ứng viên gốc `untrusted` hoặc
`system` bị loại **trước khi** tính điểm, không phải trừ điểm.

*Góp ý:* **đừng xây lại cái này.** Việc của ClawCompany là (a) đọc `DREAMS.md` qua
`agents.workspace.get` và hiện thành "Nhật ký học tập" trong tab Bộ nhớ, (b) thêm một cửa
**duyệt trước khi thăng cấp**: quản lý xem `openclaw memory promote` (chạy khô, chưa
`--apply`) rồi mới cho ghi vào `MEMORY.md`. Một nhân viên tự sửa hồ sơ kinh nghiệm của
mình lúc 3 giờ sáng mà không ai xem là rủi ro quản trị, không phải tính năng.

**(7) Quyền & sandbox.** Mặc định `sandbox.mode: "off"` — nghĩa là **agent đọc được file
host ngoài workspace bằng đường dẫn tuyệt đối**. Docs nói rõ workspace *"is the default
cwd, not a hard sandbox"*. Với sản phẩm bán cho doanh nghiệp, tôi đề nghị ép mặc định:
`sandbox.mode: "all"`, `scope: "agent"`, `workspaceAccess: "rw"`,
`docker.network: "none"` và chỉ mở `"bridge"` cho seat nào thật cần Internet. Đồng thời
`tools.exec.mode` nên là `"ask"` (allowlist + hỏi khi lệch) thay vì `"full"`.

### 3.3 Logic "tuyển dụng" một AI employee (luồng cần xây)

```
UI: Tuyển nhân sự AI  (chọn phòng ban, chức danh, mẫu từ marketplace)
 └─ 1. members  INSERT (member_type='agent', department_id, role, manager_id)
 └─ 2. agents   INSERT (runtime_agent_id = 'emp-<member_id>', lifecycle='provisioning')
 └─ 3. gateway  agents.create           → tạo entry + workspace wiring
 └─ 4. gateway  config.patch            → model, thinking, tools, sandbox, hạn mức
 └─ 5. gateway  agents.files.set × 4    → IDENTITY.md, SOUL.md, AGENTS.md, USER.md
 └─ 6. gateway  agents.list             → ĐỐI CHIẾU: entry có thật, model đúng
 └─ 7. gateway  sessions.create + chat.send "tự giới thiệu"  → nghiệm thu
 └─ 8. agents   UPDATE lifecycle='active'
```

Bước 6 và 7 là chỗ repo hay bỏ: hiện `agent_provisioning_jobs` (v8) tạo hàng job nhưng
**không đối chiếu lại với roster sống của gateway**. Bài học đã phải trả giá trong lượt
trước: `ask_nina` từng xếp seat theo `lifecycle.desc()` nên chọn "detached" trước "active";
chỉ hết khi đối chiếu với `list_agents()` thật.

Ngược lại, luồng **cho thôi việc** phải có: `lifecycle='detached'` → `agents.delete` →
quyết định giữ hay xoá workspace (đây là dữ liệu công ty, không phải rác) → thu hồi API
key → ghi audit. v31 đã ghi nhận "un-archive một member không phục hồi trạng thái runtime"
— tức luồng ngược đang hở.

### 3.4 Trạng thái L1

| Chức năng | Trạng thái |
| --- | --- |
| Bảng `agents`, `members`, seat mapping | VERIFIED |
| Dispatch task → `chat.send` → phản hồi thật | VERIFIED (task #5, có tool use) |
| Hồ sơ AI employee 7 tab | **MISSING** (UI hiện chỉ hiện model/cost/success_rate) |
| Ghi `SOUL.md`/`AGENTS.md` từ UI | **MISSING** |
| Tạo seat qua `agents.create` | **MISSING** (đang giả định phải sửa file) |
| Đọc `DREAMS.md`, duyệt promote | **MISSING** |
| Đối chiếu roster khi provisioning | STUB |
| `success_rate`, `cost_30d` | CODED — đã có nguồn v36 nhưng `success_rate` để `null` khi không đo được (đúng), và chưa đối chiếu với `usage.cost` của gateway |

---

## 4. L2 — Phòng ban & Team: nhiều agent làm việc cùng nhau

**Sự thật cần nói trước:** OpenClaw **không có** khái niệm phòng ban, cấp trên, hay điều
phối. `agents.entries` là danh sách phẳng; `openclaw agents list --tree` chỉ hiện *ai tạo
ra ai*, không phải sơ đồ tổ chức. `subagents.delegationMode: "prefer"` được docs gọi đúng
tên: *"prompt guidance only"*. Vậy **toàn bộ L2 là phần ClawCompany phải tự làm**, và đây
mới là giá trị riêng của sản phẩm.

### L2.1 Sơ đồ tổ chức (Org Graph)

**Chức năng.** Công ty → phòng ban → team → thành viên (người **và** agent), kèm đường
báo cáo.

**Logic.** `departments` + `members.manager_id`. Ràng buộc cần có mà hiện chưa có: chống
chu trình trong `manager_id`, và giữ `members.organization_id` đồng nhất với
`department → company → organization` (hiện tenancy phải join qua `company`, còn
`members.organization_id` là cột trực tiếp — hai đường có thể lệch nhau).

**Trạng thái:** bảng VERIFIED; ràng buộc toàn vẹn STUB; UI Org Map CODED.

### L2.2 Điều phối việc (Work Dispatch) — trái tim của L2

**Logic đề xuất, 6 bước:**

1. **Nhận việc**: task có `department_id` hoặc `project_id`, chưa có người làm.
2. **Chọn seat**: lọc theo phòng ban → kỹ năng (`skills`) → `lifecycle='active'` → tải
   hiện tại → hạn mức chi phí còn lại. *OpenClaw không làm bước này.*
3. **Kiểm tra hàng đợi**: một session chỉ chạy một run. Request thứ hai rơi vào
   `messages.queue.mode` — `steer` (mặc định, chèn vào run đang chạy), `followup`,
   `collect`, `interrupt`. Cap mặc định 20 message/session.
4. **Gửi**: `sessions.create` (nếu chưa có) → `chat.send` với `idempotencyKey` gồm **vân
   tay nội dung** (bài học đã trả giá: khoá theo task id làm lượt gửi thứ hai bị
   `chat-request-conflict`).
5. **Theo dõi**: `sessions.messages.subscribe` (param `key`) → ghi `runtime_events` →
   cập nhật trạng thái task (`complete → review`, `error → blocked`).
6. **Kết toán**: ghi `usage_events`, cập nhật `agent_daily_stats`, đóng hoặc chuyển tiếp.

**Trạng thái:** bước 1,4,5 VERIFIED; bước 2 **MISSING** (hiện gán tay); bước 3 chưa từng
được kiểm ở tình huống hai việc cùng lúc; bước 6 CODED.

**Góp ý:** bước 2 nên là một service thuần (`dispatch_policy.py`) nhận vào (task, danh
sách seat, tải, ngân sách) trả ra (seat, lý do chọn). Thuần thì test được bằng hành vi, và
"lý do chọn" phải lưu lại — quản lý sẽ hỏi "tại sao việc này giao cho nó".

### L2.3 Tri thức dùng chung của team

**Đây là lỗ hổng lớn nhất của tầng OpenClaw.** Trích `multi-agent.md`: *"Builtin memory
does not search another agent's transcript corpus; each agent searches only its own
configured memory."* Cross-agent search **đã bị xoá** ở v2026.8.1. Có một lối tạm là
`memory.search.extraPaths` trỏ nhiều agent vào một thư mục Markdown chung, nhưng không có
khoá ghi, không có provenance chéo, không có phân quyền.

**Kết luận thiết kế:** tri thức tổ chức **phải** nằm ở ClawCompany (`knowledge_documents`,
`knowledge_chunks`, `shared_knowledge_spaces`, `knowledge_grants` — v16 đã có bảng), và
agent chạm vào nó **qua tool**, không qua bộ nhớ OpenClaw. Nghĩa là:

- bộ nhớ cá nhân (kinh nghiệm riêng của một seat) → OpenClaw, per-agent, dreaming lo;
- tri thức công ty (SOP, quyết định, tài liệu) → Postgres + pgvector, có `knowledge_grants`
  phân quyền theo phòng ban, agent gọi `company.knowledge.search`.

Cách chia này còn giải quyết luôn hai thứ OpenClaw không có: **quyền đọc theo phòng ban**
và **thu hồi/lãng quên ở cấp tổ chức**.

**Trạng thái:** bảng + vector search CODED; `knowledge_grants` chưa được kiểm chứng là
**thực sự chặn**; phía agent chưa gọi được vì tool chưa đăng ký (xem L2.5).

### L2.4 Trao đổi & bàn giao giữa agent

ClawCompany đã có `agent_messages`, `collaboration_rooms`, `room_turns`,
`delegation_contracts`, `artifact_handoffs` (v10/v16). OpenClaw phía nó có
`sessions_spawn`/`sessions_yield` với hạn mức rõ: `maxSpawnDepth` 1–5,
`maxChildrenPerAgent` 5, `subagents.maxConcurrent` 8, findings cap 4 096 ký tự, mỗi kết
quả 512 ký tự.

**Góp ý về ranh giới:** dùng `sessions_spawn` cho **việc phụ ngắn trong một lượt** (một
seat cần tra cứu song song), dùng `delegation_contracts` của ClawCompany cho **bàn giao
thật giữa hai nhân sự** (có người chịu trách nhiệm, có SLA, có audit). Đừng mô hình hoá
"phòng ban" bằng subagent tree: nó chết theo run, không có danh tính, không đo được, và
docs thừa nhận "channel-visible progress across yield remains follow-up work".

### L2.5 Cầu tool: cho agent đọc được số liệu công ty

**Đây là việc chặn đứng giá trị của cả sản phẩm ngay lúc này.** Nina trả lời bằng kiến
thức chung vì chưa có tool nào đọc dữ liệu ClawCompany.

**Phát hiện quan trọng:** không cần viết plugin OpenClaw. `gateway/config-extensions.md`
cho khai báo MCP server:

```json5
{ mcp: { servers: { "clawcompany": {
  url: "https://api.clawcompany.internal/mcp",
  transport: "streamable-http",
  headers: { Authorization: "Bearer ${CLAWCOMPANY_TOKEN}" },
  toolFilter: { include: ["company_*"] },
  enabled: true } } } }
```

và docs nói rõ: đổi cấu hình MCP chỉ retire những server *đã đổi*, **không cần khởi động
lại gateway**.

**Góp ý mạnh: đừng đăng ký 192 tool.** Ba lý do, cái đầu là chặn cứng:

1. Schema tool **tính vào context window** (`concepts/context.md`), và
   `skills.limits.maxSkillsPromptChars` mặc định 18 000. 192 schema sẽ ăn hết ngân sách
   ngữ cảnh trước khi agent đọc được một dòng dữ liệu nào.
2. Model chọn sai tool tỉ lệ thuận với số tool. 192 lựa chọn là công thức gây lỗi.
3. 192 endpoint ấy là bề mặt *quản trị* (runner, cosign, telemetry export) — không phải
   thứ một nhân viên cần để làm việc.

Tôi đề nghị **một bộ 24 tool** chia 6 nhóm, đúng những gì một nhân viên cần:

| Nhóm | Tool | Vì sao nhân viên cần |
| --- | --- | --- |
| Bối cảnh | `company_context`, `company_org_lookup`, `company_calendar` | tôi là ai, báo cáo cho ai, hôm nay có gì |
| Công việc | `company_tasks_list`, `company_task_get`, `company_task_status`, `company_task_comment`, `company_project_get` | xem và cập nhật việc |
| Tri thức | `company_knowledge_search`, `company_knowledge_get`, `company_sop_get`, `company_decision_log` | tra SOP, tra quyết định cũ |
| Phối hợp | `company_message_send`, `company_handoff_create`, `company_artifact_create`, `company_artifact_get` | giao việc, nộp sản phẩm |
| Kiểm soát | `company_approval_request`, `company_policy_check`, `company_budget_check` | xin phép trước khi làm việc rủi ro |
| Báo cáo | `company_metric_read`, `company_report_submit`, `company_event_emit` | báo số, báo tiến độ |

`tool-contracts.json` 192 mục **giữ lại** làm danh mục nội bộ, nhưng chỉ 24 cái được đưa
vào `toolFilter.include`. Con số 192 là tài sản nếu dùng đúng chỗ: nó chứng minh mọi tool
đều trỏ tới endpoint có thật (đã đối chiếu 192/192).

**Trạng thái:** MISSING. Ưu tiên cao nhất.

### L2.6 Đo hiệu suất phòng ban

`agent_daily_stats` (v36) đã cho số theo ngày từng agent. Còn thiếu: cộng dồn theo phòng
ban, so sánh giữa các seat, và một lời thừa nhận đã ghi sẵn trong service —
`company_events` **không mang `agent_id`**, nên kết quả việc chỉ quy được về agent khi
payload có `runtime_agent_id`. Muốn đo hiệu suất tin được thì phải sửa chỗ phát sinh
event, không phải sửa chỗ đọc.

---

## 5. L3 — Công ty & Holding

| Module | Chức năng | Logic | Trạng thái |
| --- | --- | --- | --- |
| **Company Factory** | Dựng công ty từ mẫu: phòng ban, seat, SOP, quy trình | `company_provisioning_jobs` (v8) theo mẫu marketplace | CODED, chưa chạy đầu-cuối |
| **Chính sách & quyền tự chủ** | Việc nào agent tự làm, việc nào phải xin | `autonomy_policies`, `permission_policies`, `policy.py` | CODED; v18 tự khai `enforced: false` ở vài chỗ — phải kiểm |
| **Ngân sách** | Hạn mức chi theo công ty/phòng ban/seat, chặn khi vượt | `budget_envelopes`, `budget_ledger_entries` + `modelPolicy.allow` phía OpenClaw | CODED; **chưa nối** với chi phí thật từ `usage.cost` |
| **Mục tiêu & chu kỳ** | OKR, mission, chu kỳ vận hành | `executive_goals`, `missions`, `operating_cycles` | CODED |
| **Lịch** | Họp, hạn chót, mốc | `calendar_events` (v36) | VERIFIED |
| **Báo cáo** | Báo cáo điều hành, chuỗi chỉ số | `reports`, `metric_samples` (v36) | VERIFIED, có tự khai `points_are_measurements` |
| **Kiểm toán** | Ai làm gì, lúc nào, bằng quyền gì | `audit_events`, `company_events`, event replay (v34) | CODED; **thiếu retention policy** (v31 đã ghi nhận) |
| **Khách hàng & cổng ngoài** | Portal, gán agent cho khách | `customers`, `customer_portal_users` | CODED |
| **Marketplace** | Mẫu nhân sự/team/công ty/skill | `marketplace_templates` | CODED |
| **Billing** | Gói, đăng ký, biên lợi nhuận | `subscriptions`, `billing_invoices`, `metering.py` | CODED |

**Góp ý về L3:** đừng xây thêm module mới ở tầng này. 10/11 module đã có bảng và endpoint;
cái chúng thiếu là **nối với số thật và kiểm chứng**. Ví dụ cụ thể: ngân sách sẽ vô nghĩa
cho tới khi nó chặn được một `chat.send` vì seat hết hạn mức — hiện chưa có đường dây nào
từ `budget_envelopes` tới lúc gửi lệnh.

---

## 6. Cây module tổng hợp

```
ClawCompany
├── L0  Lõi runtime (OpenClaw)                         [nền tảng]
│   ├── L0.1 Kết nối gateway ...................... VERIFIED
│   ├── L0.2 Config registry (schema→form→patch) .. MISSING   ★ chặn L1
│   ├── L0.3 Model & chi phí ...................... phần VERIFIED
│   ├── L0.4 Secrets .............................. phần VERIFIED
│   └── L0.5 Cầu phê duyệt ........................ CODED, chưa chạy thật
├── L1  Nhân sự AI (agent = seat)                      [giá trị lõi]
│   ├── L1.1 Danh tính ............................ MISSING (UI)
│   ├── L1.2 Soul / tính cách ..................... MISSING (UI)
│   ├── L1.3 Mô tả công việc (AGENTS.md) .......... MISSING (UI)
│   ├── L1.4 Tư duy (model, thinking, compaction) . MISSING (UI)
│   ├── L1.5 Bộ nhớ 5 tầng ........................ MISSING (UI)
│   ├── L1.6 Học tập (dreaming + cửa duyệt) ....... MISSING
│   ├── L1.7 Công cụ, quyền, sandbox .............. MISSING (UI)
│   ├── L1.8 Hạn mức & ngân sách seat ............. STUB
│   ├── L1.9 Tuyển / cho thôi việc ................ STUB (không đối chiếu roster)
│   └── L1.10 Đánh giá hiệu suất seat ............. CODED (v36)
├── L2  Phòng ban & Team                               [OpenClaw KHÔNG có]
│   ├── L2.1 Sơ đồ tổ chức ........................ CODED
│   ├── L2.2 Điều phối việc ....................... STUB    ★ chọn seat chưa có
│   ├── L2.3 Tri thức dùng chung .................. CODED, quyền chưa kiểm
│   ├── L2.4 Trao đổi & bàn giao .................. CODED
│   ├── L2.5 Cầu tool (MCP, 24 tool) .............. MISSING  ★ chặn giá trị
│   └── L2.6 Hiệu suất phòng ban .................. STUB
└── L3  Công ty & Holding                              [đã có bảng, thiếu dây]
    ├── Factory · Chính sách · Ngân sách · OKR
    ├── Lịch · Báo cáo · Kiểm toán
    └── Khách hàng · Marketplace · Billing
```

★ = ba việc chặn: không có L0.2 thì không có màn hình cấu hình nào; không có L2.5 thì agent
không đọc được dữ liệu công ty; không có L2.2 thì không gọi được là "điều phối".

---

## 7. Mười góp ý kiến trúc

1. **Đăng ký 24 tool, không phải 192.** Schema tool ăn context window; `maxSkillsPromptChars`
   mặc định 18 000. Giữ 192 làm danh mục, lọc bằng `toolFilter.include`.
2. **Dùng MCP server thay vì viết plugin OpenClaw.** Một endpoint `/mcp`, đổi cấu hình
   không cần restart gateway. Business logic ở lại phía ClawCompany — đúng như
   `openclaw-company-bridge/README.md` đã chủ trương.
3. **Cấu hình agent bằng `config.patch` + `agents.files.set`, tuyệt đối không sửa
   `openclaw.json` bằng tay.** Dùng `expectedHash` để hai người cùng sửa không ghi đè nhau,
   và đọc `reloadKind` để biết trước có phải restart.
4. **`agentId = emp-<member_id>`.** Suy được từ database, không trùng, đọc log là biết seat
   của ai. Đổi sớm, càng để lâu càng khó.
5. **Bộ nhớ cá nhân để OpenClaw lo; tri thức tổ chức thì ClawCompany lo.** OpenClaw đã xoá
   cross-agent memory search — đừng cố vá lại bằng `extraPaths`. Tri thức chung cần phân
   quyền và thu hồi, đó là việc của database có `knowledge_grants`.
6. **Thêm cửa duyệt trước khi dreaming ghi vào `MEMORY.md`.** Chạy `memory promote` khô,
   quản lý xem, rồi mới `--apply`. Nhân viên tự sửa hồ sơ kinh nghiệm lúc 3 giờ sáng là rủi
   ro quản trị.
7. **Bật sandbox mặc định.** `mode: "all"`, `workspaceAccess: "rw"`, `docker.network: "none"`,
   `tools.exec.mode: "ask"`. Mặc định của OpenClaw là `off`, và workspace *không* phải hàng
   rào cứng — đường dẫn tuyệt đối đi ra ngoài được.
8. **Đừng viết luật trong `AGENTS.md` rồi tưởng đã chặn.** Docs nói thẳng guardrail trong
   prompt là *advisory, not enforcement*. Mỗi luật nghiệp vụ cần một chốt thật: tool policy,
   exec approval, hoặc kiểm tra phía API.
9. **Heartbeat là tiền.** Mặc định 30 phút/lần cho mỗi seat. 50 seat × 48 lần/ngày là hoá
   đơn không ai ký. Bật heartbeat cho duy nhất seat "chief of staff", kèm `activeHours`.
10. **Đối chiếu hai nguồn số tiền.** `usage_events` của ClawCompany và `usage.cost` của
    gateway chưa từng so với nhau. Trước khi dựng ngân sách chặn chi, phải biết hai con số
    lệch bao nhiêu.

---

## 8. Ba chỗ tôi chưa kiểm chứng và sẽ không viết như thể đã biết

1. **Một seat chạy hai việc cùng lúc** sẽ ra sao trong thực tế. Đã đọc mô hình hàng đợi
   (`steer` mặc định, cap 20), chưa chạy thử. Cần một test hai `chat.send` song song.
2. **`knowledge_grants` có thực sự chặn** hay chỉ là bảng ghi. Dạng lỗi này đã gặp ba lần
   trong repo (test grep source, double bỏ qua WHERE) nên tôi cho là phải kiểm bằng hành vi
   mới tin.
3. **Chi phí thật một ngày của một công ty 10 seat.** Chưa có số. Không có số thì mọi thiết
   kế ngân sách chỉ là hình thức.

---

## 9. Đọc tiếp

| File | Nội dung |
| --- | --- |
| `docs/BUILD_PLAN.md` | Chia nhỏ thành gói việc, thứ tự, định nghĩa xong, cách kiểm chứng |
| `HANDOFF.md` | Hiện trạng đã kiểm chứng, nợ kỹ thuật theo mức ưu tiên |
| `_reports/local-runtime.md` | Bằng chứng chạy thật: Postgres, Redis, gateway, 236 endpoint |
| `_reports/openclaw-protocol-audit.md` | Năm lỗi giao thức đã sửa, kèm frame thật |
| `openclaw-company-bridge/tool-contracts.json` | 192 tool contract (danh mục nội bộ) |
