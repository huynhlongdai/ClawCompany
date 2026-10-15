# So sánh nhánh origin/ui-v5, origin/ui-v6 với ui-v2 (chỉ đọc, 16/10/2026)

`git fetch origin ui-v5 ui-v6 main` rồi so bằng `merge-base` / `rev-list` / `log`. **Không merge, không push** gì lên hai nhánh này.

## Kết luận

**Cả hai nhánh đã nằm trọn trong ui-v2 — không còn gì để port, không có xung đột.**

| Nhánh | Đầu nhánh | Tác giả / ngày (commit cuối) | Là tổ tiên của ui-v2? | ui-v2 đi trước | Có commit nào ui-v2 chưa có? |
|---|---|---|---|---|---|
| `origin/ui-v5` | `aabb93f` | Rudi `<rruddi5432@gmail.com>`, 2026-09-23 | **có** (`merge-base --is-ancestor` = đúng) | 159 commit | **0** |
| `origin/ui-v6` | `a3dfc4f` | "Notion AI" `<ai@notion.local>`, 2026-10-05 | **có** | 151 commit | **0** |
| `origin/main` (tham chiếu) | `e2ea31a` | huynhlongdai, 2026-10-07 (Merge PR #6 M4a) | có | — | 0 |

ui-v5 cũng đã là tổ tiên của `origin/main` (0 commit ngoài main). ui-v6 = ui-v5 + 8 commit (gồm merge `b52d539`
"Merge origin/ui-v5 into ui-v6" và 6 commit WP-1.1…WP-4.3 của huynhlongdai ngày 15–16/9), cũng đã vào main/ui-v2.

## Mỗi nhánh chứa gì

**ui-v5** (19 commit trong lịch sử: huynhlongdai 16, boxd agent 2, Rudi 1). Commit riêng cuối:
- `aabb93f` (Rudi, 23/9) "UI v5: theme hợp nhất theo sơ đồ Elera, tài khoản lên góc phải topbar, dựng lại Work Flow board" —
  5 file, +405/−10: `app/theme-v2.css`, `components/WorkFlowBoard.tsx`, sửa `components/V17AppShell.tsx`…
- `20b6667`, `e4efcfc` (boxd agent, 22/9): sửa 17 test do môi trường, bỏ qua `celerybeat-schedule`.

**ui-v6** — commit riêng `a3dfc4f` (Notion AI, 5/10) "UI v6: một AppShell cho mọi route, sổ điều hướng tiếng Việt, ⌘K,
Hộp việc, danh bạ công cụ, viết lại Bảng việc theo trạng thái thật" — 29 file, +1490/−558 (`components/AppShell.tsx`,
`CommandPalette.tsx`, `HomeRailIfHome.tsx`, `app/v6.css`, `lib/nav.ts`, `lib/counts.ts`, `WorkspaceCockpit.tsx`…).

## Những gì của hai nhánh đã bị ui-v2 thay thế (để biết, không cần làm gì)

UI v2 (14/10, commit `125d05a` "một tầng token (tokens.css) + font tự host + primitive components/ui" và M4a/M4b) đã
viết lại shell, nên các file sau của v5/v6 **không còn trong ui-v2** — chủ ý, không phải mất mát:
`app/theme-v2.css` (v5), `components/AppShell.tsx`, `components/CommandPalette.tsx`, `components/HomeRailIfHome.tsx`,
`app/v6.css` (v6). ⌘K, sổ điều hướng, Hộp việc của v6 đã có bản mới trong ui-v2 (shell một lớp, 8 mục nav, ⌘K, `/app/inbox`).

## Đáng dọn (tuỳ anh)

- `components/WorkFlowBoard.tsx` (v5) và `components/V17AppShell.tsx` vẫn còn trong ui-v2 nhưng **không file nào import**
  → code chết, xoá được trong một commit dọn dẹp.
- Hai nhánh `ui-v5`, `ui-v6` trên GitHub chỉ còn giá trị lịch sử; có thể xoá nhánh từ xa khi anh muốn (em không đụng).
- Tác giả "Notion AI `<ai@notion.local>`" và "Rudi" là người/agent ngoài lượt của em — nếu anh không nhận ra họ, nên kiểm
  tra quyền ghi repo.
