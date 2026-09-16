# Tầng bộ nhớ của một nhân sự AI — ClawCompany khác OpenClaw ở đâu

> Tài liệu này trả lời câu hỏi: **một agent trong công ty phải nhớ những gì, và
> phần nào OpenClaw đã nhớ hộ, phần nào nó không thể nhớ vì thiết kế.**
>
> Mọi số trong đây đo được, không suy ra. Nguồn:
> `_reports/work-memory-gap.md`, `_reports/room-conductor-e2e.md`.

---

## 0. Phép đo mở đầu: agent hôm nay biết gì về việc của nó

Trước khi thiết kế, tôi dispatch một task thật cho một seat thật và ghi lại
**nguyên văn** prompt mà agent nhận:

```
Company task #1: Create 20 TikTok hooks

Generate 20 hooks based on current trend research.

Working agreement:
- Report progress as you go; the company records every gateway event.
- Do not publish externally, purchase, delete production data, or change production systems without human approval.
- Finish by stating the outcome and where the artifacts are.
```

**358 ký tự, trong đó 286 là văn bản cố định** giống nhau cho mọi task. Cùng
lúc đó, database của công ty biết:

| dữ kiện | database có | agent nhận được |
| --- | --- | --- |
| Tiêu đề task | Create 20 TikTok hooks | **có** |
| Mô tả task | Generate 20 hooks based on… | **có** |
| Mức ưu tiên | high | không |
| Trạng thái | backlog | không |
| Thuộc dự án | Summer Dress Campaign | không |
| Tiến độ dự án | 68% | không |
| Hạn chót dự án | 2026-09-30 | không |
| Công ty | Nova Fashion | không |
| Người được giao | Mia | không |
| Vai của người được giao | Content Lead | không |
| Quản lý trực tiếp | Sophia | không |

**10/12 dữ kiện công ty đã biết không đi vào prompt.** Hỏi lại agent ba câu:

> **Hỏi:** Việc tôi đang nhận thuộc dự án nào, và dự án đó nhằm mục tiêu gì?
> **Đáp:** "Hiện tại, không có thông tin nào về dự án hay việc gì cụ thể mà bạn
> đang thực hiện…"

Cả ba câu đều trả lời "không có thông tin". Đây là **điểm khởi đầu**, không phải
lỗi của OpenClaw: nó chưa bao giờ được cho biết.

---

## 1. Bảy tầng bộ nhớ mà một nhân sự trong công ty cần

Một nhân viên thật nhớ bảy loại thứ. Bảng dưới đây ánh xạ từng loại sang
OpenClaw, và **cột cuối là kết luận**.

| # | Tầng | Ví dụ | OpenClaw có? | Ai sở hữu |
| --- | --- | --- | --- | --- |
| 1 | **Danh tính & tính cách** | "tôi là Nina, chief of staff, nói ngắn gọn" | **CÓ** — `IDENTITY.md`, `SOUL.md` | OpenClaw |
| 2 | **Quy tắc nghề** | "quy tắc làm việc, SOP của vai này" | **CÓ** — `AGENTS.md` | OpenClaw |
| 3 | **Kinh nghiệm cá nhân** | "lần trước dùng cách X thì hiệu quả" | **CÓ** — `MEMORY.md` + dreaming | OpenClaw |
| 4 | **Sở thích người quản lý** | "Long thích báo cáo ba câu" | **CÓ** — `USER.md` | OpenClaw |
| 5 | **Ngữ cảnh một công việc** | "task này thuộc dự án nào, hạn khi nào, ai giao" | **KHÔNG** | **ClawCompany** |
| 6 | **Lịch sử một công việc** | "lần trước làm tới đâu, ai nhận xét gì" | **KHÔNG** | **ClawCompany** |
| 7 | **Tri thức tổ chức có phân quyền** | "SOP phòng nào, quyết định nào đã chốt" | **KHÔNG** | **ClawCompany** |

### Vì sao tầng 5–7 OpenClaw *không thể* có, chứ không phải *chưa* có

