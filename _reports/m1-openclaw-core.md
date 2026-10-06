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
