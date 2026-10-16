# M3 tiếp theo — P0 route cũ, M3c nạp tài liệu, M3e vòng học, dọn i18n, ngưỡng đổi giá

Nhánh `ui-v2`, chưa push. VM (`clawcompany`, company 3 "Tiệm Gốm Mộc") chạy tới `28978cf` (code); các commit sau chỉ đổi
test/báo cáo. Alembic VM `0059_price_change_threshold`. Tunnel: https://cgi-bikes-pretty-iso.trycloudflare.com

Tiền: khách VN tính VND (số nguyên, không phần lẻ); nền tảng (chi phí model, giá thuê agent) tính USD. CometAPI hết hạn mức
(embedding trả 403 → mọi lần nạp/tra cứu rơi về vector băm hash384), nên mọi kiểm chứng dưới đây là **xác định**
(không có lượt model thật).

| Phần | Commit | Migration | Kiểm chứng |
|---|---|---|---|
| P0 R1 — route cũ cấp tổ chức lọc theo vai trò công ty | `088a5d4` | — | test + VM (lượt trước) |
| M3c — nạp & phân loại tài liệu | `9a3ecf2` | 0057 | test + VM (lượt trước) |
| M3e — vòng học tài liệu | `670ef15`, `b1a4fef`, `8c5bfb3` | 0058 | test + VM |
| Dọn i18n (chuỗi VN ở giao diện EN) | `f21a6c5` | — | test + VM + ảnh |
| Ngưỡng % đổi giá theo công ty | `28978cf` | 0059 | test + VM + ảnh |
| Sửa test phụ thuộc giờ (v36) | `53945dc` | — | bộ test |

## P0 — route cũ cấp tổ chức (`088a5d4`)

`app/core/company_guard.py` chạy trong `get_principal` cho người bị giới hạn công ty: module biết công ty (team, docs,
leases, inbox, learning…) đi qua; module có phạm vi (work, tasks, agents, projects, approvals, dashboard, costs…) lọc
theo `company_scope.allowed_company_ids`; mọi route khác (v7–v36, a2a, routines, strategy, shared-memory, knowledge…)
mặc định **đóng 403** `org_level_route`. Vá 2 rò thật: `/team/org-chart` (không có company_id → công ty đầu của tổ chức)
và `/agents/hire/options`. VM: người xem `gom.viewer@r1.test` (viewer công ty 3) trên 16 danh sách cũ thấy 0 dấu công
ty 1; `/work/tasks/<c1>` 403, `<c3>` 200; `?company_id=1` 403.

## M3c — nạp & phân loại (`9a3ecf2`)

PDF (pypdf → OCR Tesseract `vie` khi không có lớp chữ), ảnh scan, DOCX/XLSX/PPTX/HTML/MD, URL; chống trùng sha256 (409);
đề xuất loại tài liệu + độ nhạy (PII → `personal_data`, agent không đọc); GCN ĐKDN → đề xuất hồ sơ pháp nhân (chỉ áp
dụng khi admin bấm); 8 mẫu VN; nguồn Google Drive / Notion (token mã hoá, không bao giờ trả về) đồng bộ → **bản nháp**.
VM: GCN scan → OCR, 4/5 trường đúng (đại diện "ĐỒ" thay "ĐỖ" do OCR dấu).

## M3e — vòng học tài liệu (`670ef15` + `b1a4fef` + `8c5bfb3`)

**Luồng.** Nguồn → đề xuất (một `DocProposal` + **một bản nháp** trên tài liệu) → duyệt đúng đường M3a (ma trận
`doc_publish`, không đường tắt) → ban hành → cờ/lỗ hổng nguồn đóng → eval chạy lại, ghi `eval_before` / `eval_after`.

- Nguồn 1 — cờ agent (`company_doc_flag`): mọi cờ mở trên một tài liệu gộp vào **một** đề xuất; chạy lại không tạo thêm.
- Nguồn 2 — cụm lỗ hổng: câu hỏi tra không ra (kể cả câu eval trượt, `source="eval"`) gom cụm Jaccard ≥ 0.5 trên
  token đã **gỡ thông tin cá nhân** (SĐT, email, CCCD, "chị Lan…") và bỏ từ xưng hô; cụm ≥ 3 lượt → nháp bổ sung vào
  tài liệu gần nhất, không có thì nháp FAQ mới.
- Nguồn 3 — bài học đã duyệt có nhắc mã tài liệu (POL-003…) → đề xuất trên tài liệu đó.
- Nguồn 4 — agent gọi MCP **`company_doc_propose`** (nội dung đầy đủ) → nháp; một đề xuất mở / tài liệu (lần 2 →
  `conflict`). Trong lúc chờ, agent vẫn đọc bản đang hiệu lực.
- Nội dung nháp **không do model viết** (CometAPI hết): nháp = bản hiện hành + mục "[Cần bổ sung]" liệt kê câu hỏi /
  ghi chú; người phụ trách sửa rồi gửi duyệt.
