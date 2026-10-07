# M3 · Agent / Nhân sự AI — báo cáo

**Gate (gateway thật):** tạo agent trên UI → có trong `agents.list` và đủ 5 file; sửa SOUL trên UI → file trên gateway đổi;
sửa tay trên gateway → UI báo lệch; cho agent nghỉ → session được dọn sạch.
**Kết quả:** đạt trên VM với OpenClaw 2026.9.8 — `tools/gate_m3.py` **27/27** (mỗi bước đối chiếu độc lập bằng RPC
trực tiếp + đọc file trên đĩa container gateway, không tin phản hồi của ClawCompany). Agent "Hải Đăng" tuyển bằng
wizard trên UI (ảnh `hire-result`) có trong `agents.list`, tên tiếng Việt trên gateway, 5 file đủ.

## Đã làm
| Phần | Chi tiết |
|---|---|
| Wizard tuyển (4 bước) | Vai trò (tên, chức danh, nhiệm vụ) → Phòng ban (quản lý mặc định = trưởng phòng) → Model (`models.list` của gateway) & hạn mức USD/tháng → Tính cách (5 mẫu tiếng Việt) + điều người quản lý muốn. Tuyển = seat + `agents.create` + `agents.update {name, emoji}` + ghi đủ 5 file + hạn mức `scope=member, monthly` + quyền tool riêng (tuỳ chọn). Gateway từ chối → `needs_runtime`, giữ 5 file để "Đẩy lên" sau, không báo giả |
| Bản ClawCompany của 5 file | Bảng mới `agent_file_snapshots` (nội dung + SHA-256); mọi lần ghi từ UI (kể cả tab hồ sơ cũ `PUT /files`) đều cập nhật mốc |
| Sửa hồ sơ 2 chiều | `PATCH /api/agents/{id}/hr`: tên, chức danh, phòng ban (đổi phòng → quản lý mặc định trưởng phòng mới), quản lý (chống vòng), model, tính cách → ghi DB + `agents.update` + sinh lại IDENTITY/SOUL/AGENTS/USER. Hai chốt: file đã chỉnh tay trên UI thì giữ nguyên (nút "Sinh lại từ hồ sơ"); file bị sửa trên gateway thì không ghi đè, báo lệch |
| Lệch & "Đồng bộ lại" | `GET /drift`: tên, model, từng file (`in_sync / edited_on_gateway / missing_on_gateway / untracked`), kèm nội dung 2 bản để so (UI tô dòng khác). `POST /resync`: **đẩy lên** (ghi có `expectedHash` → không ghi đè mù nếu có người sửa tiếp) hoặc **nhận bản gateway**. MEMORY.md do agent tự ghi → không tính là lệch |
| Vòng đời | Tạm dừng (dừng lượt đang chạy, task về `todo`, abort phiên chạy) / Tiếp tục (kiểm roster; mất agent → `runtime_missing`) / **Cho nghỉ**: lưu 5 file → abort + `sessions.delete` phiên phụ → `agents.delete {deleteFiles}` (phiên main không xoá riêng được) → đếm lại; việc mở trả về phòng ban hoặc giao người khác; bỏ chức trưởng phòng; người báo cáo chuyển lên quản lý trên; khoá API key; đóng hạn mức riêng. Tuỳ chọn giữ agent (xoá phiên phụ + reset phiên main) |
| Chặn dispatch | `resolve_seat` từ chối seat `paused / retired / runtime_missing` (thông báo tiếng Việt); đối chiếu roster không còn ghi đè `paused/retired` thành `detached` (trước đây khớp lại sẽ âm thầm bật lại seat tạm dừng) |
| Quyền tool theo ghế | `GET /agents/{id}/tools`: mức hiệu dụng + nguồn (riêng ghế / bậc / mặc định); UI đổi từng tool cho ghế (admin), "Theo bậc" để bỏ ghi đè |
| UI | Tab **Nhân sự AI** trong `/app/team` (danh sách đối chiếu gateway + wizard); `/app/agents/[id]` thêm khối Hồ sơ nhân sự · Vòng đời · Đồng bộ với gateway · Quyền tool. 0 lỗi console/HTTP, không tràn ngang ở 390px |
| DB | Migration `0029_agent_file_snapshots` |

## Lỗi thật tìm được khi chạy gateway thật (đã sửa)
1. `agents.update {name|emoji}` **tự viết lại IDENTITY.md** (đọc trong `/app/dist/agents-*.mjs`) → chính thao tác đổi tên bị báo "sửa tay trên gateway" và IDENTITY không được sinh lại (gate lần 1: 25/27). Nay nhận bản gateway vừa viết làm mốc khi trước đó còn khớp; fake gateway trong test mô phỏng đúng hành vi này (test fail khi bỏ bản sửa).
2. Agent tạo bằng `agents.create` thừa hưởng `agents.defaults.model = {primary, fallbacks}` → trang hồ sơ cũ **sập trắng** ("Objects are not valid as a React child") và `model_drift` luôn báo lệch giả. Sửa cả UI (`modelOf`) và server (`model_str`).
3. Không chọn model khi tuyển → cột `agents.model` trống. Nay ghi model thật đang chạy từ roster.

## Kiểm chứng
- `tests/test_m3_agents.py` **17 passed**; full pytest **1042 passed, 2 skipped**; `tsc --noEmit` sạch.
- Mutation **15/15 bị bắt**: drift không so hash, bỏ chốt "sửa trên gateway", bỏ chốt "đã chỉnh tay", không nhận IDENTITY do `agents.update`, dispatch không chặn, nghỉ không xoá phiên phụ / không xoá agent / không chuyển người báo cáo / không khoá API key / không trả việc về phòng, đẩy lên ghi mù, không mặc định trưởng phòng, đối chiếu roster ghi đè paused, `PUT /files` không lưu mốc, MEMORY tính là lệch.
- Gate VM (`GATE_PASSWORD=… python3 tools/gate_m3.py`): xem `GATE_LOG`.

## Còn lại / ghi chú
- `tools.effective` của gateway cần `sessionKey` → quyền tool theo ghế hiện là lớp ClawCompany (lớp 2); lớp `tools.allow/deny` của gateway vẫn sửa ở tab Quyền của hồ sơ.
- Agent gate trên VM: `gate-m3-*` (đã nghỉ, đã gỡ khỏi gateway), "Mai Anh" (có lệch SOUL để minh hoạ), "Hải Đăng" (tuyển qua UI) trong Nova Fashion.

## Ảnh UI (VM, 0 lỗi console/HTTP)
`docs/screenshots/m3/`: team-ai, hire-1-role, hire-2-dept, hire-4-persona, hire-result, agent-drift, agent-retire-confirm, agent-retired, agent-mobile, team-ai-mobile.
