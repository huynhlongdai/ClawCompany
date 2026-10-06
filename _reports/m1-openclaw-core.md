# M0/M1 — Deploy VM persimmon + gateway OpenClaw thật (06/10/2026)

Máy: `ssh.prized.dev` (Ubuntu 24.04, 4 vCPU, 15 GB RAM, Docker). App chạy bằng
`docker compose -f docker-compose.yml -f docker-compose.prized.yml -f docker-compose.openclaw.yml`.

## Trạng thái trước khi deploy

| Hạng mục | Đo được |
| --- | --- |
| Code trên box | `7864552` (cũ hơn HEAD 21 commit) |
| `alembic current` | `0023_budget_scopes` — **thiếu 0024–0027** |
| `OPENCLAW_MODE` | `mock` (không có gateway) |
| Log API 7 giờ | 205×200, 161×401, 0×500. 401 dồn lúc trước khi đăng nhập (app gọi API khi chưa có token) |

## Lỗi 1 — migration 0026 chết `DuplicateTable: relation "routines" already exists`

Nguyên nhân: `backend/app/main.py` gọi `Base.metadata.create_all()` lúc import. Container
api cũ chạy `uvicorn --reload` trên bind mount `./backend:/app`; khi `git reset` kéo code
mới về, uvicorn tự reload → `create_all` tạo bảng `routines*` theo model mới **trước** khi
container mới chạy `alembic upgrade head`.

- Sửa box: sao lưu DB (`~/backups/clawcompany-20261006-1333-pre-v2.sql.gz`), xoá 3 bảng
  `routines`, `routine_triggers`, `routine_runs` (đều 0 dòng), chạy lại → `0027_strategy_plans (head)`.
- Sửa code: `create_all` chỉ còn chạy với SQLite (dev/test). Postgres chỉ dựng schema bằng alembic.

## Gateway OpenClaw 2026.9.8

- Image `ghcr.io/openclaw/openclaw:2026.9.8`, service `openclaw` trong mạng docker,
  **không publish cổng**; api/worker/beat gọi `ws://openclaw:18789`.
- Cấu hình: `gateway.mode=local`, `gateway.bind=lan`, `gateway.auth.mode=token`,
  `gateway.auth.token=${OPENCLAW_GATEWAY_TOKEN}` (token ngẫu nhiên trong `.env.openclaw`
  trên VM, không commit).
- Log: `[gateway] ready`, model mặc định `openai/gpt-6-astra` — **chưa có key model**.

## Lỗi 2 — `missing scope: operator.read` (client chưa có định danh thiết bị)

Client native gửi `connect` bằng token chung nhưng không gửi `device`. Theo
`docs/gateway/protocol/auth.md`, kết nối không có device mà không thuộc hai đường tin cậy
(Control UI trusted-proxy, helper loopback nội bộ) bị **xoá hết scope**. Mọi lần chạy thật
trước đây đều dùng `--auth none --bind loopback`, nên lỗi này chưa bao giờ lộ ra.

Sửa (`app/runtime/openclaw_device.py` + `_handshake`):

1. chờ event `connect.challenge` (tối đa `openclaw_challenge_timeout_seconds`, gateway cũ không gửi thì bỏ qua);
2. ký payload v3 `v3|deviceId|clientId|clientMode|role|scopes|signedAtMs|token|nonce|platform|deviceFamily` bằng Ed25519;
3. gửi `device = {id: sha256(raw pubkey), publicKey, signature, signedAt: ts, nonce}`;
4. khoá lưu ở `OPENCLAW_DEVICE_IDENTITY_PATH` (volume `clawcompany_device`, dùng chung cho api/worker/beat → duyệt ghép đôi 1 lần), tạo bằng `O_EXCL`, quyền 600;
5. `PAIRING_REQUIRED` → thông báo tiếng Việt kèm lệnh `openclaw devices approve`.

Đối chiếu bằng chính hàm của OpenClaw (không suy đoán):

