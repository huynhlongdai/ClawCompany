# Module Công việc (Work) — rà soát hiện trạng, đối chiếu và kế hoạch

> Ngày 16/10/2026 · nhánh `ui-v2` @ `c237970` · migration head `0063_business_ledger`.
> **Cập nhật 17/10/2026:** anh đã chốt mô hình lãnh đạo (người + agent trợ lý + agent trưởng nhóm có quyền điều phối/
> tuyển) — xem §5; W0 đã làm (đo mặc định thật của gateway 9.8, biên dịch cách ly phiên, dọn 3 cặp job trùng) — xem §4.3a.
> Chỉ đọc code + báo cáo + docs upstream; **không đổi code**. Nhãn trạng thái theo nguyên tắc HANDOFF §7
> "kiểm chứng, đừng suy ra": ✅ **VM thật** = có báo cáo chạy trên VM/gateway OpenClaw thật · 🟡 **VM tất định** =
> chạy trên VM nhưng không gọi model (quota CometAPI rỗng) · 🧪 **chỉ test** = pytest/mock · ⚠️ **có mà chưa nối** ·
> ❌ **thiếu**.

## 0. Tóm tắt một trang

1. **Lõi "một agent làm một việc" đã chắc và đã chạy thật**: vòng đời task có bảng chuyển + checkout CAS, hàng
   wakeup gộp lý do, mỗi việc một phiên `agent:<rid>:company-task-<id>`, gói ngữ cảnh 7 khối + sổ việc, review chéo
   bằng phòng họp, phê duyệt exec, ngân sách giữ chỗ/quyết toán khớp `sessions.usage` ±5% (gate M4a 18/18 ×3, M4b 10/10).
2. **Làm nhóm mới có "khung", chưa có "tay"**: định tuyến trưởng phòng, chọn ghế theo tải, Nina lập kế hoạch, việc định
   kỳ đều **chỉ test**; quy trình/hợp đồng dữ liệu/SLA chạy trên VM nhưng **tất định** (không model). **Agent không tự
   tạo/giao việc con được** — không có tool `company_task_create/delegate`; chỉ Nina (`company_plan_submit`) và trưởng
   phòng (`company_task_assign`) có đường.
3. **Ghế chạy từng việc một** (`wakeup.skip_reason → seat_busy`) và **việc đang chờ người duyệt vẫn giữ ghế** → một phê
   duyệt chậm làm cả hàng đợi của agent đứng. Mỗi việc đã có phiên riêng nên giới hạn này không bắt buộc về mặt OpenClaw
   (queue `steer` chỉ áp trong *cùng phiên*).
4. **Thiếu lưới an toàn cho tự chủ dài hơi**: không trần số lượt/tiền **theo việc**, không trần số vòng SỬA khi review,
   không retry có backoff, không hàng "việc chết" (dead-letter), không trace xuyên việc cha–con–bàn giao–A2A.
5. **Hai bộ máy trùng nhau vẫn chạy trong beat lõi**: `orchestration` (OperatingCycle, gọi shim dispatch cũ) song song
   `strategy`; `events.monitor_sla` song song `sla.tick`; `operations.scan_recurring` song song `routines.tick`.
6. **Rủi ro bảo mật cần kiểm ngay (P0)**: docs OpenClaw hiện hành nói `tools.sessions.visibility` mặc định `all` và
   `tools.agentToAgent` mặc định **bật** — mọi agent trên cùng gateway đọc/gửi được phiên của agent khác. ClawCompany
   không biên dịch các khoá này (`seat_provision.seat_deny` chỉ chặn MCP ghế khác + exec). Với R2 cho thuê ghế trên
   cùng gateway, đây có thể là đường rò giữa tổ chức. **Chưa kiểm trên 9.8** — phải đo bằng `config.schema.lookup`.
7. **Native OpenClaw dùng được mà chưa dùng**: `subagents.allowAgents`/`sessions_spawn` (việc phụ song song trong một
   lượt), `tools.agentToAgent.send` (gửi-chỉ-một-chiều), `Goal` theo phiên có token budget, Standing orders trong
   AGENTS.md. Nguyên tắc giữ nguyên: **biên dịch cấu hình, không viết lại bộ não**.

---

## 1. Bản đồ hiện trạng

### 1.1 Thành phần đã có