Không phải nó thiếu tính năng. Năm tầng bộ nhớ của OpenClaw
(`concepts/memory-architecture.md`) đều bị khoá theo **một agent** hoặc **một
phiên**:

| Tầng của OpenClaw | Bề mặt | Phạm vi |
| --- | --- | --- |
| Instructions | `AGENTS.md` | một agent |
| Curated core | `MEMORY.md`, `USER.md` | một agent |
| Episodic | `memory/YYYY-MM-DD.md`, transcript | một agent / một phiên |
| Prospective | standing intents (SQLite) | một agent |
| Review | `DREAMS.md` | một agent |

Cộng ba dữ kiện nữa, đều đã kiểm:

1. **Tìm kiếm bộ nhớ chéo agent đã bị xoá** ở upstream v2026.8.1. Trích
   `multi-agent.md`: *"Builtin memory does not search another agent's transcript
   corpus; each agent searches only its own configured memory."* Nghĩa là một
   task đi qua ba agent thì có ba bộ nhớ, không ai đọc của ai.
2. **Mỗi task mở một phiên riêng** (`agent:<id>:company-task-<n>`), nên transcript
   của lần chạy thứ hai không thấy lần đầu.
3. **Dreaming hợp nhất theo agent**, chạy cron `0 3 * * *`, và chỉ ghi vào
   `MEMORY.md`. Nó không có khái niệm "task #12".

Một **công việc** đi qua nhiều phiên, nhiều ngày, nhiều người làm thì không có
tầng nào của OpenClaw để trú. Đó là toàn bộ lý do ClawCompany phải sở hữu tầng
5–7.

---

## 2. Ranh giới đã chốt

> **Kinh nghiệm cá nhân ở OpenClaw. Sự thật về công việc ở ClawCompany.**

| Thứ | Ở đâu | Cơ chế |
| --- | --- | --- |
| Tính cách, danh tính | OpenClaw | `SOUL.md`, `IDENTITY.md` — sửa từ UI qua `agents.files.set` (WP-2.2) |
| Mô tả công việc của vai | OpenClaw | `AGENTS.md` |
| Kinh nghiệm cá nhân | OpenClaw | `MEMORY.md`, dreaming tự hợp nhất |
| Ghi chú hằng ngày | OpenClaw | `memory/YYYY-MM-DD.md` |
| Nhắc việc theo điều kiện | OpenClaw | standing intents |
| **Ngữ cảnh & lịch sử một task** | **ClawCompany** | `task_journal_entries` + gói ngữ cảnh |
| **Tri thức tổ chức có quyền** | **ClawCompany** | `knowledge_documents`, `knowledge_grants` |
| **Biên bản họp** | **ClawCompany** | `room_turns` |
| **Số đo hiệu suất, chi phí** | **ClawCompany** | `agent_daily_stats`, `usage_events` |

**Luật ở chỗ chạm nhau**, hai chiều:

* Agent đọc dữ liệu công ty **qua tool**, không qua bộ nhớ riêng của nó. Lý do:
  dữ liệu công ty cần phân quyền theo phòng ban và cần thu hồi được; `MEMORY.md`
  không làm được cả hai.
* Khi một task kết thúc, **bài học cá nhân** có thể được đề xuất vào `MEMORY.md`
  của agent — nhưng qua cửa duyệt (WP-2.5). Còn **sự thật về công việc** thì ở
  lại database công ty.

---

## 3. Gói ngữ cảnh công việc — bảy khối

`backend/app/services/work_context.py`. Mỗi lần dispatch task, gói này được lắp
mới và gửi thay cho brief bốn dòng cũ.

### Thứ tự khối và ngân sách

