# Agent làm việc nhóm — năm kiểu phối hợp, và cái nào chạy được

> Tài liệu này trả lời: **nhiều agent trong một team/công ty phối hợp với nhau
> bằng cách nào, OpenClaw cho sẵn cái gì, và ClawCompany phải tự làm cái gì.**
>
> Mọi số đo được. Nguồn: `_reports/room-conductor-e2e.md`,
> `openclaw@2026.9.4` docs (`concepts/multi-agent.md`,
> `delegate-architecture.md`, `queue.md`, `subagent-yield-handoff.md`).

---

## 0. Sự thật mở đầu: OpenClaw không mô hình hoá tổ chức

Ba dữ kiện, đều trích nguyên văn từ docs upstream:

* `agents.entries` là **danh sách phẳng**. Không có `reportsTo`, không có
  `department`. `openclaw agents list --tree` chỉ hiện *ai tạo ra ai*
  (creation provenance), không phải sơ đồ tổ chức.
* Gợi ý uỷ quyền chỉ là gợi ý: `subagents.delegationMode: "prefer"` được docs
  gọi đúng tên là *"prompt guidance only"*.
* Không có cân bằng tải, không có metric hiệu suất per-agent.
  `agents.defaults.maxConcurrent` là **trần**, không phải bộ cân bằng.

Nên **toàn bộ phần "công ty" của làm việc nhóm là việc của ClawCompany.** Đó
cũng là giá trị riêng của sản phẩm này: OpenClaw là bộ não và đôi tay của một cá
nhân; tổ chức thì phải xây.

Và sự thật thứ hai, đo trong chính repo này: trước v37, **trong 93 service chỉ
có ba chỗ từng gọi `run_agent`** — `agent_dispatch`, `workflow_executor`,
`v36_insights.ask_nina`. `collaboration_rooms.py` và `delegation.py` **không có
một lời gọi runtime nào**. Nghĩa là phòng họp có thứ tự lượt mà chưa agent nào
từng nói, và hợp đồng bàn giao mà chưa agent nào từng nhận.

---

## 1. Ràng buộc vật lý phải tôn trọng

Bốn con số này định hình mọi thiết kế phối hợp. Chúng là của OpenClaw, không
phải lựa chọn của ta.

| Ràng buộc | Con số | Hệ quả cho thiết kế |
| --- | --- | --- |
| Một phiên chạy một lượt | — | Agent nói **lần lượt**, không đồng thời trong cùng phiên |
| Message thứ hai vào phiên đang chạy | queue mode `steer` (mặc định) | Nó **bị chèn vào lượt đang chạy**, không tạo lượt mới |
| Trần subagent | `maxSpawnDepth` 1–5, `maxChildrenPerAgent` 5, `subagents.maxConcurrent` 8 | Không mô hình hoá phòng ban bằng cây subagent |
| Cap kết quả subagent | findings 4 096 ký tự, mỗi kết quả 512 | Bàn giao dài phải qua artifact, không qua findings |

Ràng buộc thứ hai **đã làm tôi mất một phép đo**: phép đo trước–sau của gói ngữ
cảnh gửi gói rồi hỏi ngay trong cùng phiên, và cả ba câu hỏi đều hết thời gian
chờ — vì chúng bị `steer` vào lượt đang chạy thay vì tạo lượt mới. Cách đúng là
chờ lượt trước kết thúc. Chi tiết trong `_reports/work-memory-gap.md`.

Ràng buộc thứ nhất khớp với đời thật hơn là người ta tưởng: một cuộc họp mà mọi
người nói cùng lúc thì không ai nghe được gì.

---

## 2. Năm kiểu phối hợp trong một công ty