| Thành phần | File chính | Trạng thái | Bằng chứng / ghi chú |
|---|---|---|---|
| Vòng đời task (7 trạng thái, bảng chuyển, chặn khi còn blocker, `done` qua chốt policy) | `services/task_lifecycle.py` | ✅ | gate M4a; `tools/lint_task_status.py` cấm gán trạng thái ngoài file này |
| Checkout CAS + `task_runs` | `task_lifecycle.checkout/open_run/finish_run` | ✅ | thua giữ chỗ → 409, không thử lại |
| Dispatch: phiên riêng mỗi việc, follower ngay sau `chat.send` | `services/agent_dispatch.py` | ✅ | `_reports/m4a-work.md`, `handoff-dispatch-e2e.md` |
| Hàng wakeup (10 lý do, gộp 10 s, claim CAS, xếp lại khi ghế rảnh) | `services/wakeup.py`, beat `wakeups.drain` 5 s | ✅ | M4a lỗi #4 (review chạy 2 lần) đã sửa bằng claim |
| **Ghế chạy 1 việc/lần** | `wakeup.skip_reason` (`seat_busy`) | ✅ (giới hạn) | VM: việc chờ duyệt chặn việc sau của ghế (project-state 15/10) |
| Kết thúc lượt → review / blocked / bắt kịp câu trả lời cuối | `runtime_stream.apply_terminal_state` | ✅ | M4a lỗi #1–#2 |
| Gói ngữ cảnh 7 khối + sổ việc (bộ nhớ công việc) | `work_context.py`, `task_journal.py` | ✅ | `_reports/work-memory-gap.md` (358 → 1 310 ký tự) |
| Review chéo: phòng 2 người (`room`) / phiên sạch (`clean`) | `execution_policy.py`, `room_conductor.py` | ✅ room · 🧪 clean | M4a; `clean` chưa thấy báo cáo VM riêng |
| Phê duyệt exec + Hộp việc 1 chạm + leo thang quá hạn | `approval_listener.py`, `approval_bridge.py`, `inbox_hub.py` | ✅ | gate M4b 10/10, lỗi "Headless runs cannot wait" đã sửa |
| Ngân sách 3 nấc theo phạm vi (công ty/phòng/ghế/dự án/mục tiêu), giữ chỗ trước `chat.send` | `budget_scope.py`, `seat_limits.py` | ✅ quyết toán · 🧪 dừng mềm | chi phí khớp ±5%; trần ngày ghế CSKH bị chạm thật |
| Ma trận thẩm quyền (ai duyệt gì, ngưỡng tiền/rủi ro) | `authority.py` | 🟡 | M2b; approval #17 hoàn tiền $80 từ lượt CSKH thật |
| Phụ thuộc việc + đánh thức khi blocker đóng | `task_graph.py`, `task_lifecycle.wake_unblocked` | 🧪 + 🟡 | fan-in quy trình chạy tất định M2d |
| Trưởng phòng định tuyến (lượt `company-route-<id>`, không checkout) | `routing.py` | 🧪 | `_reports/d31…`: "chưa e2e gateway thật" |
| Chọn ghế theo phòng/kỹ năng/tải, lưu lý do | `dispatch_policy.py` | 🧪 | `success_rate` vẫn null → thực chất chọn theo tải |
| Nina phân rã mục tiêu → kế hoạch → duyệt → việc con | `strategy.py`, MCP `company_plan_submit` | 🧪 | `_reports/d33…`, G5 **chưa đóng** (`company-demo-e2e.md`) |
| Bộ máy mục tiêu cũ (OperatingCycle/DelegationAssignment, `goal_execute`) | `orchestration.py`, beat `operations.tick_cycles` 30 s | ⚠️ trùng | gọi `services.tasks.dispatch_task` (shim deprecate) |
| Việc định kỳ cron/webhook, idempotency, catch-up, tự dừng khi lỗi liên tiếp | `routines.py`, beat 30 s | 🧪 | `_reports/d34…` "chưa e2e"; trùng `operations.scan_recurring` |
| Quy trình (bước, nhánh, fan-out/fan-in, đường găng) | `process_map.py` | 🟡 | M2c/M2d, instance #4–#6 công ty 3 |
| Hợp đồng dữ liệu: nộp → kiểm schema → làm lại → leo thang | `io_contracts.py`, `escalation.py`, MCP `company_task_submit_output` | 🟡 | 3 lần nộp hỏng → inbox #30; **chưa có lượt agent thật tự nộp** |
| Giờ vận hành 24/7, SLA theo bước/chức danh, ngoài giờ → agent cùng chức danh | `operating_time.py`, beat `sla.tick` 60 s | 🟡 | trùng `events.monitor_sla`; coverage bỏ qua nghỉ phép |
| Bàn giao artifact → đổi chủ → đánh thức | `handoff_dispatch.py` | ✅ | Mia nhắc đúng chi tiết chỉ có trong lời bàn giao (gateway 9.4) |
| Phòng họp có chủ toạ, 5 điều kiện dừng | `room_conductor.py` | ✅ | 2 agent, 3 lượt; chưa thử ≥3 agent |
| Hợp đồng uỷ quyền v16 | `delegation.py` | ⚠️ | chỉ `api/v16`, không gọi runtime |
| A2A ngoài: thuê agent ngoài + mở ghế cho bên ngoài | `a2a.py`, MCP `company_delegate_external` | ✅ | CSKH mở + tự đăng ký lại; trưởng phòng gọi qua MCP (calls=3) |
| Cho thuê ghế (sàn bên cho thuê, đo phí, trần, hết hạn → thu hồi) | `seat_leases.py` | 🟡 | R2; lượt chạy thật trên ghế thuê chưa có |
| MCP công việc trên gateway (`cc-<rid>__company_*`) | `company_mcp.py` (42 tool) | ✅ đăng ký | tool việc: list/get/status/submit_output/step_outcome/comment/assign/plan_submit/checkout/message/handoff/artifact |
| API `/api/work` + UI list/board/side-peek | `api/work.py`, `work_board.py`, `app/app/work` | ✅ | M4a; P0 lọc theo vai trò công ty (088a5d4) |
| Chỉ số nhân sự agent (first-pass, số vòng sửa, chi phí/việc, đạt chuẩn hợp đồng, SLA, tuân luật) | `career.py`, `agent_workforce` | 🟡 | M2e.5; số liệu thật còn mỏng |
| Bài học từ review → duyệt → MEMORY.md | `lessons.py` | ✅ | Phase C step 8 |
| Luật cứng ở runtime (guard plugin) | `openclaw-plugins/clawcompany-guard` | 🟡 | hook bắn trong container; chưa có lượt model thật chạm luật |

### 1.2 Còn thiếu (❌)

| Thiếu | Hệ quả |
|---|---|
| Agent tạo việc con / gửi yêu cầu cho phòng khác (MCP) | không có "quản lý agent phân việc" ngoài Nina + trưởng phòng |
| Trạng thái **chờ** giải phóng ghế (chờ người / chờ việc con / chờ bên ngoài) | một phê duyệt chậm chặn cả hàng của agent |
| Đồng thời >1 việc/ghế | throughput một agent = 1 |
| Trần theo việc: tiền, số lượt, số vòng SỬA | vòng review SỬA ↔ làm lại không có trần (`execution_policy` không có max) |
| Retry có backoff + hàng việc chết | lỗi runtime → `blocked` + 1 thẻ Hộp việc, người phải tự chạy lại |
| Bảng chung (blackboard / sổ mục tiêu) | ngữ cảnh nhóm chỉ có sổ từng việc + bộ nhớ tổ chức |
| Danh mục dịch vụ nội bộ giữa phòng (đầu vào chuẩn + SLA + người duyệt) | yêu cầu liên phòng là việc "giao cho phòng" trơn |
| Trace xuyên suốt (trace_id cha–con–bàn giao–A2A–duyệt) | không trả lời được "mục tiêu này tốn bao nhiêu, kẹt ở đâu" |
| Người chịu trách nhiệm (con người) trên việc giao agent | khác Linear: agent đang là "assignee" duy nhất |
| Việc liên công ty trong cùng tổ chức | `_same_company_member` chặn; chỉ có đường A2A |
| Biên dịch `tools.sessions` / `tools.agentToAgent` / `subagents` | xem P0-1 |

### 1.3 OpenClaw native — đang dùng gì

| Native | Dùng? | Ghi chú |
|---|---|---|
| sessions (`sessions.create`, `chat.send`, history, usage, abort) | ✅ | nền của dispatch/room/review |
| `agents.create/files.set` (CAS), `config.patch` (baseHash) | ✅ | hồ sơ ghế, AGENTS.md, rules |
| exec approvals | ✅ | listener thường trực |
| Skill Workshop | ✅ | M5b |
| heartbeat | ✅ chỉ Nina | ghế thừa hành tắt heartbeat (D2.1) |
| `sessions_spawn` / `subagents.*` | ❌ | `HTTP_DENIED_TOOLS` chỉ là danh sách gương; per-agent `subagents.allowAgents` chưa biên dịch |
| `tools.agentToAgent`, `tools.sessions.visibility` | ❌ | **mặc định mở** theo docs hiện hành |
| cron (Automations) | ❌ (cố ý) | routines của ClawCompany có idempotency + catch-up + audit |
| Goal theo phiên (token budget) | ❌ | có thể là trần token native cho mỗi việc — **cần kiểm có trên 9.8** |
| Standing orders | gần như | AGENTS.md đã có "Nhận và trả việc"; chưa có chương trình thường trực từ routine |
| Workboard plugin, Swarm | ❌ (đúng) | Workboard tự nhận "không thay Linear/Jira"; Swarm chỉ cho fan-out ≥5 trong Code Mode |
| OpenTelemetry export | ❌ | chưa từng kiểm |

