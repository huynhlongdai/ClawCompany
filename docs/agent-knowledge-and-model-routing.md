---
title: "Agent: Kho tri thức & Định tuyến model tối ưu chi phí"
subtitle: "Bổ sung cho docs/agent-anatomy.md — 15/10/2026"
---

# Phần 1 — Kho tri thức và lịch học cho agent

## 1.1 Mục tiêu

Admin có ba cách cho agent "học":

1. **Nạp tài liệu trực tiếp** (PDF, DOCX, XLSX, PPTX, Markdown, ảnh có chữ).
2. **Kết nối kho có sẵn** để tự đồng bộ: Google Drive, Notion, website/URL, sau đó SharePoint/OneDrive, Confluence, GitHub, YouTube (lấy transcript khóa học).
3. **Lên lịch học (khóa học)**: chọn tài liệu theo thứ tự, chọn agent/vai học, chọn giờ học, có bài kiểm tra cuối.

## 1.2 Kiến trúc

```
Nguồn (upload / Drive / Notion / URL / ...)
   │  đồng bộ một lần hoặc theo lịch (chỉ phần thay đổi)
   ▼
Phân tích → cắt đoạn → nhúng (embedding) → pgvector (đã có trong stack)
   │  gắn phạm vi: công ty / phòng / dự án / riêng agent; kế thừa quyền của nguồn
   ▼
Một kho tri thức hợp nhất (gộp 3 kho hiện có trong knowledge_mesh)
   │
   ├─► Agent tra cứu khi làm việc: tool MCP `company_knowledge_search` (có trích dẫn nguồn)
   └─► Agent "học" theo khóa: đọc → ghi chú → đề xuất bài học/kỹ năng → làm bài thi
```

Nguyên tắc (từ research): **tra cứu (RAG) trước, chắt thành kỹ năng + bài thi sau, fine-tune cuối cùng.** Agent không nhồi cả kho vào bộ nhớ; chỉ những bài học đã duyệt mới vào MEMORY.md.

Embedding đề xuất: `text-embedding-3-small` trên CometAPI ($0.016/1 triệu token) — nạp 1.000 trang tài liệu (~500k token) tốn khoảng $0.01. Đồng thời sửa lỗi B9 (memory search lệch embedding).

## 1.3 Khóa học (lịch học)

| Thành phần | Nội dung |
|---|---|
| Khóa học | Tên, mục tiêu, danh sách module theo thứ tự (mỗi module = 1 hoặc nhiều tài liệu/đoạn) |
| Học viên | Theo vai (ví dụ mọi agent CSKH), theo phòng, hoặc chọn từng agent; agent mới tuyển vào vai đó tự được ghi danh (onboarding) |
| Lịch | Cron, ví dụ "22:00 mỗi tối 1 module", ngoài giờ làm, tôn trọng giờ yên lặng |
| Model & ngân sách | Học chạy ở tầng rẻ (T1/T2), trần chi riêng cho khóa |
| Bài thi | Sinh tự động một lần từ tài liệu (tầng mạnh), chấm bằng tầng rẻ; ngưỡng đạt, ví dụ 80% |
| Kết quả | Đạt → "chứng chỉ" trên hồ sơ agent, mở khóa quyền/việc tương ứng; trượt → học lại + ghi lỗ hổng |

**Một buổi học** (chạy trong phiên cô lập của OpenClaw, không lẫn phiên làm việc):

1. Agent đọc module qua MCP (có trích dẫn).
2. Viết ghi chú ngắn vào nhật ký ngày của nó.
3. Đề xuất tối đa vài "bài học" hoặc 1 kỹ năng mới → vào **Hộp việc** chờ người duyệt → duyệt xong mới ghi vào MEMORY.md / thư viện kỹ năng.
4. Cuối khóa: làm bài thi, chấm tự động, lưu điểm.

**Tự cập nhật:** khi nguồn thay đổi (Drive/Notion sửa tài liệu), hệ thống đánh dấu module "cũ", tạo buổi ôn ngắn cho agent đã học.

**Học từ trải nghiệm** (song song): Dreaming hằng đêm của OpenClaw chắt bài học từ việc đã làm; review kỹ năng hằng tuần; mọi đề xuất đều qua Hộp việc duyệt.

**Lỗ hổng kiến thức:** câu nào agent tra không ra hoặc bị người sửa → ghi vào danh sách "Lỗ hổng" để admin bổ sung tài liệu.

## 1.4 Màn hình cho admin

- **Thư viện tri thức:** danh sách nguồn, trạng thái đồng bộ, phạm vi, số tài liệu, lần sync cuối.
- **Kết nối:** nút nối Google Drive / Notion / URL (OAuth hoặc API key).
- **Khóa học:** trình tạo khóa (kéo thả module), lịch, học viên, ngân sách.
- **Bảng học tập:** tiến độ, điểm, chứng chỉ từng agent; lỗ hổng kiến thức.

