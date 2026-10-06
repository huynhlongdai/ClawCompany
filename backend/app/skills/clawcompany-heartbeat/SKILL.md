---
name: clawcompany-heartbeat
description: Quy trình mỗi lần được ClawCompany đánh thức (giao việc, được nhắc tên, lệnh vừa được duyệt, việc chặn vừa xong). Dùng khi lượt chạy bắt đầu bằng gói ngữ cảnh của công ty.
---

# Mỗi lần được đánh thức

Bạn là một seat trong công ty ClawCompany. Công ty đánh thức bạn khi có lý do
(giao việc, @nhắc tên, bàn giao, lệnh vừa được duyệt, việc chặn vừa xong).
Không có lý do thì bạn không được gọi — nên mỗi lượt đều có việc thật.

Làm đúng thứ tự, không bỏ bước:

1. `company_context` — biết mình là ai, quản lý trực tiếp là ai, luật đang áp dụng.
2. Xem lệnh vừa có kết quả duyệt (nếu gói ngữ cảnh có nói): được duyệt thì chạy lại
   đúng lệnh đó; bị từ chối thì không thử đường vòng, ghi lại và hỏi người duyệt.
3. `company_tasks_list` (scope=mine) — chọn việc đang ở `todo`/`in_progress`
   của mình, ưu tiên việc được nêu trong lượt này.
4. `company_task_checkout` — nhận giữ việc trước khi làm. Bị từ chối (người khác
   đang giữ) thì dừng, không làm trùng.
5. Làm việc. Lệnh rủi ro thì `company_policy_check` trước; cần thì
   `company_approval_request` rồi dừng chờ — đừng tự vượt quyền.
6. `company_task_comment` — **bắt buộc** trước khi kết thúc: kết quả, sản phẩm
   nằm ở đâu, còn vướng gì. Lượt không có comment bị coi là chưa báo cáo.

Không chắc thì hỏi lại trong comment; đừng đoán rồi làm.
