# M3 — Tài liệu & tri thức công ty (2026-10-16)

Kế hoạch: docs/company-knowledge-library-and-gaps.md (M3a–M3n). Migrations 0053–0056. Đã triển khai trên VM (công ty 3 Tiệm Gốm Mộc). UI: Công ty › Tài liệu & tri thức.

| Gói | Nội dung | Commit |
|---|---|---|
| M3a | Thư viện tài liệu lõi: sổ tài liệu (mã, loại 52/8 ngăn, chủ sở hữu, đối tượng, độ nhạy, cách agent dùng, hiệu lực, chu kỳ rà soát, lưu trữ), phiên bản bất biến, ban hành qua ma trận thẩm quyền `doc_publish`, tệp gốc (sha256), nhập SOP, beat `docs.tick`; agent chỉ thấy bản đã ban hành còn hiệu lực. Migration 0053 | 20e4527, f60ee65 |
| M3b | Tài liệu → tri thức agent: lọc quyền trước khi chấm, cắt theo đề mục + header ngữ cảnh, không dấu + IDF + RRF (Postgres FTS + pgvector), trích dẫn `[DOC:mã vN §m]`, tóm tắt cốt lõi không cắt cụt, `company_facts` + mâu thuẫn chặn mềm, MCP `company_doc_get` / `company_doc_flag` / `company_fact_get` (36 tool), guard gỡ mã nội bộ khỏi tin gửi khách, bộ eval CSKH 33 câu. Migration 0054 | 45541e7 |
| M3d | Hồ sơ bắt buộc & lưu trữ: 22 mục theo loại hình / số lao động người / DLCN / ngành (có căn cứ, "cần kiểm tra"), lớp sẵn sàng "Hồ sơ & tài liệu", hạn lưu tự tính, xoá/huỷ trước hạn 409, giữ pháp lý, huỷ chỉ chủ + giữ hash, giấy phép hết hạn → lịch tuân thủ; sửa: giấy phép lưu trữ/bị thay tắt nghĩa vụ gia hạn; UI điện thoại; nhãn i18n lớp sẵn sàng. Migration 0055 | e73e1a2, 084cece, 4a5aea1, 73187cf, 68f22fd |
| M3f | Sản phẩm/dịch vụ & bảng giá: `catalog_products` + `catalog_prices` (lịch sử, VND không phần lẻ, kênh, hiệu lực), đổi giá qua ma trận `price_change` (<10% trưởng phòng, ≥10% hoặc giá mới → chủ, người đề xuất không tự duyệt), MCP `company_product_lookup` (chỉ giá đang hiệu lực), mục sẵn sàng "Bảng giá hiện hành"; sửa: tra giá bỏ khớp yếu, bảng sản phẩm điện thoại. Migration 0056 | 1bad468, 016c876 |

## Kết quả đo

- M3b retrieval recall@6: SQLite (corpus sạch 8 tài liệu) 0.879 → 0.970 (+9.1 điểm; mục tiêu +10 chưa đạt trên corpus sạch). Postgres VM (corpus thật công ty 3, có nhiễu legacy + SOP) 0.818 → 0.939 (+12.1); section recall 0.909; trích dẫn đúng phiên bản hiện hành 1.0.
- M3f eval tra giá: top-1 = 1.0, 0 giá bịa (20 câu).
- Bộ test backend: 1,319 passed / 2 skipped (chạy theo lát).
- Ảnh UI: `_reports/ui/m3-*.png` (thư viện, chi tiết tài liệu, sự kiện công ty, hồ sơ bắt buộc, sản phẩm & giá, sẵn sàng; desktop/EN/điện thoại 390 px), 0 lỗi console.

## Việc còn mở

1. Một số chuỗi tiếng Việt từ backend (tên mục hồ sơ, căn cứ, nhãn điều khoản) vẫn hiện trong UI tiếng Anh.
2. Nút "Tạo từ mẫu" (tạo tài liệu từ mẫu) chưa làm.
3. Ngưỡng 10% đổi giá là hằng số trong code, chưa cấu hình theo công ty.
4. Định tuyến người duyệt khác người đề xuất mới chứng minh bằng test; công ty 3 chỉ có Long là người nên trên VM vẫn tự duyệt.
5. API embedding (CometAPI) trả 403 → mọi lần index/tìm rơi về hash384 (chậm hơn, kết quả trung thực nhưng chưa có ngữ nghĩa thật).
6. Cần chạy lại với agent thật (sau khi nạp CometAPI + reset trần CSKH): agent trích `[DOC:…]`, guard gỡ mã trong tin gửi khách thật, agent gọi `company_product_lookup` / `company_fact_get` tự nhiên.
7. Dữ liệu thử còn trong công ty 3: tài liệu probe FIN-001, LEG-002.
8. KHOA-HOC-NAN có giá hẹn hiệu lực 2026-10-17 — kiểm tra hôm đó giá mới tự áp dụng.
9. M3b: hai câu "Đơn bao nhiêu tiền thì được freeship?" và "so hotline cua tiem" vẫn trượt.
