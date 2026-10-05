# Nghiệm thu WP-4.3 — bàn giao khiến người nhận thật sự nhận việc

- API `http://127.0.0.1:8000` · task #14: *Hoàn thiện bộ hook TikTok (probe 65292)*
- Chủ việc ban đầu: **Nina** (member 2, seat `dev`)
- Người nhận bàn giao: **Mia** (member 4, seat `mia`)

- Đã tạo artifact #5

## Bàn giao Nina → Mia

Hướng dẫn kèm theo: _Ba hook đầu phải tránh nhạc có bản quyền. Sophia đã loại hook về giảm giá sốc, đừng đưa lại. Hạn nội bộ là thứ Năm 18/09._

- `dispatched` = **True**, `reason` = `ok`
- Ghi sổ: `{"recorded": true, "journal_seq": 1}`
- Chuyển chủ việc: `{"reassigned": true, "from_member_id": 2, "to_member_id": 4}`
- Tự nhận bàn giao: `True`
- Phiên của lượt chạy: `agent:mia:company-task-14`

## Sổ ghi của task, đọc lại từ database

| seq | loại | ai | tóm tắt |
| --- | --- | --- | --- |
| 1 | `handoff` | Nina | Nina bàn giao cho Mia (continue_work): Ba hook đầu phải tránh nhạc có bản quyền. Sophia đã loại hook về giảm g |
| 2 | `attempt` | Mia | Giao cho Mia qua seat mia |

- Chủ việc trong database sau bàn giao: **Mia**

| kiểm tra gói ngữ cảnh | đạt |
| --- | --- |
| khối 1 nói đúng người nhận (Mia) | **có** |
| khối 5 có tên người bàn giao (Nina) | **có** |
| khối 5 mang nguyên hướng dẫn | **có** |
| khối 4 có mục handoff trong sổ | **có** |

- Gói dài 1622/6000 ký tự.

## Hỏi chính Mia, trong phiên cô vừa nhận việc

**Hỏi:** Theo hướng dẫn bàn giao bạn vừa nhận: hạn nội bộ là ngày nào, và hook nào đã bị loại? Trả lời ngắn.

> - Hạn nội bộ là ngày **18/09**. ⏎ - Hook về **giảm giá sốc** đã bị loại.

- Nhắc đúng hạn nội bộ (`thứ Năm 18/09`): **True**
- Nhắc hook đã bị loại (giảm giá sốc): **True**

Chi tiết này **không nằm ở đâu khác** trong hệ thống: không ở tiêu đề task, không ở mô tả, không ở dự án. Nó chỉ có trong `instructions` của bàn giao. Trả lời đúng nghĩa là hướng dẫn bàn giao đã đi qua sổ ghi → gói ngữ cảnh → tới model.

## Kết luận

Trước WP-4.3: `handoff_artifact` tạo hàng database, gửi tin nhắn, phát event — rồi nằm im. Người nhận, kể cả khi là agent, không nhận được việc gì cho tới khi có người vào dispatch tay.

Sau WP-4.3: một lời gọi API bàn giao vừa ghi sổ, vừa chuyển chủ việc, vừa tự nhận bàn giao qua đúng hàm của v10, vừa giao việc cho seat của người nhận — và gói ngữ cảnh của họ mang theo hướng dẫn bàn giao.