```
payload_equal true      # buildDeviceAuthPayloadV3
device_id_ok true       # deriveDeviceIdFromPublicKey
signature_ok true       # verifyDeviceSignature
```

Kết quả trên VM: gateway nhận chữ ký, tạo yêu cầu ghép đôi đúng `roles: operator; scopes:
operator.read, operator.write` → duyệt → `GET /api/v19/openclaw/agents` trả `{"agents": []}` (hết 403).

Test: `tests/test_m11_device_auth.py` 11 test (full pytest 947 passed, 2 skipped); mutation 7/7 bị bắt (v2 thay v3, bỏ token,
sha1 thay sha256, bỏ O_EXCL, bỏ ts của challenge, bỏ chờ challenge, bỏ map lỗi ghép đôi).

## E2E `tools/e2e_openclaw.py` trên VM — 13/15

| Bước | Kết quả |
| --- | --- |
| login, protocol, health (`runtimeVersion=2026.9.8`), seats, reconcile, live SSE | OK |
| gateway agents | rỗng — gateway mới chưa có agent nào |
| start task (`chat.send`) | 502 `Unknown agent id "dev"` — đúng, vì chưa có agent |

Sau e2e đã gắn lại seat Nina về `nina` (script e2e đổi sang `dev`). Dữ liệu thử còn lại: 1 công ty/dự án/việc `task_id=2`.

## Việc tiếp theo của M1/M3 (đo được, chưa làm)

1. **Tạo agent trên gateway**: `agents.create {name, workspace?, model?}` cần scope
   `operator.admin` (đo: `missing scope: operator.admin`). `NativeOpenClawRuntime.create_agent`
   hiện chỉ "bind" agent có sẵn, không tạo. Cần bật `OPENCLAW_REQUEST_ADMIN_SCOPE` → duyệt
   nâng scope 1 lần → tạo agent nina/sophia-cmo/mia-content.
2. **Key model** (OpenAI/Anthropic…) cho gateway để agent chạy thật lượt đầu tiên.
3. Lỗi resume 500 (`no running event loop`), chế độ `gateway` legacy, doctor 1 nút.

## M1.2 — Một lượt việc chạy trọn vòng trên gateway thật (06/10/2026)

Đo trên VM: OpenClaw 2026.9.8 + provider CometAPI `comet/gpt-4.1-mini`. `tools/e2e_openclaw.py` với `E2E_EXPECT_REPLY=1`: **16/16 bước OK**, agent Nina trả lời thật.

| Lỗi đo được | Nguyên nhân | Sửa |
|---|---|---|
| Giao việc qua `/api/v19/tasks/{id}/start` hay `/api/tasks/{id}/dispatch`: task kẹt `in_progress`, không ghi chi phí | Chỉ wakeup và kéo thẻ v20 gắn follower | `agent_dispatch.follow_after_send` ngay sau `chat.send` cho mọi đường (idempotent, chỉ ở mode native) |
| `POST /api/v21/runtime/resume` → 500 `no running event loop` | Endpoint `def` chạy trong threadpool, `supervisor.follow` gọi `asyncio.create_task` | `async def`; hook startup `resume_openclaw_followers` cũng vậy (trước đây luôn bị bỏ qua) |
| Resume xong task vẫn kẹt | Frame `chat final` đã trôi qua trước khi gắn | `stream_catchup`: `sessions.describe {key}` → `status=done` + `lastRunId` đúng run của task thì ghi chi phí từ `chat.history` rồi đóng lượt |
| Roster thiếu agent mới tạo, seat bị coi là orphaned | `list_agents` chỉ suy từ `sessions.list` | Dùng `agents.list` + gộp session; `create_agent` gọi `agents.create` (cần scope `operator.admin`), kiểm `agentId` trả về |
| Log `/api/tasks?goal_id=undefined` | `GoalsConsole` đặt `selected = r.goal` khi phản hồi thiếu goal | Chặn ở `GoalTasks` + giữ goal cũ |