| Kiểu | Đời thật | ClawCompany hiện có | Trạng thái |
| --- | --- | --- | --- |
| **A. Phòng họp có chủ toạ** | nhiều người bàn, một người chốt | `collaboration_rooms` + bộ điều phối v37 | **CHẠY ĐƯỢC** |
| **B. Bàn giao có ngữ cảnh** | giao việc kèm hồ sơ và lời nhắn | `artifact_handoffs`, khối 5 của gói ngữ cảnh | đọc được, chưa có dây gọi agent |
| **C. Giao việc theo năng lực** | trưởng phòng phân việc | chưa có service chọn seat | **CHƯA CÓ** |
| **D. Review hai vòng** | làm xong, người khác soát | `repository_reviews`, `approvals` | có bảng, chưa nối runtime |
| **E. Làm song song rồi hợp nhất** | ba người làm ba phần | `sessions_spawn` của OpenClaw | dùng được cho việc phụ ngắn |

Thứ tự này không tuỳ tiện. **A trước** vì nó là kiểu phối hợp duy nhất mà máy
trạng thái đã có đủ chốt (thứ tự lượt, quyền chốt, trần lượt) — chỉ thiếu người
gọi agent. Xây A là nối một dây, xây C là thiết kế một thuật toán.

---

## 3. Kiểu A — phòng họp có chủ toạ (đã chạy thật)

### Cái đã có từ v16, không xây lại

| Thành phần | Chi tiết |
| --- | --- |
| `collaboration_rooms` | `mode`: `lead_routed` / `round_robin` / `free`; `turn_cursor`; `max_turns` |
| `room_participants` | `seat_order`, `can_post`, `can_decide` |
| `room_turns` | `sequence` (unique theo phòng), 5 loại: `message` / `proposal` / `decision` / `handoff` / `summary` |
| Chốt | sai lượt → `Out of turn`; không `can_decide` → không ghi được `decision`; vượt `max_turns` → từ chối |
| Event | mỗi lượt phát `collaboration.turn.<type>` ra event bus |

### Cái v37 thêm

`backend/app/services/room_conductor.py` — vòng lặp chín bước:

```
1. Kiểm phòng còn mở và còn ngân sách tiền
2. Ai nói lượt tới?          → rooms.expected_speaker (round_robin) hoặc chọn người chưa nói lâu nhất
3. Dựng prompt cho người đó  → mục tiêu phòng + roster + biên bản + gói ngữ cảnh công việc + vai
4. chat.send                 → vào PHIÊN RIÊNG của phòng: agent:<id>:room-<key>
5. Chờ trả lời               → chat.history, chỉ nhận message MỚI
6. Ghi biên bản              → rooms.post_turn (đi qua đúng mọi chốt của v16)
7. Ghi vận hành              → room_conductor_runs: prompt/reply bao nhiêu ký tự, mấy giây, lỗi gì
8. Cập nhật                  → turn_cursor, cost_spent_usd, stall_count
9. Kiểm điều kiện dừng
```

Cộng ba cột mới trên `collaboration_rooms`: `chair_member_id`,
`cost_budget_usd` / `cost_spent_usd`, `stall_count` / `stopped_reason`.

### Năm điều kiện dừng

| Lý do | Khi nào | Phòng có đóng? |
| --- | --- | --- |
| `chair_closed` | chủ toạ ghi một dòng `QUYẾT ĐỊNH:` hoặc `TÓM TẮT:` | **có** |
| `budget` | `cost_spent_usd >= cost_budget_usd` | không — để người thật vào xem |
| `stalled` | hai lượt liên tiếp không thêm thông tin mới | không |
| `max_turns` | hết trần lượt của phòng | không |
| `waiting_for_human` | round-robin tới lượt một người thật | không — chờ họ nói |

Thêm `call_limit`: hết số lượt của **lời gọi này** (khác với phòng đã dừng).

Bộ điều phối **từ chối chạy** nếu `cost_budget_usd` bằng 0. Mỗi lượt là một lời
gọi model có phí; một phòng toàn agent không có trần tiền là một hoá đơn mở, và
"quên đặt hạn mức" không phải lý do để hệ thống tự tiêu tiền.

### Biên bản một phiên họp thật

