# Một công ty gồm những gì, và công ty agent triển khai thế nào

Nghiên cứu ngày 15/10/2026 cho module Công ty. Nguồn: APQC PCF cross-industry (13 nhóm quy trình), McKinsey "The agentic organization" (26/9/2025), Microsoft Work Trend Index 2025 (Frontier Firm), Gartner (25/6/2025). Có đối chiếu với bảng đang có trong repo.

## A. Mười lớp của một công ty

| # | Lớp | Gồm gì | Ví dụ ở doanh nghiệp nhỏ VN |
|---|---|---|---|
| 1 | Pháp nhân, chủ sở hữu | loại hình, điều lệ, vốn, người đại diện theo pháp luật, ngành nghề, MST | TNHH 1TV, giám đốc kiêm chủ |
| 2 | Quản trị, quyền quyết | HĐTV/HĐQT, giám đốc, **ma trận phân quyền** (ai duyệt gì, tới mức tiền nào) | chi trên 5 triệu phải giám đốc duyệt |
| 3 | Chiến lược, mục tiêu | tầm nhìn, kế hoạch năm/quý, OKR/KPI chia xuống phòng | doanh thu quý, tỷ lệ hoàn đơn |
| 4 | Tổ chức | phòng ban, chức danh, mô tả công việc (JD), báo cáo cho ai, định biên | 1 trưởng kho, 2 CSKH |
| 5 | Quy trình (chuỗi giá trị) | APQC: 1 chiến lược, 2 sản phẩm, 3 marketing-bán hàng, 4 giao hàng hoá, 5 giao dịch vụ, 6 CSKH, 7 nhân sự, 8 IT, 9 tài chính, 10 tài sản, 11 rủi ro-tuân thủ, 12 quan hệ bên ngoài, 13 năng lực doanh nghiệp | đơn hàng → đóng gói → giao → đổi trả |
| 6 | Con người | tuyển, hội nhập, đào tạo, đánh giá, lương thưởng, kỷ luật, nghỉ việc | thử việc 2 tháng |
| 7 | Tài chính | ngân sách, thu chi, công nợ, thuế, báo cáo tài chính | kê khai thuế, BHXH |
| 8 | Khách hàng, đối tác | CRM, hợp đồng, nhà cung cấp, kênh bán | Shopee, Zalo OA |
| 9 | Tri thức | chính sách, SOP, mẫu biểu, hồ sơ, bài học | chính sách đổi trả |
| 10 | Nhịp vận hành, kiểm soát | giao ban ngày/tuần, báo cáo tháng, review quý, kiểm soát nội bộ, công cụ | họp sáng 8h |

## B. Công ty agent khác ở đâu

- McKinsey: 5 trụ (mô hình kinh doanh, mô hình vận hành, quản trị, con người-văn hoá, công nghệ-dữ liệu). Quy trình thiết kế lại theo kiểu AI-first, người đứng "trên vòng lặp" (đặt mục tiêu, chính sách, xử lý ngoại lệ) thay vì duyệt từng dòng. Nhóm 2–5 người có thể giám sát 50–100 agent chạy một quy trình đầu-cuối. Sơ đồ tổ chức chuyển thành "work chart" (trao đổi việc và kết quả). Agent kiểm soát agent: critic, guardrail, compliance. Giới hạn mở rộng chính là năng lực giám sát của con người.
- Microsoft: 3 giai đoạn: người có trợ lý → đội người + agent → người dẫn dắt, agent vận hành.
- Gartner: hơn 40% dự án agentic bị huỷ trước cuối 2027 vì chi phí, giá trị không rõ, kiểm soát rủi ro yếu → bắt đầu từ quy trình đo được tiền.

### Ánh xạ từng lớp

