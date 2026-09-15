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

### WP-2.1 Đọc hồ sơ seat

- **Việc:** endpoint gộp trả về: hàng `agents`/`members`, entry từ `agents.list`, 5 file
  workspace qua `agents.files.get` (kèm `hash`), và `agent.identity.get`.
- **Xong khi:** một seat hiện đủ 7 bộ phận, và mỗi trường ghi rõ nguồn (`db` hay `gateway`).
- **Kiểm chứng:** test hành vi + ảnh màn hình trong `_reports/ui/`.
- **Chú ý:** trả luôn `hash` ra frontend — Phase 2.2 cần nó để ghi có điều kiện.

### WP-2.2 Ghi hồ sơ seat (6 tab)

- **Việc:** tab Hồ sơ / Tính cách / Công việc / Năng lực / Quyền / Hạn mức. Tab 1–3 ghi file
  bằng `agents.files.set` + `expectedHash`; tab 4–6 ghi config bằng WP-1.2.
- **Xong khi:** sửa `SOUL.md` trong UI rồi hỏi lại agent, giọng trả lời đổi theo.
- **Kiểm chứng:** một vòng thật, có ghi lại trước/sau. Và một test cho xung đột: hai lần
  ghi với `expectedHash` cũ → lần hai nhận `agent_file_conflict`, UI hiện "ai đó vừa sửa,
  tải lại".
- **Bắt buộc:** đếm ký tự trên UI theo `bootstrapMaxChars` (20 000/file) và
  `bootstrapTotalMaxChars` (60 000). Vượt thì OpenClaw **cắt âm thầm**.

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

### WP-4.1 Service chọn seat

- **Việc:** `services/dispatch_policy.py` thuần: (task, seats, tải, ngân sách) → (seat, lý do).
  Lọc theo phòng ban → kỹ năng → `lifecycle='active'` → tải → hạn mức.
- **Xong khi:** lý do chọn được lưu vào `company_events`, quản lý đọc được "vì sao việc này
  giao cho seat đó".
- **Kiểm chứng:** test hành vi cho 6 tình huống, gồm "không seat nào đủ điều kiện" (phải trả
  lời rõ, không được chọn bừa).

### WP-4.2 Hàng đợi: hai việc một seat

- **Việc:** thử hai `chat.send` song song vào cùng session; chọn `messages.queue.mode` phù
  hợp cho ngữ cảnh công ty (tôi nghiêng về `followup`, không `steer`: chen ngang giữa một
  việc đang chạy là sai về nghiệp vụ).
- **Xong khi:** hành vi được ghi lại thành tài liệu, và ClawCompany hoặc xếp hàng chủ động
  hoặc trả về "seat đang bận, hẹn lượt".
- **Kiểm chứng:** `_reports/queue-behaviour.md` với log thật. **Đây là một trong ba chỗ
  chưa kiểm chứng đã ghi ở mục 8** của `ARCHITECTURE_TREE.md`.

### WP-4.3 Vòng đời task đủ trạng thái

- **Việc:** chạy một task có follower từ đầu để `runtime_stream` chuyển
  `complete → review` và `error → blocked`.
- **Xong khi:** cả hai đường chuyển trạng thái được chứng minh bằng event thật.
- **Kiểm chứng:** đây là việc số 3 trong mục "Việc tiếp theo" của `HANDOFF.md`, còn nợ.

### WP-4.4 Ngân sách chặn được thật

- **Việc:** nối `budget_envelopes` vào đúng lúc gửi lệnh: seat hết hạn mức thì `chat.send`
  không được gửi, task chuyển `blocked` kèm lý do.
- **Xong khi:** một seat bị chặn vì hết tiền, không phải bị chặn vì code lỗi.
- **Kiểm chứng:** test hành vi + một vòng thật với hạn mức đặt thấp có chủ ý.
- **Phụ thuộc:** WP-1.4 (phải biết số tiền nào là thật trước khi chặn theo nó).

---

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
