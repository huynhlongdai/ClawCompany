# Giọng thương hiệu (Brand Voice) — văn bản + giọng nói — báo cáo 2026-10-18

Yêu cầu của anh (18/10, "đầy đủ đi em"): module giọng thương hiệu đầy đủ cho công ty — giọng VĂN BẢN có cấu trúc theo
phiên bản + duyệt, biên dịch vào AGENTS.md, cưỡng chế, và GIỌNG NÓI (TTS) — chạy được với nhiều công ty và agent đi thuê.

Commit (nhánh `ui-v2`, chưa push): `698ea96` backend + migration 0065 + test · `0c7b011` UI · `642685b` sửa từ điển phát âm
khi nghe thử · `eab1413` sửa tràn ngang mobile · commit tài liệu này. VM chạy `eab1413`, alembic `0065_brand_voice`.

## 1. Đã làm

### Dữ liệu (migration `0065_brand_voice`, chỉ bảng mới)
| Bảng | Vai trò |
|---|---|
| `brand_voices` | một hàng = một PHIÊN BẢN giọng văn bản của một công ty: `draft → in_review → published` (bản trước → `archived`) / `rejected`; `spec` JSON; `is_demo` |
| `brand_voice_settings` | cưỡng chế của công ty: `off | flag | rework`, `min_score` (mặc định 0.7), `model_check`, `eval_suite_id` |
| `voice_checks` | mỗi lần chấm: nguồn (`try`, `submit_output`, …), kênh, điểm, đạt/không, hành động, vi phạm, ghế, việc, hợp đồng thuê |
| `voice_profiles` | giọng nói của công ty: nhà cung cấp, model, giọng, ngôn ngữ, tốc độ, cao độ, phong cách, kịch bản chào/kết, câu mẫu |
| `voice_samples` | mỗi lần "Nghe thử": văn bản gốc, văn bản sau từ điển, file âm thanh (bytea ≤ 4 MB, sha256) HOẶC lỗi thật của nhà cung cấp |

Chữ "Giọng thương hiệu" cũ của hiến chương (`company_profiles.brand_voice`) được chuyển thành `persona` của **v1 đã ban
hành** (trong migration và `ensure_legacy` cho công ty sửa hiến chương sau đó). Khi đã có bản ban hành, hiến chương không
biên dịch dòng cũ nữa (hồ sơ trả `brand_voice_superseded=true`).

### Spec giọng văn bản (`services/brand_voice.py::clean_spec`)
persona, nét tính cách, cặp **là / không là**, **xưng hô** (với khách mặc định + theo nhóm khách, nội bộ, danh sách cách
xưng cần tránh), **từ nên dùng** (dùng X thay Y), **từ cấm**, **khẳng định/cam kết cấm**, **emoji** (none/light ≤ N/free),
quy tắc định dạng, **ký tên**, lời kết, **biến thể 6 kênh** (Zalo, Facebook/Messenger, email, kịch bản gọi, website/bài
đăng, nội bộ: giọng, lời chào/kết, độ dài tối đa, emoji, chữ thô, bắt buộc ký tên), **cặp ví dụ đúng/sai**, **từ điển phát
âm**. Một từ vừa "nên dùng" vừa "cấm" → 422 `term_conflict`.

### Biên dịch vào agent
* `core_block` (≤ 1.600 ký tự, không cắt giữa dòng) nằm trong "## Kiến thức cốt lõi" ngay sau hiến chương — mọi đường sinh
  AGENTS.md (tuyển, sửa hồ sơ, `sync_core`) tự mang theo.
* Ban hành → đồng bộ lại AGENTS.md mọi ghế của tổ chức + các ghế mà công ty này đang cho thuê (sàn đổi).
* Chi tiết từng kênh: **`company_doc_get doc_code=VOICE channel=<kênh>`** — KHÔNG thêm tool mới (thêm tool sẽ đổi số tool
  mà test cũ `test_d15` đang khẳng định = 42; anh dặn không sửa test cũ). Tool trả giọng áp dụng cho chính ghế đó.