---

## 2. Ba kiểu làm việc và thứ mỗi kiểu cần

### 2a. Agent làm độc lập

| Cần | Có | Thiếu → đề xuất | Native dùng lại |
|---|---|---|---|
| Hàng việc riêng, thứ tự ưu tiên | tasks theo assignee + wakeups | ưu tiên/hạn chưa vào thứ tự drain (drain theo id) | — |
| Tự lập kế hoạch trong việc | agent tự làm trong phiên | cho agent **tạo việc con của chính mình** (W3) khi việc > 1 lượt | `Goal` theo phiên nếu có ở 9.8 |
| Checkpoint / tiếp tục sau gián đoạn | phiên riêng + sổ việc + gói ngữ cảnh | ghi "điểm dừng" có cấu trúc (đã làm / còn lại / cần gì) vào sổ khi lượt kết thúc | compaction của OpenClaw |
| Khi nào hỏi người | ma trận thẩm quyền, `company_approval_request`, exec ask | **trạng thái chờ người** không giữ ghế, quay lại đúng phiên khi có kết quả (W1) | approval resolve → `sessions_send followup` |
| Việc định kỳ tự chủ | routines (🧪) | biên dịch routine thành "Chương trình thường trực" trong AGENTS.md | Standing orders |
| Lưới an toàn | trần ngày/tháng của ghế | trần **theo việc** (tiền, lượt, vòng sửa), retry + dead-letter (W2) | — |

### 2b. Làm nhóm (một quản lý, nhiều người làm)

| Cần | Có | Thiếu → đề xuất |
|---|---|---|
| Quản lý phân rã + giao | Nina `plan_submit` (🧪), trưởng phòng `task_assign` (🧪) | MCP `company_task_delegate` cho mọi ghế có quyền quản lý theo ma trận thẩm quyền; kế thừa mục tiêu/dự án/ngân sách cắt nhỏ (W3) |
| Song song + hợp nhất (fan-out/fan-in) | `task_dependencies`, nhánh quy trình (🟡) | việc cha **chờ việc con** và được đánh thức **một lần** khi đủ, kèm tóm tắt kết quả con (W3) |
| Bàn giao có hợp đồng vào/ra | hợp đồng dữ liệu chỉ cho bước quy trình (🟡); bàn giao artifact (✅) | gắn hợp đồng cho việc giao tay/việc con, không chỉ bước quy trình (W3) |
| Review | room / clean (✅/🧪) | trần vòng SỬA → sau N vòng đưa lên người (W2) |
| Ngữ cảnh chung | sổ từng việc, bộ nhớ tổ chức | **sổ mục tiêu** kiểu Magentic task ledger: sự thật, quyết định, câu hỏi mở, kế hoạch — vào khối 3 của gói (W4) |
| Giải quyết xung đột | checkout CAS cho việc; revision artifact; phòng họp có chủ toạ chốt | chỉ chủ mục tiêu/chủ toạ ghi được `decision` vào sổ chung; câu hỏi mở tự đến chủ (W4) |
| Phát hiện kẹt | `stall_count` trong phòng họp | đếm "không tiến triển" theo mục tiêu → việc lập lại kế hoạch cho người lập (W4) |
| Việc phụ ngắn trong một lượt | — | `sessions_spawn` tới **chính ghế** (allowAgents = [] / self), chi phí gom về lượt cha (P2) |

> Giữ nguyên tắc AGENT_TEAMWORK §4E: **không mô hình hoá phòng ban bằng cây sub-agent** — sub-agent không có danh
> tính, không đo được. Bàn giao thật giữa hai nhân sự đi qua task của ClawCompany.

### 2c. Liên phòng / liên công ty / bên ngoài

| Cần | Có | Thiếu → đề xuất |
|---|---|---|
| Yêu cầu giữa phòng | giao việc cho phòng → trưởng phòng định tuyến (🧪) | **Danh mục dịch vụ nội bộ**: phòng công bố dịch vụ (đầu vào = hợp đồng, SLA, người duyệt, ai được gọi); agent gọi `company_service_request` (W5) |
| SLA giữa nhóm | SLA theo bước quy trình/chức danh (🟡) | SLA gắn dịch vụ; vi phạm → trưởng phòng **bên cung cấp** + báo bên yêu cầu (W5) |
| Agent thuê ngoài / đi thuê | A2A out/in (✅), ghế thuê (🟡) | A2A hiện **đồng bộ** `message/send`; cần trạng thái task A2A (`input-required`, `rejected`, push) cho việc dài (W7) |
| Leo thang | chuỗi chức danh → quản lý → trưởng phòng → chủ (🟡) | dùng chung cho run cap, dead-letter, dịch vụ (W2/W5) |
| Liên công ty trong một tổ chức | ❌ | P2: đi qua A2A nội bộ (mở ghế của công ty B cho công ty A) thay vì nới `_same_company_member` |

### 2d. Ngang cả ba kiểu

| Mảng | Hiện có | Cần |
|---|---|---|
| Người trong vòng lặp | Hộp việc 5 nhóm, duyệt 1 chạm, leo thang quá hạn | "người chịu trách nhiệm" (con người) trên mọi việc agent làm — kiểu Linear *delegate ≠ assignee*; mặc định = quản lý người của ghế |
| Ngân sách / chi phí theo việc | chi phí từng lượt + review trên side-peek | `max_cost_usd`, `max_runs` trên việc; việc con nhận lát cắt ngân sách cha |
| Thử lại | contract `max_attempts`; routine tự dừng | chính sách retry cho lỗi tạm (mạng, 429, gateway restart) 1′/5′/30′; lỗi nội dung không retry |
| Dead-letter | ❌ | danh sách việc chết: lý do, lượt cuối, nút "chạy lại / giao người khác / huỷ" |
| Quan sát | dòng thời gian việc, `company_events`, `model.routed` | `trace_id` xuyên mục tiêu → việc → lượt → duyệt → A2A; dòng thời gian mục tiêu; OTel của gateway (P2) |
| Chất lượng → Agent HR | first-pass, số vòng sửa, chi phí/việc, đạt chuẩn hợp đồng, SLA | thêm: tỉ lệ việc phải leo thang, phút chờ người, tỉ lệ việc chết, chi phí/kết quả theo kiểu làm việc; đưa vào `dispatch_policy` khi có ≥ N mẫu (bỏ `success_rate=null`) |