| # | Khối | Trả lời câu hỏi | Trần ký tự | Nguồn |
| --- | --- | --- | --- | --- |
| 1 | Bạn là ai trong việc này | tôi là ai, báo cho ai | 400 | `members`, `departments` |
| 2 | Việc cần làm | làm gì, ưu tiên nào | 1 200 | `tasks` |
| 3 | Nằm trong bức tranh nào | dự án gì, mục tiêu gì, hạn khi nào | 900 | `projects`, `companies` |
| 4 | Trước đây đã đi tới đâu | lần trước làm gì, ai nhận xét gì | 1 400 | `task_journal_entries` |
| 5 | Ai bàn giao cho bạn | ai giao, kèm hướng dẫn gì | 700 | `artifact_handoffs` |
| 6 | Luật áp dụng | SOP nào, quyết định nào đã chốt | 1 000 | `sops`, `decisions`, `approvals` |
| 7 | Thoả thuận làm việc | được tự quyết gì, phải xin gì | 400 | hằng số (brief cũ) |

Tổng ngân sách gói: **6 000 ký tự**. Tổng các trần lớn hơn con số đó có chủ ý —
hiếm khi mọi khối đều đầy, và trần từng khối chỉ để một khối không ăn hết.

### Quy tắc cắt, và vì sao nó không đối xứng

Khi vượt ngân sách, cắt theo thứ tự **4 → 3 → 5 → 1**.

**Khối 2, 6 và 7 không bao giờ bị cắt.**

Lý do, và đây là điểm thiết kế quan trọng nhất của module: *thiếu bối cảnh thì
agent làm **kém**; thiếu luật thì agent làm **sai**.* Hai hậu quả đó không cùng
hạng, nên không được đối xử như nhau khi phải chọn cái gì bỏ đi.

Sổ ghi 30 mục được nén bằng cách lấy 8 mục gần nhất và **nói ra** rằng đã nén:

```
## 4. Việc này trước đây đã đi tới đâu
- (Sổ ghi có 30 mục; dưới đây là 8 mục gần nhất.)
- [16/09 12:14] Mia · attempt → partial: Đã nghiên cứu 12 trend, chọn 5 hướng
- [16/09 12:14] Sophia · review → rejected: 3/5 hướng lệch tông thương hiệu
```

### Gói thật trông thế nào

Đo trên task #1 của dữ liệu seed: **1 310 ký tự** so với 358 của brief cũ. Nó
mang đủ Mia / Content Lead / Marketing / quản lý Sophia / Summer Dress Campaign
/ 68% / còn 14 ngày / Nova Fashion — tức đúng 10 dữ kiện đã bị mất trước đây.

---

## 4. Sổ ghi của task — tầng bộ nhớ mới

`task_journal_entries` (migration `0017_v37_work_memory_rooms`).

| Cột | Ý nghĩa |
| --- | --- |
| `task_id` + `seq` | thứ tự trong sổ; **unique** nên hai lượt ghi song song không chiếm cùng số |
| `actor_member_id` | ai ghi; NULL là hệ thống ghi |
| `kind` | `attempt` / `result` / `review` / `handoff` / `note` / `decision` / `blocker` |
| `summary` | **một câu** — đây là thứ đi vào prompt |
| `detail` | đầy đủ; **không** đi vào prompt |
| `outcome` | `success` / `partial` / `failed` / `rejected` / `blocked` / `cancelled`, hoặc rỗng |
| `runtime_run_id`, `runtime_session_key` | truy lại đúng lượt chạy nào sinh ra mục này |

Hai quy tắc giữ sổ không thành bãi rác:

1. **`summary` ngắn, `detail` dài.** Một task chạy 50 lần vẫn không làm nổ ngân
   sách ký tự, vì mỗi lần chỉ góp một câu.
2. **`outcome` rỗng nghĩa là *chưa đo được*, không phải thất bại.** `digest()`
   trả `success_rate: null` khi chưa có mục nào đo được — cùng lý lẽ với
   `success_rate` của v36. Tỉ lệ tính trên mẫu chưa đo là một con số nói dối.