### Cưỡng chế
* Bộ chấm tất định `check_text`: từ cấm, cam kết cấm (khớp cả khi gõ không dấu với cụm ≥ 2 tiếng; "bán" không bị nhầm
  "bạn"), xưng hô sai / thiếu gọi khách theo nhóm, emoji, độ dài kênh, markdown ở kênh chat, dấu "!!", thiếu ký tên email, từ
  nên thay. Điểm = 1 − (cao 0.4 / vừa 0.2 / thấp 0.08 mỗi lỗi); đạt = không có lỗi nặng và điểm ≥ ngưỡng.
* Gắn vào `io_contracts.submit` (đường `company_task_submit_output` + nộp từ UI): các trường văn bản gửi khách
  (`customer_message`, `reply`, `message`, `caption`, `post_text`, `content`, `body`, `email_body`, `script`…), kênh lấy từ
  trường `channel` (mặc định Zalo), nhóm khách từ `segment`.
  * `flag` (mặc định): kết quả vẫn đạt, ghi `voice_checks` + thẻ Hộp việc mới `voice_flag` cho quản lý ghế / chủ công ty.
  * `rework`: lỗi giọng thành lỗi hợp đồng dữ liệu (`giọng.<mã>`), tính một lần nộp, trả làm lại như cũ.
  * `off`: không chấm.
* Người duyệt "ngữ cảnh sạch" (`execution_policy.run_clean_review`) thấy thêm dòng điểm giọng gần nhất của việc.
* Chấm bằng model (`/chat/completions`, model `voice_check_model` = gpt-5-nano): chỉ khi công ty bật cờ; chỉ tham khảo,
  không quyết; lỗi/hết quota → `status=error` nói thật.
* Agent HR (`/team/agent-hr`) + scorecard Sự nghiệp: `voice_score`, `voice_checks`, `voice_pass_rate` (không tính ô thử).
* Bộ eval giọng: `POST /team/brand-voice/eval-suite` tạo/cập nhật một `eval_suite` từ các ví dụ (không được có từ/cam kết cấm
  + cách xưng bị tránh, phải gọi khách đúng) — chạy k lần bằng nút đánh giá có sẵn ở Sự nghiệp agent. "Kiểm bộ quy tắc trên
  ví dụ" (selftest) kiểm câu đúng phải đạt, câu sai phải bị bắt.

### Giọng nói
* Adapter TTS không phụ thuộc nhà cung cấp: `CometTTS` (OpenAI-compatible `POST {base}/audio/speech`, base + key dùng chung
  cấu hình CometAPI của embedding; `gpt-4o-mini-tts` nhận `instructions` = ngôn ngữ + cao độ + phong cách), `FakeTTS` chỉ khi
  `tts_fake_enabled` (kiểm thử; UI không hiện khi tắt).
* "Nghe thử" (câu mẫu / lời chào / lời kết, ≤ 600 ký tự): áp **từ điển phát âm** (bản nháp đang soạn trước, rồi bản ban hành)
  → gọi TTS → lưu file; lỗi nhà cung cấp → lưu lần thử lỗi + trả **424** `tts_provider_quota | tts_provider_auth |
  tts_provider_error | tts_not_configured | …` với nguyên văn lỗi. Không bao giờ giả thành công.

### Nhiều công ty + cho thuê
* Mỗi công ty một giọng, phiên bản riêng; tổ chức khác 404, viewer đọc được nhưng không sửa (R1).
* Ghế thuê: phần cốt lõi là của BÊN THUÊ → giọng bên thuê ở "Lớp của bên thuê"; giọng bên cho thuê không vào.
* Sàn: từ cấm + cam kết cấm của bên cho thuê thêm vào mục "Sàn của bên cho thuê (KHÔNG ĐƯỢC GHI ĐÈ)"; bộ chấm luôn chấm thêm
  (nguồn `provider_floor`), vi phạm sàn luôn **trả làm lại** kể cả khi bên thuê để `flag`/`off`; bên thuê tắt cưỡng chế thì
  chỉ còn sàn được chấm.

