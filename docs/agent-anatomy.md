---
title: "Bài toán Agent — Nhân viên số của ClawCompany"
subtitle: "Giải phẫu agent, hiện trạng repo + gateway, và lộ trình (14/10/2026)"
---

# 1. Tóm tắt một trang

**Mục tiêu:** mỗi agent trong ClawCompany là một *nhân viên số* hoàn chỉnh — có danh tính, tính cách, các tầng bộ nhớ, kỹ năng, công cụ (tay chân), đầu óc suy nghĩ, nhịp làm việc tự chủ, khả năng làm nhóm, khả năng tự học, và một "sự nghiệp" (thử việc → đánh giá → thăng quyền → nghỉ việc).

**Hiện trạng (đã kiểm chứng trên VM, OpenClaw 2026.9.8):**

- Thiết kế phần "hồ sơ nhân sự" đã tốt và thật sự nối với gateway: tuyển agent → tạo agent trên gateway + sinh 5 file IDENTITY/SOUL/AGENTS/USER/MEMORY tiếng Việt, 5 preset tính cách, ngân sách tháng, phát hiện lệch, đồng bộ hai chiều, tạm dừng/nghỉ việc (gate M3 27/27 ×3).
- Bộ nhớ công việc theo task (`task_journal_entries` + gói ngữ cảnh 7 khối) là phần độc đáo nhất.
- Làm nhóm thật: bàn giao đánh thức người nhận, phòng họp có giới hạn lượt/chi phí, review chéo, hàng đợi đánh thức theo giờ làm và ngân sách.

**Nhưng trên gateway thật, phần lớn "nội tại" chưa tới được agent:**

1. MCP công ty chưa đăng ký → agent không đọc được dữ liệu công ty (25 tool `company_*` nằm chờ).
2. Các seat seed sẵn chưa có hồ sơ: SOUL/AGENTS/USER của Nina vẫn là mẫu tiếng Anh mặc định, không seat nào có MEMORY.md.
3. Mỗi agent mới chỉ chỉnh được tên + model; chưa có chính sách công cụ, sandbox (Nina chạy `exec` không sandbox), kỹ năng, sub-agent, heartbeat riêng.
4. Kỹ năng chỉ là metadata, không có nội dung/phiên bản/eval.
5. Chưa có vòng học: không có bài học → duyệt → MEMORY.md, không eval, không scorecard (tỷ lệ thành công đang là số seed).
6. Tìm kiếm bộ nhớ hỏng (embedding provider lệch chat provider); kiến thức chia 3 kho, agent không với tới.
7. Mức tự chủ đặt theo công ty, chưa theo từng seat/hành động.
8. Chưa có tuyển dụng → đào tạo → đánh giá → thăng chức.

**Kết luận:** không cần tự viết lại "bộ não". OpenClaw đã có sẵn phần lớn nguyên liệu (bộ nhớ nhiều tầng + Dreaming, Skill Workshop, thư viện kỹ năng, sandbox, tool policy, sub-agent, heartbeat/cron, approvals, audit). Việc của ClawCompany là **biên dịch hồ sơ nhân sự thành cấu hình gateway, quản trị (duyệt, phạm vi, ngân sách) và đo lường (eval, scorecard)** — bằng tiếng Việt, theo mô hình doanh nghiệp.

# 2. Giải phẫu một nhân viên số (16 bộ phận)

