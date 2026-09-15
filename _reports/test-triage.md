# Phân loại 37 failure của lần chạy test đầu tiên

Bối cảnh: docs v20→v35 đều ghi "tests written but not executed — no network in
the build sandbox". Đây là lần đầu tiên 616 hàm test được thực thi.

Môi trường chạy: Python **3.12.14** (uv), SQLite (`DATABASE_URL=sqlite:///./_test.db`),
**không** có Postgres/pgvector/Redis/Docker.

Kết quả: **582 passed · 37 failed · 1 skipped** (`_reports/pytest-first-run.log`).

---

## Kết luận quan trọng nhất

**Không có failure nào chứng minh một lỗi nghiệp vụ mà người dùng nhìn thấy.**
Nhưng cũng không có failure nào vô hại: chúng phơi ra ba khuyết điểm hệ thống.

1. **Test dùng test double tự viết, và double đó bỏ qua điều kiện WHERE.**
   Ví dụ `FakeDb` trong `test_v27_board_truth.py` trả về *mọi* task cho mọi
   truy vấn. Code thật lọc `status == "in_progress" AND runtime_session_key IS NOT NULL`
   ở tầng SQL, nên test vừa **báo sai** (fail dù code đúng) vừa **kiểm chứng
   thiếu** (không hề xác nhận mệnh đề lọc). Đây là rủi ro lớn hơn cả 37 failure:
   582 test đang pass cũng phần lớn theo cùng một kiểu.
2. **Refactor v26 không kéo theo test v22.** `stream_registry`/`runtime_leases`
   đã chuyển sang `redis_pool.pool`, nhưng test vẫn gán `reg._redis = FakeRedis()`
   — một thuộc tính không còn được đọc. Test fail mà code không sai.
3. **Nhiều assertion ghim số cứng theo version** (`"1.23.0"`, `"1.24.0"`,
   `bridge_contract_count_is_181`). Mỗi lần bump version là vỡ test, nên nếu có
   ai từng chạy test thì đã không ghim kiểu này.

---

## Nhóm 1 — Khác biệt hợp đồng trong code (đáng sửa ở phía code): 2 vấn đề, 13 test

### 1.1 Hai định nghĩa "kind" trong cùng một đường ghi — 12 test

| Nơi | Cách xác định kind |
| --- | --- |
| `row_revision.kind_of()` | `__entity_kind__` nếu có, ngược lại tên class |
| `row_guard.kind()` | **chỉ** tên class |

`compare_and_set` dùng cả hai: `rev.parse_revision` sinh/đọc token theo
`kind_of`, rồi so với `kind(entity)`. Với ORM thật hai hàm trùng nhau nên lỗi
này **tiềm ẩn, chưa gây sự cố production**, nhưng nó là một đường phân nhánh
thừa trong đúng cái module mà v28 dựng lên để làm "guard có hiệu lực".

Test fail: `test_v28_write_guards.py` (4), `test_v30_exact_revisions.py` (6),
cộng 2 test v28 khác cùng nguyên nhân.

→ **Sửa:** `row_guard.kind()` uỷ quyền cho `rev.kind_of()`. Một dòng.

### 1.2 `limit=0` trong sổ kiểm toán — 1 test

`write_audit.feed()`: `max(1, min(int(limit or DEFAULT_LIMIT), MAX_LIMIT))`.
`limit=0` rơi vào `or` nên thành 50. Test `test_feed_limit_is_clamped_not_trusted`
đòi 1.

Hai cách hiểu đều có lý ("0 = dùng mặc định" vs "0 = kẹp xuống sàn 1"). Đây là
**hợp đồng chưa được quyết**, không phải lỗi. Ghi vào nợ kỹ thuật, giữ hành vi
code, sửa test kèm chú thích.

---

## Nhóm 2 — Test double lạc hậu sau refactor: 16 test