Dispatch ghi một mục `attempt` mỗi lần giao việc. Nếu ghi sổ thất bại, việc vẫn
chạy nhưng lỗi được đẩy vào `LOG_JOURNAL_FAILURES` — **một sổ ghi có lỗ là một
sổ ghi nói dối về lịch sử**, nên chỗ hở phải đọc được.

---

## 4b. Phép đo trước–sau: cùng ba câu, cùng một seat

| Câu hỏi | Trước (brief 358 ký tự) | Sau (gói 1 310 ký tự) |
| --- | --- | --- |
| Việc thuộc dự án nào, mục tiêu gì? | *"không có thông tin nào về dự án"* | *"dự án **Summer Dress Campaign**… tiến độ 68% và còn 14 ngày"* |
| Ai giao việc, là quản lý hay đồng nghiệp? | *"không thể xác định"* | trả lời được, **nhưng nhầm vai** — xem ghi chú dưới |
| Hạn chót khi nào, còn mấy ngày? | *"phụ thuộc thông tin cụ thể mà bạn có"* | *"**14 ngày**, tới ngày 30 tháng 9 năm 2026"* |

**Câu thứ hai trả lời sai, và nguyên nhân là lỗi của phép đo.** Task #1 được gán
cho Mia nên khối 1 của gói nói "bạn là Mia", nhưng phép đo gửi gói đó vào seat
`dev` (Nina) — seat duy nhất đã kiểm chứng chạy được ở thời điểm đo. Một agent
nhận hồ sơ của người khác rồi bị hỏi "ai là quản lý của tôi" thì nhầm là dễ hiểu.

`dispatch_task` thật không có chỗ nhầm này: gói được lắp cho
`task.assignee_member_id` và gửi tới đúng seat của người đó. Nhưng bài học vẫn
cần ghi: **gói phải tới đúng seat của người mà khối 1 đang nói về**, nếu không
agent sẽ trả lời như thể nó là người khác.

## 5. Chứng cứ tầng bộ nhớ này tới được agent

Trong phiên họp thật (`_reports/room-conductor-e2e.md`), Nina mở đầu:

> "Mia, tôi biết bạn đã **nghiên cứu 12 trend TikTok** gần đây và chọn ra
> **5 hướng khả thi**, nhưng có **3/5 hướng đã bị Sophia từ chối** do không phù
> hợp với thương hiệu…"

Cả ba dữ kiện đó nằm trong `task_journal_entries`, không nằm trong tiêu đề task,
và không nằm trong bộ nhớ của OpenClaw. Nina đọc được chúng vì gói ngữ cảnh mang
chúng vào prompt.

---

## 6. Ba chỗ chưa làm, nói trước

1. **Tri thức tổ chức (tầng 7) chưa nối vào gói.** Khối 6 hiện chỉ đọc `sops`,
   `decisions`, `approvals` ở mức tổ chức, chưa lọc theo phòng ban và chưa kiểm
   `knowledge_grants` có thực sự chặn. Việc đó thuộc WP-3.3.
2. **Chưa có đường ngược từ task về `MEMORY.md`.** Bài học cá nhân sau mỗi task
   vẫn phải người tự viết; cửa duyệt tự động là WP-2.5.
3. **Ngân sách 6 000 ký tự là phỏng đoán có căn cứ, chưa phải số đo.** Nó dựa
   trên cỡ context window và giá mỗi lượt, nhưng chưa đo "gói dài bao nhiêu thì
   chất lượng trả lời bắt đầu giảm". Muốn biết thì phải chạy A/B, và đó là việc
   cần rubric.

---

## 7. Đọc tiếp

| File | Nội dung |
| --- | --- |
| `docs/AGENT_TEAMWORK.md` | năm kiểu phối hợp, chi tiết nhất là phòng họp có chủ toạ |
| `_reports/work-memory-gap.md` | phép đo trước–sau, cùng ba câu hỏi |
| `_reports/room-conductor-e2e.md` | biên bản một phiên họp thật giữa hai agent |
| `docs/ARCHITECTURE_TREE.md` | cây module bốn tầng và ranh giới OpenClaw/ClawCompany |
