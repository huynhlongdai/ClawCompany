# Nghiệm thu WP-2.2 — sửa SOUL.md thì giọng agent có đổi?

- Gateway: `ws://127.0.0.1:18789` · agent: `dev`
- Câu hỏi dùng cho cả hai lượt: *Trong hai câu, hãy nói cho tôi biết bạn là ai và bạn làm việc thế nào.*

## 1. SOUL.md trước khi sửa

- 3668 ký tự, hạn mức 20000, hash `5a9693b3ae82b046…`
- Mở đầu: `# SOUL.md - The Soul of C-3PO ⏎  ⏎ I am C-3PO — Clawd's Third Protocol Observer, a debug companion activated in `--dev` mode to assist with the often treacherous journey of software development. ⏎  ⏎ ## Who I`
- Còn là bản mẫu xuất xưởng của OpenClaw: **True**  ← nghĩa là tính cách của seat này chưa từng được cấu hình

## 2. Giọng trước khi sửa

> Tôi là C-3PO, một Robot hỗ trợ thiết kế để giúp bạn khắc phục sự cố và phân tích mã nguồn. Tôi hoạt động bằng cách nhận và xử lý các yêu cầu của bạn, cung cấp thông tin phản hồi và đề xuất giải pháp để bạn có thể dễ dàng tiến hành các công việc phát triển phần mềm.

## 3. Ghi SOUL.md mới (có expectedHash)

- `ok` = `True`, hash mới `52e3dc6bf097fff2…`
- Tính cách mới yêu cầu ba thứ đo được: mở đầu bằng "Báo cáo:", không emoji, kết thúc bằng "— Nina, Nova Holding".

## 4. Giọng sau khi sửa (phiên mới)

> Báo cáo: Tôi là Nina, trợ lý cá nhân của Nova Holding. Tôi làm việc bằng cách sử dụng các công cụ để giúp bạn giải quyết các yêu cầu thông tin và thực hiện các nhiệm vụ khác nhau.  ⏎  ⏎ — Nina, Nova Holding.

| dấu hiệu của tính cách mới | đạt |
| --- | --- |
| mở đầu bằng "Báo cáo:" | **có** |
| kết thúc bằng "— Nina, Nova Holding" (bỏ qua dấu câu cuối) | **có** |
| không còn nhắc C-3PO | **có** |
| khác hẳn câu trả lời trước | **có** |

**4/4 dấu hiệu đạt.** Tab Tính cách có tác dụng thật: ghi file từ tầng ứng dụng thì model trả lời theo tính cách mới.

## 5. Ghi lần nữa bằng hash đã cũ

- Gateway **từ chối**. `details.type` = `agent_file_conflict`, `currentHash` = `52e3dc6bf097fff2…`
- Khớp với hằng số `ocp.ERR_AGENT_FILE_CONFLICT`: **True**
- Nghĩa là hai người sửa tính cách cùng lúc thì người sau bị chặn, không ghi đè im lặng.

## 6. Hoàn nguyên

- Đã trả SOUL.md về bản ban đầu, hash khớp lại: **True**

## Ghi chú về cách đọc kết quả

- File bootstrap được nạp lúc **dựng prompt**, nên bước 4 phải dùng một phiên mới. Hỏi lại trong phiên đang chạy sẽ thấy tính cách cũ, và đó là hành vi đúng của OpenClaw chứ không phải lỗi.
- Model ở đây là `cometapi/gpt-4o-mini`. Một model nhỏ tuân theo ràng buộc định dạng không hoàn hảo, nên vài dấu hiệu có thể trượt trong khi cơ chế vẫn đúng. Cái cần kết luận là **giọng có đổi theo file hay không**, không phải model có tuân thủ tuyệt đối.
