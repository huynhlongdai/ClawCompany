# M4b · Hộp việc, phê duyệt, chi phí — spec 1 trang

Kiểm kê từ code `main @ e2ea31a` (không suy từ docs). Mục "Mới trong M4b" là phần làm ở nhánh `m4b-inbox`.

## 1. Hiện trạng đã kiểm (trước M4b)

| Loại | Có gì | Ở đâu |
|---|---|---|
| Bảng | `inbox_items` (gộp theo `(người nhận, group_key)`, `kinds`, `count`, `body` — 0025) | `models/extended.py` |
| | `approvals` (`expires_at`, `escalate_to_member_id`, `escalated_at` — 0025; `payload`, `revision` — 0027) | `models/entities.py` |
| | `budget_envelopes` (`scope_type/scope_id`, `warn_pct`, `threshold_state` ok/warned/exhausted — 0023), `budget_ledger_entries` (reserve/spend/release/credit) | `models/v9.py` |
| | `usage_events` loại `model_usage` (tiền model từ `session.message`), `task_runs.cost_usd` | `cost_ledger.py` |
| Service | `inbox.py`: `notify` gộp theo task, 9 loại báo, hook ORM cho mọi `Approval` (hạn 24h + người leo thang + dòng inbox; đóng dòng khi có kết quả), `escalate_overdue` | |
| | `budget_scope.py`: cổng giữ chỗ trước `chat.send` (`gate`), quyết toán luỹ đẳng, đối chiếu `sessions.usage`, nấc 80% (inbox + luật khối 6) / 100% (seat `paused`, việc `blocked`), `override` có audit | |
| | `approval_bridge.decide` (approval `openclaw:` → `exec.approval.resolve`) | |
| Job | Celery beat `approvals.escalate_overdue` 60s + vòng trong tiến trình API (`approval_escalate_seconds`) | `worker.py`, `main.py` |
| Endpoint | `GET /inbox`, `POST /inbox`, `POST /inbox/{id}/read` (extended) · `GET /v9/inbox/mine`, `POST /v9/inbox/{id}/status`, `GET /v9/approvals/quick`, `POST /v9/approvals/escalate-overdue` · `GET /approvals`, `POST /approvals`, `POST /approvals/{id}/resolve` · `GET /v20/approvals/openclaw`, `GET /v21/approvals/readiness`, `POST /v21/approvals/{id}/decide` · `POST /v24/approvals/backfill` · `POST /strategy/plans/{id}/request-revision` · `GET|POST /v9/budgets`, `GET /v9/budgets-overview`, `GET /v9/budgets/{id}`, `POST /v9/budgets/{id}/override`, `POST /v9/budgets/{id}/entries` · `GET /tasks/cost-reconciliation` · `/v35/spend/*` (phân bổ chi theo delegation — nhóm ẩn) | `api/*.py` |
| Trang | `/app/inbox` (`InboxConsole`: 4 nguồn ghép phía trình duyệt), `/app/approve` (`QuickApprove`, inline style), `/app/budgets` (`BudgetsConsole`, class v9) | `components/` |

**Lỗ hổng đo được trong code cũ:** `POST /approvals/{id}/resolve` với approval thường **không kiểm `status`** (duyệt lại một hàng đã quyết vẫn 200 và chạy lại hậu quả) và cho **mọi manager** quyết dù đã có người duyệt; không có nấc giữa "cảnh báo" và "dừng hẳn"; số đếm chuông ghép từ 3 request và không khớp hộp việc.

## 2. Mới trong M4b

**API `/api/inbox`** (`api/inbox.py`, luật ở `services/inbox_hub.py`)

| Đường | Việc |
|---|---|
| `GET /items?status=open\|all\|…&group=&member_id=&department_id=` | dòng hộp việc của người đăng nhập + phê duyệt anh được quyết mà chưa có dòng; 5 nhóm `approvals` (Cần anh duyệt) · `review` (Cần anh xem: vào review, run lỗi) · `budget` · `lessons` (Bài học đề xuất) · `updates`; `counts` {open, unread, need_action, overdue, by_group}; mỗi thẻ duyệt có `can_decide`, `revision`, `kind` (stage/plan/budget/gateway/other), hạn bằng câu tiếng Việt, `escalation_blocked` |
| `GET /summary` | chỉ số đếm (chuông/menu) |
| `POST /items/{id}/status`, `POST /items/read-all` | đã đọc / xong; dòng của người khác → 403 |
| `POST /approvals/{id}/decide` | `{decision: approve\|reject, note, expected_revision, grant_scope?}` — một chạm. Giành quyền bằng `UPDATE … WHERE status='pending' AND revision=?` → hai lần bấm: một thắng, một 409 `already_decided`; revision cũ → 409 `stale_revision`; không phải người duyệt hiện tại → 403 `not_the_approver` (không có người duyệt → quản lý trở lên); từ chối thiếu lý do → 422 `note_required`. Hậu quả theo loại: chặng duyệt / kế hoạch Nina / chi tiếp ngân sách / gateway (`approval_bridge`, nói thẳng khi chưa gửi được) / đánh thức seat xin duyệt |
| `POST /escalate` | (quản lý) chạy vòng leo thang ngay; câu kết quả nói rõ yêu cầu nào không có cấp trên |