| Test | Nguyên nhân |
| --- | --- |
| `test_v22_cluster_runtime.py` (6) | gán `_redis` thay vì thay `redis_pool.pool` (v26) |
| `test_v26_shared_fabric.py` (1) | cùng nguyên nhân |
| `test_v27_board_truth.py` (2) | `FakeDb.execute` bỏ qua WHERE → task `session_key=None` bị coi là đang chạy |
| `test_v29_cascade_archive.py` (2) | `FakeDepartment` thiếu `status` (cột do v31 thêm) |
| `test_v31_field_audit.py` (3) | `_Event` thiếu `company_id` (write_audit đọc trường này) |
| `test_v30_exact_revisions.py` (1) | `entity_archive` dùng `isinstance` với model thật, `FakeProject` không thoả |
| `test_v35_spend_push.py` (1) | `_Session` thiếu `.query` mà `live_channel` gọi |

→ **Sửa ở phía test**, không đổi code.

---

## Nhóm 3 — Assertion tự mâu thuẫn hoặc quá giòn: 7 test

| Test | Vấn đề |
| --- | --- |
| `test_v34_replay.py::test_event_json_wraps_non_dict` | tên test nói "wraps", assertion đòi `{}`; code trả `{"value": [...]}` — đúng như tên test |
| `test_v30_exact_revisions.py::test_cursor_advances_past_filtered_out_events` | docstring giải thích phải trỏ cursor tới event **đã quét**, nhưng assertion đòi id của dòng **đã trả về** (30) — tự phản biện chính nó; code làm đúng docstring (27) |
| `test_v34::test_replay_does_not_call_record_usage` · `test_v35::test_spend_module_never_writes_usage_rows` | grep chuỗi `record_usage` trong source; chuỗi đó nằm trong **docstring** giải thích "module này không gọi record_usage" |
| `test_v30::test_guarded_update_sets_updated_at_explicitly` | grep `updated_at=now` trong source, code viết cách khác |
| `test_v31_bugfixes.py` (2) | linter AST tự viết coi builtin `str` là "undefined name"; assertion khác đòi `clear_owner` không xuất hiện trong khi v31 đã thêm |

→ **Sửa ở phía test**: kiểm chứng hành vi bằng gọi hàm, không bằng grep source.

---

## Nhóm 4 — Assertion ghim version/số lượng: 3 test

| Test | Kỳ vọng | Thực tế |
| --- | --- | --- |
| `test_v33_recovery::test_the_service_version_moved_with_the_router` | `"1.23.0"` | `1.25.0` |
| `test_v34_replay::test_service_version_bumped` | `"1.24.0"` | `1.25.0` |
| `test_v34_replay::test_bridge_contract_count_is_181` | 181 tool | 192 tool |

→ **Sửa ở phía test**: so sánh version là **đơn điệu tăng** và số tool là
**không giảm**, thay vì ghim con số của version cũ.

---

## Nhóm 5 — Thiếu hạ tầng, không kiểm chứng được tại đây: 1 test

`test_v11_repository_delivery::test_delivery_test_review_merge_and_rollback`
gọi executable `python`; sandbox chỉ có `python3` (image Docker
`python:3.12-slim` thì có `python`). Sửa test dùng `sys.executable` sẽ kiểm
chứng được ngay, nhưng phải giữ nguyên allowlist
`REPOSITORY_TEST_ALLOWED_EXECUTABLES`.

---

## Không nằm trong 37 failure nhưng phải nói

- **Không có test nào cần Postgres/pgvector/Redis thật.** Toàn bộ suite chạy
  trên SQLite + fake. Nghĩa là mọi phát biểu về pgvector, Redis lease, mTLS,
  cosign, OTLP export trong docs **chưa từng được kiểm chứng bằng test**.
- `package.json` vẫn ghi `"name": "clawcompany-v14", "version": "1.4.0"` trong
  khi service là `1.25.0`.
- Không có `conftest.py`, không có CI config, không có `pytest.ini`/`pyproject.toml`.
- 2941 DeprecationWarning, gần hết là `datetime.utcnow()`.
