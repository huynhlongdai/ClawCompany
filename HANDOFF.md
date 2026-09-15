# HANDOFF — ClawCompany

Nguồn sự thật về hiện trạng dự án. README kể lịch sử v4→v35; file này trả lời
"bây giờ đang ở đâu, chạy thế nào, và việc gì tiếp theo".

- Ngày tiếp nhận: **2026-09-15**
- Nguồn: `clawcompany_v35_spend_push.zip` (459 file, không có `.git`)
- Repo: `https://github.com/huynhlongdai/ClawCompany`
- Service version: `1.25.0` · Migration head: `0015_v32_department_status_not_null`

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

### Không có Docker (như sandbox tiếp nhận)

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
| Test suite | **608 passed · 12 failed · 1 skipped** | `_reports/pytest-after-repair.log` |
| Lần chạy đầu tiên | 582 passed · 37 failed | `_reports/pytest-first-run.log` |
| Frontend build | **xanh**, 49 route prerender | `npx next build` |
| Bridge contract | **192/192** khớp route thật | `tools/inventory.py` |
| Migration | chưa chạy thật (không có Postgres) | — |
| OpenClaw native | **không thể kết nối gateway thật** | `_reports/openclaw-protocol-audit.md` |
| Postgres/pgvector/Redis/mTLS/cosign/OTLP | **chưa từng kiểm chứng** | không có test nào chạm tới |

Trước lượt tiếp nhận này, **chưa một test nào từng được thực thi** — docs
v20→v35 đều ghi "tests written but not executed".

## 5. Đã sửa trong lượt tiếp nhận

Ba lỗi code thật, mỗi lỗi kèm test hành vi canh giữ:

1. **`live_channel` scope tenant qua cột không tồn tại** (`353c074`).
   `_run_ids()` và `live_tasks()` lọc `Task.organization_id`; bảng `tasks`
   không có cột đó. Mọi lời gọi kênh SSE của v35 nổ `AttributeError` — tính
   năng mới nhất chưa từng chạy được. Sửa bằng join
   `task → project → company`. Test cũ *grep source tìm đúng dòng lỗi*, tức
   nó bảo tồn lỗi thay vì phát hiện; đã thay bằng test hai tenant trên SQLite.
2. **`row_guard` có hai định nghĩa "kind"** (`5bdf642`). `row_guard.kind()`
   dùng tên class, `row_revision.kind_of()` ưu tiên `__entity_kind__`, và
   `compare_and_set` dùng cả hai. Với 5 ORM entity hiện tại chúng trùng nhau
   nên lỗi còn tiềm ẩn — nhưng đây đúng là module v28 dựng lên để guard "có
   hiệu lực". Đã hợp nhất.
3. **Payload approval vi phạm schema đóng của upstream** (`657262a`).
   `exec.approval.resolve` gửi kèm `sessionKey`, không nằm trong
   `ExecApprovalResolveParamsSchema` (`closedObject`), nên bị gateway từ chối.
   Cũng bỏ bộ lọc `sessionKey` mà v24 suy đoán cho `exec.approval.list`.
4. **Frontend chưa từng build được** (`2414256`). `tsconfig.json` không khai
   `baseUrl`/`paths` trong khi 29 file import qua `@/`; `lib/api.ts` khai
   `request<T>` không có default nên 288 lời gọi trả `Promise<unknown>`.

## 6. Nợ kỹ thuật, theo mức ưu tiên

### P0 — phủ định mệnh đề cốt lõi của sản phẩm

**Adapter OpenClaw native không nói đúng giao thức.** Mọi request frame thiếu
`type: "req"`; response đọc `result` thay cho `ok`/`payload`; handshake sai
hình dạng so với `ConnectParamsSchema`; subscribe dùng `sessionKey` thay vì
`key`. Chi tiết, dẫn nguồn upstream và các bước sửa: `_reports/openclaw-protocol-audit.md`.
Chưa sửa vì đây là một khối thay đổi cần kiểm chứng với gateway thật.

### P1 — cách đo đang cho tín hiệu sai

**Test dùng double tự viết bỏ qua điều kiện WHERE.** `FakeDb` trong
`test_v27_board_truth.py` trả về mọi task cho mọi truy vấn. Nghĩa là 608 test
đang xanh cũng phần lớn không kiểm chứng SQL thật. Ba biểu hiện đã gặp:

- test grep source thay vì kiểm hành vi — một trong số đó đã *bảo tồn* lỗi P0;
- assertion ghim số cứng theo version (`"1.23.0"`, `181 tool`) — bằng chứng
  chúng chưa từng chạy;
- fake không có cột mà code thật đọc (`departments.status`, `company_id`).

Phân loại đầy đủ 37 failure: `_reports/test-triage.md`.

### P2 — hạ tầng chưa được chứng minh

Không có test nào cần Postgres, pgvector, Redis, mTLS, cosign hay OTLP. Mọi
phát biểu trong docs về các lớp đó là **thiết kế**, không phải kết quả đo.
Cần một lần chạy `docker compose up` + `alembic upgrade head` thật.

### P3 — vệ sinh mã nguồn

- Không có `conftest.py`, `pytest.ini`/`pyproject.toml`, không có CI.
- ~2900 `DeprecationWarning`, gần hết là `datetime.utcnow()`.
- `services/tasks.py` là shim deprecate của `agent_dispatch.py`.
- `company_events` không có chính sách retention (v31 đã ghi nhận).
- Un-archive một member không phục hồi trạng thái runtime (v31 đã ghi nhận).
- 12 test còn đỏ: v28 (4) + v30 (8) — cần harness ORM thật cho conditional
  UPDATE, xem `_reports/test-triage.md` nhóm 1.1.

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

1. Chạy thật bằng Docker: `docker compose up` + `alembic upgrade head` +
   `seed.py`, ghi lại kết quả. (Sandbox tiếp nhận không có Docker; dự kiến làm
   trên một máy ảo boxd.sh.)
2. Đóng 12 test còn đỏ bằng harness ORM thật cho `compare_and_set` — đây cũng
   là lần đầu mệnh đề "guard có hiệu lực" của v28 được chứng minh.
3. Quyết định P0: sửa adapter giao thức OpenClaw theo
   `_reports/openclaw-protocol-audit.md`, rồi kiểm chứng với một gateway thật.
4. Thêm CI tối thiểu: pytest + `next build` trên mỗi push.
5. Chỉ sau đó mới bàn tới v36 và luồng "nhập sơ đồ tổ chức thật → ánh xạ sang
   seat agent".

## 9. Bản đồ tài liệu

| File | Nội dung |
| --- | --- |
| `README.md` | lịch sử v4→v35, mỗi version tự khai giới hạn |
| `HANDOFF.md` | file này — hiện trạng và việc tiếp theo |
| `_reports/inventory.md` | kiểm kê endpoint/bảng/service/test/bridge (sinh tự động) |
| `_reports/test-triage.md` | phân loại 37 failure của lần chạy đầu |
| `_reports/openclaw-protocol-audit.md` | đối chiếu giao thức với upstream |
| `_reports/pytest-first-run.log` | log chạy test lần đầu tiên |
| `_reports/pytest-after-repair.log` | log sau khi sửa |
| `docs/architecture-v*.md` | thiết kế từng version (25 file) |
| `design/clawcompany-ui-canvas.html` | design canvas không cần build |
| `tools/inventory.py` | script sinh `_reports/inventory.md` |
