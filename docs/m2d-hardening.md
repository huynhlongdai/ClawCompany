# M2d — Gia cố M2c: quy trình v2, lịch sử KPI, lịch tuân thủ có ngày lễ, smoke A2A/deploy

Nối tiếp `m2c-company-operations.md`. Anh duyệt 16/10/2026 ("tiếp tục"). Nguyên tắc như M2b/M2c: biên dịch vào
cơ chế đã có, không dựng động cơ thứ hai; tiền **chỉ USD**; mọi chuỗi UI qua i18n (vi + en).

## 1. Quy trình v2 — rẽ nhánh + song song (migration `0044_process_branching`)

**Dữ liệu**: `process_steps` và `process_step_runs` thêm `depends_on` (JSON — seq các bước đứng trước), `condition`
(JSON `{field, op, value}`), `branch` (nhãn nhánh); step run thêm `outcome` (kết quả bước) và `skip_reason`.
Migration chuyển quy trình tuyến tính cũ: bước seq>1 phụ thuộc seq-1. Hàng `depends_on = NULL` vẫn đọc là tuyến tính.

**Đồ thị**: `depends_on` rỗng = chạy ngay khi bắt đầu; nhiều bước cùng phụ thuộc một bước = **song song (fan-out)**;
một bước phụ thuộc nhiều bước = **gộp nhánh (fan-in)**. Chỉ được trỏ về bước đứng trước → không có vòng.
API vắng `depends_on` → nối tiếp bước trước (client cũ không đổi hành vi). Mỗi cạnh = một `task_dependencies`.

**Điều kiện**: `field` = `amount_usd` | `input.<khoá>` (dữ liệu vào của lần chạy) | `step<N>.outcome` (kết quả bước
đứng trước, ghi qua `POST /team/process-step-runs/{id}/outcome`); `op` = `== != > >= < <= empty not_empty`. So sánh
chữ không phân biệt hoa thường; số so như số. Trường không có giá trị → chỉ `empty` đúng.

**Chạy** (`process_map._settle`): một bước chờ được xét khi MỌI bước trước đã xong/bỏ qua — mọi bước trước bị bỏ
qua → bỏ qua (nhánh chết lan xuống); điều kiện sai → bỏ qua; đúng → "Cần làm". Bước gộp chạy khi ít nhất một nhánh
trước đã xong. Bước bị bỏ qua → task "Huỷ" có lý do (task_dependencies coi huỷ là đóng). Lần chạy xong khi không
còn bước chờ/đang làm. Bước gốc được đánh thức lúc bắt đầu; bước sau do `wake_unblocked` sẵn có.

**Thời gian chu trình theo nhánh**: `stats.branches` (mỗi nhãn: số lần nhánh chạy trọn, TB từ lúc bước đầu nhánh tới
lượt tới lúc bước cuối nhánh xong) + `stats.paths` (lần chạy xong đi qua tập nhánh nào → chu trình TB, "—" = đường
chính). Thời lượng kỳ vọng của quy trình = **đường găng** (bước song song không cộng dồn).

**UI** (tab Quy trình): mỗi bước có "Chạy sau" (chip B1…), nhãn nhánh, điều kiện (trường / phép / giá trị); đổi
chỗ/xoá bước tự đánh số lại tham chiếu. Thẻ quy trình hiện "sau B1, B2", "chỉ khi Số tiền ≥ $50", nhánh; dòng thời
gian theo đường đi/nhánh. Lần chạy hiện bước "Bỏ qua" + lý do, ô "Ghi kết quả" cho bước đang tới lượt.

Giới hạn tự khai: kết quả bước do người ghi qua UI/API (agent chưa có tool MCP để ghi `outcome`; bước sau xét
lúc tới lượt nên phải ghi trước khi chuyển Xong); điều kiện một vế (chưa AND/OR); chu trình vẫn tính giờ đồng hồ.
