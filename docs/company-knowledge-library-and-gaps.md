# Thư viện tài liệu & tri thức công ty + rà soát phần còn thiếu của module Công ty

Nghiên cứu ngày 16/10/2026, nhánh `ui-v2`. Chỉ đọc code, không sửa. Tiếp nối `company-anatomy-and-agent-company.md`,
`agent-knowledge-and-model-routing.md`, `m2b-company-foundation.md`, `m2c-company-operations.md`, `m2e-agent-native-company.md`,
`r-rental-and-multi-company.md`. Nguồn ở cuối, mục "Nguồn". Mọi điểm pháp lý là **lịch tham khảo, không phải tư vấn pháp lý**;
điểm nào chưa kiểm chứng trên trang chính thức/uy tín đều ghi "cần kiểm tra".

---

## 0. Tóm tắt một trang

**Anh nói đúng: module Công ty chưa có "tủ hồ sơ".** Hiện có một *kho tri thức để agent tra cứu* (`knowledge_documents` → cắt đoạn →
tìm kiếm có trích dẫn, 3 lớp cốt lõi biên dịch vào AGENTS.md) và bảng `sops`. Nhưng một tài liệu hiện chỉ là "văn bản thô + phạm vi":
không có **loại tài liệu**, **chủ sở hữu**, **phiên bản**, **trạng thái duyệt**, **ngày hiệu lực / ngày rà soát**, **mức nhạy cảm**,
**thời hạn lưu trữ**, không giữ **tệp gốc**, không biết tài liệu nào **bắt buộc theo luật** mà công ty còn thiếu. Agent đang đọc cả
bản nháp lẫn bản đã cũ như nhau.

**Năm phát hiện chính cho thư viện:**

1. **Tách "hồ sơ" (record) và "tài liệu" (document) như ISO 9001 §7.5** — tài liệu có phiên bản, được duyệt, có hiệu lực và bị thay thế;
   hồ sơ là bằng chứng tại một thời điểm, không sửa, chỉ lưu đủ hạn rồi huỷ. Cùng một bảng, khác vòng đời.
2. **Agent chỉ được đọc bản "đã ban hành và đang hiệu lực"**; mỗi tài liệu khai báo *cách agent dùng*: cốt lõi (luôn trong AGENTS.md),
   tra cứu (RAG có trích dẫn mã tài liệu + phiên bản + mục), chỉ qua tool (số liệu có cấu trúc: giá, tồn kho, khách — không bao giờ cắt đoạn),
   hoặc không cho agent. Đo trên VM 15/10: agent không tự tra khi khách hỏi chính sách → phần cốt lõi phải là **bản tóm tắt theo chức danh**
   sinh từ tài liệu đã ban hành.
3. **Độ tươi là dữ liệu, không phải hy vọng**: chủ sở hữu + chu kỳ rà soát (mẫu Guru: người xác minh + khoảng xác minh), quá hạn rà soát →
   gắn nhãn "cần rà soát" + Hộp việc cho chủ; KCS "flag it or fix it": agent được *đánh dấu* tài liệu sai khi dùng, lỗ hổng gom thành "tài
   liệu cần viết".
4. **Luật VN cho sẵn khung "hồ sơ bắt buộc" và thời hạn lưu** — Điều 11 Luật DN 2020 (+ điểm h danh sách chủ sở hữu hưởng lợi từ 1/7/2025),
   Điều 41 Luật Kế toán + Điều 12–14 NĐ 174/2016 (5 năm / 10 năm / vĩnh viễn), nội quy lao động (Điều 118–121 BLLĐ 2019), Luật Bảo vệ dữ
   liệu cá nhân 91/2025/QH15 + NĐ 356/2025 (hiệu lực 1/1/2026, **NĐ 13/2023 hết hiệu lực**). Biến thành **danh mục yêu cầu là dữ liệu sửa
   được, có căn cứ** (giống `compliance_rules`), cấp "sẵn sàng" chấm theo đó.
5. **Truy hồi phải lọc quyền *trước* khi model thấy** (security trimming), và nâng chất lượng bằng cắt theo đề mục + tiêu đề ngữ cảnh +
   lai BM25/embedding (Anthropic: giảm 49% truy hồi hỏng, 67% khi thêm rerank). Code hiện chấm điểm trong Python trên tối đa 20.000 đoạn
   — chạy được cho kho nhỏ, không mở rộng được.

**Thiếu khác (mục B), ưu tiên P0:** thư viện tài liệu + hồ sơ bắt buộc; **danh mục sản phẩm/dịch vụ & bảng giá** (agent bán hàng/CSKH đang
không có nguồn giá có cấu trúc); lọc phạm vi công ty ở các route cũ (điều kiện trước R3/R4). P1: khách hàng/CRM + đồng ý dữ liệu cá nhân,
hợp đồng & đối tác, họp & quyết định, tài chính kinh doanh, rủi ro & kiểm soát, thông báo nội bộ có xác nhận đã đọc, hội nhập nhân sự người,
báo cáo chủ/HĐQT + gói bằng chứng kiểm toán. P2: tài sản/kho, khiếu nại khách & không phù hợp, hoá đơn điện tử, kênh bán.

**Thứ tự đề xuất:** M3a Thư viện lõi → M3b Tài liệu thành tri thức agent → M3c Nạp & phân loại → M3d Hồ sơ bắt buộc & lưu trữ → M3e Vòng học
→ M3f Sản phẩm & giá → M3g Khách hàng & DLCN → M3h Hợp đồng & đối tác → M3i Họp & quyết định → M3j Tài chính → M3k Rủi ro → M3l Thông báo →
M3m Hội nhập người → M3n Báo cáo chủ & kiểm toán. Chi tiết + tiêu chí nghiệm thu ở mục C.

---

## 1. Hiện trạng trong code (đã đọc)

| Thứ | Ở đâu | Có gì | Thiếu gì cho "tủ hồ sơ" |
|---|---|---|---|
| Tài liệu tri thức | `models/entities.py::KnowledgeDocument` (`knowledge_documents`) | org/company/department/project/agent scope, `title`, `source_type` (text/upload/url), `content` (text đã trích), `content_hash` (khoá trùng), `source_url`, `synced_at`, `is_core`, `role_keyword` (lớp nghề), `access_level` (**không nơi nào đọc**), `indexed` | loại tài liệu, chủ sở hữu, phiên bản + lịch sử, trạng thái duyệt, hiệu lực/rà soát/hết hạn, nhạy cảm, lưu trữ, tệp gốc, liên kết tới quy trình/chức danh |
| Cắt đoạn + chỉ mục | `services/knowledge_hub.py` (`chunk_text` 1.000 ký tự chồng 150; `reindex`) + `knowledge_chunks` + `knowledge_vectors` (JSON) | embedding thật nếu có key CometAPI, nếu không thì vector băm 384 chiều | cắt theo đề mục, tiêu đề ngữ cảnh, BM25/FTS, pgvector thật (vector đang nằm trong JSON, cosine tính ở Python) |
| Tra cứu | `knowledge_hub.search` + MCP `company_knowledge_search`, `company_knowledge_get` | điểm lai từ khoá + cosine, `visible_docs_query` lọc phạm vi (công ty/phòng/dự án/agent, R2 thêm tài liệu được cấp qua hợp đồng thuê), trích dẫn `[KB#id§n: tiêu đề]`, ghi lỗ hổng khi điểm < 0.34 | lọc theo trạng thái/hiệu lực, theo nhạy cảm, theo chức danh (chỉ có `role_keyword` khớp chữ), xếp hạng theo độ tươi, rerank; người (member=None) thấy cả tổ chức |
| Cốt lõi 3 lớp | `knowledge_hub.core_section` (12.000 ký tự: riêng 3.000 / nghề 4.500 / công ty 4.500) + `company_foundation.charter_block` đứng đầu | biên dịch vào "## Kiến thức cốt lõi" của AGENTS.md, `sync_core` chạy nền | cắt cứng theo ngân sách ký tự (tài liệu sau bị cụt thành link); chưa có bản tóm tắt theo chức danh; không biết tài liệu nào đã hết hiệu lực |
| Đồng bộ nguồn | `fetch_url` + `resync` (URL), `mark_courses_stale` | URL đổi nội dung → khoá học "cần ôn" | Google Drive, Notion, OCR (PDF scan trả chuỗi rỗng qua `pypdf`), XLSX/PPTX/ảnh |
| Lỗ hổng, khoá học, bài học | `models/learning.py` (`knowledge_gaps`, `courses`, `course_enrollments`), `services/lessons.py` (bài học → Hộp việc → MEMORY.md) | gap log có đếm lặp, khoá học có quiz + lịch, bài học có duyệt | gap không gom cụm/không sinh nháp tài liệu; bài học không đi ngược về tài liệu nguồn |
| SOP | `models/extended.py::SOP` (`sops`, có `company_id` từ 0047) + MCP `company_sop_get` + `process_steps.sop_id` | tiêu đề, `version` (chuỗi), chủ, nội dung, `status` (draft…), `compliance_score` | không có lịch sử phiên bản, không duyệt, không vào kho tra cứu chung; hai nơi chứa tri thức (KB và SOP) |
| Không gian tri thức chia sẻ | `knowledge_mesh` + `shared_knowledge_*` (v16) | phân quyền none/read/contribute/admin theo công ty/phòng/nhóm/người, nhật ký truy cập | là kho thứ ba song song; quyền ở đây chưa áp vào `knowledge_documents` |
| Sẵn sàng agent | `agent_readiness.py` lớp "Tri thức" 15% | 2 kiểm tra: có tài liệu cốt lõi; bước quy trình có SOP | không kiểm hồ sơ bắt buộc, không kiểm độ tươi |
| Thuê ghế | `seat_leases.knowledge_doc_ids` → `visible_docs_query`, `layered_core` | bên thuê thấy đúng tài liệu được cấp, mất khi hợp đồng hết | chưa có cờ "được chia sẻ/xuất" trên tài liệu, chưa có mẫu tài liệu cho R3 |
| Quyết định | `decisions` + MCP `company_decision_log` | tiêu đề, bối cảnh, phương án, khuyến nghị, chủ, trạng thái, tác động | biên bản họp, người dự, nghị quyết, việc giao sau họp |

