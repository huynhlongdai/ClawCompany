# Chạy thật lần đầu: Postgres + Redis + API + frontend + gateway OpenClaw

Ngày: 2026-09-15. Không Docker, không root, không boxd — toàn bộ chạy user-space
trong một sandbox.

## Cách dựng

| Thành phần | Thay cho service nào trong docker-compose | Bằng gì |
| --- | --- | --- |
| PostgreSQL 16.2 + pgvector | `db` (`pgvector/pgvector:pg16`) | `pgserver` (PyPI), unix socket |
| Redis | `redis:7-alpine` | binary `redis-server` mà `redislite` nhúng, cổng 16379 |
| API | `api` | `uvicorn app.main:app` qua `tools/run_api.sh` |
| Worker | `worker` | `celery -A app.worker.celery_app worker` |
| Frontend | `web` | `next dev -p 3000` |
| Nhân agent | (không có trong compose) | OpenClaw **2026.9.4 thật**, `ws://127.0.0.1:18789` |

```bash
.venv/bin/python tools/devstack.py up      # in ra env
eval "$(.venv/bin/python tools/devstack.py env)"
cd backend && ../.venv/bin/python -m alembic upgrade head && ../.venv/bin/python seed.py
bash tools/run_api.sh
.venv/bin/python tools/smoke.py
.venv/bin/python tools/e2e_openclaw.py
```

## Kết quả đo

| Phép thử | Kết quả |
| --- | --- |
| `alembic upgrade head` trên Postgres sạch | **OK** — 160 bảng, head `0015_v32_department_status_not_null` |
| `seed.py` | **OK** — 8 công ty, 7 thành viên (4 người + 3 agent), 7 dự án |
| Smoke 236 endpoint (`tools/smoke.py`) | **236/236 OK** |
| Đường dây OpenClaw đầu-cuối (`tools/e2e_openclaw.py`) | **15/15 bước OK** |
| Test đơn vị | 640 passed · 1 skipped |
| `next dev` — 6 route chính | tất cả HTTP 200 |
| Celery worker trên Redis thật | `ready`, đăng ký đủ task |

### Đường dây OpenClaw: những gì thực sự xảy ra

```
POST /api/auth/login                 -> token
GET  /api/v19/openclaw/health        -> status healthy, runtimeVersion 2026.9.4
GET  /api/v19/openclaw/agents        -> [{"id": "dev", "sessions": 2}]   ← roster THẬT từ gateway
POST /api/v19/openclaw/reconcile     -> 3 seat seed thành "orphaned" (đúng: gateway dev không có nina/mia)
POST /api/v19/openclaw/bind          -> agent:dev:main
POST /api/v19/tasks/7/start          -> session_key agent:dev:company-task-7, status in_progress
GET  /api/v19/tasks/7/transcript     -> messages thật, có đúng prompt ClawCompany đã gửi
GET  /api/v35/live/stream            -> SSE, frame "event: snapshot" + data thật
```

Đây là lần đầu mệnh đề "ClawCompany chạy trên nền cốt lõi OpenClaw" được kiểm
chứng bằng một gateway thật, không phải `OPENCLAW_MODE=mock`.

### v21/v22/v26: lần đầu báo chế độ cluster thay vì process-local

Với Redis thật, ba cờ mà docs nói sẽ "thú nhận" khi thiếu Redis nay báo đúng:

```json
{"pool":     {"backend": "redis", "available": true, "shared_pool": true},
 "lease":    {"backend": "redis", "single_process_only": false},
 "registry": {"backend": "redis", "cluster_wide": true}}
```

## Lỗi đã phát hiện và sửa trong lượt này

| # | Lỗi | Vì sao test không thấy |
| --- | --- | --- |
| 1 | `alembic_version.version_num` VARCHAR(32) < revision id 42 ký tự | SQLite không cưỡng chế độ dài VARCHAR |
| 2 | `0001_baseline` tạo sẵn cột của 0013/0014 -> `DuplicateColumn` | Chưa ai chạy chuỗi migration trên DB sạch |
| 3 | **Không đăng nhập được vào bản cài mới**: `EmailStr` từ chối `.local` mà seed lại tạo `admin@clawcompany.local` | Test auth không dùng email của seed |
| 4 | `GET /api/v33/progress/drift` 500 — `Project.organization_id` không tồn tại | Test grep source **ghim chính dòng lỗi** |
| 5 | `POST .../tasks/{id}/assign` trả 200 cho body sai khoá rồi không làm gì | Không có test đi hai bước assign → move |

Chi tiết từng lỗi nằm trong commit message tương ứng.

## Còn hổng, nói thẳng

- **Không phải phép thử `docker compose up`.** Kết quả này chứng minh code chạy
  được với Postgres/Redis thật, không chứng minh file compose đúng.
- **Một lượt chạy agent không tới được trạng thái kết thúc**: gateway dev không
  có credential model (`no authentication source configured for openai`).
  Giao thức đã đúng tới tận tầng gọi model; phần còn lại là cấu hình.
- **Luồng approval chưa kiểm đầu-cuối**: cần một lệnh bị `exec approval` gate.
- ~~CORS chỉ có một origin~~ — **đã sửa**: mặc định nay gồm cả
  `http://localhost:3000` và `http://127.0.0.1:3000`, và docker-compose khai
  giống vậy.
- ~~passlib + bcrypt 4.x in AttributeError mỗi lần hash~~ — **đã sửa**: bỏ
  passlib (bản cuối 2020, đọc `bcrypt.__about__` đã bị bcrypt 4.1 xoá), gọi
  thẳng `bcrypt`. Định dạng hash không đổi (`$2b$`) nên mọi hash cũ và API key
  đã phát hành vẫn verify được; kiểm chứng lại bằng seed từ DB sạch: log sạch,
  đăng nhập được, smoke 236/236 và e2e 15/15 vẫn xanh.
- **mTLS runner, cosign, OTLP export, Firecracker/Kubernetes** vẫn nằm ngoài:
  chúng cần hạ tầng ngoài, không phải cấu hình.
- Smoke chỉ tự động gọi **GET**; đường ghi được viết tay và giới hạn ở dữ liệu
  do chính script tạo. 274 operation còn lại (POST/PATCH/DELETE) chưa được gọi.