| Lớp | Agent làm | Người giữ | ClawCompany đang có | Thiếu |
|---|---|---|---|---|
| 1 Pháp nhân | soạn hồ sơ, nhắc hạn | ký, chịu trách nhiệm pháp lý | `companies` (tên, mô tả) | hồ sơ pháp nhân, hiến chương |
| 2 Quyền quyết | xin duyệt đúng người, đúng mức | đặt ngưỡng, duyệt ngoại lệ | approvals, autonomy levels, budget 3 nấc | **ma trận phân quyền** chung (tiền / loại việc / mức rủi ro) |
| 3 Mục tiêu | đề xuất kế hoạch, theo dõi số | chốt mục tiêu | `executive_goals`, `portfolio_objectives`, Nina planner | KPI chia công ty → phòng → seat, nối scorecard |
| 4 Tổ chức | — | thiết kế sơ đồ | departments, members, seat người/agent, trưởng phòng, mẫu công ty | **chức danh + JD + định biên** tách khỏi người ngồi |
| 5 Quy trình | chạy từng bước | sở hữu quy trình, xử lý ngoại lệ | `sops`, `workflows`, routines, task review chéo | bản đồ quy trình có chủ, SOP chạy được, đo thời gian chu trình |
| 6 Con người | — | tuyển, đánh giá | AgentHR: thử việc, eval pass^k, thăng/hạ bậc | vòng đời cho seat người; vai trò mới (người điều phối agent) |
| 7 Tài chính | ghi sổ, đối chiếu, báo cáo | duyệt chi, ký | chi phí model, ngân sách | sổ thu chi kinh doanh, công nợ, lịch thuế |
| 8 Khách hàng | CSKH, bán hàng | quan hệ lớn, khiếu nại nặng | `customers`, kênh chat, A2A | nối CRM/sàn, hợp đồng |
| 9 Tri thức | tra cứu, đề xuất bài học | duyệt bài học | 3 lớp tri thức lõi, KB embedding, lessons, Skill Studio | gắn tri thức theo quy trình |
| 10 Nhịp vận hành | soạn giao ban, báo cáo | họp, quyết định | routines, inbox, cost board | giao ban tự động, bảng điều hành theo nhịp |

## C. Lộ trình triển khai cho một doanh nghiệp

0. **Chẩn đoán (1 tuần):** kiểm kê quy trình theo 13 nhóm APQC, chấm mỗi quy trình: tần suất, quy tắc rõ, dữ liệu số, rủi ro/đảo ngược được, đo được tiền.
1. **Nền:** hồ sơ công ty + hiến chương (giá trị, giọng thương hiệu, điều cấm), sơ đồ chức danh, ma trận phân quyền, tri thức lõi.
2. **Lighthouse:** một quy trình đầu-cuối có ROI rõ (ví dụ đơn hàng → CSKH → đổi trả). Agent ở mức thử việc, người duyệt nhiều.
3. **Mở rộng theo phòng:** mỗi phòng 1 người phụ trách + nhiều agent, KPI theo seat, tự học có duyệt.
4. **Liên phòng:** agent bàn giao cho nhau, critic/compliance agent, người chuyển sang đặt chính sách và xử lý ngoại lệ.

Chỉ số: tỷ lệ người:agent, % việc agent xong không phải sửa, chi phí mỗi việc, thời gian chu trình, sự cố/ngoại lệ, giờ người duyệt mỗi tuần.

## D. Đề xuất cho module Công ty (thứ tự)

1. Hồ sơ pháp nhân + Hiến chương công ty, biên dịch vào tri thức lõi của mọi agent.
2. Chức danh (position) tách khỏi người: JD, KPI, quyền công cụ, định biên; seat người hay agent đều ngồi vào chức danh.
3. Ma trận phân quyền chung: một chỗ quyết ai duyệt gì theo tiền / loại việc / rủi ro; approvals, budget, autonomy đọc từ đây.
4. Bản đồ quy trình: quy trình có chủ, các bước gắn chức danh, SOP chạy được, đo thời gian chu trình.
5. Mục tiêu/KPI chia xuống phòng và seat, nối scorecard.
6. Nhịp vận hành: giao ban sáng, báo cáo tuần/tháng tự động.
7. Lịch tuân thủ VN (thuế, BHXH, giấy phép).
8. Trình hướng dẫn "chẩn đoán sẵn sàng agent" khi tạo công ty: hỏi đáp → đề xuất sơ đồ người + agent và quy trình lighthouse.

Tái dùng bảng có sẵn: `sops`, `decisions`, `executive_goals`, `portfolio_objectives`, `operating_cycles`, `recurring_operations`, `routines`, `autonomy_policies`, `budget_envelopes`.