### API (`/api/team`, vai trò công ty)
`GET brand-voice` (member) · `PUT brand-voice/draft` (manager) · `GET brand-voice/versions/{id}` · `POST …/{id}/submit`,
`…/{id}/discard` (manager) · `POST …/{id}/decide` (admin; người gửi không tự duyệt trừ chủ) · `PUT brand-voice/settings`
(admin) · `POST brand-voice/check` (ô thử) · `GET brand-voice/checks` · `POST brand-voice/selftest` · `POST
brand-voice/eval-suite` · `GET brand-voice/agent-view/{agent_id}` · `GET|PUT voice-profile` · `POST voice-profile/preview` ·
`POST voice-profile/spoken-text` · `GET voice-samples` · `GET voice-samples/{id}/audio`. Router khai trong
`company_guard.AWARE`.

### UI
Công ty › Pháp nhân & quản trị › **Giọng thương hiệu** (`/app/company?tab=voice`, `components/BrandVoice.tsx`): thanh trạng
thái (bản đang áp dụng / nháp / chờ duyệt / demo) + Lưu nháp / Gửi duyệt / Duyệt & ban hành / Từ chối / Bỏ nháp; 5 tab
**Văn bản · Theo kênh · Ví dụ · Giọng nói · Kiểm tra** (ô thử văn bản → điểm + danh sách lỗi theo ngôn ngữ người dùng, cài
đặt cưỡng chế, bộ eval, lịch sử chấm). Soạn = quản lý, ban hành/cài đặt = quản trị; người chỉ xem thấy form khoá. 217 khoá
i18n `bv.*` vi+en + `nav.co_giong_thuong_hieu`.

## 2. Kiểm chứng

### Test
* `tests/test_brand_voice.py` — 11 test hành vi (API thật + ORM SQLite + gateway giả): chuyển chữ cũ → v1, vòng duyệt và vai
  trò, AGENTS.md sinh lại/không còn dòng cũ, tuyển sau mang giọng, bộ chấm (từng luật), ô thử + cờ model, tool VOICE, rework
  /flag trên `company_task_submit_output`, Agent HR, eval suite, giọng nói (spy adapter, từ điển, file, quyền, adapter giả),
  lỗi quota 424 lưu lần thử lỗi, cho thuê (giọng bên thuê + sàn không nới được), seed demo.
* Toàn bộ backend: **1.383 passed / 2 skipped / 0 failed** (110 file + `test_wp37` tách 3×12 theo node id); KHÔNG sửa test cũ.
* `tsc --noEmit` sạch, `next build` ok (`work/bv/next_build.log`).

### VM (tất định; `work/vm_bv.py check|seed|flow|sim|tts|viewer|agents`)
* Migration 0065 chạy trên Postgres; co.3 Tiệm Gốm Mộc có chữ giọng cũ → **v1 đã ban hành** (persona = chữ cũ).
* `POST /learning/core/sync` → AGENTS.md của CSKH trên gateway (`workspace-shop-a407-cskh`) có "### Giọng thương hiệu Tiệm Gốm
  Mộc (v1 …)", dòng hiến chương cũ không còn (6 ghế ghi được; ghế 1, 2, 3 không có agent trên gateway — đã biết từ trước).
* Seed **bản nháp DEMO v2** (không ban hành) + cấu hình giọng nói demo cho co.3. Ô thử theo bản nháp: câu đúng 1.0 đạt; câu sai
  0.0 (từ cấm, cam kết cấm, xưng hô "bạn"/"tôi", emoji, "!!", từ nên thay); email thiếu ký tên + emoji 0.72; Facebook quá dài
  0.8; selftest 3/3 đúng đạt, 3/3 sai bị bắt; mâu thuẫn từ → 422.
* Mô phỏng ban hành v2 trên Postgres: khối giọng 1.574/1.600 ký tự, tool VOICE kênh phone đúng; cưỡng chế flag → `flag`, rework
  → `rework` (lỗi `giọng.banned_claim`, `giọng.wrong_address`), câu đúng → `none` 1.0.