| Bộ phận (ẩn dụ con người) | Cơ chế | OpenClaw có sẵn | ClawCompany cần thêm |
|---|---|---|---|
| Danh tính | Tên, chức danh, phòng ban, cấp trên, avatar | `IDENTITY.md`, `identity{}` | Đã có; seed cũ cần render lại |
| Tính cách | Giọng, mức trang trọng, xưng hô (anh/chị/em), giá trị, Big Five làm gợi ý văn phong, ví dụ nên/không nên | `SOUL.md` | Form tính cách có phiên bản + test giữ vai (persona trôi sau ~8 lượt) |
| Mô tả công việc | Sứ mệnh, KPI, trong/ngoài phạm vi, quy tắc leo thang | `AGENTS.md` | Template JD theo vai (Sale, CSKH, Kế toán…) |
| Bộ nhớ tạm (working) | Cửa sổ ngữ cảnh, kế hoạch/todo, nén | session, compaction | Ngân sách token theo lượt chạy |
| Bộ nhớ ngắn hạn | Nhật ký ngày, transcript, log lượt chạy | `memory/YYYY-MM-DD.md` | Dòng thời gian tra cứu được |
| Bộ nhớ dài hạn cá nhân | Sự kiện, quyết định, bài học đã chắt lọc | `MEMORY.md` + Dreaming | UI xem/sửa/quên; duyệt trước khi ghi |
| Bộ nhớ về con người | Chỉ dẫn về từng người agent phục vụ | `USER.md` | Hồ sơ từng người, gắn nhãn dữ liệu cá nhân |
| Bộ nhớ công việc | Ngữ cảnh từng task | — | **Đã có** (journal + context pack) |
| Bộ nhớ tổ chức/nhóm | Chính sách, thuật ngữ, sản phẩm, khách hàng | — (cần kiểm tra chia sẻ chéo) | Bộ nhớ chung theo phạm vi org/phòng/dự án, chỉ đọc, qua MCP |
| Kiến thức (sách, tài liệu, khóa học) | Kho tri thức có trích dẫn | memory search | Nạp tài liệu → đề thi tự sinh → nhật ký "câu chưa trả lời được" |
| Kỹ năng | Thư mục SKILL.md có phiên bản, nạp khi cần | skills, ClawHub, Skill Workshop, library | Registry kỹ năng công ty + quy trình thăng cấp có eval |
| Tay chân (công cụ) | MCP, trình duyệt, code, tích hợp | tool policy, sandbox, elevated, `mcp add` | Lưới quyền: công cụ × đọc/nháp/gửi/trả tiền/xóa × Cho phép/Hỏi trước/Tắt, trần chi VND |
| Đầu óc (suy luận) | Model chính + dự phòng + model cố vấn + mức thinking | `model{primary,fallbacks}`, `thinkingDefault`, `decisionModel` | Preset định tuyến theo loại việc (rẻ cho việc thường, mạnh khi cần) |
| Nhịp làm việc độc lập | Heartbeat, cron, sự kiện, ý định thường trực | heartbeat, cron, intents | Routine gắn mục tiêu, giờ yên lặng |
| Lương tâm (rào chắn) | Điều kiện cứng cho hoàn tiền/hóa đơn/thanh toán, duyệt, audit | exec approvals, permission modes, audit | Tự chủ theo **hành động**, hộp duyệt trên điện thoại/Zalo |
| Xã hội (làm nhóm) | Task một chủ, brief bàn giao, reviewer, quản lý, A2A | sub-agents, agent send, team create | Sơ đồ tổ chức, bảng task (đã có), bảng chung của nhóm |
| Sự nghiệp | Eval, scorecard, thử việc, thăng quyền, rollback | — | Màn hình vòng đời kiểu HR |

# 3. Nguyên tắc thiết kế (rút từ research)