- `docs.tick` (mỗi giờ) chạy cả ba nguồn + đo lại đề xuất đã ban hành. API `/api/team/doc-learning` (GET, `/propose`,
  `/eval`, `/proposals/{id}/dismiss`); Hộp việc kind `doc_proposal`.
- UI: **Công ty › Tài liệu & tri thức › Vòng học** (vi + en): KPI (tài liệu còn hạn rà soát, cờ mở/đã đóng, lỗ hổng
  mở/đã đóng bằng tài liệu, eval mới nhất), cụm câu hỏi, đề xuất mở → đã ban hành → từ chối/bỏ qua kèm eval trước/sau,
  lịch sử eval. "Tỉ lệ lỗ hổng / lượt tra" hiện **chưa đo** (chưa có bộ đếm lượt tra) — nói thẳng, không bịa.

**Truy hồi (sửa trong M3e).** Loại câu trả lời mong đợi (hỏi số tiền → đoạn có số tiền; hỏi số điện thoại → đoạn có
số; hỏi thời lượng → đoạn có "n ngày"), bỏ cụm hỏi / lời xin / dấu câu khỏi từ khoá, "điện thoại/sđt" → "hotline";
vector băm (cả pgvector, vốn cũng là vector băm) **không vào RRF**; FTS Postgres khớp cụm đồng nghĩa dạng cụm
(`mien <-> phi <-> van <-> chuyen`) thay vì từ rời, `ts_rank_cd` chuẩn hoá ×0.3.

| Eval CSKH 33 câu, công ty 3, Postgres (corpus thật gồm tài liệu cũ + SOP gây nhiễu) | recall@6 | đúng mục | top-1 |
|---|---|---|---|
| Đường cũ (legacy) | 0.818 | — | — |
| M3b / M3e trước sửa Postgres (deploy `670ef15`) | 0.970 | 0.939 | 0.576 |
| Sau `b1a4fef` | **1.000** | **1.000** | **0.727** |

SQLite (8 tài liệu sạch): recall@6 1.0, đúng mục 1.0. Hai câu M3b còn trượt nay đúng top-1 trên VM:
"Đơn bao nhiêu tiền thì được freeship?" → `[DOC:POL-004 §1] Phí vận chuyển` (0.914); "so hotline cua tiem" →
`[DOC:CUS-001 §1] Giờ mở cửa và liên hệ` (0.8). Câu diễn đạt khác (không có trong bộ eval): "cho minh xin so dien thoai
cua shop" → CUS-001 §1; "Mua bao nhiêu tiền thì được miễn phí ship vậy shop?" → POL-004 §1. 9 câu top-1 còn sai đều do
tài liệu cũ trùng nội dung (DOC-2/DOC-4, SOP PRC-001/002 không chia mục) — đáp án đúng vẫn trong top 6.

**VM (work/vm_m3e.py).** MCP `company_doc_flag` CUS-001 (2 cờ mở) → `POST /doc-learning/propose` → 1 đề xuất, nháp v2
(chạy lại vẫn 1) → sửa nháp (thêm "Mua số lượng lớn") → gửi duyệt (admin là chủ → tự duyệt theo ma trận) → ban hành v2
→ 2 cờ `resolved`, đề xuất `published` → `POST /doc-learning/eval` ghi `eval_after` 1.0/0.727 → tra "mua số lượng lớn"
→ `[DOC:CUS-001 v2 §6]`. Cụm 3 câu có tên/SĐT/email → 1 nháp, **0/6** chuỗi cá nhân lọt vào nháp (đã bỏ qua + huỷ nháp).
MCP `company_doc_propose` POL-004 → nháp v2; lần 2 `conflict`.

**Sự cố trên VM, đã hoàn nguyên:** script thử `propose` gửi duyệt nháp POL-004 bằng tài khoản admin; admin là chủ nên
bản v2 (chứa đoạn thử "Giao hoả tốc 60.000đ") được **tự ban hành**. Đã ban hành v3 = nguyên văn v1
(`work/vm_m3e_revert.py`); script đã sửa để không gửi duyệt nữa. Đề xuất #3 vẫn ghi `published` trong lịch sử.

Tests `tests/test_m3e_doc_learning_loop.py` (5). Hai chỗ sửa test, có ghi lý do tại chỗ: phản hồi `submit` trả trạng thái
**tài liệu** (luôn "published" khi v1 đã ban hành) chứ không phải phiên bản; hai câu dữ liệu test có cùng bộ từ khoá nên
`record_gap` gộp đúng thành một dòng. Lỗi code thật tìm ra khi chạy test: `agent_propose` truyền id phiên bản vào
`diff` (nhận số phiên bản); cụm lỗ hổng không gom câu có tên/SĐT; regex tên không bắt "Chị" viết hoa.

## Dọn i18n (`f21a6c5`)

Backend trả **mã + tham số**, giao diện dịch; câu tiếng Việt cũ giữ cho Hộp việc / agent.
- Hồ sơ bắt buộc: `why_code` / `why_params` (`below_min_humans {humans, min}`, `entity_type`, `no_personal_data`,
  `other_industry`, `disabled`); dòng "Danh mục sản phẩm có giá" → `title_key`.