Kết luận: nền **truy hồi** đủ dùng cho kho nhỏ; phần **quản trị tài liệu** (ISO 7.5) gần như chưa có. Nên **mở rộng `knowledge_documents`
thành sổ tài liệu chuẩn** (một bản ghi chuẩn cho mỗi tài liệu), không dựng kho thứ tư; SOP và không gian chia sẻ dần trỏ về đây.

---

## A. Thiết kế thư viện tài liệu & tri thức công ty

### A1. Nguyên tắc rút từ nghiên cứu

| Nguồn | Điều lấy về | Áp vào ClawCompany |
|---|---|---|
| ISO 9001:2015 §7.5 (hướng dẫn ISO/TC176) | Tài liệu tạo/cập nhật phải có nhận diện (tiêu đề, ngày, tác giả, mã), định dạng, **xem xét và phê duyệt**; kiểm soát: phân phối & truy cập, lưu giữ & bảo quản (đọc được), **kiểm soát thay đổi (phiên bản)**, **lưu trữ & huỷ**; tài liệu bên ngoài cần cho vận hành cũng phải nhận diện và kiểm soát; hồ sơ làm bằng chứng phải được bảo vệ khỏi sửa đổi ngoài ý muốn. ISO nhấn mạnh "hệ thống quản lý có tài liệu", không phải "hệ thống giấy tờ" — phân tích quy trình quyết định cần bao nhiêu tài liệu. | Mỗi tài liệu có mã + phiên bản + người duyệt; bản ghi phiên bản **bất biến**; tài liệu ngoài (luật, hợp đồng đối tác, giấy phép) là loại riêng; **hồ sơ** khoá sửa sau khi lưu; danh mục bắt buộc bắt nguồn từ quy trình (D4) chứ không phải danh sách dài vô ích. |
| KCS v6 (Consortium for Service Innovation) | Vòng Giải quyết: *capture* trong luồng việc, *structure* theo khuôn đơn giản (Vấn đề – Môi trường – Cách giải quyết – Nguyên nhân), *reuse is review*, *flag it or fix it*; vòng Tiến hoá: sức khoẻ nội dung, trạng thái bài (độ tin cậy, đối tượng, quản trị), lưu trữ bài cũ, phân tích miền tri thức để viết bài giá trị cao từ mẫu tái dùng. Bài chỉ chứa phần dùng lại được, **không chứa thông tin riêng của khách**; có trường "giải pháp nội bộ" ẩn với đối tượng ngoài. | Mẫu "bài FAQ/xử lý" cho CSKH; agent đánh dấu/đề xuất sửa khi dùng; đếm tái dùng từng tài liệu; gom lỗ hổng thành bài mới; nội dung gửi khách tách khỏi phần nội bộ. |
| Guru (verification) | Mỗi thẻ có **người xác minh + khoảng xác minh** (mặc định 1 tháng), trạng thái Đã xác minh / Chưa xác minh / Chưa xét; hết hạn → vào hàng việc của người xác minh; tác tử AI có thể cấu hình **chỉ dùng nguồn đã xác minh**; tự lưu trữ thẻ chưa xác minh 6 tháng mà không ai xem. | Trường `review_interval_days`, `reviewer`, trạng thái độ tươi; beat nhắc rà soát vào Hộp việc; chính sách truy hồi theo độ tươi; đề xuất lưu trữ tài liệu chết. |
| Anthropic — Contextual Retrieval (19/9/2024) | Kho < ~200.000 token có thể đưa thẳng vào prompt (kèm prompt caching); lớn hơn thì RAG: cắt vài trăm token, **lai embedding + BM25**, thêm ngữ cảnh cho từng đoạn trước khi nhúng/đánh chỉ mục: giảm 35% (embedding), 49% (+BM25), 67% (+rerank) tỷ lệ truy hồi hỏng top-20. | Giữ "cốt lõi trong ngữ cảnh" cho kho nhỏ (đúng hướng hiện tại); đoạn mang tiêu đề ngữ cảnh *xác định* (tên tài liệu › đề mục › loại › ngày hiệu lực) — rẻ, không cần model; thêm FTS Postgres + pgvector; rerank T1 chỉ khi eval cho thấy cần. |
| Azure AI Search — security trimming | Lưu danh tính/nhóm được phép trên mỗi tài liệu lúc đánh chỉ mục, **lọc ở truy vấn** để chỉ trả tài liệu người gọi được xem; quan trọng cho RAG/agent. | `visible_docs_query` mở rộng: lọc trạng thái, hiệu lực, nhạy cảm, đối tượng (chức danh/phòng), hợp đồng thuê — **trước** khi chấm điểm, không lọc sau khi model đã thấy. |
| Notion/Confluence (cấu trúc wiki thông dụng) | Không gian theo nhóm (Công ty / Phòng / Dự án), trang chủ "Bắt đầu ở đây", sổ tay nhân viên, chính sách, quy trình, mẫu biểu; nhãn xác minh có hạn. *(Đây là quan sát thực hành phổ biến; không lấy số liệu từ đó.)* | Cây hiển thị theo **loại tài liệu × phòng**, không bắt người dùng tự dựng thư mục. |

### A2. Khung pháp lý Việt Nam phải phản ánh (đã kiểm chứng)

