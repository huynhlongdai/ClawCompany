# HANDOFF — ClawCompany

Nguồn sự thật về hiện trạng dự án. README kể lịch sử v4→v35; file này trả lời
"bây giờ đang ở đâu, chạy thế nào, và việc gì tiếp theo".

- Ngày tiếp nhận: **2026-09-15**
- Nguồn: `clawcompany_v35_spend_push.zip` (459 file, không có `.git`)
- Repo: `https://github.com/huynhlongdai/ClawCompany`
- Lượt gần nhất: **WP-1.1, WP-1.2, WP-2.1, WP-2.2, WP-4.0, WP-4.1, WP-4.3 đã xong**
  (2026-09-16) — bề mặt điều khiển OpenClaw đã mở, hồ sơ nhân sự AI đọc/ghi
  được, **tầng bộ nhớ công việc**, **phòng họp có chủ toạ** và **bàn giao gọi
  được agent** đã chạy thật.
  Đọc `docs/AGENT_WORK_MEMORY.md` và `docs/AGENT_TEAMWORK.md` trước khi làm
  tiếp; kế hoạch ở `docs/BUILD_PLAN.md`.
- Service version: `1.26.0` · Migration head: **`0017_v37_work_memory_rooms`**

---

## 1. Dự án này là gì

ClawCompany số hoá một công ty thật thành các agent phối hợp làm việc. Nhân
thực thi là [OpenClaw](https://github.com/openclaw/openclaw) — ClawCompany
không tự chạy model, nó là **control plane** đặt lên trên gateway OpenClaw:
tổ chức, phòng ban, ghế (seat) người hoặc agent, dự án, bảng việc, tri thức,
phê duyệt, chi phí, kiểm toán.

Vòng điều khiển: Founder/Nina → initiative/SLO → runner → thực thi → bằng
chứng → release → quan trắc → sự cố → khắc phục.

## 2. Kiến trúc

```
Next.js 14 (app router, 49 route, 66 console component)
        │  fetch REST, token trong localStorage
        ▼
FastAPI  45 router · 490 endpoint · /api/{v7..v35}
        │
        ├── 93 service module (13.8k dòng) — nơi chứa luật nghiệp vụ
        ├── SQLAlchemy 2.0 · 159 bảng · Alembic 15 migration
        ├── Celery + Redis (worker, beat)
        └── app/runtime/  ← adapter OpenClaw (mock | native | gateway-legacy)
                │
                ▼
        OpenClaw Gateway (WebSocket :18789)

openclaw-company-bridge/tool-contracts.json — 192 tool contract để agent
OpenClaw gọi ngược lại ClawCompany. 192/192 khớp route thật (đã kiểm).
```

Phân lớp theo version (đọc `_reports/inventory.md` để có bảng đầy đủ):

| Nhóm | Version | Nội dung |
| --- | --- | --- |
| Nền tảng công ty | v1–v10 | tổ chức, ghế, dự án, việc, tri thức, event bus, artifact |
| Giao hàng phần mềm | v11–v15 | repo, CI/CD, sandbox, release, runner PKI, telemetry, SRE |
| Đa agent | v16–v18 | team, phòng họp có luật lượt, delegation, knowledge mesh, cockpit ghi |
| Nhân OpenClaw | v19–v26 | giao thức thật, live run, lease, takeover, reconcile, Redis fabric |
| Dữ liệu cho UI | v36 | chuỗi thời gian chỉ số, lịch, số theo ngày của agent, hạn chót dự án, hỏi Nina qua model |
| Tính đúng của bảng | v27–v32 | progress dẫn xuất, guard ghi, lưu trữ dây chuyền, kiểm toán field |
| Vận hành | v33–v35 | khôi phục, replay, đối chiếu chi phí delegation, kênh SSE |

## 3. Cách chạy

### Có Docker (khuyến nghị)

```bash
docker compose up
docker compose exec api python seed.py
# UI http://localhost:3000 · API docs http://localhost:8000/docs
# admin@clawcompany.local / ChangeMe123!
```

`docker-compose.yml` dựng: Postgres (pgvector), Redis, api, worker, beat, web.

### Dựng gateway OpenClaw thật để kiểm chứng (không cần Docker)

Đây là cách mệnh đề "nói được giao thức OpenClaw" được đóng dấu, và là cách
duy nhất phát hiện ra lớp lỗi wire-format mà 89 test không thấy.

```bash
# OpenClaw 2026.9.4 cần Node >= 24.16
curl -fsSL https://nodejs.org/dist/v24.16.0/node-v24.16.0-linux-x64.tar.xz | tar -xJ -C /tmp/nodejs --strip-components=1
export PATH=/tmp/nodejs/bin:$PATH
npm install --prefix /tmp/oc openclaw@2026.9.4
/tmp/oc/node_modules/.bin/openclaw gateway --dev --auth none --bind loopback --port 18789 --allow-unconfigured &

# rồi dò từ phía ClawCompany
cd backend && OPENCLAW_MODE=native OPENCLAW_GATEWAY_WS=ws://127.0.0.1:18789 \
  ../.venv/bin/python ../tools/probe_e2e.py
```

Schema upstream đọc được ngay từ gateway đã cài — dùng nó thay vì suy đoán:

```bash
node -e 'const m=require("/tmp/oc/node_modules/openclaw/dist/gateway/protocol/index.js");
  const s=m.ChatSendParamsSchema; console.log(s.required, s.additionalProperties, Object.keys(s.properties))'
```

Gateway dev không có credential model, nên một lượt chạy sẽ dừng ở
`no authentication source configured for openai`. Đó là giới hạn cấu hình,
không phải giao thức.

### Không có Docker: dựng Postgres + Redis thật ngay tại chỗ

`tools/devstack.py` nhúng PostgreSQL 16 (kèm pgvector) và Redis ở user-space —
không cần Docker, không cần root. Đây là cách toàn bộ tầng dữ liệu của dự án
được kiểm chứng lần đầu.

```bash
.venv/bin/python tools/devstack.py up
eval "$(.venv/bin/python tools/devstack.py env)"
cd backend && ../.venv/bin/python -m alembic upgrade head && ../.venv/bin/python seed.py
bash tools/run_api.sh                      # API 127.0.0.1:8000
.venv/bin/python tools/smoke.py            # 236 endpoint
.venv/bin/python tools/e2e_openclaw.py     # đường dây OpenClaw đầu-cuối
```

### Không có Docker (chỉ chạy test)

**Bắt buộc Python 3.12.** Code dùng `int | None` trong annotation mà
SQLAlchemy đánh giá lúc chạy, nên Python 3.9/3.10 sẽ nổ ngay khi import model.

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r backend/requirements.txt

# test (SQLite, không cần Postgres/Redis)
cd backend && DATABASE_URL="sqlite:///./_test.db" JWT_SECRET=test \
  ../.venv/bin/python -m pytest -q

# frontend
npm install && npx next build
```

## 4. Hiện trạng đã kiểm chứng (không phải đọc code mà suy ra)

| Hạng mục | Trạng thái | Bằng chứng |
| --- | --- | --- |
| Test suite | **780 passed · 0 failed · 1 skipped** | `pytest -q`, 2026-09-16 |
| Bàn giao gọi được agent | **Mia nhận việc và nhắc lại đúng chi tiết chỉ có trong hướng dẫn bàn giao** | `_reports/handoff-dispatch-e2e.md` |
| UI chi tiết công việc | **bấm Bàn giao thật trên UI: sổ ghi 2→4 mục, gói ngữ cảnh 1622→1954 ký tự**, 0 lỗi console | `_reports/ui/task-*.png` |
| Tầng bộ nhớ công việc | **prompt 358 → 1 310 ký tự**, agent trả lời được ba câu trước đó mù | `_reports/work-memory-gap.md` |
| Phòng họp có chủ toạ | **hai agent thật họp 3 lượt, chủ toạ chốt, phòng đóng** | `_reports/room-conductor-e2e.md` |
| `agents.create` qua wire | **tạo được seat `mia` trên gateway thật** | cùng log trên |
| Bề mặt điều khiển gateway | **8/8 method đọc gọi được**, ghi config thật OK | `_reports/native-probe-agents.log` |
| Optimistic concurrency của config | **gateway từ chối baseHash cũ** | cùng log trên |
| Hồ sơ nhân sự AI (đọc) | **gộp 3 nguồn OK**, phát hiện lệch model DB↔gateway | `GET /api/agents/1/profile` trên bản chạy thật |
| Ghi SOUL.md rồi hỏi lại agent | **giọng đổi theo file, 4/4 dấu hiệu** | `_reports/seat-soul-e2e.md` |
| Xung đột ghi file | **gateway trả `agent_file_conflict`, API trả 409** | cùng log trên + `_reports/seat-soul-e2e.md` |
| UI hồ sơ seat, 6 tab | **0 lỗi console**, chốt hạn mức ký tự có hiệu lực | `_reports/ui/seat-*.png` |
| Smoke endpoint trên bản chạy thật | **244/244 OK** | `_reports/smoke.json` |
| Đường dây OpenClaw đầu-cuối qua API | **15/15 bước OK** | `_reports/e2e-openclaw.txt` |
| Lần chạy đầu tiên | 582 passed · 37 failed | `_reports/pytest-first-run.log` |
| Frontend build | **xanh**, 49 route prerender | `npx next build` |
| Bridge contract | **192/192** khớp route thật | `tools/inventory.py` |
| Migration | **đã chạy trên Postgres 16 thật**, 165 bảng, head `0017` | `_reports/local-runtime.md` |
| OpenClaw native | **đã kết nối được gateway thật** (2026.9.4) | `_reports/native-probe-after-fix.log` |
| Postgres + pgvector | **đã chạy thật** (pgserver) | `_reports/local-runtime.md` |
| Redis (lease/registry v21–v26) | **đã chạy thật**, báo `cluster_wide: true` | `_reports/local-runtime.md` |
| Celery worker | **lên được**, đăng ký đủ task | `_reports/local-runtime.md` |
| Frontend `next dev`, 6 route chính | HTTP 200 | `_reports/local-runtime.md` |
| mTLS runner / cosign / OTLP export | **chưa từng kiểm chứng** | cần hạ tầng ngoài |

Trước lượt tiếp nhận này, **chưa một test nào từng được thực thi** — docs
v20→v35 đều ghi "tests written but not executed".

## 5. Đã sửa trong lượt tiếp nhận

Các lỗi code thật đã sửa, mỗi lỗi kèm test canh giữ:

1. **Adapter OpenClaw không nói đúng giao thức** (`26e5a4d`) — năm lỗi
   wire-format, chi tiết ở P0 bên dưới. Đây là lỗi nghiêm trọng nhất: nó phủ
   định mệnh đề "xây trên nền cốt lõi OpenClaw", và không một test nào trong 89
   test của v19→v35 thấy nó.
2. **`live_channel` scope tenant qua cột không tồn tại** (`353c074`).
   `_run_ids()` và `live_tasks()` lọc `Task.organization_id`; bảng `tasks`
   không có cột đó. Mọi lời gọi kênh SSE của v35 nổ `AttributeError` — tính
   năng mới nhất chưa từng chạy được. Sửa bằng join
   `task → project → company`. Test cũ *grep source tìm đúng dòng lỗi*, tức
   nó bảo tồn lỗi thay vì phát hiện; đã thay bằng test hai tenant trên SQLite.
3. **`row_guard` có hai định nghĩa "kind"** (`5bdf642`). `row_guard.kind()`
   dùng tên class, `row_revision.kind_of()` ưu tiên `__entity_kind__`, và
   `compare_and_set` dùng cả hai. Với 5 ORM entity hiện tại chúng trùng nhau
   nên lỗi còn tiềm ẩn — nhưng đây đúng là module v28 dựng lên để guard "có
   hiệu lực". Đã hợp nhất.
4. **Payload approval vi phạm schema đóng của upstream** (`657262a`).
   `exec.approval.resolve` gửi kèm `sessionKey`, không nằm trong
   `ExecApprovalResolveParamsSchema` (`closedObject`), nên bị gateway từ chối.
   Cũng bỏ bộ lọc `sessionKey` mà v24 suy đoán cho `exec.approval.list`.
5. **Chuỗi migration không chạy được trên Postgres** (`5e03242`).
   `alembic_version.version_num` là VARCHAR(32) còn revision id dài tới 42 ký
   tự; và `0001_baseline` tạo sẵn những cột mà 0013/0014 mới được quyền thêm.
   Cả hai đều ẩn với SQLite. Kèm `tests/test_migration_chain.py`.
6. **Không ai đăng nhập được vào bản cài mới** (`99150bb`). `seed.py` tạo
   `admin@clawcompany.local` và README quảng cáo đúng tài khoản đó, nhưng
   `EmailStr` từ chối TLD `.local` → 422; `UserOut.email` cũng vậy nên
   `/auth/me` sẽ 500. Đăng nhập và đọc identity đã lưu nay dùng `StoredEmail`;
   đăng ký vẫn giữ `EmailStr`.
7. **`GET /api/v33/progress/drift` trả 500** (`99150bb`) — `Project.organization_id`
   không tồn tại, đúng cùng lớp lỗi với `live_channel`. Test cũ grep source
   ghim chính dòng lỗi; đã thay bằng kiểm chứng hai tenant.
8. **`assign` trả 200 cho body nó không hiểu** (`99150bb`).
   `TaskAssign.assignee_member_id` có default `None` nên sai tên khoá thành
   "bỏ gán" và trả 200 dù không làm gì.
9. **Frontend chưa từng build được** (`2414256`). `tsconfig.json` không khai
   `baseUrl`/`paths` trong khi 29 file import qua `@/`; `lib/api.ts` khai
   `request<T>` không có default nên 288 lời gọi trả `Promise<unknown>`.

## 6. Nợ kỹ thuật, theo mức ưu tiên

### P0 — ĐÃ ĐÓNG: adapter OpenClaw giờ nói đúng giao thức

Đã sửa và **kiểm chứng với gateway OpenClaw 2026.9.4 thật** (commit `26e5a4d`).
Trước đó: `1008 policy violation — invalid request frame`, không một RPC nào đi
qua nổi. Năm lỗi chặn toàn bộ: frame thiếu `type: "req"`; đọc `result` thay cho
`ok`/`payload`; handshake sai `ConnectParamsSchema` (kể cả `client.id` phải
thuộc enum đóng `GATEWAY_CLIENT_IDS`); subscribe dùng `sessionKey` thay vì
`key`; `chat.send` gửi `metadata` và thiếu `idempotencyKey`.

Nay: `hello-ok` protocol 4, role `operator`, `sessions.create` trả `sessionId`
thật, `chat.send` đi qua tầng giao thức. 16 test hồi quy trong
`tests/test_v35_1_protocol_frames.py` pin hình dạng frame **không cần gateway**.

**Đã đóng luôn phần còn lại** (2026-09-15, vòng bốn): gateway nay có provider
model thật (CometAPI, key đọc từ file ngoài config qua SecretRef). Đo được:
`agent model cometapi/gpt-4o-mini`; dispatch company task #5 cho ra câu trả lời
thật **kèm tool use**; `POST /api/v36/nina/ask` trả `answered: true` trong 6,2
giây. Khởi động gateway bằng `tools/run_gateway.sh`.

Hai lỗi chặn phát hiện nhờ chạy trọn luồng, đã sửa:
- `POST /api/v20/tasks/{id}/follow` **luôn 500**: endpoint khai `def` mà
  `supervisor.follow()` gọi `asyncio.create_task()`, nên FastAPI chạy nó trong
  threadpool không có event loop. Cả tính năng "theo dõi phiên" mà v20→v26
  dựng lên không gọi được qua API của chính nó.
- `idempotencyKey` khoá theo task nên **chặn lượt gửi thứ hai** cho cùng task
  (`chat-request-conflict`). Nay khoá gồm vân tay nội dung.

Còn lại: **agent chưa có tool đọc dữ liệu ClawCompany**. 192 tool contract
trong `openclaw-company-bridge/` chưa được đăng ký với agent trên gateway, nên
Nina trả lời bằng kiến thức chung thay vì đọc số của công ty. Đây là việc kế
tiếp rõ ràng nhất.

### P1 — cách đo đang cho tín hiệu sai

**Test dùng double tự viết bỏ qua điều kiện WHERE.** `FakeDb` trong
`test_v27_board_truth.py` trả về mọi task cho mọi truy vấn. Nghĩa là 608 test
đang xanh cũng phần lớn không kiểm chứng SQL thật. Ba biểu hiện đã gặp:

- test grep source thay vì kiểm hành vi — một trong số đó đã *bảo tồn* lỗi P0;
- assertion ghim số cứng theo version (`"1.23.0"`, `181 tool`) — bằng chứng
  chúng chưa từng chạy;
- fake không có cột mà code thật đọc (`departments.status`, `company_id`).

Phân loại đầy đủ 37 failure: `_reports/test-triage.md`. Suite đã xanh hoàn
toàn (636 passed), nhưng **xanh không đồng nghĩa với đã kiểm chứng**: phần lớn
vẫn chạy trên double. Hai file v28/v30 là mẫu nên noi theo — model ORM thật,
SQLite in-memory, assertion hành vi.

### P2 — ĐÃ ĐÓNG PHẦN LỚN: hạ tầng đã được chứng minh

Postgres 16 + pgvector, Redis, Celery, API, frontend và một gateway OpenClaw
thật đều đã chạy cùng lúc; migration đi hết chuỗi; 236 endpoint xanh; đường dây
dispatch agent đi đầu-cuối. Chi tiết và những chỗ còn hổng:
`_reports/local-runtime.md`.

Còn lại trong P2: mTLS runner, cosign, OTLP export, Firecracker/Kubernetes —
những thứ cần hạ tầng ngoài chứ không phải cấu hình. Và đây **không phải** phép
thử `docker compose up`: nó chứng minh code chạy với Postgres/Redis thật, không
chứng minh file compose đúng.

### P3 — vệ sinh mã nguồn

- Không có `conftest.py`, `pytest.ini`/`pyproject.toml`, không có CI.
- ~2900 `DeprecationWarning`, gần hết là `datetime.utcnow()`.
- `services/tasks.py` là shim deprecate của `agent_dispatch.py`.
- `company_events` không có chính sách retention (v31 đã ghi nhận).
- Un-archive một member không phục hồi trạng thái runtime (v31 đã ghi nhận).
- ~~12 test còn đỏ~~ — đã đóng: `test_v28_write_guards.py` và
  `test_v30_exact_revisions.py` giờ dùng model SQLAlchemy thật trên SQLite
  in-memory, nên `compare_and_set` được kiểm qua conditional UPDATE thật. Test
  lost-race tạo race bằng một UPDATE ngoài luồng và nhận `rowcount = 0` thật —
  lần đầu mệnh đề v28 "guard có hiệu lực, không phải khuyến nghị" được chứng
  minh.

## 7. Nguyên tắc khi làm việc trên repo này

1. **Kiểm chứng, đừng suy ra.** Codebase này có 25 tài liệu kiến trúc rất tự
   tin về những thứ chưa từng chạy. Trước khi tin một mệnh đề trong docs, hỏi
   "cái gì chứng minh điều này?".
2. **Không thêm version mới trước khi đóng P0/P1.** v7→v35 đã có 45 router;
   thêm v36 lên một nền chưa kiểm chứng là chồng nợ lên nợ.
3. **Test bằng hành vi, không bằng grep source.** Repo này đã có một test grep
   source *bảo tồn* lỗi thật.
4. **Đừng sửa test cho xanh.** Mỗi lần đổi assertion phải ghi lý do tại chỗ và
   nói rõ đó là lỗi code hay lỗi test.
5. **Giữ giọng "nói thẳng" của docs cũ.** Điểm mạnh nhất của dự án này là các
   docs tự khai giới hạn (`enforced: false`, `process_local: true`,
   `derivable: false`). Đừng làm mất nó.
6. **Commit theo từng việc hoàn thành**, conventional commit, tiếng Việt được.

## 8. Việc tiếp theo

**Kế hoạch build đầy đủ nay nằm ở hai file, đọc chúng trước danh sách dưới đây:**

- `docs/ARCHITECTURE_TREE.md` — cây module bốn tầng (L0 lõi runtime → L1 nhân sự
  AI → L2 phòng ban → L3 công ty), chức năng và logic từng module, đối chiếu
  ranh giới "OpenClaw lo gì / ClawCompany lo gì" dựa trên docs upstream
  2026.9.4, kèm nhãn hiện trạng và mười góp ý kiến trúc.
- `docs/BUILD_PLAN.md` — 6 phase, ~24 gói việc cỡ 1–3 buổi, mỗi gói có định
  nghĩa xong và cách kiểm chứng. Đường tới hạn:
  `WP-1.1 → WP-1.2 → WP-2.1/2.2 → WP-3.1 → WP-4.1`.

**Đã làm xong WP-1.1 + WP-1.2** (2026-09-16), nên đoạn dưới đây giữ lại làm
lịch sử của quyết định:

Một mệnh đề sai đã được phát hiện và **đã sửa** (gói WP-1.1):
`runtime/openclaw_protocol.py` khẳng định *"There is no `agents.create`"*, nhưng
2026.9.4 có thật `agents.create/update/delete`, `agents.files.get/set` (kèm
`expectedHash` CAS), `agents.workspace.get`, và `config.patch/schema.lookup`.
Nghĩa là **cấu hình agent làm được hoàn toàn từ UI qua gateway**, không phải sửa
`openclaw.json` bằng tay — đây là nền cho toàn bộ màn hình hồ sơ nhân sự AI.

Các việc còn nợ từ lượt trước, đã được gộp vào kế hoạch trên:

1. Chạy thật bằng Docker: `docker compose up` + `alembic upgrade head` +
   `seed.py`, ghi lại kết quả. (Sandbox tiếp nhận không có Docker; dự kiến làm
   trên một máy ảo boxd.sh.) → WP-6.3
2. Chạy trọn một task OpenClaw tới trạng thái kết thúc, xác nhận
   `runtime_stream` ghi đúng event và task chuyển trạng thái
   (`complete → review`, `error → blocked`). → WP-4.3
3. Thêm CI tối thiểu: pytest + `next build` trên mỗi push. → WP-5.3
4. Đăng ký tool cho agent đọc dữ liệu công ty — nhưng **24 tool qua MCP
   server**, không phải 192 tool: schema tool tính vào context window và
   `skills.limits.maxSkillsPromptChars` mặc định là 18 000. → WP-3.1
5. Luồng "nhập sơ đồ tổ chức thật → ánh xạ sang seat agent" đặt cuối vì nó cần
   hồ sơ seat (Phase 2) và cầu tool (Phase 3) xong trước. → WP-6.4

## 9. Bản đồ tài liệu

| File | Nội dung |
| --- | --- |
| `README.md` | lịch sử v4→v35, mỗi version tự khai giới hạn |
| `HANDOFF.md` | file này — hiện trạng và việc tiếp theo |
| `docs/ARCHITECTURE_TREE.md` | cây module 4 tầng, logic, ranh giới OpenClaw/ClawCompany |
| `docs/AGENT_WORK_MEMORY.md` | bảy tầng bộ nhớ, ranh giới với OpenClaw, gói ngữ cảnh bảy khối |
| `docs/AGENT_TEAMWORK.md` | năm kiểu phối hợp, phòng họp có chủ toạ, ràng buộc vật lý của runtime |
| `docs/BUILD_PLAN.md` | 6 phase, ~24 gói việc, định nghĩa xong và cách kiểm chứng |
| `_reports/inventory.md` | kiểm kê endpoint/bảng/service/test/bridge (sinh tự động) |
| `_reports/test-triage.md` | phân loại 37 failure của lần chạy đầu |
| `_reports/openclaw-protocol-audit.md` | đối chiếu giao thức với upstream + kết quả đo |
| `_reports/native-probe-before-fix.log` | bằng chứng 1008 trước khi sửa |
| `_reports/native-probe-after-fix.log` | bằng chứng kết nối được sau khi sửa |
| `tools/probe_*.py` | script dò adapter với gateway thật |
| `_reports/local-runtime.md` | biên bản chạy thật cả stack |
| `_reports/smoke.txt` · `smoke.json` | kết quả 236 endpoint |
| `_reports/e2e-openclaw.txt` | đường dây OpenClaw đầu-cuối |
| `tools/devstack.py` | dựng Postgres + Redis nhúng |
| `tools/run_api.sh` | khởi động API trên devstack |
| `tools/smoke.py` | smoke toàn bộ bề mặt API |
| `tools/e2e_openclaw.py` | kiểm chứng đường dây agent đầu-cuối |
| `_reports/pytest-first-run.log` | log chạy test lần đầu tiên |
| `_reports/pytest-after-repair.log` | log sau khi sửa |
| `docs/architecture-v*.md` | thiết kế từng version (25 file) |
| `design/clawcompany-ui-canvas.html` | design canvas không cần build |
| `tools/inventory.py` | script sinh `_reports/inventory.md` |
