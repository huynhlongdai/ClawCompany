# UI v2 — báo cáo (nhánh `ui-v2`, chưa push)

Ngày 2026-10-14. Viết theo HANDOFF §7: chỉ ghi cái đã chạy và thấy; cái chưa kiểm chứng ghi là chưa.

## Tóm tắt thẳng

- 11 commit trên `ui-v2` từ `395acd0`. Backend **không đổi một dòng** (`git diff 395acd0..HEAD -- backend` rỗng). Không sửa test nào.
- Backend pytest: **1087 passed, 2 skipped** (454 s), đúng baseline.
- `npx tsc --noEmit` sạch, `next build` xanh (70 route).
- Chụp thật bằng Chromium 130 (Playwright 1.48) trên `next start` + uvicorn SQLite + `seed.py` + `tools/seed_ui_v2.py`: 35 trang × sáng/tối × 1440/390 = 140 ảnh, **0 lỗi console/HTTP ≥400/pageerror, 0 tràn ngang** (4 file `docs/screenshots/ui-v2/report-*.json`).
- **Chưa chạy với gateway OpenClaw thật** — mọi ảnh ở `OPENCLAW_MODE=mock`. Trang Cài đặt › OpenClaw vì thế hiện "Lỗi · Chế độ runtime: mock" và "không đọc được gateway" ở hồ sơ agent; đó là trạng thái thật của mock, không phải lỗi UI.
- **6 job nền của module Phòng thí nghiệm chưa tắt** (plan-v2-modules §2 yêu cầu tắt): `devcloud.cleanup_expired`, `v14.reap_runner_leases`, `v14.evaluate_slos`, `v14.review_portfolios`, `v15.control_plane_tick`, `v15.export_telemetry`. Lý do: phải sửa backend, ngoài phạm vi nhánh này. Cờ Lab hiện chỉ ẩn trang (localStorage `cc_lab` / `NEXT_PUBLIC_LAB=on`). Rủi ro còn đó: `control_plane_tick` ghi vào `approvals` nên có thể đẩy phê duyệt lạ vào Hộp việc.

## Đã đổi gì

1. **Một tầng token** (`design/brand/tokens.css`), font tự host, primitive `components/ui/*` (Button, Panel, Tabs, StatusPill, EmptyState, Field, Dialog, Skeleton, Toast). `app/styles/legacy.css` bắc cầu class cũ (`v8Card`, `panel`, `tmTable`…) sang token mới để trang chưa viết lại không vỡ.
2. **Một shell** trong layout: menu 8 mục (Hộp việc, Tổng quan, Công việc, Mục tiêu & Kế hoạch, Đội ngũ, Việc định kỳ, Chi phí, Cài đặt), ⌘K, breadcrumb, thanh dưới + ngăn kéo trên điện thoại, cờ Phòng thí nghiệm.
3. Trang viết lại trên hệ thống mới: Tổng quan "Hôm nay công ty làm gì", Hộp việc, Công việc (danh sách / bảng / dự án / side-peek), Mục tiêu & Kế hoạch (3 tab), Đội ngũ (sơ đồ cây + 5 tab), Việc định kỳ + Quy trình, Chi phí + Ngân sách, Cài đặt (Chung, OpenClaw, Kỹ năng, Bí mật, Thành viên, Phòng thí nghiệm), onboarding 4 bước, trang nhận lời mời, đăng nhập.
4. Lượt này (bước 3–4 của handoff):
   - **Hồ sơ agent** `/app/agents/[id]`: ba khối dài liền nhau (≈6000 px trên điện thoại) → 3 tab trên URL: *Đang làm gì* (AgentDetail) · *Nhân sự* (`?tab=hr`, AgentHRPanel) · *Cấu hình OpenClaw* (`?tab=openclaw`, SeatProfile). Logic ba component giữ nguyên; nút Tạm dừng / Cho nghỉ việc có viền (trước là ghost, nhìn như chữ trơn).
   - **Chi tiết việc** `/app/tasks/[id]`: nội dung trong `.panel` trước dính sát viền → trả lề 16 px; dòng tiêu đề đổi `trạng thái: in_progress · ưu tiên: high` thành nhãn tiếng Việt; 4 ô số gọn lại; lưới 2 cột inline → class `.tdCols`, co về 1 cột dưới 1100 px.
   - Mỗi trang đúng **một lượt**, không vòng lặp.