## 1.5 Dữ liệu

- `KnowledgeConnector(type[upload|gdrive|notion|url|sharepoint|confluence|github|youtube], credential_ref, scope, sync_cron, acl_mode)`
- `KnowledgeDoc(connector_id, external_id, title, version_hash, scope, updated_at)` · `KnowledgeChunk(doc_id, text, embedding, position)`
- `Course(title, goal, modules[], audience{roles,departments,agents}, schedule_cron, model_tier, budget_vnd, pass_score)`
- `Enrollment(agent_id, course_id, progress, status[learning|passed|failed|stale], score, certified_at)`
- `Quiz / QuizAttempt` · `LessonProposal(agent_id, source_ref, content, status)` → Hộp việc · `KnowledgeGap(agent_id, question, task_id, resolved_by_doc)`

# Phần 2 — Định tuyến model tối ưu chi phí

## 2.1 Bài toán

Mỗi lượt chạy của agent chọn **model rẻ nhất mà vẫn đạt chất lượng** cho việc đó. Thước đo đúng là **chi phí trên mỗi kết quả được chấp nhận**, không phải giá mỗi lần gọi (model rẻ mà phải làm lại hoặc người phải sửa thì thực ra đắt).

## 2.2 Các tầng model (giá CometAPI thật, USD / 1 triệu token, kiểm 15/10/2026)

| Tầng | Dùng cho | Model chính | Giá vào / ra | Dự phòng |
|---|---|---|---|---|
| T0 Luật | Phân việc theo luật, mẫu cố định, không cần LLM | — | $0 | — |
| T1 Siêu rẻ | Phân loại, gắn nhãn, tóm tắt ngắn, heartbeat, tiêu đề, chấm bài thi | `gpt-5-nano` | $0.04 / $0.32 | `qwen3.8-flash` ($0.12 / $0.376) |
| T2 Thường | Trả lời khách, soạn thảo, việc hằng ngày, học bài | `gpt-5-mini` | $0.20 / $1.60 | `deepseek-v4-flash` (~$0.176 / $0.528) |
| T3 Mạnh | Lập kế hoạch nhiều bước, review chéo, việc rủi ro, tài liệu dài | `gemini-3.8-flash` | $0.60 / $3.00 | `claude-sonnet-5` ($1.60 / $8.00) |
| T4 Chuyên gia | Hiếm: quyết định lớn, chính sách, sự cố | `claude-sonnet-5` (+ thinking) | $1.60 / $8.00 | — |

Hiện đang chạy `gpt-4.1-mini` (giá chính thức $0.40 / $1.60, Comet giảm ~20%); `gpt-5-mini` rẻ hơn ở đầu vào và mạnh hơn, nên làm mặc định T2. Đây là gợi ý ban đầu; bảng tầng phải được **chứng minh bằng eval** trên việc thật trước khi cố định.

## 2.3 Bộ định tuyến chọn tầng thế nào

Điểm độ khó tính từ tín hiệu có sẵn, **luật trước, model sau**:

| Tín hiệu | Ví dụ ảnh hưởng |
|---|---|
| Loại việc (từ task/routine) | gắn nhãn → T1; trả lời khách → T2; lập kế hoạch → T3 |
| Rủi ro hành động | có gửi ra ngoài, tiền, xóa → +1 tầng hoặc bắt buộc duyệt |
| Khách hàng nhìn thấy | +1 tầng nếu là kênh khách quan trọng |
| Độ dài ngữ cảnh | > 50k token → tầng có ngữ cảnh lớn |
| Cần công cụ nhiều bước | ≥ 3 bước tool → tối thiểu T2 |
| Lịch sử | việc cùng loại bị trả lại/sửa nhiều → nâng tầng mặc định |
| Ngân sách còn lại của seat | dưới 20% → hạ trần tầng, việc không gấp xếp hàng |
| Mức tự chủ / thử việc | agent thử việc dùng tầng thấp + duyệt nhiều hơn |

Khi luật không đủ chắc: dùng **decisionModel** của OpenClaw (bộ phân loại ONNX chạy CPU trên VM, chi phí $0) hoặc 1 lượt T1 (~$0.0001) để chấm độ khó.

**Leo thang có giới hạn (cascade):** chạy tầng được chọn → kiểm tra kết quả bằng luật (đúng định dạng, không hứa điều cấm, độ dài, gọi tool thành công) → hỏng thì nâng **một** tầng, tối đa 2 lần, ghi lý do. Lỗi 401/400 thì báo lỗi, không leo thang (đúng bài học từ lỗi Nina).

## 2.4 Ánh xạ vào OpenClaw (không phải tự viết proxy)