Đo được với hai agent thật trên gateway 2026.9.4 (`_reports/room-conductor-e2e.md`).
Seat thứ hai (`mia`) được tạo **qua wire** bằng `agents.create` — chính method mà
repo từng khẳng định không tồn tại.

| # | Người | Loại | Nội dung (rút gọn) |
| --- | --- | --- | --- |
| 1 | Nina (chủ toạ) | `message` | "…Mia đã nghiên cứu 12 trend và chọn 5 hướng khả thi. Bạn chia sẻ chi tiết để chúng ta thảo luận?" |
| 2 | Mia | `proposal` | 5 hook cụ thể, mỗi cái kèm lý do |
| 3 | Nina | `decision` | "`QUYẾT ĐỊNH:` chấp nhận 5 hook…" → phòng đóng |

Vận hành: prompt 2 250 → 2 630 → 4 023 ký tự, mỗi lượt ~10 giây, hai session
riêng `agent:dev:room-…` và `agent:mia:room-…`. **Không lượt nào dùng
`agent:<id>:main`** — biên bản họp không làm bẩn phiên mà người vận hành đang
dùng để chat với agent.

Điều đáng chú ý nhất: lượt 1 của Nina nhắc "12 trend", "5 hướng khả thi",
"3/5 bị Sophia từ chối". Cả ba nằm trong `task_journal_entries` — **tầng bộ nhớ
công việc đi tới được agent qua gói ngữ cảnh.**

### Ba lỗi mà chỉ chạy thật mới thấy

Ba lỗi này không một test nào với câu trả lời dàn dựng phát hiện được. Ghi lại vì
chúng là bài học, không chỉ là mục changelog.

**1. "Sẽ quyết định" bị đọc thành "tôi chốt".** Nina mở đầu cuộc họp bằng *"sau
khi lắng nghe, chúng ta **sẽ quyết định** và giao nhiệm vụ"* — một dự định tương
lai. Bộ phân loại theo từ khoá đọc thành quyết định, phòng đóng sau một lượt,
Mia không nói được câu nào.

*Sửa:* **đừng suy diễn cái có thể yêu cầu.** Prompt dặn chủ toạ viết một dòng
riêng bắt đầu bằng đúng chữ `QUYẾT ĐỊNH:`; không có dòng đó thì cuộc họp tiếp tục.

**2. Chốt chống treo không bắt được vòng lặp luân phiên.** Bản đầu so lượt mới
với lượt **liền trước** của phòng. Nhưng vòng lặp trong cuộc họp luân phiên có
hình `A B A B` — hai lượt liền nhau luôn khác nhau. Đo được: Nina lặp lại nguyên
văn ở lượt 1 và 3, Mia ở lượt 2 và 4, `stall_count` vẫn bằng 0.

*Sửa:* so với lượt gần nhất của **chính người nói**, cộng cả lượt liền trước.

**3. Đọc lại câu trả lời cũ trong cùng session — nguyên nhân gốc của lỗi 2.**
Phòng họp dùng một session dài, nên từ lượt hai trở đi session **đã có** câu trả
lời cũ. Bản đầu đọc "message trợ lý cuối cùng"; khi model chưa kịp trả lời trong
nhịp poll đầu, nó đọc lại câu cũ và tưởng là câu mới. Bằng chứng nằm ngay trong
số đo: lượt 1 mất 10,09 giây (hai nhịp poll) còn lượt 3 chỉ 5,06 giây (một nhịp)
và trả về **đúng từng ký tự** câu của lượt 1.

*Sửa:* chụp vân tay các message trợ lý **trước khi gửi**, rồi chỉ nhận message
không có trong tập đó.

---

## 4. Bốn kiểu còn lại — nên làm gì tiếp

### B. Bàn giao có ngữ cảnh

Đã có `artifact_handoffs` với `from_member_id`, `to_member_id`, `purpose`,
`instructions`, và khối 5 của gói ngữ cảnh đã đọc nó — agent nhận việc thấy được
"Nina bàn giao (review): Kiểm tông thương hiệu trước khi đăng".

