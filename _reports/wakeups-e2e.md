# D2.1 — Hàng đợi wakeup + skill heartbeat: kết quả đo thật

Ngày đo: 06/10/2026. Gateway OpenClaw 2026.9.8 thật (`ws://127.0.0.1:18789`), model giả có kịch bản
(`tools/scripted_llm.py`, giá đặt 3/15 USD per 1M token), API chạy với `WAKEUP_DRAIN_SECONDS=5`,
cửa sổ gộp 10 giây. Không ai bấm dispatch trong mọi kịch bản dưới đây.

## Kết luận

| Tiêu chí "Xong khi" | Kết quả | Bằng chứng |
|---|---|---|
| Giao task trên UI → có run ≤ 60 giây | **Đạt — 14,2 giây** (cửa sổ 10 s + vòng drain 5 s) | `evidence/d21/e2e_wakeup.txt` bước A |
| Hai sự kiện trong 10 giây → 1 run | **Đạt** — giao việc + @Nina: wakeup #23 `dispatched`, #24 `coalesced` vào #23, **1** `chat.send` cho phiên task 35 | bước B, `chat_send_by_session.json` |
| Hết ngân sách → wakeup `skipped` lý do `budget` | **Đạt** — hạn mức $0.04 < ước lượng $0.05: `budget: … remaining 0.04`, **0** `chat.send` cho task 36 | bước C |
| Seat bận → bỏ qua rồi tự chạy lại | **Đạt** — #20 `seat_busy: run #20`, run #20 xong → #22 xếp lại (`requeued_from: 20`) → run #21 | bước D |
| Số chi phí/ngày trước và sau khi tắt heartbeat | **Có** — xem mục 3 | `evidence/d21/heartbeat_*.txt` |

Chi phí thật mỗi lượt e2e (sổ chi phí D1.2, từ `session.message`): **$0,0667** / lượt (~21,9k token vào, 68 ra).

## 1. Cách chạy

```
ADMIN=true DRAIN=5 tools/devup_approval.sh /tmp/frames_d21b.jsonl
.venv/bin/python tools/e2e_wakeup.py /tmp/frames_d21b.jsonl     # 7/7 OK
.venv/bin/python tools/shot_d21.py 35                            # UI, 0 lỗi console
```

`e2e_wakeup.py` có bước 0 (preflight): huỷ việc e2e còn mở của seat, từ chối lệnh chờ duyệt của
chúng, đợi seat rảnh. Lần chạy thứ hai **không có** bước này đã đỏ đúng chỗ: việc tồn đọng của lần
trước được requeue và chiếm seat — hành vi đúng của hàng đợi, nhưng làm sai kịch bản đo.

## 2. Lỗi chỉ lộ ra khi chạy thật