* R1: viewer co.3 GET 200 / PUT nháp 403 / nghe thử 403 / co.1 403; tổ chức thuê → co.3 404.
* Ảnh: `_reports/ui/bv-*.png` (16: 5 tab desktop, selftest, kết quả ô thử, nghe thử, en ×3, mobile ×5). Mobile 390 px
  scrollWidth = 390 ở mọi tab; lỗi console duy nhất = 424 của lần nghe thử thật (đúng mong đợi).

### TTS thật
Gọi thật CometAPI `POST https://api.cometapi.com/v1/audio/speech` (gpt-4o-mini-tts, giọng nova) **5 lần** → đều **HTTP 403
`insufficient_user_quota`** ("organization and owner combined quota is zero, need $0.0048"). API trả 424
`tts_provider_quota`, UI hiện nguyên văn lỗi, lưu 5 dòng `voice_samples` trạng thái `error`, **không có file âm thanh nào**.
Chưa nghe được giọng tiếng Việt thật — cần nạp quota CometAPI rồi bấm "Nghe thử" lại.

## 3. Sự cố trên VM (đã hoàn nguyên)
Chế độ `sim` lần đầu gọi `company_mcp.call(...)` trong giao dịch định rollback; hàm đó ghi sự kiện `mcp.tool.called` và
**commit** giữa chừng → bản demo v2 thành "published", v1 "archived" trên co.3 khoảng ~1 phút. Đã hoàn nguyên bằng
`work/vm_bv_revert.py` (v2 → draft, v1 → published), không có lần đồng bộ AGENTS.md nào chạy trong khoảng đó (lần sync sau
ghi v1). Script đã sửa để không gọi `company_mcp.call` trong mô phỏng.

## 4. Còn mở / giới hạn (nói thẳng)
1. **Tool riêng `company_brand_voice` chưa có** — đi qua `company_doc_get doc_code=VOICE` để giữ số tool (test cũ). Muốn tool
   riêng thì phải đổi assertion `test_d15` (ghi lý do).
2. **Cưỡng chế chỉ ở kết quả có hợp đồng dữ liệu** (trường văn bản gửi khách của `company_task_submit_output`). Tin chat tự do
   (Zalo/portal/A2A qua gateway) CHƯA bị chấm; plugin guard chưa biên dịch từ/cam kết cấm của giọng vào `message_sending`.
   Bước tiếp: đưa từ cấm + cam kết cấm thành luật cứng (runtime_rules → guard).
3. Đường duyệt: chỉ reviewer "ngữ cảnh sạch" thấy dòng điểm giọng; phòng duyệt 2 người chưa.
4. Bản v1 chuyển từ hiến chương mang thêm luật mặc định (emoji ≤ 2, độ dài kênh) mà chữ cũ không nói — chỉ gắn cờ (chế độ
   mặc định `flag`). co.3 còn tài liệu cốt lõi cũ **PRD-003 "Giọng thương hiệu"** (M3b) trùng chủ đề — nên lưu trữ hoặc gộp
   vào trang giọng sau khi anh duyệt bản demo.
5. Chấm bằng model và bộ eval giọng chạy k lần **chưa chạy thật** (CometAPI hết quota). Eval suite chưa tạo trên VM.
6. Ghế thuê dùng giọng bên thuê + sàn: chỉ chứng minh bằng test (VM không còn hợp đồng thuê đang chạy).
7. Người gửi không tự duyệt (trừ chủ): có code, test chỉ phủ đường chủ duyệt. Cao độ là gợi ý trong `instructions` (OpenAI TTS
   không có tham số pitch; `tts-1` bỏ qua). File nghe thử lưu trong DB, chưa có hạn dọn.
8. Dữ liệu demo còn trên VM co.3: bản nháp v2 (DEMO, chưa ban hành), cấu hình giọng nói demo, 5 lần nghe thử lỗi, vài dòng
   chấm nguồn `try`. Bản nháp chờ anh sửa → Gửi duyệt → Duyệt & ban hành.