Còn thiếu: **không ai gọi agent khi có bàn giao**. Một bàn giao nằm im tới khi
có người dispatch task. Việc cần làm nhỏ: khi `artifact_handoffs` được tạo với
`to_member_id` là một agent đang hoạt động, ghi một mục `handoff` vào sổ ghi task
rồi dispatch. Nên gộp vào WP-4.1.

### C. Giao việc theo năng lực — chưa có, và đây là việc khó nhất

Không có service nào chọn người làm. Task được gán tay.

Thiết kế đề xuất: một service **thuần** nhận `(task, danh sách seat, tải hiện
tại, ngân sách còn lại)` trả về `(seat, lý do chọn)`. Thuần thì test được bằng
hành vi, và **lý do chọn phải lưu lại** — quản lý sẽ hỏi "tại sao việc này giao
cho nó", và "thuật toán chọn" không phải một câu trả lời.

Cảnh báo về phạm vi: OpenClaw không có metric hiệu suất per-agent, nên "chọn
người giỏi nhất việc này" chưa có dữ liệu để tính. `agent_daily_stats` của v36
là khởi đầu, nhưng `success_rate` của nó trả `null` khi chưa đo được — và một
thuật toán phân việc dựa trên `null` thì chỉ là phân việc theo thứ tự id.

### D. Review hai vòng

`repository_reviews` và `approvals` đã có. Cái thiếu giống kiểu A: không ai gọi
agent reviewer. Dùng lại được gần hết bộ điều phối phòng họp — một review là một
phòng hai người với `max_turns` nhỏ và chủ toạ là người duyệt.

### E. Làm song song rồi hợp nhất

Đây là chỗ **nên dùng OpenClaw chứ đừng tự xây**: `sessions_spawn` /
`sessions_yield` đã có, kèm trần rõ ràng.

Nhưng chỉ dùng cho **việc phụ ngắn trong một lượt** (một seat cần tra cứu song
song ba nguồn). **Đừng mô hình hoá phòng ban bằng cây subagent**: subagent chết
theo run, không có danh tính, không đo được, và docs thừa nhận *"channel-visible
progress across yield remains follow-up work"*.

Ranh giới: `sessions_spawn` cho việc phụ trong một lượt;
`delegation_contracts` của ClawCompany cho bàn giao thật giữa hai nhân sự (có
người chịu trách nhiệm, có SLA, có audit).

---

## 5. Ba điều chưa kiểm chứng, nói trước

1. **Chưa thử một phòng ba agent trở lên.** Đã chạy hai. Với ba người, câu hỏi
   mở là chi phí tăng tuyến tính còn chất lượng thảo luận thì không — và
   `TRANSCRIPT_LINES = 12` có thể phải giảm.
2. **`cost_per_turn_usd` là ước lượng do caller đưa vào, không phải giá thật.**
   Giá thật nằm ở `usage.cost` của gateway, và hai nguồn tiền của dự án chưa từng
   được đối chiếu (WP-1.4 còn nợ). Mọi trần tiền hiện tại chặn theo số ước lượng.
3. **Ngưỡng treo `0.92` là phỏng đoán.** Nó bắt được vòng lặp lặp-nguyên-văn đã
   gặp, nhưng chưa biết nó có bắt được kiểu "nói khác chữ mà cùng nội dung" hay
   không. Muốn biết thì phải có mẫu phòng họp thật nhiều hơn một.

---

## 6. Đọc tiếp

| File | Nội dung |
| --- | --- |
| `docs/AGENT_WORK_MEMORY.md` | bảy tầng bộ nhớ, ranh giới OpenClaw/ClawCompany, gói ngữ cảnh |
| `_reports/room-conductor-e2e.md` | biên bản phiên họp thật, kèm số vận hành |
| `_reports/work-memory-gap.md` | phép đo trước–sau của gói ngữ cảnh |
| `backend/app/services/room_conductor.py` | vòng lặp chín bước, năm điều kiện dừng |