| Chủ đề | Quy định | Ý nghĩa cho thư viện |
|---|---|---|
| Tài liệu doanh nghiệp phải lưu giữ | **Điều 11 Luật DN 59/2020/QH14**: tuỳ loại hình phải lưu (a) điều lệ, quy chế quản lý nội bộ, sổ đăng ký thành viên/cổ đông; (b) văn bằng bảo hộ SHCN, giấy chứng nhận đăng ký chất lượng, **giấy phép và giấy chứng nhận khác**; (c) giấy tờ sở hữu tài sản; (d) phiếu biểu quyết, biên bản kiểm phiếu, **biên bản họp** HĐTV/ĐHĐCĐ/HĐQT, các quyết định; (đ) bản cáo bạch; (e) báo cáo BKS, kết luận thanh tra, kết luận kiểm toán; (g) sổ kế toán, chứng từ, BCTC năm. Lưu tại trụ sở hoặc nơi điều lệ quy định; **thời hạn theo pháp luật**. | Bộ "hồ sơ pháp lý" lõi cho mọi công ty; lớp "Hồ sơ" trong chấm sẵn sàng. |
| Chủ sở hữu hưởng lợi | **Luật 76/2025/QH15** (thông qua 17/6/2025, hiệu lực **1/7/2025**) sửa Luật DN: thêm khoản 5a Điều 8 (thu thập, cập nhật, lưu giữ thông tin chủ sở hữu hưởng lợi, cung cấp khi được yêu cầu) và **điểm h khoản 1 Điều 11: Danh sách chủ sở hữu hưởng lợi (nếu có)**; lưu thông tin ít nhất 05 năm kể từ ngày giải thể/phá sản; DN thành lập trước 1/7/2025 bổ sung khi đăng ký/thông báo thay đổi gần nhất. | Thêm loại hồ sơ "Danh sách chủ sở hữu hưởng lợi" (nhạy cảm: dữ liệu cá nhân); trường trong hồ sơ pháp nhân M2b. |
| Lưu trữ tài liệu kế toán | **Điều 41 Luật Kế toán 88/2015/QH13** (VBHN 25/VBHN-VPQH ngày 26/2/2025, đã sửa bởi Luật 38/2019 và Luật 56/2024): đưa vào lưu trữ **trong 12 tháng** kể từ kết thúc kỳ kế toán năm; người đại diện theo pháp luật chịu trách nhiệm; tối thiểu **5 năm** (tài liệu dùng cho quản lý, chứng từ không dùng trực tiếp ghi sổ), **10 năm** (chứng từ dùng ghi sổ, sổ kế toán, BCTC năm), **vĩnh viễn** (có tính sử liệu). **NĐ 174/2016/NĐ-CP Điều 12–15** liệt kê chi tiết (vd. phiếu thu/chi/nhập/xuất kho không lưu trong tập kế toán: 5 năm; tài liệu thanh lý TSCĐ, kiểm kê, thành lập/chia tách/giải thể, hồ sơ kiểm toán/thanh tra: 10 năm); mốc tính hạn = ngày kết thúc kỳ kế toán năm (trừ trường hợp riêng). | Lớp lưu trữ `acct_5y / acct_10y / permanent` tính `retain_until` tự động; cấm xoá trước hạn. |
| Nội quy lao động | **Điều 118 BLLĐ 45/2019/QH14**: mọi NSDLĐ phải ban hành nội quy; **từ 10 NLĐ trở lên phải bằng văn bản**; phải tham khảo tổ chức đại diện NLĐ (nếu có). **Điều 119**: từ 10 NLĐ phải **đăng ký** tại cơ quan chuyên môn về lao động cấp tỉnh, nộp hồ sơ trong **10 ngày** kể từ ngày ban hành. **Điều 121**: hiệu lực sau **15 ngày** kể từ khi cơ quan nhận đủ hồ sơ; dưới 10 NLĐ ban hành bằng văn bản thì tự quyết hiệu lực. Dưới 10 NLĐ không bắt buộc văn bản nhưng phải thoả thuận kỷ luật, trách nhiệm vật chất trong HĐLĐ (khoản 1 Điều 69 NĐ 145/2020). | Yêu cầu có điều kiện theo số NLĐ (đếm ghế **người**, không đếm agent); vòng đời có bước "đăng ký" và `effective_from` = ngày nhận hồ sơ + 15. |
| Lưu trữ | **Luật Lưu trữ 33/2024/QH15** (ban hành 21/6/2024, hiệu lực **1/7/2025**; NĐ 113/2025 hướng dẫn, hiệu lực 21/7/2025): **tài liệu lưu trữ số có đầy đủ giá trị pháp lý như thông điệp dữ liệu** (khoản 3 Điều 7); quy định tài liệu tạo lập dạng số, bản số hoá, kho lưu trữ số; tổ chức không phải cơ quan nhà nước thuộc "lưu trữ tư" (khoản 14 Điều 2). | Thư viện số là nơi lưu chính thức được (kèm tệp gốc + hash + nhật ký); phần nghiệp vụ nộp lưu lịch sử chủ yếu cho khu vực nhà nước — không mô phỏng. |
| Dữ liệu cá nhân | **Luật Bảo vệ dữ liệu cá nhân 91/2025/QH15** (thông qua 26/6/2025, **hiệu lực 1/1/2026**, 5 chương 39 điều) + **NĐ 356/2025/NĐ-CP** (31/12/2025, hiệu lực 1/1/2026, **thay NĐ 13/2023** — NĐ 13 hết hiệu lực từ 1/1/2026). Điểm chính: im lặng không phải đồng ý; quyền rút đồng ý, xoá, huỷ, khử nhận dạng; **ứng viên không trúng tuyển phải bị xoá/huỷ dữ liệu**; **NSDLĐ xoá/huỷ dữ liệu NLĐ khi chấm dứt hợp đồng** (theo tóm tắt của LuatVietnam; ngoại lệ khi luật khác buộc giữ — *cần kiểm tra điều khoản cụ thể*); thông báo khi lộ lọt; NĐ 356 quy định thủ tục **đánh giá tác động xử lý DLCN**, chuyển xuyên biên giới, **nhân sự/bộ phận bảo vệ DLCN**, lưu và chứng minh sự đồng ý, **DLCN trong hệ thống AI**. | Nhãn nhạy cảm `personal_data` / `sensitive_personal_data`; tài liệu chứa DLCN **không vào RAG**; lớp lưu trữ "xoá khi hết mục đích"; bộ hồ sơ DLCN (chính sách, hồ sơ đánh giá tác động, nhật ký đồng ý) vào danh mục bắt buộc — ngưỡng áp dụng cho DN nhỏ **cần kiểm tra** trong NĐ 356. |

Chưa kiểm chứng trong đợt này (để `needs_review=true` khi gieo): bắt buộc **thang lương, bảng lương** (BLLĐ Điều 93), **quy chế dân chủ ở
cơ sở**, **thoả ước lao động tập thể** (chỉ khi có thương lượng), chính sách đổi trả/bảo mật cho **website TMĐT** (NĐ 52/2013, 85/2021),
giấy chứng nhận **ATTP** (F&B), **quy chế tài chính** (không thấy là bắt buộc với DN tư nhân trong nguồn đã đọc), thời hạn lưu **HĐLĐ / hồ sơ
BHXH** cho doanh nghiệp.

### A3. Phân loại tài liệu (taxonomy)

Mỗi tài liệu có `doc_class` (**document** — có phiên bản, áp dụng; **record** — bằng chứng, khoá sửa) và `doc_type`:

| Nhóm | `doc_type` (ví dụ) | Lớp | Mặc định agent dùng | Lưu trữ mặc định |
|---|---|---|---|---|
| Pháp lý | `legal_registration` (GCN ĐKDN), `charter_legal` (Điều lệ), `member_register` (sổ thành viên/cổ đông), `beneficial_owners`, `license` (giấy phép con, có `expires_at`), `ip_certificate`, `asset_title` | record | `none` (agent thấy siêu dữ liệu: số, ngày, hạn) | suốt đời DN (chính sách công ty — luật chỉ nói "theo pháp luật") ; chủ sở hữu hưởng lợi ≥ 5 năm sau giải thể |
| Quản trị | `internal_regulation` (quy chế quản lý nội bộ), `meeting_minutes`, `resolution`/`decision`, `authority_policy` (văn bản ma trận phân quyền), `board_report`, `audit_conclusion` | document / record | `retrieve` cho quy chế; `none` cho biên bản | suốt đời DN |
| Chiến lược | `strategy_plan`, `okr_plan`, `budget_plan` | document | `core` bản tóm tắt cho trưởng phòng | 10 năm |
| Chính sách | `policy` (đổi trả, bảo hành, bảo mật, chống hối lộ, sử dụng AI, DLCN…), `privacy_notice` | document | `core` (tóm tắt theo chức danh) + `retrieve` | thay thế → giữ bản cũ 10 năm |
| Sổ tay & nội quy | `handbook`, `labor_rules` (nội quy, có bước đăng ký), `code_of_conduct`, `collective_agreement` | document | `retrieve` (agent HR/CSKH nội bộ) | như trên |
| Quy trình | `sop`, `work_instruction`, `checklist` (gắn `process_steps`) | document | `retrieve`; tóm tắt bước vào AGENTS.md của chức danh làm bước đó | như trên |
| Sản phẩm & giá | `product_sheet`, `price_list`, `service_catalog`, `promo` | document — **nguồn thật là bảng có cấu trúc (M3f)** | `tool_only` cho giá/tồn; `retrieve` cho mô tả | 5 năm |
| Thương hiệu | `brand_guide`, `tone_guide`, `content_template` | document | `core` (giọng) + `retrieve` | thay thế |
| Khách hàng | `faq`, `kcs_article` (Vấn đề–Môi trường–Giải pháp–Nguyên nhân, có phần nội bộ), `canned_reply` | document | `retrieve` (bản cho khách vs nội bộ) | lưu trữ khi hết dùng |
| Hợp đồng & đối tác | `contract`, `nda`, `partner_terms`, `supplier_profile` | record (bản ký) + siêu dữ liệu có cấu trúc (M3h) | `none` nội dung; `tool_only` điều khoản chính (hạn, giá trị, SLA) | 10 năm sau hết hạn (đề xuất; *cần kiểm tra*) |
| Nhân sự | `employment_contract`, `hr_file`, `job_description` (đồng bộ từ `positions`) | record, `personal_data` | `none` (trừ JD) | xoá khi hết mục đích (Luật 91/2025) trừ khi luật khác buộc giữ |
| Tài chính – kế toán | `accounting_voucher`, `ledger`, `financial_statement`, `tax_filing`, `invoice` | record | `none` / `tool_only` số tổng | 5 / 10 năm / vĩnh viễn theo NĐ 174 |
| Mẫu biểu | `template` (mẫu đơn, mẫu hợp đồng, mẫu báo giá — có placeholder) | document | `tool_only` (agent điền mẫu) | thay thế |
| Bên ngoài | `external_law`, `external_standard`, `platform_policy` (chính sách sàn) | document (`source=external`) | `retrieve`, kèm ngày kiểm tra cuối | theo nguồn |
| Học hỏi | `lesson`, `postmortem`, `decision_record` (ADR) | record | `retrieve` | 5 năm |