## Lỗi thấy trên ảnh chụp và đã sửa

| Thấy gì | Nguyên nhân | Sửa |
|---|---|---|
| Điện thoại: breadcrumb trên thanh trên chỉ còn một vệt "'", cạnh đó vừa có ô tìm kiếm vừa có nút kính lúp | `.ui-top .ui-search-btn{display:flex}` nằm SAU media query `display:none` nên thắng → ô tìm kiếm chiếm chỗ, breadcrumb bị ép 0 px | thêm media query sau quy tắc đó (`ui.css`) |
| Điện thoại: mũi tên "›" thừa trước tiêu đề breadcrumb | `Icon` đặt `display:block` inline | `.ui-crumbs > svg{display:none !important}` ≤420 px |
| Công việc (danh sách, cả 1440 và 390, sáng/tối): tiêu đề nhóm "Đang làm" đè lên dòng việc đầu tiên | `.wkList{overflow:hidden}` biến nó thành khung cuộn nên `position:sticky; top:52px` tính từ đỉnh danh sách | `overflow:clip` |
| Công việc 390: 3 bộ lọc bị cắt còn "Mọi", "Mọi p" | select co theo chip + nút Tạo việc trên cùng hàng | 3 select chia đều một hàng (`flex:1 1 28%`); "Mọi người nhận" vẫn hơi chạm mũi tên ở 390 px |
| Tổng quan 390: dải số có một ô xám trống | "Chi hôm nay" span cả hàng → lưới 2 cột lẻ 1 ô | bỏ span, thành lưới 2×2 |
| Tổng quan 390: bảng "Vừa chạy" cắt tên việc còn "#5 Lên…", cột Chi phí tràn | 6 cột trên 358 px | ẩn Ai làm / Lượt / Cập nhật ≤640 px |
| Đội ngũ 390: sơ đồ mở ở mép trái, nút gốc công ty nằm ngoài màn hình | khung cuộn ngang bắt đầu ở 0 | lần đầu render cuộn ra giữa |
| Việc định kỳ 390: "Chọn ở danh sách bên trái" (trên điện thoại không có "bên trái") | copy | "Chọn một routine trong danh sách để xem lần chạy." |
| Hồ sơ agent: trang quá dài, ba khối cũ chồng nhau | — | chia tab (trên) |
| Chi tiết việc: chữ và ô nhập dính sát viền khung | legacy `.panel{padding:0}` | trả lề (trên) |

Đã xem tận mắt (read_file từng ảnh / ghép tờ) các trang lõi ở 390 sáng, 1440 sáng, 1440 tối, 390 tối: Tổng quan, Hộp việc, Công việc list + board, Mục tiêu, Kế hoạch, Đội ngũ sơ đồ, hồ sơ agent (3 tab), Việc định kỳ, Chi phí, Cài đặt, Cài đặt › OpenClaw, onboarding, đăng nhập, chi tiết việc. Chế độ tối: không thấy chữ chìm nền; nút gốc sơ đồ tổ chức là khối sáng trên nền tối (cố ý, đảo màu chữ).

Còn thấy nhưng **chưa sửa** (nhỏ):
- Bảng Đối soát nhân sự ở Cài đặt › OpenClaw trên 390 px: pill "Đang hoạt động" ở cột cuối bị cắt mép; bảng cuộn ngang được trong khung, không tràn trang.
- Chi tiết việc 390: 4 ô số xếp 1 cột (lưới inline `minmax(168px,1fr)`), trang dài.
- Bảng quyền tool (tab Nhân sự): cột cuối "mặc định" xuống 2 dòng ở 1440.
- Ảnh fullPage ở 390 có thanh dưới (fixed) nằm giữa ảnh — đó là cách Playwright chụp phần tử fixed, không phải lỗi bố cục.

## Kết quả kiểm tra