Chi phí khớp gateway tuyệt đối: task 6 = 12 797 in × 0,4 + 63 out × 1,6 (USD/1M) = **$0,0052196**; task 5 (bắt kịp sau resume) = **$0,005242** = `usage.cost.total` của gateway. Không ghi trùng: `__openclaw.id` trong history trùng `messageId` của `session.message`.

Test: `tests/test_m12_followers.py` 22 test, mutation **10/10** bị bắt. Full pytest **969 passed, 2 skipped**. `tsc --noEmit` sạch.

## M1.3 — Lỗi có CORS, /health báo schema, doctor 1 nút, tự nối lại, chaos test (06/10/2026)

| Việc | Kết quả đo trên VM (gateway 2026.9.8 thật) |
|---|---|
| Lỗi chưa bắt → JSON tiếng Việt `{detail, code, request_id}` **có header CORS** (`JSONErrorMiddleware` nằm trong CORS) | `OpenClawProtocolError` → 502 `openclaw_error`; timeout → 504; mất kết nối → 503; còn lại 500 `internal_error` |
| `/health` báo `schema: ok/behind` (so `alembic_version` với head), `?deep=1` hỏi gateway | `{"status":"ok","schema":{"db":["0027_strategy_plans"],...},"openclaw":{"status":"healthy","version":"2026.9.8"}}` |
| Doctor `GET /api/v19/openclaw/doctor` + bảng "Kiểm tra kết nối" trên `/app/openclaw` | 7/8 xanh: DB, chế độ, token, kết nối + thiết bị, model `comet/gpt-4.1-mini`, agent↔ghế, quyền duyệt. Cảnh báo thật: chưa có skill heartbeat |
| Bỏ chế độ `gateway` kiểu cũ (`runtime/gateway.py` đã xoá) | `OPENCLAW_MODE=gateway` cũ được hiểu là `native`, không âm thầm rơi về mock |
| Follower tự nối lại (backoff 1,2,4…≤30s, tối đa 8 lần; im lặng 60s không tính là lỗi), bắt kịp trước mỗi lần nghe lại | Chaos #2: restart gateway 23:12:45 → lên lại 23:12:55 → `chat.final` nhận trực tiếp → task **review** lúc 23:13:01 |
| Resume khi khởi động + quét phiên mồ côi mỗi 60s (`OPENCLAW_RESUME_ON_BOOT`, `OPENCLAW_CLAIM_SWEEP_SECONDS`) | Task 4 kẹt sau chaos #1 được sweeper nhận lại và đóng, không ai bấm nút |
| Khoá cổng: Postgres 5432, Redis 6379, API 8000 chỉ nghe `127.0.0.1` (`docker-compose.prized.yml`, `ports: !override`) | Chỉ còn web 3000 mở ra ngoài; E2E sau đó vẫn 16/16 |

**Hai phát hiện thật từ chaos test:**

1. OpenClaw 2026.9.8 **tự chạy tiếp lượt bị ngắt bằng một runId mới**, mở đầu bằng tin `[System] Your previous turn was interrupted by a gateway restart…`. Catch-up nay nhận "chuỗi lượt": run gốc + các run tiếp nối sau tin hệ thống đó, miễn không có tin user thật chen vào. Chi phí tính cho cả hai run (task 4: $0,0064348 + $0,0051884 = **$0,0116232**).
2. Gateway mặc định **chặn cài skill tải lên** (`skills.install.allowUploadedArchives`), nên `heartbeat-skill` trả `uploads_disabled`. Doctor nay đọc `config.get` để nói đúng nguyên nhân và lệnh sửa, thay vì hiện nút "Cài ngay" rồi thất bại. Chưa bật trên VM, đang chờ duyệt.

Test: `tests/test_m13_doctor_errors.py` 21 test + 3 test chuỗi lượt trong `test_m12_followers.py`; mutation **11/11** và **4/4**. Full pytest **993 passed, 2 skipped**. Ảnh UI: `docs/screenshots/m1/` (9 trang, 0 lỗi console, 0 HTTP ≥ 400).