Không bắt người dùng hiểu hết danh sách: giao diện nhóm 8 ngăn (Pháp lý & quản trị · Chính sách & sổ tay · Quy trình & mẫu · Sản phẩm & thương
hiệu · Khách hàng · Hợp đồng & đối tác · Nhân sự · Tài chính), loại chi tiết do hệ thống đoán khi nạp (A7).

### A4. Siêu dữ liệu (mở rộng `knowledge_documents`)

```
-- định danh
doc_code         'CS-POL-003'  (tiền tố phòng + loại + số; duy nhất trong công ty)
doc_class        document | record
doc_type         (A3)
company_id       BẮT BUỘC cho tài liệu mới (bỏ NULL = cả tổ chức, trừ tài liệu nền tảng của chủ tổ chức)
-- trách nhiệm
owner_position_id  chức danh chịu trách nhiệm (sống sót khi người nghỉ) ; owner_member_id (tuỳ chọn)
reviewer_kind/…    người rà soát mặc định = chủ; người duyệt lấy từ ma trận phân quyền (action 'doc_publish')
-- đối tượng & quyền
audience         {company: true} | {department_ids:[…]} | {position_ids:[…]} | {seat_ids:[…]}   (thay role_keyword)
sensitivity      public | internal | confidential | restricted | personal_data | sensitive_personal_data
agent_use        core | retrieve | tool_only | none
customer_facing  bool  (được trích nguyên văn cho khách)
lease_shareable / exportable  bool (A9)
-- vòng đời
status           draft | in_review | approved | published | superseded | archived | disposed
version_no       số nguyên tăng ; current_version_id
effective_from / effective_to ; review_interval_days ; review_due_at ; last_reviewed_at/by
supersedes_id
-- nguồn & lưu
source_type      upload | text | url | gdrive | notion | generated | structured
source_of_truth  internal | external_link | structured_table:<tên>
file_artifact_id tệp gốc (PDF/DOCX/ảnh) + mime + sha256
retention_class  (A3) ; retain_until ; legal_hold bool ; disposal_approved_by
-- đo
reuse_count, cited_count, flag_count, last_used_at
```

Bảng mới: `knowledge_document_versions` (bất biến: version_no, content, content_hash, file_artifact_id, change_note, author, approved_by,
approved_at, approval_id), `document_links` (tài liệu ↔ `process`/`process_step`/`position`/`sop`/`io_contract`/`company_rule`/
`compliance_rule`/`contract`), `document_flags` (agent/người đánh dấu: sai, cũ, mâu thuẫn, thiếu; kèm task/run), `document_requirements`
(A8), `company_facts` (A6).

### A5. Vòng đời & duyệt

```
draft ──gửi duyệt──▶ in_review ──duyệt (ma trận 'doc_publish')──▶ approved ──tới effective_from──▶ published
   ▲                     │ trả về                                                          │
   └─────────────────────┘                                    bản mới published ──▶ superseded (bản cũ)
published ──hết hiệu lực/thu hồi──▶ archived ──hết retain_until + duyệt huỷ──▶ disposed (chỉ giữ siêu dữ liệu + hash)
```

- **Duyệt dùng ma trận phân quyền M2b**, thêm loại việc `doc_publish` (rủi ro theo `sensitivity` và `doc_type`: chính sách gửi khách, nội quy,
  quy chế → chủ; SOP phòng → trưởng phòng). Người duyệt luôn là người (đúng luật M2b). Approval → Hộp việc, ghi `approval_id` vào phiên bản.