1. **Ngữ cảnh mới là tài nguyên khan hiếm, không phải dung lượng lưu.** Bộ nhớ, kỹ năng, công cụ, sub-agent đều để đưa *ít token nhất nhưng đúng nhất* vào model đúng lúc.
2. **Dùng file thuần, ghi rõ nguồn gốc mỗi ký ức** (chủ/agent/không tin cậy/hệ thống). Nội dung web không bao giờ tự đẩy mình vào bộ nhớ dài hạn.
3. **Dọn dẹp bộ nhớ ở nền**, không phải lúc đang trả lời (Dreaming, sleep-time agent). Một điều được lên bộ nhớ dài hạn vì *dùng nhiều lần thấy có ích*, không vì được viết tự tin.
4. **Quên bằng xếp hạng, không bằng xóa:** cũ thì giảm điểm; sự thật thay đổi thì đánh dấu "bị thay thế" và giữ lịch sử; chỉ xóa cứng khi có yêu cầu riêng tư.
5. **Phạm vi bộ nhớ:** công ty / phòng / dự án / riêng agent / từng người. Chủ đề nhạy cảm mặc định tắt.
6. **Học từ sách/tài liệu/khóa học:** ưu tiên kho tri thức (RAG) trước, rồi chắt thành kỹ năng + bài thi, tinh chỉnh model là cuối cùng (RAG thắng fine-tune khi thêm kiến thức — EMNLP 2024).
7. **Tự cải thiện phải có rào:** agent không được sửa bài eval, tính cách, quy tắc vận hành, quyền của chính nó; người chấm ẩn; mọi thay đổi có phiên bản và rollback. (Darwin Gödel Machine từng "gian lận" bằng cách xóa dấu kiểm tra thay vì sửa lỗi.)
8. **Tự chủ đặt theo hành động, không theo agent** — dựa trên mức đảo ngược được, rủi ro, chi phí. Quyền phải thực thi ở runtime, không chỉ trong prompt. Không để một agent vừa có dữ liệu riêng tư, vừa đọc nội dung không tin cậy, vừa có đường gửi ra ngoài.
9. **Đa agent chỉ khi một agent chịu trách nhiệm ghi:** đọc song song, reviewer ngữ cảnh sạch, model cố vấn, quản lý–nhân viên thì tốt; "bầy đàn" tự do thì không. Đa agent tốn ~15× token.
10. **Quản lý agent như nhân viên:** JD, onboarding, thử việc có eval (bắt đầu 20–50 task lấy từ lỗi thật), scorecard, thăng quyền, rollback, offboarding. Với agent gặp khách, đo "k lần đều đúng" chứ không phải "đúng 1 lần" (75%/lần → 3/3 lần chỉ ~42%).

# 4. Vòng đời nhân viên số

1. **Tuyển (đã có):** chọn vai + JD + tính cách + model + ngân sách → tạo agent trên gateway + render file.
2. **Onboarding (thiếu):** gán bộ nhớ tổ chức, kỹ năng bắt buộc theo vai, quyền công cụ mặc định an toàn, MCP công ty.
3. **Đào tạo (thiếu):** nạp tài liệu/khóa học vào kho tri thức → tự sinh đề thi → agent làm bài → đạt ngưỡng mới qua.
4. **Thử việc (thiếu):** chạy tự chủ mức thấp, mọi hành động ngoài đều "Hỏi trước"; chấm eval + review của người.
5. **Làm việc & tự học (thiếu một nửa):** Dreaming chắt bài học → **Hộp việc duyệt** → MEMORY.md; Skill Workshop đề xuất kỹ năng → eval → duyệt → thư viện.
6. **Đánh giá định kỳ (thiếu):** scorecard tháng: tỷ lệ hoàn thành, k-lần-đúng, tỷ lệ bị sửa/ghi đè, leo thang đúng, CSAT, chi phí/việc, vi phạm chính sách, số "lỗ hổng kiến thức".
7. **Thăng quyền / hạ quyền:** đổi mức tự chủ theo hành động dựa trên scorecard; mỗi lần đổi là một `AgentVersion` có rollback.
8. **Nghỉ việc (đã có):** tạm dừng/retire; cần thêm bàn giao bộ nhớ công việc + kỹ năng nhóm cho người kế nhiệm.

# 5. Mô hình dữ liệu đề xuất (control plane)

- `Persona(version, voice_rules, formality, pronoun_scheme, big5, do/dont_examples, channel_overrides)` → biên dịch ra SOUL.md/IDENTITY.md.
- `JobDescription(version, mission, goals, kpis, in/out_of_scope, escalation_rules)` → biên dịch ra AGENTS.md.
- `MemoryItem(scope[org|team|project|agent|person], kind[fact|decision|lesson|preference|policy], provenance, sensitivity, importance, valid_from/to, superseded_by, recall_count)` — riêng agent vẫn nằm trong file OpenClaw; control plane chỉ mirror/index và sở hữu phạm vi org/phòng/dự án.
- `KnowledgeSource(scope, type[book|sop|course|url|drive], ingest_status, exam_id)` — gộp 3 kho hiện tại thành một.
- `Skill(scope[company|team|agent-learned], version, skill_md, files, status[draft|nominated|evaluating|approved|archived], eval_suite_id, approved_by)`.
- `Permission(agent, connector, action_class[read|draft|send|pay|delete], mode[allow|ask|off], daily_cap_vnd, autonomy_level)` → biên dịch ra `tools.allow/deny`, sandbox, approvals.
- `EvalSuite / EvalRun / Scorecard / AgentVersion(hash persona+JD+skills+model+permissions, rollback_of)`.
- `Approval`, `AuditEvent` (ghi kèm phiên bản bộ nhớ/kỹ năng/model của từng lượt chạy).

