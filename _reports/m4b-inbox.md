# M4b · Hộp việc, phê duyệt, chi phí — báo cáo

**Gate (gateway thật): CHƯA CHẠY.** Chưa có key model, nên chưa có lượt chạy thật nào qua OpenClaw ở module này.
Mọi kết quả dưới đây là ORM thật + SQLite + HTTP thật với runtime giả (ghi lời gọi `chat.send` / `respond_approval`),
và một lượt chạy UI thật (API uvicorn + `next start` + Chromium) trên dữ liệu seed. Module **chưa được gọi là "ổn định"**.

Nhánh local `m4b-inbox` (chưa push — chưa có credentials). Spec: `docs/m4b-spec.md`.

## API gom về `/api/inbox` và `/api/costs` (spec từ code)
| Đường | Việc |
|---|---|
| `GET /inbox/items` | hộp việc của người đăng nhập, 5 nhóm: Cần anh duyệt · Cần anh xem · Ngân sách · Bài học đề xuất · Thông báo; `counts` {open, unread, need_action, overdue, by_group}; thẻ mang `seat` + `department`, lọc `group`, `member_id`, `department_id`; phê duyệt anh quyết được mà chưa có dòng inbox vẫn hiện |
| `GET /inbox/summary` | số đếm cho chuông (chuông nay = `need_action`, cùng nguồn với trang) |
| `POST /inbox/items/{id}/status`, `/items/read-all` | đã đọc / xong; dòng của người khác → 403 tiếng Việt |
| `POST /inbox/approvals/{id}/decide` | một chạm: `UPDATE … WHERE status='pending' AND revision=?` giành quyền → 409 `already_decided` / `stale_revision`; 403 `not_the_approver`; 422 `note_required` khi từ chối thiếu lý do; budget có `grant_scope` task/seat/department; gateway đi qua `approval_bridge` và **nói thẳng khi chưa gửi được tới OpenClaw** |
| `POST /inbox/escalate` | (quản lý) leo thang ngay; quá hạn mà không có quản lý → trưởng phòng; vẫn không có → nói rõ, không spam audit |
| `GET /costs/overview` | chi model hôm nay / 7 ngày / kỳ, theo agent / phòng / công ty / ngày từ `usage_events.model_usage` |
| `GET|POST /costs/budgets`, `GET|PATCH|DELETE /costs/budgets/{id}`, `POST …/override` | ngân sách công ty / phòng ban / nhóm / agent, 3 nấc: cảnh báo → **dừng mềm** (mới, `soft_stop_pct`, migration 0030) → dừng cứng 100% |

Dừng mềm: chạm nấc → cổng dispatch (`budget_scope.gate`, dùng chung cho lượt thường, lượt định tuyến, lượt phòng họp) tự tạo
**một** phê duyệt `budget_soft:e<id>:t<task>` gửi quản lý người của seat và chặn `chat.send`; duyệt → đánh thức lại seat;
duyệt cho cả seat / cả phòng → các yêu cầu đang chờ mà nó phủ được duyệt theo; từ chối → không hỏi lại; rời nấc / override / lưu trữ
→ phê duyệt chi tiếp `expired`. Dừng cứng luôn thắng phê duyệt.

Đường cũ vẫn chạy, trả `Deprecation: true` + `Link: <…>; rel="successor-version"`: `GET /inbox`, `/inbox/{id}/read`,
`/v9/inbox/mine`, `/v9/inbox/{id}/status`, `/v9/approvals/quick`, `/v9/approvals/escalate-overdue`, `/approvals/{id}/resolve`,
`/v21/approvals/{id}/decide`, `/v9/budgets`, `/v9/budgets-overview`, `GET /v9/budgets/{id}`, `/v9/budgets/{id}/override`.

## Thiết kế cho công ty agent (theo định hướng anh, 14/10)
Ngân sách / phê duyệt / hộp việc khoá theo seat – phòng ban – nhóm (`agent_teams`), không chỉ theo việc; hộp việc có chỗ cho
**đề xuất bài học** (loại `lesson_proposal`, nhóm riêng, phê duyệt `lesson:` đi qua đúng luồng một chạm, hậu quả hiện là chỗ giữ
`applied: false` để M5 nối vào `MEMORY.md`). Chi tiết `docs/m4b-spec.md` §3.

## Lỗi thật tìm được (đã sửa)
1. **`POST /approvals/{id}/resolve` quyết lại một hàng đã quyết vẫn 200** và chạy lại hậu quả (đánh thức seat lần hai) — đo bằng
   request thật: 200 → 200, trạng thái bị lật `approved → rejected`. Nay 409 `already_decided` (route cũ), route mới giành quyền nguyên tử.