- `cd backend && DATABASE_URL=sqlite:///./_test.db JWT_SECRET=test ../.venv/bin/python -m pytest -q` → `1087 passed, 2 skipped, 16019 warnings in 454.30s`.
- `npx tsc --noEmit` → 0 lỗi.
- `next build` (NEXT_PUBLIC_AUTH_REQUIRED=true, NEXT_PUBLIC_API_BASE=http://127.0.0.1:8000/api) → xanh; log đầy đủ `_reports/ui-v2-data/build-after.log`.
- Chụp: `node tools/shoot_ui_v2.mjs <light|dark> <desktop|mobile>` (Playwright cài ngoài repo ở `/tmp/pw`, symlink vào `node_modules/`; Debian 13 cần `apt-get install libatk1.0-0t64 libatk-bridge2.0-0t64 libatspi2.0-0t64 libxcomposite1 libxdamage1 libxrandr2 libgbm1 libxkbcommon0 libasound2t64 libnss3 libcups2t64`).

## Bundle trước / sau

Trước: `_reports/ui-v2-data/build-before.log` (build trước redesign; không rõ env NEXT_PUBLIC lúc đó — biến này gần như không đổi kích thước). Sau: `_reports/ui-v2-data/build-after.log`. Shared first-load không đổi: **87.2 kB → 87.2 kB**.

| Route | Trước: page | Trước: first-load | Sau: page | Sau: first-load | Δ first-load |
|---|---|---|---|---|---|
| `/` | 16.7 kB | 114 kB | 147 B | 87.4 kB | -26.6 kB |
| `/app/os` | 45.2 kB | 159 kB | 4.74 kB | 124 kB | -35.0 kB |
| `/app/inbox` | 5.2 kB | 119 kB | 4.59 kB | 118 kB | -1.0 kB |
| `/app/work` | 11.2 kB | 125 kB | 12.4 kB | 125 kB | +0.0 kB |
| `/app/tasks/[id]` | 6.98 kB | 126 kB | 8.86 kB | 121 kB | -5.0 kB |
| `/app/goals` | 2.27 kB | 121 kB | 5.29 kB | 122 kB | +1.0 kB |
| `/app/strategy` | 3.7 kB | 118 kB | 4.89 kB | 118 kB | +0.0 kB |
| `/app/nina` | 2.6 kB | 117 kB | 3.57 kB | 117 kB | +0.0 kB |
| `/app/team` | 5.65 kB | 128 kB | 8.27 kB | 129 kB | +1.0 kB |
| `/app/agents/[id]` | 6.55 kB | 129 kB | 7.34 kB | 128 kB | -1.0 kB |
| `/app/routines` | 4.39 kB | 119 kB | 4.78 kB | 118 kB | -1.0 kB |
| `/app/workflows` | 2.22 kB | 116 kB | 3.03 kB | 116 kB | +0.0 kB |
| `/app/costs` | 5.24 kB | 119 kB | 4.09 kB | 117 kB | -2.0 kB |
| `/app/openclaw` | 3.49 kB | 118 kB | 3.17 kB | 116 kB | -2.0 kB |
| `/app/settings` | — (chưa có) | — | 4.42 kB | 119 kB | mới |
| `/app/secrets` | 1.37 kB | 116 kB | 3.23 kB | 116 kB | +0.0 kB |
| `/app/agent-tools` | 4.31 kB | 119 kB | 3.63 kB | 112 kB | -7.0 kB |
| `/onboarding` | — (chưa có) | — | 7.47 kB | 115 kB | mới |
| `/invite/[token]` | 2.27 kB | 99.1 kB | 6.38 kB | 109 kB | +9.9 kB |

Đọc bảng: thắng lớn nhất là `/app/os` **159 kB → 124 kB** (page 45.2 kB → 4.74 kB, bỏ FounderCockpit cũ) và `/` 114 → 87.4 kB. Các trang khác dao động ±2 kB; `/invite/[token]` tăng 9.9 kB (trang lời mời viết lại ở 2cff85a; chưa phân tích chunk nào gây ra). Trung vị first-load trên 66 route có ở cả hai bản: 116 kB → 110 kB; route nặng nhất: trước `/app/os` 159 kB, sau `/app/team` 129 kB.

## Commit (từ `395acd0`)

```
6227cbf docs(ui): chụp lại ui-v2 — 35 trang × sáng/tối × 1440/390, 0 lỗi console, 0 tràn ngang
f6af022 feat(ui): hồ sơ agent chia 3 tab (Đang làm gì · Nhân sự · Cấu hình OpenClaw); chi tiết việc trả lề, nhãn tiếng Việt, 2 cột co về 1
c5be703 fix(ui): sửa lỗi thấy trên ảnh chụp — breadcrumb điện thoại bị ép 0px, tiêu đề nhóm sticky đè dòng đầu, bộ lọc Công việc cắt chữ, ô trống ở dải số Tổng quan, bảng Vừa chạy trên 390px, sơ đồ tổ chức mở giữa
40fadda fix(ui): sidebar full chiều cao, lưới Tổng quan, cột board co lại, .ui-grid; Mục tiêu tự chọn; seed + script chụp ảnh ui-v2
2cff85a feat(ui): onboarding 4 bước, trang nhận lời mời; sửa 5 trang trả về rỗng sau khi bỏ AuthGate
6e423e4 feat(ui): Việc định kỳ + tab Quy trình; Cài đặt › OpenClaw, Bí mật trên hệ thống mới
ab9bb01 feat(ui): Đội ngũ — sơ đồ tổ chức dạng cây, tab Agent/Người/Phòng ban/Đào tạo, hồ sơ agent
9793b15 feat(ui): Mục tiêu & Kế hoạch gộp tab — Mục tiêu · Kế hoạch chờ duyệt · Nina lập nhanh
a43e570 feat(ui): Tổng quan "Hôm nay công ty làm gì" + Hộp việc, Công việc, Chi phí trên hệ thống mới
957c93e refactor(ui): một shell trong layout, menu 8 mục, ⌘K, cờ Phòng thí nghiệm, điện thoại
125d05a feat(ui): một tầng token (tokens.css) + font tự host + primitive components/ui
```
(+ commit báo cáo này.) Tác giả: `Hark AI <ai@clawcompany.local>`. Chưa push.

## Ảnh chụp

`docs/screenshots/ui-v2/<trang>-<1440|390>-<light|dark>.jpg`, 35 trang × 4 = 140 ảnh, fullPage (trừ palette, đăng nhập, lời mời: chỉ khung nhìn). Trang:
tong-quan, hop-viec, cong-viec-list, cong-viec-board, cong-viec-peek, cong-viec-du-an, muc-tieu, ke-hoach, nina, doi-ngu-so-do, doi-ngu-agent, doi-ngu-nguoi, doi-ngu-dao-tao, agent-ho-so, agent-nhan-su, agent-openclaw, viec-dinh-ky, quy-trinh, chi-phi, chi-phi-ngan-sach, openclaw, cai-dat, phong-thi-nghiem, ky-nang, bi-mat, onboarding, lab-repositories, lab-control-center, khac-su-kien, khac-phong-hop, chi-tiet-viec, danh-ba, palette (⌘K / menu Thêm), dang-nhap, loi-moi.

Bốn ảnh nên xem trước: `tong-quan-1440-light.jpg`, `hop-viec-390-light.jpg`, `cong-viec-board-1440-dark.jpg`, `doi-ngu-so-do-1440-light.jpg`.

## 27 trang Phòng thí nghiệm

Danh sách này là **suy ra**: plan-v2-modules §2 nói "ẩn 27 trang" nhưng không liệt kê tên. Chọn theo nhóm plan nêu (giao phần mềm v11–v15 + điều hành v9/v10), nằm ở `lib/nav.ts` → `LAB_PAGES`. Route vẫn chạy, chỉ ẩn khỏi menu/⌘K khi cờ tắt.

- Giao phần mềm (14): /app/repositories, /app/delivery, /app/reviews, /app/cicd, /app/releases, /app/release-manager, /app/deployments, /app/progressive-delivery, /app/sandboxes, /app/workspaces, /app/workspace-gateway, /app/dev-cloud, /app/engineering, /app/portfolio
- Vận hành & tin cậy (9): /app/runners, /app/sre-control, /app/incidents, /app/observability, /app/telemetry-federation, /app/trust, /app/supply-chain, /app/production-trust, /app/secrets-federation
- Điều hành đời cũ (4): /app/control-center, /app/founder-cockpit, /app/autonomy, /app/simulation

## Kiểm kê lượt 2 (trước khi restyle) — `python3 tools/ui_inventory.py`

Kiểm kê tĩnh: mỗi route → component nó kéo vào (đệ quy) → số class còn lấy từ `legacy.css` và số chuỗi tiếng Anh trong JSX. "cũ" = còn ít nhất một class legacy hoặc một chuỗi tiếng Anh. 68 route `page.tsx`; **27 "mới", 41 "cũ"** lúc bắt đầu lượt này. 60 file component còn dùng class legacy.

legacy.css: 18871 byte, 217 class

| Route | Class legacy còn dùng | Chuỗi tiếng Anh (tĩnh) | Trạng thái |
|---|---|---|---|
| `/` | 0 | 0 | mới |
| `/app/agent-tools` | 11 | 0 | cũ |
| `/app/agents` | 18 | 4 | cũ |
| `/app/agents/[id]` | 20 | 0 | cũ |
| `/app/approve` | 0 | 0 | mới |
| `/app/artifacts` | 11 | 4 | cũ |
| `/app/autonomy` | 8 | 3 | cũ |
| `/app/budgets` | 0 | 0 | mới |
| `/app/cicd` | 9 | 2 | cũ |
| `/app/collaboration` | 10 | 0 | cũ |
| `/app/communications` | 8 | 0 | cũ |
| `/app/company-factory` | 12 | 3 | cũ |
| `/app/control-center` | 16 | 0 | cũ |
| `/app/costs` | 0 | 0 | mới |
| `/app/customers` | 14 | 0 | cũ |
| `/app/delivery` | 13 | 4 | cũ |
| `/app/deployments` | 10 | 2 | cũ |
| `/app/dev-cloud` | 10 | 3 | cũ |
| `/app/engineering` | 11 | 2 | cũ |
| `/app/events` | 12 | 2 | cũ |
| `/app/flow` | 0 | 0 | mới |
| `/app/founder-cockpit` | 14 | 2 | cũ |
| `/app/goals` | 7 | 0 | cũ |
| `/app/inbox` | 0 | 0 | mới |
| `/app/incidents` | 7 | 1 | cũ |
| `/app/knowledge-mesh` | 7 | 0 | cũ |
| `/app/live-runs` | 14 | 0 | cũ |
| `/app/marketplace` | 12 | 0 | cũ |
| `/app/memory` | 8 | 2 | cũ |
| `/app/nina` | 0 | 0 | mới |
| `/app/observability` | 9 | 2 | cũ |
| `/app/openclaw` | 0 | 0 | mới |
| `/app/os` | 1 | 0 | cũ |
| `/app/portfolio` | 9 | 2 | cũ |
| `/app/production-trust` | 12 | 4 | cũ |
| `/app/progressive-delivery` | 8 | 2 | cũ |
| `/app/quality` | 6 | 2 | cũ |
| `/app/release-manager` | 8 | 2 | cũ |
| `/app/releases` | 10 | 2 | cũ |
| `/app/reports` | 14 | 0 | cũ |
| `/app/repositories` | 10 | 6 | cũ |
| `/app/reviews` | 8 | 1 | cũ |
| `/app/routines` | 0 | 0 | mới |
| `/app/routing` | 11 | 0 | cũ |
| `/app/runners` | 12 | 4 | cũ |
| `/app/sandboxes` | 7 | 3 | cũ |
| `/app/secrets` | 0 | 0 | mới |
| `/app/secrets-federation` | 10 | 3 | cũ |
| `/app/settings` | 0 | 0 | mới |
| `/app/settings/lab` | 0 | 0 | mới |
| `/app/simulation` | 6 | 2 | cũ |
| `/app/sre-control` | 11 | 4 | cũ |
| `/app/strategy` | 0 | 0 | mới |
| `/app/supply-chain` | 8 | 2 | cũ |
| `/app/system` | 0 | 0 | mới |
| `/app/tasks/[id]` | 18 | 0 | cũ |
| `/app/team` | 10 | 0 | cũ |
| `/app/telemetry-federation` | 7 | 2 | cũ |
| `/app/trust` | 10 | 6 | cũ |
| `/app/work` | 0 | 0 | mới |
| `/app/workflows` | 0 | 0 | mới |
| `/app/workspace-gateway` | 9 | 3 | cũ |
| `/app/workspace-ops` | 15 | 1 | cũ |
| `/app/workspaces` | 8 | 3 | cũ |
| `/invite/[token]` | 0 | 0 | mới |
| `/onboarding` | 0 | 0 | mới |
| `/portal` | 10 | 3 | cũ |
| `/portal/chat` | 7 | 0 | cũ |


## Chưa làm / còn lại

- **6 job nền Lab chưa tắt** (xem trên) — cần cờ env ở backend; `lib/nav.ts` có `LAB_JOBS` ghi tên để làm sau.
- **Chưa chạy với gateway OpenClaw thật** — chỉ mock. Ảnh hồ sơ agent tab Cấu hình OpenClaw hiện khối lỗi "MockOpenClawRuntime has no attribute rpc" (mock không có RPC file); cần chụp lại với gateway thật.
- **Trang chưa restyle** (vẫn chạy nhờ `legacy.css` bắc cầu, nhìn đồng màu nhưng bố cục cũ): 27 trang Lab; /app/events, /app/collaboration, /portal, /portal/chat; ruột của SeatProfile (6 tab file/config), AgentHR (form, vòng đời, lệch, ma trận tool) và các khối phụ của chi tiết việc (Chặng duyệt, Liên kết, Lượt chạy, Đánh thức) — hồ sơ agent và chi tiết việc mới được một lượt bố cục, chưa viết lại từng khối trên `components/ui`.
- `tools/shot_seat.py` (công cụ cũ) giả định SeatProfile nằm ngay trên `/app/agents/{id}`; giờ ở `?tab=openclaw`. Không phải test, chưa sửa.
- Các lỗi nhỏ còn thấy trên ảnh (mục "chưa sửa" ở trên).

## Đợt hoàn thiện + i18n (2026-10-14, tối)

- Độ phủ route: **68/68** chạy trên giao diện mới (`tools/ui_inventory.py`); `legacy.css` 18.871 byte → **đã xoá**.
- i18n: từ điển có kiểu tự viết (`messages/vi.json` + `en.json`, 1843 khoá khớp nhau; thiếu khoá → `tsc` lỗi). Locale ở cookie `cc_locale` + `users.locale` (migration 0031, `PATCH /auth/me`). Ngày/số/tiền theo `Intl`. Số ít/số nhiều tiếng Anh bằng cú pháp `{p0:item|items}` trong `t()`.
- Backend trả lỗi theo `Accept-Language` (vi mặc định, en khi yêu cầu). Nhãn rủi ro, loại phê duyệt và hạn duyệt trong Hộp việc/Tổng quan dựng ở frontend theo locale (`lib/risk.ts`, `lib/approvalText.ts`), không còn dùng `risk_vi`/`kind_vi`/`deadline_vi`.
- Cờ `LAB_JOBS_ENABLED` (mặc định tắt) chặn 6 job Lab, có test hành vi.
- pytest: **1101 passed, 2 skipped, 1 failed**. Ca hỏng là `test_v36_insights.py::test_local_today_follows_the_configured_timezone`, phụ thuộc giờ chạy (10:00–12:00 UTC); chạy lại ngoài khung giờ đó thì xanh (16 passed). Không sửa test.
- `tsc` sạch, `next build` xanh. First-load: `/app/os` 124 kB, `/app/inbox` 117 kB, `/app/work` 125 kB, `/app/team` 128 kB, `/invite/[token]` 102 kB (trước 109 kB).
- Ảnh chụp (`docs/screenshots/ui-v2b/`): bản vi gồm 80 trang × 1440/390 × sáng/tối; bản en gồm 31 trang lõi ở 1440 và Hộp việc ở 390. **0 lỗi console/HTTP, 0 tràn ngang, 0 chữ Anh sót ở bản vi, 0 chữ tràn nút ở bản en.**

### Còn lại
- Thân 27 trang Lab và các trang phụ còn khoảng 566 chuỗi tiếng Việt viết cứng, chưa có bản en.
- Backend vẫn trả một số nhãn tiếng Việt cố định trong dữ liệu (`status_vi`, nguồn chi phí…). Dữ liệu seed cũng là tiếng Việt.
- Ca test phụ thuộc múi giờ nên được sửa riêng: cần anh duyệt vì đây là sửa test.
- Chưa chạy với gateway OpenClaw thật (chỉ chạy chế độ mock).