1. **Follower không bao giờ được gắn sau wakeup.** `drain` gọi `registry.follow` — tên không tồn
   tại (`supervisor` mới đúng); lỗi bị nuốt trong `except`. Hậu quả: run #17 được gateway chạy xong
   nhưng ClawCompany không nghe được frame cuối → run "đang chạy" mãi → seat kẹt `seat_busy` 30 phút.
   18 test xanh vì không test nào đi qua nhánh `follow=True`. Đã sửa (`_follow`, gắn ngay sau
   `chat.send`, trước mọi ghi DB — xem giới hạn #5 của `approval-e2e.md`) và thêm
   `test_dispatch_from_a_wakeup_attaches_the_follower_to_the_new_session` (đỏ trên mã cũ:
   `KeyError: 'followed'` + log `'StreamRegistry' object has no attribute 'follow'`).
2. **Wakeup ngoài giờ làm nằm im mãi.** Bị `skipped outside_active_hours` thì không sự kiện nào
   đánh thức lại. Đã thêm `requeue_when_hours_open` (mỗi task một lần khi giờ làm bắt đầu) + test.
3. **Panel "Đánh thức" đứng ở "đang chờ gộp".** Drain chạy ở backend, panel không biết khi nào
   xong. Đã cho panel hỏi lại 4 giây/lần khi còn dòng `queued`; ảnh `ui/d21-wakeups-after-mention.png`.

## 3. Heartbeat: trước / sau (WP-6.2)

**Trước (đo trên gateway thật):** `agents.defaults.heartbeat.every` chưa đặt → mặc định OpenClaw
30 phút. Phiên `agent:dev:main` có lượt heartbeat lúc 00:07:42, 00:37:42, 01:07:42, 01:37:42 — đúng
30 phút, dù không có việc. Mỗi lượt 10.005–10.722 token vào, 117 ra, **$0,0326–0,0339**.

HEARTBEAT_AFTER_PLACEHOLDER

## 4. Skill `clawcompany-heartbeat`

Nội dung: `backend/app/skills/clawcompany-heartbeat/SKILL.md` (company_context → approval vừa có
kết quả → company_tasks_list → company_task_checkout → làm → company_task_comment bắt buộc).
API: `POST /api/v19/openclaw/heartbeat-skill` (admin) — cài cho mọi seat agent đã gắn rồi đọc lại
`skills.status`; không coi là cài nếu gateway không liệt kê.

**Kế hoạch ghi "cài qua `agents.files.set`" — kiểm trên gateway thật thì không làm được:**

| Đường | Kết quả trên 2026.9.8 |
|---|---|
| `agents.files.set` | chỉ nhận 6 tên file bootstrap (AGENTS/SOUL/IDENTITY/USER/BOOTSTRAP/MEMORY.md); tên khác → `unsupported file` (`agents-*.mjs`, `ALLOWED_FILE_NAMES`) |
| `skills.library.save` | `SKILL_LIBRARY_IDENTITY_REQUIRED` — cần "durable Gateway profile", kết nối shared-token bị từ chối |
| `skills.upload.*` + `skills.install source=upload` | đúng đường, nhưng gateway trả `Uploaded skill archive installs are disabled by skills.install.allowUploadedArchives` |

ClawCompany báo đúng lý do `uploads_disabled` cho từng seat. **Chưa cài thật**: bật
`skills.install.allowUploadedArchives` là nới một chốt an ninh của gateway, nên em dừng lại chờ anh
quyết (trình kiểm duyệt tự động cũng chặn bước này khi chưa có đồng ý). Seat `sophia-cmo`,
`mia-content` gắn với agent id không có trên gateway (`unknown agent id`) — cần reconcile.

## 5. Mutation (mỗi đột biến chạy lại `test_d21_wakeups.py` / `test_d21_heartbeat_policy.py`)

| # | Đột biến | Kết quả |
|---|---|---|
| M1 | Bỏ pre-check dedupe trong `enqueue` | **xanh** — UNIQUE(dedupe_key) ở DB vẫn chặn bản trùng; đúng thiết kế, chốt cuối là DB |
| M2 | Bỏ cửa sổ gộp 10 s | đỏ |
| M3 | Bỏ gộp lý do cùng task | đỏ |
| M4 | Bỏ kiểm seat bận | đỏ |
| M5 | Bỏ chặn ngân sách | đỏ |
| M6 | Ngân sách không lọc theo công ty | đỏ |
| M7 | Bỏ kiểm activeHours | đỏ |
| M8 | Bỏ hạn 30 phút cho run treo | đỏ |
| M9 | Bỏ kiểm người nhận việc khi @nhắc | đỏ |
| M10 | Bỏ kiểm seat_inactive | đỏ |
| M11 | Bỏ `requeue_when_hours_open` | đỏ |
| M12 | Mã cũ gọi `registry.follow` | đỏ (test mới) |
| M13 | Chính sách heartbeat ghi cả agent chưa có trong config | đỏ |

## 6. Giới hạn còn lại

1. **Celery worker không giữ follower** (follower sống trong tiến trình API). Chạy drain bằng beat
   `drain-wakeups` thì cần `OPENCLAW_CLAIM_SWEEP_SECONDS>0` để API nhận phiên mồ côi. Dev dùng drain
   trong API (`WAKEUP_DRAIN_SECONDS`), mặc định **tắt** vì bật là cho hệ thống tự gọi model có phí.
2. Mention một seat **không phải** người nhận việc bị `skipped not_assignee` — chưa có luồng "nhờ
   xem giúp" cho người ngoài; để D2.2 (review_requested) xử lý.
3. Ước lượng giữ chỗ cố định $0,05/run; thực đo $0,0667 → D2.3 sẽ giữ chỗ/quyết toán theo số thật.