- Ghi chú nạp M3c: `note_code` / `note_params` ánh xạ theo mẫu câu — chạy cả các dòng đã nạp trước đó (VM: 0 dòng không mã).
- Điều khoản thuê agent: `terms_detail` (USD) → UI tự ghép "$0.05/task · actual model cost + 20% · cap $3.00/month".
- Tiền: `fmtMoney` / `fmtPrice` theo locale (vi "1.950.000 ₫", en "₫1,950,000") thay cho chuỗi `display` kiểu VN.
Tests `tests/test_m3n_i18n_codes.py` (3).

## Ngưỡng % đổi giá theo công ty (`28978cf`)

`company_profiles.price_change_high_pct` (NULL = mặc định 10). Đổi giá ≥ ngưỡng (tăng hoặc giảm) hoặc giá đầu tiên →
chủ duyệt; dưới ngưỡng → trưởng phòng. Chỉ quản trị công ty đổi (1..100, null = về mặc định), ghi sự kiện
`catalog.settings_changed`, không hồi tố đề xuất đang chờ. API `GET/PUT /api/team/catalog/settings`; UI **Sản phẩm & giá ›
Đổi ngưỡng**. Tests `tests/test_m3n_price_threshold.py` (2). VM: 0/101/"x" → 422; 15 → listing 15, công ty 1 vẫn 10;
đặt lại mặc định.

## Kiểm thử

- Backend: **1.337 passed, 2 skipped** (103 tệp, chạy theo lát song song 2; `test_wp37` tách theo node id vì cả tệp
  quá 112 s). Một test đỏ không liên quan: `test_v36_insights::test_local_today_follows_the_configured_timezone` giả định
  UTC+14 và UTC−12 luôn lệch 1 ngày — thật ra lệch 2 ngày khi UTC 10:00–12:00; sửa test (`53945dc`).
- `tsc --noEmit`: sạch. `next build`: chạy trong image web trên VM khi deploy `28978cf` — biên dịch + kiểm kiểu xong,
  70/70 trang tĩnh (`work/next_build_vm.log`); không chạy được trong sandbox (giới hạn 120 s).
- Ảnh `_reports/ui/m3n-*.png` (VM, 0 lỗi console, 390 px không tràn ngang): `m3n-learning(.png|-en|-mobile)`,
  `m3n-ingest(.png|-en|-mobile)`, `m3n-catalog(.png|-mobile)` (form ngưỡng mở), `m3n-records-en`, `m3n-docs-en`,
  `m3n-catalog-en`, `m3n-authority-en`, `m3n-leaseout-en`.

## Còn mở

1. **Chưa có lượt agent thật** cho: trích `[DOC:…]` + che trích dẫn với tin nhắn khách thật; agent tự gọi
   `company_doc_flag` / `company_doc_propose` trong lúc làm việc; vòng học với embedding thật (khi có embedding thật,
   vector vào lại RRF — cần đo lại eval). Tất cả cần CometAPI có hạn mức.
2. Top-1 Postgres 0.727: phần sai còn lại do tài liệu cũ trùng nội dung (DOC-2/DOC-4, SOP không chia mục). Nên lưu trữ
   tài liệu cũ đã có bản chính sách mới, hoặc chia mục SOP.
3. Nháp từ cụm lỗ hổng chỉ liệt kê câu hỏi — người phải viết câu trả lời (không có model). Cụm có thể gắn nhầm tài liệu
   (VM: cụm "khắc chữ lên ly" gắn vào SOP PRC-001 vì điểm ≥ 0.25) — người duyệt bỏ qua được.
4. "Tỉ lệ lỗ hổng / lượt tra" chưa đo (chưa đếm lượt tra theo kỳ).
5. Giao diện EN vẫn còn tiếng Việt ở: căn cứ pháp lý (tên văn bản luật VN), tên tài liệu/sản phẩm/câu hỏi (dữ liệu),
   tiêu đề + bằng chứng Approval / Hộp việc do backend ghép, `last_error` của nguồn đồng bộ, loại hình ("tnhh_1tv").
6. UI vẫn hiện mục menu cấp tổ chức cho người bị giới hạn công ty (bấm vào nhận 403 rõ ràng).
7. Dữ liệu VM sau kiểm chứng: CUS-001 v2 có mục "Mua số lượng lớn" (nội dung demo); POL-004 v3 = v1; 7 lỗ hổng mở là
   câu từ các lượt kiểm chứng trước.
8. Chưa push: `origin/ui-v2` vẫn ở `c5d51ff`.

## Anh cần làm

- **CometAPI: nạp hạn mức** (embedding + model) — để chạy lại eval với embedding thật và các lượt agent thật ở mục 1.
- **Google Drive:** tạo OAuth app (Client ID/Secret, redirect về ClawCompany) hoặc cho em tài khoản Drive để thử —
  hiện ô token chỉ nhận access token tạm, chưa tự làm mới.
- **Notion:** tạo integration, gửi **Internal Integration Token** và chia sẻ các trang cần đồng bộ cho integration đó.
- Quyết định có cho em push nhánh `ui-v2` không (cần PAT GitHub đọc được từ phiên này).