2. Route cũ cho **mọi manager** quyết approval thường dù đã có người duyệt; route mới chỉ cho người duyệt hiện tại (sau leo thang là cấp trên).
3. Không có nấc giữa "cảnh báo" và "dừng hẳn": chạm 100% là seat bị tạm dừng ngay — nay có dừng mềm cần duyệt.
4. Số trên chuông ghép từ 3 request khác nguồn với Hộp việc → nay lấy từ `/api/inbox/summary`.
5. Lộ ra khi chụp UI: thẻ phê duyệt gateway quá hạn báo "không có cấp trên để chuyển lên" (gateway vốn không leo thang) → nay "gateway
   sẽ tự huỷ lệnh này"; phong bì cũ loại goal/project hiện nhãn tiếng Anh; chip nấc tràn ra ngoài thẻ ở 390px.

## Kiểm chứng
- `tests/test_m4b_inbox.py` **24 test** (ORM thật + SQLite + HTTP): nhóm/đếm/tách hộp việc từng người và từng tổ chức; duyệt một chạm
  đóng dòng + audit + đánh thức; từ chối thiếu lý do; người duyệt không hợp lệ (nhân viên, chủ không phải người duyệt, tổ chức khác,
  không có người duyệt, người duyệt là seat agent); **đua duyệt hai phiên** (một thắng, một 409, đúng một audit); **revision cũ**;
  gateway qua bridge đúng một lần + nói thẳng khi chưa gửi được; leo thang lên quản lý (người duyệt cũ mất quyền), **không có quản lý**
  (nói rõ, không spam), xuống trưởng phòng; **dừng mềm chặn dispatch** tới khi duyệt; từ chối giữ chặn; **dừng cứng chặn dispatch dù đã
  duyệt mềm**; nâng hạn mức huỷ phê duyệt; thứ tự nấc; cấp theo phòng gỡ cả hàng chờ; ngân sách nhóm chỉ phủ thành viên nhóm; bài học;
  CRUD ngân sách tiếng Việt (nấc sai, trùng phạm vi, phạm vi tổ chức khác, quyền); override bắt lý do; tổng chi chỉ tính `model_usage`;
  đường cũ có Deprecation + Link, đường mới không.
- Mutation `tools/mutate_m4b.py`: **29/29 bị bắt**. Lần đầu M1 (bỏ UPDATE giành quyền) **sống sót** — test đua không giữ tham chiếu tới
  bản đã đọc nên identity map nạp lại hàng đã duyệt; lỗi ở test, đã siết.
- Full pytest trên commit UI cuối (`07e3eef`): **1087 passed, 2 skipped** (5 phút 57 giây; trước M4b: 1063 passed) — không sửa test cũ nào.
- Frontend: `npx tsc --noEmit` sạch; `npx next build` xanh (`/app/inbox` 5.2 kB, `/app/costs` 5.24 kB).
- UI (`tools/shoot_m4b.mjs`, Chromium, 1440px + 390px): 0 lỗi console/HTTP của app (chỉ có 407 tải font Google do proxy sandbox),
  0 tràn ngang; bấm thật nút Duyệt trên thẻ gateway ở 390px → thông báo "Đã duyệt — nhưng CHƯA gửi được tới OpenClaw… (Upstream
  reply not configured: OPENCLAW_REQUEST_APPROVALS_SCOPE)"; `/app/approve` → `/app/inbox?group=approvals`.

## Còn lại cho gate gateway thật
- Duyệt lệnh exec của agent từ Hộp việc trên điện thoại khi gateway thật đang chờ (`exec.approval.resolve` tới nơi, lượt chạy chạy tiếp).
- Dừng mềm với chi phí thật: seat chạm nấc giữa kịch bản "Ra mắt bộ sưu tập hè, $20" → phê duyệt → chạy tiếp; chi phí trên trang Chi phí
  khớp `sessions.usage` ±5% (D1.2 đã có đối chiếu, M4b chưa đo lại).
- Leo thang thật theo Celery beat trên box (ở đây chỉ chạy qua API / hàm).
- Người chỉ bị ping đúng số lần mong muốn (G5): cần đếm trên gateway thật.

## Ghi chú
- Gộp theo việc của D3.5 vẫn giữ: báo "chờ duyệt" và "run lỗi" của cùng một việc dồn vào một dòng (dòng nằm ở "Cần anh xem"), thẻ duyệt
  khi đó vẫn hiện riêng ở "Cần anh duyệt" nhờ đường bù "phê duyệt chưa có dòng". Có thể tách rõ hơn ở M7.
- Kỳ ngân sách vẫn `total` (chưa reset theo tháng). Trang cũ `InboxConsole`, `QuickApprove`, `BudgetsConsole` không còn route nào trỏ tới, file giữ lại.
- `components/BeCang.tsx` là bản mascot SVG đầu tiên trong repo (trước M4b chưa có component Bé Càng nào, dù brief nói "như các trang mới khác").

## Ảnh UI
`docs/screenshots/m4b/`: inbox, inbox-approvals, inbox-reject, inbox-after-approve, costs-overview, costs-budgets (+ bản `-mobile` 390px).