- **Hồ sơ (record)** không có draft/review: lưu là khoá; sửa = tạo hồ sơ mới liên kết `supersedes_id` (đúng ISO "bảo vệ khỏi sửa đổi ngoài ý
  muốn").
- **Bước riêng theo loại**: `labor_rules` có mốc "đã nộp đăng ký" → `effective_from` = ngày nhận + 15 ngày (Điều 121); `license` có `expires_at`
  → sinh `compliance_deadlines` (M2c D7) nhắc trước N ngày.
- **Nhắc rà soát**: beat `docs.tick` (mỗi giờ, như `compliance.tick`): `review_due_at` tới → Hộp việc `doc_review_due` cho chủ (người ngồi chức
  danh chủ, agent → người quản lý gần nhất); quá hạn 30 ngày → nhãn "cần rà soát" hiện cho agent; `effective_to` qua → tự `archived` và biên dịch lại
  AGENTS.md. Mặc định khoảng rà soát: chính sách 180 ngày, SOP 90, FAQ 60, giá 30, pháp lý theo hạn giấy phép.
- **Thông báo khi ban hành**: phiên bản mới của tài liệu `core`/`retrieve` → `knowledge_hub.sync_core` cho ghế liên quan, khoá học dùng tài liệu
  → "cần ôn" (đã có `mark_courses_stale`), ghế người → thông báo có xác nhận đã đọc (M3l).
- **SOP**: giữ bảng `sops` (đang được `process_steps.sop_id` dùng) nhưng thêm `sops.document_id`; nội dung + phiên bản sống ở thư viện; `company_sop_get`
  đọc bản published. Hợp nhất hẳn ở bước sau khi UI cũ bỏ.

### A6. Tài liệu trở thành tri thức agent

**Bốn mức dùng (`agent_use`)** — quyết định một lần trên tài liệu, không để model tự đoán:

| Mức | Vào đâu | Dành cho | Quy tắc |
|---|---|---|---|
| `core` | AGENTS.md "## Kiến thức cốt lõi" | hiến chương, giọng thương hiệu, chính sách gửi khách, điều cấm | biên dịch **bản tóm tắt theo chức danh** (`core_summary`, ≤ 600 ký tự/tài liệu, người duyệt cùng lúc với tài liệu) thay vì cắt cứng nội dung; kèm mã `[CS-POL-003 v4]` và "chi tiết: company_doc_get" |
| `retrieve` | RAG qua `company_knowledge_search` | sổ tay, SOP chi tiết, FAQ/KCS, quy chế, luật bên ngoài | chỉ phiên bản `published` đang hiệu lực, đúng đối tượng, đúng nhạy cảm; trích dẫn **mã + phiên bản + mục** |
| `tool_only` | MCP có cấu trúc (`company_product_lookup`, `company_contract_get`, `company_template_fill`, `company_fact_get`) | giá, tồn kho, điều khoản hợp đồng, mẫu biểu, số liệu công ty | **không cắt đoạn**; số liệu đọc từ bảng → không bịa giá |
| `none` | chỉ siêu dữ liệu | hồ sơ pháp lý scan, HĐLĐ, chứng từ, dữ liệu cá nhân | agent biết "có GCN ĐKDN số …, cấp ngày …, hạn …" nhưng không đọc nội dung |

**Lọc trước khi chấm** (`visible_docs_query` mới): công ty của ghế (+ tài liệu được cấp qua hợp đồng thuê) → `status=published` và
`effective_from ≤ now < effective_to` → đối tượng (phòng/chức danh/ghế) → `sensitivity` ≤ trần của ghế (mặc định agent: `internal`; ghế
có chức danh HR/kế toán được nâng có duyệt) → `agent_use ∈ {core, retrieve}`. Người dùng UI thấy theo vai trò công ty (R1) + nhạy cảm.

**Truy hồi tốt hơn** (giữ API cũ):
- Cắt theo đề mục Markdown/DOCX (đã giữ `##` khi trích) rồi mới theo độ dài; mỗi đoạn mang **tiêu đề ngữ cảnh xác định**
  `"[CS-POL-003 v4 · Chính sách đổi trả › 2. Điều kiện · hiệu lực 01/09/2026]"` đưa vào cả embedding lẫn chỉ mục từ khoá (cách rẻ của
  Contextual Retrieval, không tốn model).
- Postgres: `tsvector` (FTS, cấu hình `simple` + bỏ dấu song song để bắt cả gõ không dấu) + `pgvector` thay vector JSON; hợp nhất bằng
  reciprocal rank fusion; SQLite dev giữ đường Python hiện tại.
- Xếp hạng có độ tươi: tài liệu "cần rà soát" bị trừ điểm và kết quả trả kèm `stale: true` để agent nói "theo tài liệu (đang chờ rà soát)".
- Rerank T1 chỉ bật khi bộ eval CSKH cho thấy lợi (đo, không đoán).

**Trích dẫn**: định dạng mới `[DOC:CS-POL-003 v4 §2]` (giữ đọc được `[KB#…]` cũ). Trích dẫn ghi vào `task_journal` của lượt chạy và
`reuse_count`; **tin gửi khách không lộ mã nội bộ** — guard plugin (M2e.2) thêm luật `phrase` chặn mẫu `[DOC:` ở `message_sending` khi `external_only`.

**Phát hiện mâu thuẫn**:
1. `company_facts` (khoá–giá trị có nguồn): `refund_window_days=7 ← CS-POL-003 v4 §2`, `hotline`, `warranty_months`, `shipping_fee_threshold`…
   Khi nạp/ban hành, T1 trích ứng viên sự kiện → so với sự kiện đang có và với **bảng có cấu trúc** (hồ sơ pháp nhân M2b, ma trận phân quyền,
   giá M3f) → khác nhau thì chặn ban hành mềm: cảnh báo + Hộp việc cho hai chủ tài liệu.
2. Lúc ban hành, tìm tài liệu `published` cùng `doc_type` + chủ đề gần (cosine cao) → gợi ý "thay thế bản này?" để tránh hai chính sách song song.
3. Hiến chương "điều cấm" vs nội dung tài liệu `customer_facing` → kiểm bằng luật cứng sẵn có (`company_rules/test`) trước khi duyệt.

### A7. Nạp tài liệu (ingestion)

| Nguồn | Hiện có | Cần thêm |
|---|---|---|
| Tải lên | PDF (pypdf), DOCX, TXT/MD/CSV/HTML/JSON | lưu **tệp gốc** vào artifact store + sha256; XLSX (openpyxl → bảng Markdown), PPTX; **OCR** cho PDF scan/ảnh (Tesseract `vie` trên worker, hoặc model thị giác T2 khi Tesseract kém — đo trên mẫu GCN ĐKDN thật); phát hiện "PDF không có lớp chữ" thay vì nạp chuỗi rỗng |
| URL | `fetch_url` + `resync` | lịch đồng bộ (`sync_cron`), ghi `last_checked_at` cho tài liệu bên ngoài (luật, chính sách sàn) |
| Google Drive | chưa | OAuth theo công ty, chọn thư mục, xuất Google Docs → DOCX/Markdown, theo dõi thay đổi bằng change token, giữ quyền nguồn làm gợi ý `audience` |
| Notion | chưa | token tích hợp, trang → Markdown, đồng bộ theo `last_edited_time` |
| Biểu mẫu trong app | chưa | soạn trực tiếp bằng trình soạn Markdown có khuôn theo `doc_type` (KCS: Vấn đề/Môi trường/Giải pháp/Nguyên nhân + phần nội bộ) |

**Tự phân loại khi nạp** (T1, ~$0.0001/tài liệu, người xác nhận): `doc_type`, phòng/đối tượng gợi ý, `sensitivity` (kết hợp regex PII của
`company_rules` — có CCCD/SĐT/email hàng loạt → `personal_data` và `agent_use=none`), ngày hiệu lực/hết hạn đọc được trong văn bản, `doc_code`
đề xuất. Tất cả là **đề xuất** — tài liệu vào `draft`.

**Trích sự kiện vào dữ liệu công ty** (đề xuất qua Hộp việc, không ghi thẳng): GCN ĐKDN → tên pháp nhân, MST, ngày thành lập, người đại diện,
vốn, ngành nghề của `company_profiles` (M2b); điều lệ → loại hình, cơ quan quản trị; chính sách → `company_facts`; bảng giá → sản phẩm M3f;
giấy phép → `compliance_rules` "giấy phép/hạn riêng" với `expires_at`; nội quy → giờ làm mặc định của `seat_schedules`.

### A8. Phát hiện thiếu hồ sơ (readiness)

`document_requirements` là **dữ liệu sửa được theo công ty**, gieo mặc định giống `compliance_rules`: `key`, tên, `doc_type`, điều kiện áp dụng
(loại hình, số NLĐ người, có xử lý DLCN khách, ngành/gói mẫu), mức (`required | recommended`), **căn cứ pháp lý**, `needs_review`.

| Gói | Yêu cầu (mức · căn cứ) |
|---|---|
| Mọi doanh nghiệp | GCN ĐKDN (required · Luật DN) · Điều lệ — công ty TNHH/CP/hợp danh (required · Đ11a) · Sổ đăng ký thành viên/cổ đông (required · Đ11a) · Danh sách chủ sở hữu hưởng lợi nếu có (required · Đ11h, Luật 76/2025) · Biên bản họp & quyết định (required · Đ11d) · Giấy phép con theo ngành (required nếu ngành có điều kiện · Đ11b — danh sách ngành *cần kiểm tra*) · Sổ, chứng từ, BCTC năm (required · Đ11g, Luật Kế toán Đ41) · Ma trận phân quyền bằng văn bản (recommended) |
| Có người lao động | HĐLĐ từng người (required · BLLĐ) · Nội quy lao động: có (mọi NSDLĐ) / bằng văn bản + đăng ký khi ≥ 10 NLĐ (required · Đ118–119) · Thang bảng lương (*cần kiểm tra* · Đ93) · Sổ tay nhân viên (recommended) |
| Có dữ liệu cá nhân khách/NLĐ | Chính sách/thông báo xử lý DLCN (required · Luật 91/2025) · Hồ sơ đánh giá tác động xử lý DLCN (required/ngưỡng *cần kiểm tra* · NĐ 356/2025) · Quy trình xử lý yêu cầu của chủ thể dữ liệu & sự cố lộ lọt (recommended) · Chính sách dùng AI với dữ liệu khách (recommended · NĐ 356 có mục AI) |
| Shop online | Chính sách đổi trả, vận chuyển, bảo hành, bảo mật hiển thị cho khách (recommended · NĐ TMĐT *cần kiểm tra*) · FAQ CSKH (recommended) · Bảng giá hiện hành (required cho agent bán hàng — điều kiện vận hành, không phải luật) |
| Agency | Mẫu hợp đồng dịch vụ, NDA, quy trình duyệt nội dung với khách, brand guide của từng khách (recommended) |
| Kế toán dịch vụ | Chứng chỉ/đăng ký hành nghề dịch vụ kế toán (*cần kiểm tra*) · Quy chế bảo mật hồ sơ khách (recommended) |

Chấm sẵn sàng: lớp "Tri thức" của `agent_readiness` tách thành **"Hồ sơ & tài liệu"**: % yêu cầu `required` có tài liệu `published`/record
còn hiệu lực, % tài liệu `core/retrieve` không quá hạn rà soát, tỷ lệ lỗ hổng mở/tuần; mỗi mục có `fix_href` tới đúng ngăn + nút "Tạo từ mẫu".

### A9. Quyền truy cập & cho thuê

- **Bên cho thuê → bên thuê**: tài liệu được cấp qua `seat_leases.knowledge_doc_ids` phải có `lease_shareable=true` và `sensitivity ≤ internal`,
  không chứa DLCN; bên thuê thấy **bản published tại thời điểm** (và bản mới khi bên cho thuê ban hành — đúng "sàn" luôn mới nhất), nhãn "Tài liệu của
  bên cho thuê — chỉ đọc". Chính sách sàn của bên cho thuê (`policy` với `agent_use=core`) biên dịch vào mục "Sàn của bên cho thuê" (đã có `layered_core`).
- **Bên thuê → bên cho thuê**: không bao giờ; `visible_docs_query` của bên cho thuê không có nhánh nào đọc công ty bên thuê (giữ đúng R2).
- **Xuất mẫu R3** (`clawcompany.template/v2`): chỉ tài liệu `exportable=true`, `doc_class=document`, không `personal_data`; xuất **khung** (đề mục +
  placeholder như `{{ten_cong_ty}}`, `{{so_ngay_doi_tra}}` lấy từ `company_facts`) chứ không xuất nguyên văn số liệu của công ty nguồn; record
  không bao giờ xuất. Khi nhập: tài liệu vào `draft` của công ty mới + danh sách placeholder cần điền → chấm sẵn sàng thấy ngay chỗ thiếu.
- Vai trò công ty (R1): viewer đọc `internal`, manager/owner đọc tới `confidential`; `restricted/personal_data` cần quyền riêng theo tài liệu (danh sách
  người) — nhật ký truy cập dùng lại mẫu `knowledge_access_logs`.

### A10. Vòng học: bài học → đề xuất sửa tài liệu

1. **Đánh dấu khi dùng (KCS "flag it or fix it")**: MCP `company_doc_flag(doc_code, reason ∈ wrong|outdated|conflict|missing_case, note, task_id)` →
   `document_flags` + Hộp việc chủ tài liệu (gộp theo tài liệu). Agent chức danh được cấp quyền "sửa" (tương tự *license to modify*) thì gửi
   `company_doc_propose(doc_code, diff)` → tạo phiên bản `draft` kèm diff → duyệt như A5.
2. **Bài học đã duyệt** (`lessons.apply`): nếu bài học trỏ tới tài liệu đã được trích dẫn trong task (biết qua trích dẫn ở `task_journal`) hoặc mâu
   thuẫn `company_facts` → sinh thêm "đề xuất sửa tài liệu" thay vì chỉ ghi MEMORY.md của một agent; tri thức tốt trở thành của **công ty**.
3. **Gom lỗ hổng (Evolve loop)**: hằng tuần gom `knowledge_gaps` theo cụm (embedding) → cụm ≥ N lần → T2 soạn **nháp bài FAQ/KCS** từ các task đã giải
   quyết liên quan (không chép thông tin riêng của khách) → `draft` cho chủ phòng.
4. **Sức khoẻ nội dung** (bảng): % tài liệu đúng hạn rà soát (mục tiêu ≥ 80%, theo khuyến nghị Guru), tái dùng/trích dẫn theo tài liệu, tài liệu không
   ai dùng 180 ngày (đề xuất lưu trữ), cờ mở, mâu thuẫn mở, lỗ hổng mở. KPI mới cho D5: `doc_freshness_rate`, `knowledge_gap_rate`.

### A11. Bề mặt (đề xuất)

- **API** (`/api/team/docs…`, giữ `/api/learning/docs` làm lớp tương thích): CRUD + `POST /docs/{id}/versions`, `/submit`, `/publish`, `/archive`,
  `/dispose`, `/flags`, `GET /docs/requirements`, `POST /docs/requirements/seed`, `GET /docs/health`, `GET/PUT /company-facts`.
- **MCP mới**: `company_doc_get` (theo mã, bản published), `company_doc_flag`, `company_doc_propose`, `company_fact_get`, `company_template_fill`.
- **UI**: Công ty → tab **"Tài liệu"**: 8 ngăn; danh sách có huy hiệu trạng thái/độ tươi/nhạy cảm/cách agent dùng; trang tài liệu: xem, lịch sử phiên bản
  + diff, ai duyệt, liên kết quy trình/chức danh, "agent đã trích dẫn N lần"; ngăn **"Còn thiếu"** (danh mục bắt buộc) và **"Cần rà soát"**.

---

## B. Rà soát toàn module Công ty so với một công ty thật

Ước lượng cỡ: S ≈ ≤ 3 ngày, M ≈ 1–2 tuần, L ≈ 3+ tuần (một người + agent coder, gồm test + i18n + VM).

| # | Phần thiếu | Vì sao quan trọng với công ty agent | Ưu tiên | Cỡ | Đã có một phần trong code |
|---|---|---|---|---|---|
| 1 | **Thư viện tài liệu & hồ sơ** (mục A) | agent trả lời theo bản nháp/cũ = sai chính sách hàng loạt; không chứng minh được với cơ quan kiểm tra | **P0** | L | `knowledge_documents`, chunks, `sops`, gap log, khoá học |
| 2 | **Sản phẩm/dịch vụ & bảng giá** | agent bán hàng/CSKH báo giá, tồn, khuyến mãi; giá phải là dữ liệu có cấu trúc + duyệt khi đổi, không phải đoạn văn RAG | **P0** | M | không có (`customers` là tenant nền tảng; mẫu shop có quy trình "Đăng sản phẩm mới" + hợp đồng dữ liệu "Bài đăng sản phẩm") |
| 3 | **Phạm vi công ty ở route cũ** (`/api/work`, `/api/tasks`, `/api/agents`, chi phí, v7–v36) | người bị giới hạn công ty vẫn đọc dữ liệu cả tổ chức; chặn R3/R4 | **P0** (nợ kỹ thuật) | M | R1 `company_access`, `require_company_role`, ma trận cô lập test |
| 4 | **Khách hàng/CRM + đồng ý DLCN** | agent CSKH cần lịch sử khách, phân khúc, ghi chú; Luật 91/2025: đồng ý, rút đồng ý, xoá theo yêu cầu, chứng minh đồng ý | P1 | L | `conversations`, `customer_chat_bindings`, kênh chat, A2A; `company_rules` loại `pii` (che PII) |
| 5 | **Hợp đồng & đối tác/nhà cung cấp** | agent cần biết điều khoản, SLA, hạn gia hạn; ma trận đã có loại việc `contract` nhưng không có sổ hợp đồng | P1 | M | `authority_rules` (`contract`), `compliance_rules` "giấy phép/hạn riêng", `external_agents` (A2A) |
| 6 | **Họp & quyết định** (biên bản, nghị quyết, việc sau họp) | Luật DN Đ11d buộc lưu biên bản & quyết định; agent cần biết quyết định mới nhất; việc sau họp phải thành task | P1 | M | `decisions` + MCP `company_decision_log`, `calendar_events`, `rhythm_reports`, `approvals` |
| 7 | **Tài chính kinh doanh** (sổ thu chi, công nợ phải thu/trả, ngân sách theo phòng/dự án, dòng tiền) | agent kế toán/mua hàng cần số dư ngân sách thật để tự quyết trong ma trận; báo cáo chủ | P1 | L | `budget_envelopes`/`budget_ledger_entries` (đang là chi phí model, USD), `cost_ledger`, `billing_invoices` (hoá đơn nền tảng), `lease_usage` — **quy ước "chỉ USD" xung đột với sổ kế toán VND: cần anh quyết** |
| 8 | **Rủi ro & kiểm soát nội bộ** (sổ rủi ro: khả năng × tác động, chủ, biện pháp, ngày rà soát) | công ty agent rủi ro mới (lộ dữ liệu, cam kết sai, chi vượt); McKinsey/Gartner: kiểm soát rủi ro yếu là lý do dự án agent bị huỷ | P1 | M | `incidents` (SRE), `rule_violations`, `compliance_deadlines`, `security_reviews` |
| 9 | **Thông báo nội bộ có xác nhận đã đọc** | chính sách mới ban hành phải tới đủ người (ack) và agent (sync AGENTS.md + ôn) | P1 | S | Hộp việc, `sync_core`, `mark_courses_stale` |
| 10 | **Hội nhập & hồ sơ nhân sự người** (checklist ngày 1, khoá học cho người, hồ sơ HĐLĐ, nghỉ việc → thu hồi quyền + xoá DLCN đúng hạn) | ghế người vẫn là người duyệt và xử lý ngoại lệ; hội nhập tốt = duyệt nhanh | P1 | M | `seat_schedules`, `seat_leaves`, lời mời, `user_seats`; khoá học chỉ cho agent |
| 11 | **Báo cáo chủ/HĐQT + gói bằng chứng kiểm toán** (tháng/quý: KPI, chi phí, sự cố, vi phạm, quyết định, rủi ro; xuất PDF có hash) | chủ đứng "trên vòng lặp" cần một bản đọc 10 phút; kiểm toán cần chuỗi bằng chứng ai-duyệt-gì | P1 | M | `rhythm_reports` (ngày/tuần), `audit_events`, `write_trail`, `task_journal`, `evidence_signatures` |
| 12 | **Chiến lược/OKR** trong module Công ty (kế hoạch năm, check-in quý) | KPI cascade đã có nhưng thiếu "vì sao" và nhịp check-in mục tiêu | P2 | S | `executive_goals`, `portfolio_objectives`, `kpi_definitions` + lịch sử, Nina planner |
| 13 | **Tài sản & kho** | shop cần tồn kho cho agent bán; tài sản cho kế toán (TSCĐ) | P2 | M | không có |
| 14 | **Khiếu nại khách & không phù hợp** (ISO 8.7/10.2) | đo chất lượng agent từ phía khách; nguồn bài học | P2 | S | `rule_violations`, `task_outputs` (sai chuẩn), `incidents` |
| 15 | **Hoá đơn điện tử & thuế thực thi** | lịch đã có, chưa có lập/nhận hoá đơn | P2 | M (tích hợp nhà cung cấp) | `compliance_calendar` |
| 16 | **Kênh bán & tích hợp** (sàn TMĐT, Zalo OA, website) | nguồn đơn hàng cho quy trình D4 | P2 | L | `integrations`, kênh chat |

---

## C. Thứ tự xây (gói M3) và tiêu chí nghiệm thu

Quy ước giữ như M2: mỗi gói một migration riêng (từ **0053**), biên dịch vào cơ chế có sẵn (AGENTS.md, ma trận phân quyền, Hộp việc, beat,
guard plugin), test hành vi + test cô lập R1 cho bảng mới, i18n vi+en, deploy + kiểm trên VM công ty 3 (Tiệm Gốm Mộc).

### M3a — Thư viện tài liệu lõi (P0, L) — migration `0053_document_library`
Phạm vi: cột A4 trên `knowledge_documents`, `knowledge_document_versions`, `document_links`, lưu tệp gốc (artifact + sha256), vòng đời A5 với
loại việc `doc_publish` trong ma trận (gieo mặc định), beat `docs.tick` (rà soát/hiệu lực/hết hạn), UI tab "Tài liệu" (8 ngăn, trang tài liệu,
lịch sử + diff), backfill tài liệu cũ: `status=published`, `version_no=1`, `doc_class=document`, `doc_type` đoán theo tiêu đề, `agent_use = core nếu
is_core else retrieve`, `audience` từ `role_keyword`; `sops.document_id` + chép nội dung SOP thành phiên bản 1.
Nghiệm thu:
- Bản `draft`/`in_review` **không** xuất hiện trong `company_knowledge_search`, `company_knowledge_get`, `core_section` (test).
- Ban hành v2 → v1 thành `superseded`, AGENTS.md của ghế liên quan được sinh lại trong ≤ 1 nhịp `sync_core`, khoá học dùng tài liệu chuyển "cần ôn".
- Phiên bản đã duyệt không sửa được (PATCH → 409); record không sửa được sau khi lưu.
- Người duyệt lấy đúng từ ma trận (`policy` gửi khách → chủ; SOP phòng → trưởng phòng); agent không tự duyệt tài liệu của mình.
- `review_due_at` qua → đúng một thẻ Hộp việc `doc_review_due` cho người phụ trách là người; `effective_to` qua → tài liệu rời AGENTS.md.
- Ma trận cô lập R1 mở rộng cho route `/docs` sạch (không rò công ty/tổ chức khác).
- Tài liệu cũ sau migration vẫn tra ra như trước (test hồi quy kết quả search trên bộ mẫu).

### M3b — Tài liệu thành tri thức agent (P0, M) — `0054_doc_retrieval`
Phạm vi: `agent_use` 4 mức, `core_summary` theo tài liệu + biên dịch theo chức danh, lọc trước-chấm-điểm (trạng thái/hiệu lực/đối tượng/nhạy cảm),
cắt theo đề mục + tiêu đề ngữ cảnh, FTS + pgvector + RRF trên Postgres, trích dẫn `[DOC:mã vN §m]`, cờ `stale`, luật guard chặn mã nội bộ trong tin gửi
khách, `company_facts` + phát hiện mâu thuẫn v1 (số liệu), MCP `company_doc_get`, `company_fact_get`.
Nghiệm thu:
- Bộ eval CSKH (≥ 30 câu hỏi chính sách/giá trên công ty 3): recall@6 của truy hồi mới ≥ bản cũ + 10 điểm %, và câu trả lời của agent có trích dẫn đúng
  phiên bản đang hiệu lực ≥ 90% (đo bằng log, không ước đoán).
- Tài liệu `sensitivity=personal_data` hoặc `agent_use=none` không bao giờ vào kết quả của agent (test).
- Hai tài liệu ghi số ngày đổi trả khác nhau → ban hành bản thứ hai bị cảnh báo mâu thuẫn + Hộp việc cho hai chủ.
- Tin nhắn ra khách chứa `[DOC:` bị guard sửa/chặn (test plugin như M2e.2).
- AGENTS.md cốt lõi không vượt 12.000 ký tự và không còn tài liệu bị cắt cụt giữa chừng (dùng tóm tắt).

### M3c — Nạp & phân loại (P1, M) — `0055_doc_ingestion`
Phạm vi: XLSX/PPTX, OCR (Tesseract `vie`, fallback model thị giác có trần chi), Google Drive + Notion connector theo công ty (đồng bộ thay đổi), tự phân
loại T1 + PII regex → đề xuất `doc_type/sensitivity/audience/doc_code/effective`, trích sự kiện → Hộp việc đề xuất cập nhật hồ sơ pháp nhân / `company_facts`
/ giấy phép.
Nghiệm thu: PDF scan GCN ĐKDN mẫu → trích đúng MST, tên, ngày cấp (≥ 4/5 trường trên 5 mẫu); không còn tài liệu nạp với nội dung rỗng (422 rõ ràng);
sửa một Google Doc → tài liệu thư viện có bản `draft` mới trong ≤ 1 chu kỳ đồng bộ; tài liệu có ≥ 3 số CCCD tự gắn `personal_data` + `agent_use=none`; mọi
trích xuất là đề xuất (không ghi thẳng `company_profiles`).

### M3d — Hồ sơ bắt buộc & lưu trữ (P0 phần danh mục, P1 phần huỷ) — `0056_document_requirements`
Phạm vi: `document_requirements` (gói chung + có NLĐ + có DLCN + gói ngành), có căn cứ + `needs_review`; lớp "Hồ sơ & tài liệu" trong `agent_readiness`;
"Tạo từ mẫu" (mẫu là tài liệu `template` của nền tảng); `license.expires_at` → `compliance_deadlines`; `retention_class` → `retain_until` tự tính (NĐ 174
mốc kết thúc năm tài chính), `legal_hold`, huỷ cần duyệt chủ, giữ siêu dữ liệu + hash sau huỷ.
Nghiệm thu: công ty TNHH có 12 ghế người, chưa có nội quy → mục "Nội quy lao động (bằng văn bản + đăng ký)" đỏ, có căn cứ Đ118–119; xuống 8 ghế người →
mục đổi thành "có nội quy (không bắt buộc văn bản)"; agent không được đếm vào số NLĐ; chứng từ năm 2026 gắn `acct_10y` → `retain_until=31/12/2036`; xoá trước
hạn → 409; giấy phép hết hạn sau 30 ngày → có hạn trong lịch tuân thủ với người nhận đúng; UI hiện dải "lịch tham khảo, không phải tư vấn pháp lý".

### M3e — Vòng học tài liệu (P1, M) — `0057_doc_feedback`
Phạm vi: `document_flags`, MCP `company_doc_flag` / `company_doc_propose`, bài học → đề xuất sửa tài liệu, gom lỗ hổng hằng tuần → nháp KCS, bảng sức khoẻ
nội dung, KPI `doc_freshness_rate`, `knowledge_gap_rate`.
Nghiệm thu: agent đánh dấu tài liệu → một thẻ Hộp việc gộp cho chủ; đề xuất sửa tạo `draft` có diff và đi đúng đường duyệt M3a; 5 lỗ hổng cùng cụm → 1 nháp bài
không chứa tên/số điện thoại khách (test PII); bảng sức khoẻ hiện đúng số trên dữ liệu mẫu.

### M3f — Sản phẩm/dịch vụ & bảng giá (P0, M) — `0058_catalog`
Phạm vi: `products` (mã, tên, mô tả, biến thể, đơn vị, trạng thái), `price_lists` + `prices` (hiệu lực từ/đến, kênh, tiền tệ), khuyến mãi; đổi giá qua ma trận (loại
việc mới `price_change`); MCP `company_product_lookup`; trang mô tả sản phẩm là tài liệu `product_sheet` liên kết.
Nghiệm thu: agent CSKH trả giá đúng giá đang hiệu lực từ tool (eval 20 câu, 0 giá bịa); đổi giá > ngưỡng cần duyệt; giá hết hiệu lực không trả về.

### M3g — Khách hàng & dữ liệu cá nhân (P1, L) — `0059_crm_consent`
Phạm vi: `contacts`/`accounts` của **doanh nghiệp người dùng** (tách khỏi `customers` tenant), nhật ký tương tác nối hội thoại, `consents` (mục đích, kênh,
thời điểm, bằng chứng), yêu cầu của chủ thể dữ liệu (xem/sửa/xoá/rút đồng ý) thành quy trình D4 có SLA, sổ hoạt động xử lý DLCN, tài liệu DLCN của M3d.
Nghiệm thu: rút đồng ý → agent không nhắn marketing cho liên hệ đó (luật cứng/tool chặn); yêu cầu xoá chạy hết quy trình và để lại hồ sơ bằng chứng; dữ liệu
liên hệ không vào RAG.

### M3h — Hợp đồng & đối tác (P1, M) — `0060_contracts`
Phạm vi: sổ hợp đồng (bên, loại, giá trị, hiệu lực, gia hạn tự động, hạn báo trước, SLA, chủ), nhà cung cấp/đối tác, tệp ký là record M3a, hạn gia hạn →
lịch tuân thủ, MCP `company_contract_get` (điều khoản chính), ký hợp đồng mới đi loại việc `contract` của ma trận.
Nghiệm thu: hợp đồng sắp hết hạn 30 ngày → việc + Hộp việc cho chủ; agent hỏi SLA nhà cung cấp nhận đúng số từ tool, không đọc tệp ký.

### M3i — Họp & quyết định (P1, M) — `0061_meetings`
Phạm vi: cuộc họp (loại: HĐTV/ĐHĐCĐ/HĐQT/giao ban/khác), người dự, biên bản (record), nghị quyết/quyết định (nâng `decisions`: số, ngày, hiệu lực, thay thế),
việc sau họp → task; agent soạn biên bản từ ghi chú, người duyệt ký; quyết định hiệu lực → `company_facts`/tài liệu liên quan nhận cờ "cần cập nhật".
Nghiệm thu: biên bản duyệt xong khoá sửa; 3 việc sau họp thành 3 task đúng người; `company_decision_log` trả quyết định mới nhất đang hiệu lực.

### M3j — Tài chính kinh doanh (P1, L) — `0062_business_ledger`
Điều kiện trước: **anh quyết tiền tệ** (quy ước hiện tại "chỉ USD" của M2 vs sổ kế toán VND của doanh nghiệp VN). Phạm vi: sổ thu chi, công nợ phải thu/trả
theo khách/nhà cung cấp, ngân sách theo phòng/dự án nối `budget_envelopes`, đối chiếu với chứng từ (record M3a); không thay phần mềm kế toán — xuất/nhập.
Nghiệm thu: agent mua hàng kiểm ngân sách còn lại trước khi xin duyệt; báo cáo tuần có thu–chi–công nợ quá hạn.

### M3k — Rủi ro & kiểm soát (P1, M) · M3l — Thông báo có xác nhận (P1, S) · M3m — Hội nhập nhân sự người (P1, M) · M3n — Báo cáo chủ & gói kiểm toán (P1, M)
- M3k: sổ rủi ro gắn quy trình/chức danh, biện pháp kiểm soát trỏ tới luật cứng/ma trận/SLA thật (kiểm soát "có trong hệ thống" vs "chỉ trên giấy", giống điều
  cấm hiến chương M2e.2), rà soát định kỳ. Nghiệm thu: mỗi rủi ro cao có ≥ 1 kiểm soát đang cưỡng chế hoặc bị đánh dấu "chỉ trên giấy".
- M3l: thông báo (thường gắn ban hành tài liệu) → người phải bấm "đã đọc" trong N ngày, agent tự sync; tỷ lệ đã đọc theo phòng. Nghiệm thu: chính sách mới tới
  100% ghế người liên quan, nhắc lại người chưa đọc sau 3 ngày.
- M3m: checklist hội nhập theo chức danh (tài liệu phải đọc, khoá học cho người, quyền cần cấp), nghỉ việc → thu hồi `company_access`/`user_seats` + lịch xoá DLCN.
  Nghiệm thu: nhân viên mới có checklist tự sinh; nghỉ việc thu hồi quyền trong ngày.
- M3n: báo cáo tháng/quý cho chủ (KPI, chi phí, SLA, vi phạm, quyết định, rủi ro, sức khoẻ tài liệu) + gói bằng chứng xuất PDF có hash từ `audit_events`/
  `approvals`/phiên bản tài liệu. Nghiệm thu: một quyết định chi tiền truy ngược được tới luật ma trận, người duyệt, bản chính sách áp dụng lúc đó.

**Song song, trước R3/R4:** P0 #3 lọc phạm vi công ty ở route cũ (đã ghi trong `r-rental-and-multi-company.md`), và R3 xuất mẫu dùng cờ `exportable` của M3a.

---

## Nguồn (đã mở và đọc ngày 16/10/2026)

Pháp lý Việt Nam
- Luật Doanh nghiệp 59/2020/QH14, Điều 11 (toàn văn): https://thuvienphapluat.vn/van-ban/Doanh-nghiep/Luat-Doanh-nghiep-so-59-2020-QH14-427301.aspx
- Luật 76/2025/QH15 sửa Luật DN (chủ sở hữu hưởng lợi; điểm h k1 Đ11; hiệu lực 1/7/2025): https://luatvietnam.vn/doanh-nghiep/8-diem-moi-cua-luat-sua-doi-luat-doanh-nghiep-561-102729-article.html ;
  lưu ≥ 05 năm sau giải thể (trích từ toàn văn qua kết quả tìm kiếm): https://luatvietnam.vn/doanh-nghiep/luat-doanh-nghiep-sua-doi-2025-so-76-2025-qh15-403856-d1.html
- Luật Kế toán, VBHN 25/VBHN-VPQH (26/2/2025), Điều 41: https://thuvienphapluat.vn/van-ban/Ke-toan-Kiem-toan/Van-ban-hop-nhat-25-VBHN-VPQH-2025-Luat-Ke-toan-651529.aspx
- NĐ 174/2016/NĐ-CP, Điều 12–15: https://thuvienphapluat.vn/van-ban/Ke-toan-Kiem-toan/Nghi-dinh-174-2016-ND-CP-huong-Luat-ke-toan-336391.aspx
- Luật Lưu trữ 33/2024/QH15 (21/6/2024, hiệu lực 1/7/2025): https://vanban.chinhphu.vn/?docid=211191&pageid=27160 ; tài liệu giới thiệu (giá trị pháp lý tài liệu số, lưu trữ tư):
  https://moc.gov.vn/pl/tin-tuc/370/tai-lieu-gioi-thieu-pho-bien-luat-luu-tru-nam-2024.aspx ; NĐ 113/2025/NĐ-CP: https://congbao.chinhphu.vn/van-ban/nghi-dinh-so-113-2025-nd-cp-44996.htm
- Luật Bảo vệ dữ liệu cá nhân 91/2025/QH15 (26/6/2025, hiệu lực 1/1/2026): https://congbao.chinhphu.vn/van-ban/luat-so-91-2025-qh15-45578.htm ;
  Bộ Công an: https://bocongan.gov.vn/chinh-sach-phap-luat/bai-viet/luat-bao-ve-du-lieu-ca-nhan-chinh-thuc-co-hieu-luc-thi-hanh-tu-ngay-01-01-2026-1767186124 ;
  điểm chính + NĐ 356/2025/NĐ-CP thay NĐ 13/2023: https://luatvietnam.vn/legal-updates/the-latest-law-on-personal-data-protection-and-the-guiding-documents-892-106778-article.html ;
  NĐ 356/2025 (ban hành 31/12/2025, hiệu lực 1/1/2026): https://caa.gov.vn/van-ban/356-2025-nd-cp-30668.htm
- BLLĐ 2019 Điều 118–121 (nội quy): https://www.atld.vn/law/3193/content ; https://thuvienphapluat.vn/phap-luat/co-bat-buoc-phai-ban-hanh-noi-quy-lao-dong-doi-voi-doanh-nghiep-su-dung-duoi-10-nguoi-lao-dong-khon-500442-24845.html ;
  thủ tục đăng ký: https://dichvucong.gov.vn/p/home/dvc-tthc-thu-tuc-hanh-chinh-chi-tiet.html?ma_thu_tuc=154838

Thực hành quản trị tài liệu & tri thức
- ISO, Guidance on the requirements for Documented Information of ISO 9001:2015: https://www.iso.org/files/live/sites/isoorg/files/standards/docs/en/iso_9001_2015_guidance_documented_information.pdf ;
  nguyên văn §7.5.3 (trích lại): https://asqasktheexperts.org/2018/03/23/iso-requirements-or-good-documentation-practices/
- KCS v6 Practices Guide — Technique 5.1 Article Structure: https://library.serviceinnovation.org/KCS/KCS_v6/KCS_v6_Practices_Guide/030/040/010/020 ; Double Loop: https://library.serviceinnovation.org/KCS/KCS_v6/KCS_v6_Practices_Guide/030/025
- Guru — What is Verification: https://help.getguru.com/docs/what-is-verifcation ; auto-archive (6 tháng chưa xác minh + 0 lượt xem): https://help.getguru.com/docs/automating-card-management-autoarchive-duplicate-detection
- Anthropic — Contextual Retrieval: https://www.anthropic.com/engineering/contextual-retrieval
- Microsoft — Security filter pattern (security trimming) Azure AI Search: https://learn.microsoft.com/en-us/azure/search/search-security-trimming-for-azure-search

Code đã đọc (repo, nhánh `ui-v2`): `backend/app/models/entities.py` (KnowledgeDocument), `models/knowledge_chunks.py`, `models/learning.py`, `models/extended.py`
(SOP, Decision, Customer, Integration, AuditEvent), `models/v9.py`, `models/v10.py`, `models/v36.py`, `services/knowledge_hub.py`, `services/company_mcp.py`
(tool knowledge/sop/decision), `services/agent_readiness.py`, `api/learning.py`; danh sách bảng toàn bộ `models/*.py`; migration mới nhất `0052_seat_leases`.

## Giới hạn của báo cáo (nói thẳng)

- Không chạy code, không đo truy hồi hiện tại; con số cải thiện là của Anthropic trên bộ dữ liệu của họ — M3b phải tự đo trên eval CSKH.
- Các mục ghi "cần kiểm tra" chưa được đối chiếu văn bản gốc (thang bảng lương, quy chế dân chủ, NĐ TMĐT, ATTP, ngưỡng đánh giá tác động DLCN cho DN nhỏ, thời
  hạn lưu HĐLĐ/BHXH, nghĩa vụ xoá dữ liệu NLĐ khi nghỉ — tóm tắt của LuatVietnam, chưa đọc điều khoản).
- Thời hạn "suốt đời doanh nghiệp" cho hồ sơ pháp lý/biên bản là **đề xuất chính sách công ty**, không phải con số luật (Luật DN chỉ nói "theo quy định của pháp luật").
- Ước lượng cỡ (S/M/L) là ước đoán theo nhịp các gói M2; chưa tính thời gian UI đang được một agent khác làm song song.