# 6. Lỗi đã phát hiện

- **B1** Resync đẩy tên hiển thị ("GPT-4.1") làm model ID thật.
- **B2** `nina/ask` trả `answered:true` cả khi nội dung là lỗi; so số tin nhắn với `limit=50` nên phiên >50 tin luôn timeout; chọn seat đầu tiên thay vì đúng Nina.
- **B3** Không có endpoint tạo agent trên gateway cho seat seed sẵn (đề xuất `POST /api/agents/{id}/provision`).
- **B4** 6 khóa cấu hình seat (`timeoutSeconds`, `compaction.*`, `maxConcurrent`, `subagents.maxConcurrent`, `subagents.maxChildrenPerAgent`) không hợp lệ ở schema 9.8 → lưu sẽ lỗi (suy luận, chưa thử ghi).
- **B5** MCP công ty chưa đăng ký. **B6** Thiếu skill heartbeat. **B7** File seat không nhất quán. **B8** Cột hiệu suất là số tĩnh. **B9** Memory search chưa cấu hình đúng embedding.

# 7. Lộ trình đề xuất

**Giai đoạn A — Cho agent "sống thật" (1–2 tuần, chủ yếu sửa nối dây):**

1. Endpoint provision/render cho seat có sẵn (sửa B3, B7) → mọi agent có đủ 5 file tiếng Việt.
2. Đăng ký MCP công ty cho từng seat (B5) → agent đọc được task, khách hàng, kiến thức.
3. Sửa B1, B2, B4; cấu hình embedding cho memory search (B9).
4. Mặc định an toàn: sandbox cho seat thực thi, đồng bộ "Tắt" thành `tools.deny` trên gateway; cài heartbeat (B6).

**Giai đoạn B — Nội tại có thể tùy chỉnh (M5a):**

5. Form Tính cách + Mô tả công việc có phiên bản, biên dịch ra file; test giữ vai tiếng Việt.
6. Lưới quyền theo hành động + trần chi VND; model chính/dự phòng/mức thinking theo loại việc.
7. Bộ nhớ: UI xem/sửa/quên theo tầng; bộ nhớ chung org/phòng/dự án qua MCP.

**Giai đoạn C — Tự học có kiểm soát (M5b, điểm khác biệt so với Paperclip):**

8. Dreaming/bài học → Hộp việc duyệt → MEMORY.md.
9. Kho tri thức hợp nhất + nạp sách/tài liệu/khóa học + đề thi tự sinh + nhật ký lỗ hổng.
10. Skill Studio trên Skill Workshop/library: đề xuất → eval → duyệt → thư viện công ty, có rollback.

**Giai đoạn D — Sự nghiệp & đội nhóm (M6):**

11. Eval suite theo vai, scorecard thật, thử việc, thăng/hạ quyền theo `AgentVersion`.
12. Mẫu làm nhóm: quản lý–nhân viên, reviewer ngữ cảnh sạch, model cố vấn; A2A cho "agent thuê ngoài".

# 8. Câu hỏi còn mở

- Ràng buộc pháp lý VN về lưu trữ bộ nhớ có dữ liệu cá nhân (Nghị định 13/2023) và hóa đơn điện tử (Nghị định 123) — cần kiểm tra pháp lý.
- Chất lượng giữ vai/xưng hô tiếng Việt giữa các model — chưa có benchmark, phải tự đo.
- OpenClaw có bộ nhớ chia sẻ chéo agent ngoài workspace chung không — cần thử thực tế.

*Chi tiết đầy đủ và nguồn: `work/agent-audit.md` (ma trận năng lực theo file/endpoint) và `work/agent-research.md` (research có URL).*
