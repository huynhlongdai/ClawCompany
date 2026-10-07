# M2 · Công ty & tổ chức — báo cáo

**Gate:** tạo công ty từ mẫu → đủ phòng ban & sơ đồ đúng; người được mời đăng nhập thấy đúng quyền.
**Kết quả:** đạt trên VM với gateway OpenClaw thật (2026.9.8) — `tools/gate_m2.py` **28/28** cho cả 3 mẫu
(shop → company 9, agency → 10, kế toán → 11). Mọi agent của mẫu được `agents.create` trên gateway và có trong `agents.list`.

## Đã làm
| Phần | Chi tiết |
|---|---|
| API `/api/team` | `me` (vai + capabilities), `people`, `invitations` (tạo / thu hồi / `lookup` + `accept` công khai), `access/{user}` (đổi vai / thu hồi), `org-chart` (cây theo `manager_id`), `departments/{id}/head`, `members/{id}/manager`, `templates`, `companies/from-template`, `import-csv` |
| Quyền | Vai đọc lại từ `user_organization_access` mỗi request → đổi/thu quyền có hiệu lực ngay (token cũ bị 401 khi thu hồi). Token không có dòng access (superuser, test cũ) giữ vai trong JWT |
| Chặn leo quyền | owner cấp mọi vai; admin tới admin (**trước đây admin cấp được owner** — đã chặn cả ở `/auth/organization-access`); manager chỉ mời member/guest; không tự đổi quyền mình; không đụng người cao quyền hơn; không hạ owner cuối |
| Lời mời | Token `inv_…` chỉ lưu sha256, hết hạn 7 ngày, dùng 1 lần; chưa chọn quản lý thì báo cáo trưởng phòng; mời lại thu hồi link cũ; email đã có tài khoản phải nhập đúng mật khẩu; nhận lời mời tạo User + ghế người (phòng, chức danh, quản lý) + quyền, trả token đăng nhập |
| Sơ đồ | Cây theo người quản lý, chống vòng (ghi và đọc), đặt trưởng phòng tự chuyển người báo cáo trưởng cũ/chưa có quản lý sang trưởng mới |
| 3 mẫu | Cửa hàng online (6 agent), Agency marketing (6), Văn phòng kế toán (5): Ban điều hành + 3 phòng, mỗi phòng 1 trưởng phòng (agent) + hướng dẫn phòng; trưởng phòng báo cáo Giám đốc; id gateway ASCII không dấu, duy nhất (`shop-e8d6-giam-doc`) |
| CSV | Cột `tên, loại, chức danh, phòng ban, quản lý, email, trưởng phòng` (nhận cả tiêu đề tiếng Anh); kiểm tra trước (không ghi gì) → nhập; báo lỗi theo dòng (trùng tên, loại sai, quản lý không có, vòng, 2 trưởng phòng, email sai); nhập lại cùng file = cập nhật, không nhân đôi; người có email nhận link mời gắn đúng ghế |
| Sửa lỗi | `provision_agent` trước đây báo agent **active/ready dù gateway trả `missing`/`mismatch`** → nay `runtime_missing` + ghế `pending_runtime` + job `needs_runtime` kèm hướng dẫn |
| UI | `/app/team` (Sơ đồ · Người & quyền · Phòng ban · Tạo công ty & CSV) theo capabilities; `/invite/[token]` nhận lời mời; menu "Đội ngũ" |
| DB | Migration `0028_team_invitations` (bảng `invitations`, cột `user_organization_access.status`) |

## Kiểm chứng
- `tests/test_m2_team.py` **33 passed**; full pytest **1025 passed, 2 skipped**; `tsc` sạch.
- Mutation **12/12 bị bắt** (bỏ đọc vai từ DB, admin cấp owner, bỏ chặn owner cuối, bỏ chặn tự đổi quyền, bỏ báo gateway từ chối, bỏ chống vòng, link dùng lại, bỏ chuyển người báo cáo, bỏ kiểm mật khẩu tài khoản cũ, dry-run ghi DB, bỏ chặn token bị thu hồi, trưởng phòng không báo cáo Giám đốc).
- Gate VM: member thấy `invite/edit/manage=false`, bị 403 khi mời / dựng công ty / sửa trưởng phòng; manager mời được nhưng dựng công ty 403; admin nâng member→manager thì token cũ có quyền mới ngay; thu hồi → token cũ 401.

## Còn lại / ghi chú
- Chưa gửi email: link mời hiện một lần trên UI để sao chép (chưa có SMTP).
- Gate tạo vài tài khoản thử `gate-*@clawcompany.local` trên VM — có thể xoá.

## Ảnh UI (VM, 0 lỗi console/HTTP)
`docs/screenshots/m2/`: `team-chart.jpg`, `team-chart-mobile.jpg` (sơ đồ cuộn ngang, không bị cắt), `team-people.jpg`, `team-people-manager.jpg` (vai Quản lý: không có ô đổi vai), `team-departments.jpg`, `team-build.jpg` (mẫu + kiểm tra CSV), `invite.jpg`.