- Mỗi agent: `model.primary` = tầng mặc định theo vai, `model.fallbacks` = tầng dự phòng.
- `utilityModel` = T1 (tiêu đề, tóm tắt) · `heartbeat.model` = T1 · `subagents.model` theo việc con.
- Mỗi lượt chạy có thể ghi đè model (`openclaw agent --model ...` / tham số tương ứng qua gateway) → ClawCompany chọn tầng trước khi gửi việc.
- **Prompt caching:** SOUL/AGENTS/USER là tiền tố cố định → đặt đầu prompt để hưởng giá cache (rẻ hơn ~10 lần ở model hỗ trợ).
- `modelPolicy.allow` = chỉ các model trong bảng tầng → agent không tự chọn model đắt.
- CometAPI có `model=auto`, nhưng model thay đổi ngầm, không tái lập được → chỉ dùng thử, không làm mặc định.

## 2.5 Tự tối ưu theo thời gian

Ghi mỗi lượt: loại việc, tầng, model, token, chi phí, thời gian, kết quả (được chấp nhận / bị sửa / làm lại). Mỗi tuần:

- Tính **chi phí trên kết quả được chấp nhận** cho từng cặp (loại việc × tầng).
- Nếu tầng thấp hơn đạt tỷ lệ chấp nhận gần bằng (ví dụ chênh < 3 điểm %) → đề xuất hạ tầng mặc định cho loại việc đó.
- Nếu tầng hiện tại bị sửa nhiều → đề xuất nâng tầng.
- Đề xuất đi vào Hộp việc để admin duyệt; mọi thay đổi bảng tầng có phiên bản + rollback.
- Thêm model mới vào bảng chỉ sau khi chạy cùng bộ eval.

## 2.6 Ước tính tiết kiệm

Giả định một agent làm 200 việc/ngày, mỗi việc ~6.000 token vào + 800 token ra:

| Cách chạy | Chi phí/việc | Chi phí/ngày | Chi phí/tháng |
|---|---|---|---|
| Tất cả bằng `claude-sonnet-5` | ~$0.016 | ~$3.20 | ~$96 |
| Tất cả bằng `gpt-5-mini` | ~$0.0025 | ~$0.50 | ~$15 |
| Định tuyến: 60% T1, 25% T2, 15% T3 (`gemini-3.8-flash`) | ~$0.0018 | ~$0.36 | ~$11 |

Định tuyến rẻ hơn khoảng **89%** so với dùng một model mạnh cho mọi việc, và vẫn dành model mạnh cho 15% việc khó. Con số thật phụ thuộc tỷ lệ làm lại — phải đo bằng log ở 2.5.

## 2.7 Màn hình

- **Bảng tầng model** (admin): tầng → model chính/dự phòng, giá, trạng thái eval.
- **Chính sách định tuyến**: luật theo loại việc/rủi ro, trần tầng theo phòng/seat.
- **Chi phí**: theo tầng, theo loại việc, chi phí/kết quả chấp nhận, đề xuất hạ/nâng tầng.
- Trên mỗi lượt chạy: hiện "tầng T2 · gpt-5-mini · lý do: trả lời khách".

## 2.8 Dữ liệu

- `ModelTier(code, primary_model, fallbacks[], price_in, price_out, cache_price, eval_status, version)`
- `RoutingRule(priority, match{task_type, risk, channel, department, seat}, min_tier, max_tier)`
- `RunRouting(run_id, task_type, signals{}, chosen_tier, model, escalations[], tokens_in/out, cost, outcome[accepted|edited|redo|failed])`
- `RoutingSuggestion(task_type, from_tier, to_tier, evidence{}, status)` → Hộp việc

# Phần 3 — Thứ tự làm

1. (Giai đoạn A) Nối dây agent + sửa B1–B4, B9 — đồng thời đặt bảng tầng tĩnh T1/T2/T3 vào cấu hình từng agent (`model.primary/fallbacks`, `utilityModel`, `heartbeat.model`, `modelPolicy.allow`).
2. Kho tri thức hợp nhất + nạp tài liệu + MCP tra cứu có trích dẫn.
3. Bộ định tuyến luật + log `RunRouting` + hiển thị chi phí theo tầng.
4. Kết nối Google Drive, Notion, URL; đồng bộ theo lịch.
5. Khóa học + bài thi + chứng chỉ + Hộp việc duyệt bài học.
6. Cascade có kiểm tra + đề xuất hạ/nâng tầng hằng tuần.

Nguồn giá: CometAPI Models API (api.cometapi.com/api/models, đọc 15/10/2026, đã nhân hệ số 0.8); bài "How to Route LLM Requests…" của CometAPI (04/09/2026) cho giá deepseek-v4-flash; danh sách model khả dụng lấy trực tiếp bằng key test.