---

## 3. Đối chiếu với sản phẩm/mẫu tương tự

| Sản phẩm / mẫu | Cơ chế đáng học | ClawCompany | Mượn gì |
|---|---|---|---|
| **Paperclip** ([core concepts](https://github.com/paperclipai/paperclip/blob/master/docs/start/core-concepts.md), [SPEC-implementation](https://github.com/paperclipai/paperclip/blob/master/doc/SPEC-implementation.md), [SPEC](https://github.com/paperclipai/paperclip/blob/b4a7efa8d2c1e2f57c042d50fda0157e025feac6/doc/SPEC.md)) | heartbeat (nhận việc → checkout → làm → cập nhật), checkout nguyên tử, ngân sách tháng dừng cứng, board duyệt kế hoạch CEO, "pause bất kỳ việc/cây việc con" | đã có tương đương heartbeat (wakeup), checkout, ngân sách, duyệt kế hoạch | **tạm dừng cả cây việc con**; mọi việc truy về mục tiêu |
| **CrewAI hierarchical** ([docs](https://docs.crewai.com/en/learn/hierarchical-process), [tasks/guardrails](https://docs.crewai.com/edge/en/concepts/tasks)) | manager LLM phân việc + kiểm kết quả; guardrail kiểm output trước khi sang việc sau | hợp đồng dữ liệu = guardrail; phân việc tất định | **giữ** phân việc tất định có lý do ghi lại; cộng đồng báo manager LLM giao nhầm người ([thread](https://community.crewai.com/t/manager-agent-delegates-task-to-wrong-agent-in-a-hierarchical-process/3179)) |
| **LangGraph** ([interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts), [checkpointers](https://docs.langchain.com/oss/python/langgraph/checkpointers)) | `interrupt()` lưu trạng thái, chờ người vô hạn, `Command(resume)` | phê duyệt có, nhưng **giữ ghế** khi chờ | trạng thái chờ + tiếp tục đúng phiên (W1) |
| **Magentic-One** ([paper](https://arxiv.org/html/2411.04468), [MS Agent Framework](https://learn.microsoft.com/en-us/agent-framework/workflows/orchestrations/magentic)) | task ledger (sự thật, phỏng đoán, kế hoạch) + progress ledger; stall counter > 2 → phản tư, lập lại kế hoạch; plan sign-off | `stall_count` chỉ trong phòng họp | sổ mục tiêu + đếm kẹt theo mục tiêu (W4) |
| **OpenAI Agents SDK** ([handoffs](https://openai.github.io/openai-agents-python/handoffs), [orchestration](https://developers.openai.com/api/docs/guides/agents/orchestration), [tracing](https://github.com/openai/openai-agents-python/blob/main/docs/tracing.md)) | handoff (chuyển quyền) vs agent-as-tool (quản lý giữ quyền); `input_filter` lọc lịch sử; span cho run/tool/handoff | bàn giao = đổi chủ; `company_ask_advisor` = agent-as-tool; gói ngữ cảnh = input filter | mô hình span cho trace (W6); "bắt đầu với 1 agent, chỉ thêm chuyên gia khi tách được năng lực/chính sách" |
| **Google A2A** ([spec](https://a2a-protocol.org/latest/specification/), [life of a task](https://a2a-protocol.org/latest/topics/life-of-a-task/), [streaming/async](https://a2a-protocol.org/latest/topics/streaming-and-async/)) | task states `submitted/working/input-required/auth-required/completed/failed/canceled/rejected`; push notification cho việc dài | A2A 0.3.0 `message/send` đồng bộ | ánh xạ trạng thái việc ↔ A2A; `rejected` cho agent từ chối việc; push (W7) |
| **Linear for Agents** ([agents](https://linear.app/agents), [agent interaction](https://linear.app/developers/agent-interaction), [blog](https://linear.app/now/our-approach-to-building-the-agent-interaction-sdk)) | giao cho agent = *delegate*, người vẫn là assignee chịu trách nhiệm; agent session: working / awaiting input / error / complete | agent là assignee duy nhất | trường **người chịu trách nhiệm**; trạng thái phiên hiển thị "chờ anh trả lời" |
| **OpenClaw native** ([multi-agent](https://docs.openclaw.ai/concepts/multi-agent), [sessions & subagents config](https://docs.openclaw.ai/gateway/config-tools/sessions-and-subagents), [specialist lanes](https://docs.openclaw.ai/concepts/parallel-specialist-lanes), [standing orders](https://docs.openclaw.ai/automation/standing-orders), [goal](https://docs.openclaw.ai/tools/goal)) | cách ly theo agentId; `agentToAgent.send` một chiều; `subagents.allowAgents` mặc định chỉ chính mình, `maxConcurrent` 8, `maxChildrenPerAgent` 5; "khoá theo phiên, năng lực model dùng chung" | chưa biên dịch các khoá này | biên dịch an toàn (W0); dùng spawn cho việc phụ trong lượt (P2) |

Kết luận đối chiếu: so với Paperclip, ClawCompany **mạnh hơn** ở hợp đồng dữ liệu, ma trận thẩm quyền, giờ vận hành/SLA
theo luật VN, cho thuê ghế, vòng học; **yếu hơn** ở chỗ agent chưa tự phân việc được và chưa có tạm dừng theo cây. Không
framework nào ở trên giải hộ phần "công ty" — đúng như AGENT_TEAMWORK §0.

---

## 4. Danh sách khoảng trống và kế hoạch

### 4.1 Ưu tiên

| # | Mức | Khoảng trống | Vì sao mức này |
|---|---|---|---|
| G1 | **P0** | `tools.sessions.visibility` / `tools.agentToAgent` / `subagents.allowAgents` không được biên dịch; mặc định docs = mở | có thể rò phiên giữa ghế, giữa công ty, giữa bên cho thuê–đi thuê trên cùng gateway |
| G2 | **P0** | Ghế 1 việc/lần + chờ duyệt giữ ghế | một phê duyệt chậm đứng cả agent; chặn mọi kịch bản nhóm |
| G3 | **P0** | Không trần theo việc (tiền/lượt/vòng SỬA), không retry/backoff, không dead-letter | tự chủ dài hơi = hoá đơn mở; lỗi tạm phải người chạy lại |
| G4 | **P0** | Bộ máy trùng trong beat lõi (orchestration↔strategy, monitor_sla↔sla.tick, scan_recurring↔routines) | hai nguồn sự thật, có thể giao/leo thang đôi |
| G5 | **P1** | Agent không tạo/giao việc con; không fan-in cho việc giao tay | kiểu làm nhóm (2b) không thành |
| G6 | **P1** | Không sổ chung theo mục tiêu/dự án, không đếm kẹt | nhóm không chung ngữ cảnh, không tự lập lại kế hoạch |
| G7 | **P1** | Không danh mục dịch vụ nội bộ | liên phòng không có đầu vào chuẩn/SLA |
| G8 | **P1** | Không trace xuyên suốt + chỉ số chất lượng mới | không đo được nhóm, Agent HR thiếu dữ liệu |
| G9 | **P1** | Chưa có gate thật cho làm nhóm (G5 "Ra mắt bộ sưu tập hè") | toàn bộ 2b/2c mới là test/tất định |
| G10 | P2 | A2A đồng bộ, chưa có trạng thái task chuẩn/push | việc dài với agent ngoài |
| G11 | P2 | Liên công ty trong tổ chức | mô hình holding |
| G12 | P2 | `sessions_spawn` cho việc phụ trong lượt; OTel gateway | tối ưu, không chặn |

### 4.2 Gói việc (W) — mỗi gói 1–3 buổi, migration nối từ `0064`

Cột **Kiểm** : 🟢 tất định (SQLite + Postgres VM, runtime giả hoặc RPC gateway không model) · 🔴 cần quota CometAPI.

| Gói | Nội dung | Migration | Định nghĩa xong (acceptance) | Kiểm |
|---|---|---|---|---|
| **W0 · An toàn & dọn trùng** ✅ 17/10 | (1) đo trên 9.8 bằng `config.schema.lookup` + `config.get`; biên dịch `tools.sessions.visibility=self`, `tools.agentToAgent.enabled=false` (khoá **toàn gateway** — 9.8 không có bản theo agent), `agents.entries.<ghế>.subagents.allowAgents=[<ghế>]`; đặt trong `wire_gateway`, khi API khởi động (native) và `POST /api/agents/gateway/isolation`; `GET` cùng path báo lệch. (2) bỏ `operations.tick_cycles`, `events.monitor_sla`, `operations.scan_recurring` khỏi beat; chủ duy nhất: strategy (mục tiêu), `sla.tick` (SLA mới + hồ sơ SLAProfile cũ cho việc chưa có đồng hồ), `routines.tick` (routine + việc định kỳ cũ, claim CAS) | — | xem §4.3a | 🟢 xong · 🔴 1 lượt model thật thử đọc phiên người khác vẫn nên chạy khi có quota |
| **W1 · Chờ không giữ ghế + đồng thời ghế** ✅ 17/10 (🟢 VM tất định, xem §4.3b) | việc `blocked` có `wait_kind` ∈ `human|children|external|budget` + `wait_ref`; lượt kết thúc khi xin duyệt → ghế rảnh; kết quả duyệt → wakeup `approval_resolved` **cùng phiên việc**. `agents.max_parallel_runs` (mặc định 1, tối đa theo `agents.defaults.maxConcurrent`), `skip_reason` đếm lượt mở thay vì "có lượt" | `0064_work_wait_parallel` (tasks.wait_kind/wait_ref/wait_since; agents.max_parallel_runs) | việc A chờ duyệt, việc B của cùng ghế chạy ngay; duyệt A → A tiếp tục đúng session key; ghế `max_parallel_runs=2` chạy 2 việc 2 phiên, việc thứ 3 `seat_busy`; Hộp việc hiện "chờ anh" kèm phút chờ | 🟢 mock · 🔴 1 lượt thật |
| **W2 · Trần, thử lại, việc chết** | `tasks.max_cost_usd`, `max_runs`, `max_revisions` (mặc định theo công ty); `budget_scope.gate` cộng phạm vi `task`; vòng SỬA thứ N+1 → leo thang người; lỗi tạm (mạng/429/gateway restart/`runtime_error`) → retry 1′/5′/30′ qua `wakeups.not_before`; hết lượt → `work_dead_letters` + 1 thẻ Hộp việc | `0065_work_limits` (cột tasks + bảng work_dead_letters + wakeups.not_before) | vượt `max_runs` → blocked `run_cap` + đúng 1 thẻ; lỗi tạm thử lại đúng lịch rồi vào dead-letter; nút chạy lại/giao người khác/huỷ; review SỬA lần 4 (max 3) → người | 🟢 |
| **W3 · Agent trưởng nhóm điều phối + fan-in** | Theo quyết định 17/10 (§5 Q1): agent **cấp trưởng nhóm** (`seat_tier=lead`, trưởng phòng/quản lý theo chức danh M2b) có **quyền điều phối**: gọi agent trong nhóm, tạo/quản lý/giao việc. MCP `company_task_delegate` (tiêu đề, mô tả, người nhận/phòng, hợp đồng, hạn, lát ngân sách, reviewer mặc định = người giao), `company_task_children`, `company_task_manage` (đổi hạn/ưu tiên/người nhận, huỷ, mở lại việc con của mình); quyền theo `authority` (`task_delegate`: trong phòng = trưởng nhóm tự làm; ngoài phòng → *yêu cầu* tới trưởng nhóm kia); cha `wait_kind=children`, đánh thức **một lần** khi con đóng hết, khối "Kết quả việc con" trong gói ngữ cảnh; trần độ sâu 3, fan-out 8 (mặc định, chưa chốt); `tasks.accountable_member_id` = **lãnh đạo người** chịu trách nhiệm (mặc định quản lý người của ghế). Agent thừa hành **không** giao việc; agent trợ lý chỉ *đề xuất* (§5 vai trò trợ lý) | `0066_task_delegation` (tasks.accountable_member_id, delegated_by_member_id, origin; authority seed `task_delegate`) | agent trưởng nhóm giao 3 việc con song song cho 3 ghế → cha thức dậy 1 lần với 3 kết quả; nhân viên/trợ lý gọi delegate → 403 + gợi ý đường đề xuất; giao sang phòng khác → thành yêu cầu cho trưởng nhóm đó; vượt độ sâu/fan-out → lỗi tiếng Việt; con có hợp đồng nộp sai → làm lại như M2e.3 | 🟢 · 🔴 agent tự phân việc |
| **W3b · Agent trưởng nhóm tuyển agent** | Agent trưởng nhóm được **tạo agent mới** (mở ghế theo chức danh có sẵn → `agent_hr.hire` + `seat_provision`) hoặc **thêm agent từ chợ agent** (thuê ghế — dùng lại R2 `seat_leases`: offer/accept, sàn bên cho thuê, trần, đo phí). MCP `company_seat_request` {position_id, cách: `create`\|`lease`, offer_code?, lý do, ngân sách tháng}. **Mặc định:** còn chỉ tiêu (`positions.headcount` M2b > số ghế đang có) **và** trong ngân sách (phòng/công ty, `budget_scope`; phí thuê ước tính tháng ≤ phần còn lại) → agent trưởng nhóm tự làm, ghi audit + báo lãnh đạo người (thẻ thông tin). **Vượt** chỉ tiêu hoặc ngân sách, hoặc chức danh chưa có → Approval theo ma trận thẩm quyền (`hire_agent` M2b; thêm `lease_agent`), người duyệt là lãnh đạo người. Ghế mới luôn ở `probation` (career M5b), quản lý người = lãnh đạo của nhóm; cách ly phiên W0 áp ngay khi tạo. Không tự nới chính sách/quyền công cụ của ghế mới quá sàn chức danh | `0066b`/`0067` tuỳ thứ tự (authority seed `lease_agent`; `agent_hires` nhật ký: ai đề xuất, cách, lease_id, approval_id) | trong chỉ tiêu + ngân sách → ghế mới có trên gateway (AGENTS.md theo chức danh, `subagents.allowAgents=[chính nó]`), không thẻ duyệt; chỉ tiêu đầy → đúng 1 Approval cho lãnh đạo người, duyệt → tạo, từ chối → không tạo; thuê từ chợ → lease active với sàn bên cho thuê, vượt ngân sách → Approval; agent thừa hành/trợ lý gọi → 403; tạo trùng (gọi 2 lần) → 1 ghế | 🟢 · 🔴 agent tự quyết tuyển |
| **W4 · Sổ chung mục tiêu/dự án + đếm kẹt** | `work_ledger_entries` (phạm vi goal/project, loại fact/decision/question/risk/plan, tác giả, `supersedes_id`); MCP `company_ledger_read/note`; `decision` chỉ chủ mục tiêu/chủ toạ ghi; `question` → wakeup chủ; ≤2 000 ký tự vào khối 3; mỗi giờ: mục tiêu không có việc đóng/ghi sổ mới trong N giờ → `stall_count++`, quá ngưỡng → việc "Lập lại kế hoạch" cho seat chiến lược | `0067_work_ledger` | 2 agent cùng mục tiêu thấy quyết định của nhau ở lượt sau; agent thường ghi `decision` → 403; câu hỏi mở đánh thức chủ; kẹt 2 nhịp → 1 việc lập lại kế hoạch, không đôi | 🟢 |
| **W5 · Danh mục dịch vụ nội bộ** | `service_catalog` (phòng cung cấp, tên, hợp đồng đầu vào/ra, SLA policy, người duyệt, ai được gọi, công khai cho agent); MCP `company_service_list/request` → việc giao phòng cung cấp + định tuyến D3.1 + SLA timer; UI Công ty › Vận hành › Dịch vụ nội bộ | `0068_service_catalog` | Kinh doanh yêu cầu "Xuất kho" thiếu trường → 422 lỗi tiếng Việt; hợp lệ → việc ở phòng Kho, SLA chạy; quá SLA → trưởng phòng Kho + thẻ báo bên yêu cầu; bên yêu cầu thấy trạng thái | 🟢 |
| **W6 · Trace & chỉ số làm việc** | `trace_id` (mục tiêu hoặc việc gốc) lan sang việc con, task_runs, approvals, handoffs, lượt A2A, phòng review; API dòng thời gian mục tiêu (cây việc, chi phí, phút chờ người, điểm kẹt); chỉ số mới vào `career.scorecard` + trọng số `dispatch_policy` khi đủ mẫu | `0069_work_trace` | một mục tiêu 1 cha + 3 con + 1 review + 1 duyệt → dòng thời gian đủ 6 nhánh, tổng chi phí = tổng các lượt; scorecard có `escalation_rate`, `human_wait_minutes`, `dead_letter_rate` | 🟢 |
| **W7 · A2A bất đồng bộ** | ánh xạ trạng thái việc ↔ A2A (`input-required` ↔ chờ người, `rejected`); `tasks/get`, push notification về webhook đã ký; agent ngoài làm "người nhận" của việc qua ghế proxy có trần như ghế thuê | `0070_a2a_tasks` | việc dài với agent ngoài trả `working` rồi push `completed`; `input-required` thành thẻ Hộp việc; chi phí ngoài ghi vào trace | 🟢 với agent giả · 🔴 với seat thật |
| **W8 · Gate thật làm nhóm (= G5)** | kịch bản "Ra mắt bộ sưu tập hè, $20": Nina lập kế hoạch → người duyệt → 3 phòng song song qua W3 → bàn giao có hợp đồng → review → fan-in → người bị ping ≤2 lần → chi phí khớp `sessions.usage` ±5% | — | `tools/gate_work.py` xanh 3 lần liên tiếp, 0 lỗi 500/console | 🔴 (ước ~1–2 USD/lần với T1/T2) |

**Thứ tự đề xuất:** `W0 ✅ → W1 → W2 → W3 → W3b → W4 → W6 → W5 → W8 → W7`.
W0–W2 là nền an toàn (không làm thì làm nhóm chỉ nhân rủi ro). W3 là thứ mở khoá kiểu 2b. W6 đi trước W5 vì dịch vụ liên
phòng cần trace để đo SLA giữa bên. W8 chạy ngay khi có quota — có thể kéo lên sau W3 nếu anh nạp CometAPI sớm.

### 4.3a Kết quả W0 (17/10/2026)

**Mặc định thật của gateway OpenClaw 2026.9.8 trên VM** (`config.schema.lookup` + `config.get`, script
`work/w0/vm_w0_schema.py`; docs đóng gói trong image `/app/docs/gateway/config-tools/sessions-and-subagents.md`):

| Khoá | Mặc định 9.8 | Trên VM trước W0 | Phạm vi |
|---|---|---|---|
| `tools.sessions.visibility` | `all` — "any session on the Gateway, including other agents and users" (enum `self\|tree\|agent\|all`) | chưa đặt → `all` | chỉ gốc `tools` (không có `agents.entries.*.tools.sessions`) |
| `tools.agentToAgent.enabled` | `true`; `allow` rỗng = mọi cặp agent | chưa đặt → bật | chỉ gốc `tools` |
| `agents.*.subagents.allowAgents` | "same agent only" khi không đặt | chưa đặt (defaults chỉ có `maxConcurrent 8`, `archiveAfterMinutes 60`) | defaults + từng entry |
| `tools.agentToAgent.send` | không tồn tại trên 9.8 (docs cũ nhắc) | — | — |

**Bằng chứng rò thật trước khi sửa** (`work/w0/vm_w0_probe.py`, gọi `POST /tools/invoke` của gateway = đúng chuỗi chính
sách tool của agent, không gọi model): từ phiên `agent:shop-a407-cskh:company-task-48`, `sessions_list` thấy phiên của
`shop-a407-truong-kho`, `sessions_history` đọc được transcript "Báo cáo tuần" của Trưởng kho (HTTP 200).

**Đã đổi:** `seat_provision.session_isolation_values/ensure_session_isolation` (visibility `self`, agentToAgent tắt,
`allowAgents=[ghế]`), gộp vào `wire_gateway`, chạy khi API khởi động (`OPENCLAW_ENFORCE_SESSION_ISOLATION`, mặc định bật),
`GET/POST /api/agents/gateway/isolation` (admin tổ chức, ORG_ONLY). Chọn `self` thay vì `agent`: cùng một ghế có phiên A2A/
cổng khách của nhiều khách — `agent` vẫn cho phiên khách này đọc phiên khách kia. Hệ quả chấp nhận: agent không tự đọc
phiên việc khác của chính mình (ngữ cảnh đã có gói 7 khối + sổ việc do backend dựng).

**Job trùng → một chủ:** mục tiêu = strategy/Nina (`strategy.owns_goal`: có việc lập kế hoạch → `create_cycle` từ chối,
`tick_cycle` không phát việc; việc định kỳ `nina_goal` không dựng chu kỳ cũ); SLA = `sla.tick` (đồng hồ giành bằng CAS
`running→breaching`; hồ sơ SLAProfile cũ chạy trong cùng tick, bỏ việc đã có đồng hồ); định kỳ = `routines.tick` →
`routines.tick_all` (routine + `RecurringOperation` giành bằng CAS trên `next_run_at`). Phát hiện trên VM: việc định kỳ cũ
"Daily growth & risk review" (org 1) mỗi 08:00 tạo một mục tiêu + chu kỳ cũ; 2 chu kỳ (#1, #2) đang `running` mãi với 1
assignment `failed` + 3 `queued` — sau W0 không còn beat nào tick chúng (chạy tay qua `/api/v9/cycles/{id}/tick`).

### 4.3b Kết quả W1 (17/10/2026)

**Đã làm** (commit `12577c4`, migration `0064_work_wait_parallel`, VM Postgres đã lên 0064):

- **Chờ trong lượt** (lệnh exec chờ người duyệt): `record_approval` → `task_wait.begin(in_turn)` đặt
  `task_runs.waiting_since` — lượt vẫn mở trên gateway nhưng **không tính** vào chỗ chạy của ghế, lý do `seat_busy` được
  xếp lại ngay. Có quyết định (`approval_bridge.decide` hoặc frame `exec.approval.resolved`) → xoá dấu chờ, **đúng lượt
  cũ** chạy tiếp (gateway tự tiếp tục; không `chat.send` mới, không hàng `task_runs` mới). Việc vẫn `in_progress`.
- **Chờ ngoài lượt**: `company_approval_request` trả `approval_required` trong lượt của việc, hoặc `company_task_status`
  `status=blocked, wait_for=human` (câu hỏi → thẻ Hộp việc `agent_question` cho quản lý người) → lượt kết thúc
  (`completed`), việc `blocked` + `wait_kind=human`, `wait_ref=approval:<id>|question:<inbox id>`; **không** sang review,
  **không** thẻ "run lỗi". Hết chờ (duyệt/từ chối qua API/Hộp việc, hoặc `POST /api/work/tasks/{id}/answer`) → việc về
  `todo` + wakeup (`approval_resolved` / mới: `input_received`) mang `resume` → drain gửi **tin ngắn** vào đúng phiên
  `agent:<rid>:company-task-<id>` ("[Tiếp tục việc #…] … ĐÃ ĐƯỢC DUYỆT / BỊ TỪ CHỐI / Câu trả lời: …"), không dựng lại gói
  7 khối. Duyệt trong lúc agent còn trong lượt → hết chờ ngay, lượt kết thúc bình thường. Huỷ/đóng/gỡ "bị chặn" bằng tay,
  hoặc lượt lỗi/huỷ → bỏ chờ. Review của người vốn đã không giữ ghế (lượt kết thúc ở `review`) — có test giữ điều đó.
- **Đồng thời theo ghế**: `agents.max_parallel_runs` mặc định 1, tối đa **3 (default, chưa chốt — D2)**; giới hạn hiệu
  dụng = min(ghế, sàn hợp đồng thuê `seat_leases.max_parallel_runs`, NULL = 1); bên thuê đặt cao hơn sàn → 422
  `above_lease_floor`. Giành chỗ **nguyên tử** (`seat_concurrency.open_run`): khoá dòng `agents` của ghế bằng UPDATE,
  đếm lượt đang chạy (mở, không chờ, chưa quá 30′), còn chỗ thì tạo `task_runs` trong **cùng giao dịch**. Đường wakeup
  dùng nó; drain lấp đủ chỗ trống trong một lần (giới hạn 1 thì hành vi y như trước). Định tuyến ngoài giờ (`operating_time.route`)
  và chọn người theo chức danh (`process_map.pick_assignee`) xếp theo tải/giới hạn, bỏ việc đang chờ; `dispatch_policy`
  không tính lượt đang chờ.
- **API/UI**: `GET/PUT /api/agents/{id}/concurrency`; thẻ "Làm song song" ở Hồ sơ agent › Nhân sự (nhãn "Mặc định, chưa
  chốt"); bảng việc có huy hiệu "Chờ người duyệt / người trả lời · N phút" và khung chờ ở side-peek (trả lời ngay tại đó);
  i18n vi+en.

**Giới hạn nói thẳng:** (1) lượt chờ exec được tiếp tục luôn được nhận lại kể cả khi ghế đã đầy (gateway chạy tiếp ngay,
ta không chặn được) → ghế tạm vượt giới hạn, không nhận lượt MỚI tới khi về dưới (`over_limit` trong API/UI). (2) Giành chỗ
nguyên tử chỉ ở đường wakeup; dispatch tay cũ (`/api/tasks/{id}/dispatch`, v19/v20) vẫn là thao tác người chủ động, chỉ kiểm
trước như trước; lượt định tuyến trưởng phòng vẫn kiểm trước (không nguyên tử). (3) Agent có *tự* gọi
`wait_for=human`/kết thúc lượt khi được bảo chờ hay không — **chưa đóng dấu** (cần model thật, quota CometAPI rỗng).
(4) `wait_kind` `children/external/budget` mới có trong từ vựng, chưa có nguồn phát (W3/W7/W2). (5) Dòng thời gian việc
hiện mã sự kiện thô `task.waiting`/`task.resumed`.

**Kiểm:** `tests/test_w1_wait_parallel.py` 12 test; cả bộ backend 1 372 passed / 2 skipped / 0 failed (không sửa test cũ);
`tsc` sạch; `next build` qua. VM (Postgres thật, runtime giả trong tiến trình, không gọi model/gateway; ghế thử "W1 Probe"
ở org 2/công ty 4 — `work/vm_w1.py`): đua 8 luồng/8 phiên Postgres × 6 vòng (giới hạn 1/2/2/1/2/3) → đúng 1/2/2/1/2/3 lượt,
0 lỗi; luồng 15/15 PASS; HTTP concurrency 200/422/422/200, danh sách + chi tiết việc có `waiting`; ảnh
`_reports/ui/w1-*.png` (vi/en/mobile 390 px, scrollWidth đúng). Dữ liệu thử đã huỷ, ghế thử để `paused`.

### 4.3 Kiểm được gì khi chưa có quota

- **Kiểm tất định được ngay**: toàn bộ W0 (config trên gateway thật qua RPC, không cần model), W1–W6 bằng runtime giả +
  Postgres VM, quét hai tổ chức (mẫu `test_r1_isolation.py`), chaos "khởi động lại gateway giữa lượt" cho retry W2.
- **Bắt buộc model thật**: agent có *tự* gọi `company_task_delegate`/`submit_output`/`ledger_note` hay không; chất lượng
  phân rã kế hoạch của Nina; số lần người bị ping; chi phí nhóm thật (đa agent ~15× token theo agent-anatomy §3).
  Đây là các mệnh đề hiện **chưa đóng dấu** và phải ghi rõ trong báo cáo từng gói.

---

## 5. Quyết định (anh chốt 17/10/2026) và mặc định còn mở

### 5.1 Mô hình lãnh đạo — **đã chốt**

| # | Quyết định | Nội dung |
|---|---|---|
| Q1 | Lãnh đạo công ty | Mỗi công ty có **lãnh đạo là NGƯỜI** + **1–2 agent cấp TRỢ LÝ** phục vụ lãnh đạo |
| Q2 | Agent trưởng nhóm có quyền điều phối | Agent **cấp trưởng nhóm** (team-lead) được gọi agent, tạo/quản lý/giao việc, và **tạo agent mới hoặc thêm agent từ chợ agent** (thuê — dùng lại R2 `seat_leases`) → W3 + W3b |
| Q3 | Ranh giới tự quyết | **Trong chỉ tiêu chức danh (headcount M2b) và trong ngân sách** → agent trưởng nhóm tự làm (có audit + thẻ thông tin cho lãnh đạo). **Vượt** → lãnh đạo người duyệt theo **ma trận thẩm quyền** |

### 5.2 Vai trò agent trợ lý (assistant) — định nghĩa

| Mặt | Định nghĩa |
|---|---|
| Phục vụ ai | Đúng **một lãnh đạo người** (`members.manager_id` của ghế trợ lý = lãnh đạo đó); công ty có 1–2 trợ lý |
| Làm gì | **Phân loại Hộp việc** của lãnh đạo (gom, ưu tiên, tóm tắt thẻ, gợi ý quyết định — không tự bấm duyệt); **soạn nháp** (email, tin nhắn, biên bản, tài liệu, kế hoạch) để lãnh đạo duyệt; **xếp lịch** (đề xuất giờ họp, nhắc hạn, chuẩn bị tài liệu họp M3i) |
| Được *yêu cầu* | Tạo đề xuất việc/yêu cầu gửi trưởng nhóm, đề xuất tuyển agent, đề xuất đổi tài liệu (M3e) — mọi thứ đi dưới dạng **đề xuất chờ người hoặc trưởng nhóm quyết** |
| **Không** được | Ghi đè quyết định của lãnh đạo hay trưởng nhóm; giao việc thẳng cho agent khác (`company_task_delegate` 403); duyệt Approval thay người; tuyển/thuê agent; gửi ra ngoài khi chưa được duyệt (action:send theo cấp career) |
| Kỹ thuật | `seat_tier=assistant` (mới, cạnh `lead`/`executor`), quyền tool mặc định: đọc Hộp việc của lãnh đạo mình (`inbox.read:principal`), nháp (`action:draft`), lịch; `subagents.allowAgents=[chính nó]` như mọi ghế; người chịu trách nhiệm = lãnh đạo được phục vụ |

### 5.3 Mặc định còn mở — **default, chưa chốt**

| # | Câu hỏi | Mặc định đang dùng (chưa chốt) |
|---|---|---|
| D2 | Mỗi agent làm mấy việc cùng lúc | **1, cho phép 2–3 theo ghế** (default, chưa chốt); W1 "chờ không giữ ghế" bật luôn |
| D3 | Trần mặc định theo việc | **$0,50 · 6 lượt · 3 vòng SỬA** mỗi việc; vượt → một thẻ cho người chịu trách nhiệm (default, chưa chốt) |
| D4 | Agent nói chuyện trực tiếp qua OpenClaw | **Không** — `agentToAgent` tắt, `sessions.visibility=self`, sub-agent chỉ chính mình; mọi trao đổi qua task/bàn giao/A2A (default, chưa chốt — **đã biên dịch ở W0** vì là chặn rò giữa tổ chức trên gateway dùng chung; nới cần anh quyết) |
| D5 | Người chịu trách nhiệm việc agent làm | **Quản lý người của ghế** (= lãnh đạo người của nhóm), đổi được trên việc (default, chưa chốt) |
| D6 | Độ sâu / fan-out giao việc của trưởng nhóm | **3 / 8** (default, chưa chốt) |

(D1 cũ "ai được giao việc" đã thay bằng Q2: agent trưởng nhóm; thừa hành không; trợ lý chỉ đề xuất.)

---

## Phụ lục — file đã đọc

`HANDOFF.md`, `docs/plan-v2-modules.md`, `docs/agent-anatomy.md`, `docs/AGENT_TEAMWORK.md`, `work/project-state.md`
(ngoài repo), `_reports/{m4a-work,m4b-inbox,d31…d34,company-demo-e2e,execution-policy-e2e,wakeups-e2e}.md`;
code: `services/{task_lifecycle,agent_dispatch,wakeup,runtime_stream,execution_policy,work_context,routing,dispatch_policy,strategy,orchestration,routines,process_map,io_contracts,escalation,operating_time,a2a,delegation,seat_provision,seat_profile,company_mcp,budget_scope,career,agent_hr}.py`,
`runtime/openclaw_protocol.py`, `models/{entities,work_graph}.py`, `worker.py`, `api/work.py`.
