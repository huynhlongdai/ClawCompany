# Gate G4 — vòng vận hành: giao → tự chạy → review → done

Task #38 (06/10/2026, gateway OpenClaw 2026.9.8 thật, model giả có kịch bản):

1. Người giao việc cho seat Nina trên bảng (`/api/v18/workspace/tasks/38/assign`). **Không ai bấm dispatch.**
2. Hàng wakeup (D2.1) gộp 10 s rồi tự gửi `chat.send`; follower gắn ngay sau đó.
3. Agent chạy lệnh (exec được duyệt qua Hộp việc — D1.1), tự ghi báo cáo vào sổ qua MCP (D1.5).
4. Run kết thúc → `review`; chặng review (D2.2) giao cho Long.
5. Long yêu cầu sửa → agent được đánh thức lại (`changes_requested`) và tự làm lại → Long duyệt → `done`.

Tổng 29,4 giây. **Chi phí thật $0,33855** (2 lượt), khớp `sessions.usage` của gateway 0,00%.
Chi tiết: `execution-policy-e2e.md`, `wakeups-e2e.md`, bằng chứng `evidence/d22/`.

Còn thiếu để G4 trọn vẹn theo kế hoạch: chặn ngân sách ba nấc (D2.3).