**API `/api/costs`** (`services/cost_board.py`)

| Đường | Việc |
|---|---|
| `GET /overview?days=30` | tổng chi model hôm nay / 7 ngày / kỳ, theo agent / phòng / công ty / ngày — từ `usage_events.model_usage` (cost_ledger) |
| `GET /budgets`, `POST /budgets`, `GET\|PATCH\|DELETE /budgets/{id}`, `POST /budgets/{id}/override` | ngân sách theo **công ty / phòng ban / nhóm / agent**, 3 nấc: cảnh báo `warn_pct` → **dừng mềm** `soft_stop_pct` (mới, cột 0030) → **dừng cứng** 100%. Kiểm nấc (cảnh báo < mềm < 100), trùng phạm vi 409, phạm vi tổ chức khác 404; ngân sách đã dừng cứng chỉ mở qua override có lý do |

**Dừng mềm** (`budget_scope.soft_gate`): phong bì ở nấc mềm → mỗi việc trong phạm vi muốn chạy lượt mới phải có phê duyệt `budget_soft:e<id>:t<task>` (tự tạo một lần, gửi quản lý người của seat, hiện ở nhóm "Cần anh duyệt"); duyệt → đánh thức lại seat; từ chối → không hỏi lại; rời nấc (nâng hạn mức / override / lưu trữ) → mọi phê duyệt chi tiếp `expired`. Dừng cứng luôn thắng phê duyệt.

**Alias cũ** (vẫn chạy, `Deprecation: true` + `Link: <mới>; rel="successor-version"`): `GET /inbox`, `/inbox/{id}/read`, `/v9/inbox/mine`, `/v9/inbox/{id}/status`, `/v9/approvals/quick`, `/v9/approvals/escalate-overdue`, `/approvals/{id}/resolve`, `/v21/approvals/{id}/decide`, `/v9/budgets`, `/v9/budgets-overview`, `GET /v9/budgets/{id}`, `/v9/budgets/{id}/override`. Không đổi: `POST /inbox` (tạo dòng), `/v9/budgets/{id}/entries`, `/v20/approvals/openclaw`, `/v35/spend/*`.

**UI:** `/app/inbox` (thẻ duyệt một chạm, chạy ở 390px; `/app/approve` → nhóm duyệt), `/app/costs` "Chi phí" (Tổng quan + Ngân sách 3 nấc; `/app/budgets` → tab Ngân sách).

## 3. Thiết kế cho "công ty agent" (theo định hướng của anh, 14/10)

Mục tiêu sản phẩm là biến công ty truyền thống thành công ty agent: đủ phòng ban và nhân sự, nhân sự AI
học và tiến bộ, làm theo nhóm và làm độc lập. Phạm vi M4b giữ nguyên, nhưng ba phần được khoá theo
**seat / phòng ban / nhóm**, không chỉ theo từng việc:

- **Ngân sách:** phạm vi `company | department | team | member(seat)` (`team` = `agent_teams` +
  `agent_team_members` đang `active`; chạm dừng cứng thì chỉ seat trong nhóm bị tạm dừng). Phê duyệt chi tiếp
  ở nấc dừng mềm được yêu cầu theo việc, nhưng người duyệt chọn **phạm vi cấp**: `task` (mặc định) /
  `seat` / `department` (`grant_scope` lưu ở `approvals.payload`). Cấp cho seat/phòng → mọi yêu cầu đang chờ
  mà nó phủ được duyệt theo (đóng dòng hộp việc), seat được đánh thức lại, việc mới trong phạm vi không hỏi lại
  tới khi phong bì rời nấc.
- **Phê duyệt / leo thang:** người được quyết = người duyệt hiện tại, hoặc người quản lý (là người) của seat
  agent khi người duyệt là seat. Quá hạn mà không có quản lý → **trưởng phòng** của seat xin duyệt
  (`inbox.department_head_for`) trước khi báo "không có cấp trên".
- **Hộp việc:** mỗi thẻ mang `seat` và `department` (người nhận việc hoặc seat xin duyệt); lọc
  `?member_id=` / `?department_id=` để trưởng phòng xem hàng chờ của phòng mình.
- **Chỗ cho vòng học M5:** loại báo `lesson_proposal` và nhóm riêng **"Bài học đề xuất"** (`lessons`);
  phê duyệt `policy_key` `lesson:…` hiện thẻ loại `lesson` và đi qua đúng luồng duyệt một chạm (đua / revision /
  người duyệt). Hậu quả hiện là chỗ giữ (`effect: lesson, applied: false`) — M5 nối vào ghi `MEMORY.md`
  của agent qua `agents.files.set`.

## 4. Chưa làm / ngoài phạm vi
- **Chưa chạy gate gateway thật** (chưa có key model): phê duyệt `openclaw:` chỉ thử với runtime giả có `respond_approval`; chi phí khớp ±5% chưa đo lại ở M4b.
- Kỳ ngân sách (`period`) vẫn `total` — chưa có reset theo tháng.
- Dọn trang cũ `InboxConsole`/`QuickApprove`/`BudgetsConsole` để M7 (không còn route nào trỏ tới sau M4b, file giữ lại).
