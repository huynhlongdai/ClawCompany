# D0.2 — Thay test double ở vùng sẽ sửa

**Kết quả:** Test của vùng `tasks` (board_truth, board_restore) giờ chạy trên ORM thật (SQLite in-memory, model thật). Mỗi DB thử có thêm dự án/tổ chức "nhiễu", nên **bỏ bất kỳ điều kiện WHERE nào cũng làm test đỏ**. Double cũ thì vẫn xanh hết.

## Đã đổi
| File | Trước | Sau |
|---|---|---|
| `test_v27_board_truth.py` | `FakeDb`: đếm trả *mọi* task, bỏ qua `project_id`; `_eval_where` tự viết, gặp mệnh đề lạ thì cho qua | ORM thật + dự án nhiễu (3 done + 1 đang chạy có session); 22 test (thêm 1: task đã chạy xong vẫn giữ session key nhưng không chặn lưu trữ) |
| `test_v28_write_guards.py` (phần restore) | `FakeEvent` tự dựng payload; `FakeDb.execute` trả cùng một danh sách cho mọi truy vấn; 4 test chỉ grep mã nguồn (`inspect.getsource`) | Bản lưu trữ tạo bằng `archive_project` thật rồi khôi phục; sự kiện ghi thật; 4 test grep đổi thành test hành vi (lọc tổ chức, lấy bản mới nhất, payload có `previous_status`/`task_statuses`); thêm test "payload nêu task của dự án khác thì không đụng tới" |
| `test_v35_spend_push.py` | `_Session` có `.query()` trả rỗng | phiên SQLite thật |

## Mutation (bỏ chốt → test phải đỏ)
| Bỏ ở production | Test mới | Double cũ |
|---|---|---|
| `board_truth.task_counts`: `WHERE project_id` | 9 fail | 0 fail |
| `live_attachments`: `project_id` | 5 fail | 0 fail |
| `live_attachments`: `status = in_progress` | 1 fail | — |
| `live_attachments`: `session_key IS NOT NULL` | 1 fail | — |
| `archive_project`: `WHERE project_id` | 2 fail | 0 fail |
| `board_restore.last_archive_event`: lọc tổ chức | 1 fail | (chỉ grep) |
| `last_archive_event`: lọc project | 1 fail | — |
| `restore_preview`: `project_id` khi đọc task | 1 fail | — |
| `last_archive_event`: lấy bản cũ nhất thay vì mới nhất | 1 fail | — |

## Đã rà, giữ nguyên
- `approvals`, `runtime_stream`, `budget`: test (v9, v20–v25, v23, D1.1, D1.2, D1.5) đã dùng ORM thật. Double còn lại chỉ thay **hệ thống ngoài** (gateway `FakeRuntime`, `FakeRedis`, lease/registry), không thay DB.

## Còn lại của WP-5.1 (không chặn ai)
- `test_v28` phần guard: 5 chỗ dùng `FakeDb` để kiểm việc từ chối *trước khi* chạm DB (token sai, field lạ). Test UPDATE có điều kiện thì đã chạy trên SQLite thật.
- `test_v29_cascade_archive.py` (32 test) và `test_v30_exact_revisions.py` (36 test) vẫn dùng `FakeDb` cho cascade công ty/phòng ban.
- `test_v34_replay.py`, `test_v35_*`: nhiều test grep mã nguồn.
