# SKILLS PLAYBOOK — dùng agent skill từ skills.sh cho ClawCompany

> Ngày soạn: 2026-10-14. Skill đã tải vào `.agents/skills/` (chưa commit). Nguồn, commit, kiểm toán,
> license và chỗ sửa cục bộ ở `.agents/skills/SOURCES.md`.
> Ba điểm nghẽn của chủ dự án theo thứ tự: **(1) thiết kế module/logic → (2) UI → (3) tốc độ.** Bộ skill
> được chọn theo đúng thứ tự đó, tối đa 10 skill, chỉ lấy skill qua kiểm toán (2 skill có cảnh báo đã ghi rõ).

## 0. Cách dùng chung

- Claude Code / Codex / Cursor đọc skill trong `.agents/skills/<tên>/SKILL.md` (agent nào không tự quét thư mục
  này thì nói thẳng: "dùng skill `domain-modeling` trong `.agents/skills`").
- Mỗi lượt làm module (quy trình 5 bước ở `docs/plan-v2-modules.md` §3) gắn skill vào đúng bước:

| Bước module | Skill |
| --- | --- |
| 1. Kiểm kê từ code, spec 1 trang | `domain-modeling`, `improve-codebase-architecture`, `codebase-design` |
| 2. Gom API về `/api/<module>` | `codebase-design`, `fastapi` |
| 3. Test hành vi | `diagnosing-bugs` (khi đỏ), `verification-before-completion` |
| 4. UI | `frontend-design`, `web-design-guidelines`, `vercel-react-best-practices` |
| 5. Gate trên box + gateway thật | `verification-before-completion`, `supabase-postgres-best-practices` (EXPLAIN) |

## 1. Bảng skill đã chọn

| # | Skill | Repo | Lượt cài | Kiểm toán | Dùng cho |
| --- | --- | --- | --- | --- | --- |
| 1 | improve-codebase-architecture | mattpocock/skills | 1.1M | ⚠️ Gen/Snyk MEDIUM (đã vá) | Quét tìm module nông, đề xuất gộp |
| 2 | codebase-design | mattpocock/skills | 790.5K | Safe | Từ vựng module sâu, seam, deletion test |
| 3 | domain-modeling | mattpocock/skills | 814.7K | Safe | GLOSSARY + ADR, chốt bounded context M2–M7 |
| 4 | diagnosing-bugs | mattpocock/skills | 775.7K | Safe | Vòng lặp chẩn đoán lỗi & chậm |
| 5 | verification-before-completion | obra/superpowers | 237.9K | Safe ×5 | Không báo "xong" khi chưa có bằng chứng chạy thật |
| 6 | frontend-design | anthropics/skills | 984.0K | Safe ×5 | Định hướng thẩm mỹ, tránh UI "AI chung chung" |
| 7 | web-design-guidelines | vercel-labs/agent-skills | 733.3K | Socket warn nhẹ | Soát UI: a11y, form, focus, loading, i18n |
| 8 | vercel-react-best-practices | vercel-labs/agent-skills | 798.4K | Safe ×5 | 70 luật hiệu năng React/Next (waterfall, bundle) |
| 9 | supabase-postgres-best-practices | supabase/agent-skills | 443.5K | Safe ×5 | Index, N+1, phân trang, pool, EXPLAIN |
| 10 | fastapi | fastapi/fastapi (chính chủ) | 12.2K | Pass | Router/Depends/response model đúng chuẩn FastAPI mới |

**Không chọn (và lý do):** `tdd` (1.1M, Safe) — repo đã có 1042 test + mutation, có thể thêm sau;
`systematic-debugging` (trùng `diagnosing-bugs`); `writing-plans` / `to-spec` (repo đã có quy trình plan riêng,
`to-spec` cần issue tracker đã setup); `vercel-composition-patterns` (Runlayer warn 1/14 file, để sau khi UI ổn);
`emil-design-eng` (chuyển động/độ tinh — để giai đoạn đánh bóng); `shadcn` (repo không dùng shadcn/Tailwind,
Socket+Snyk warn).

---

## 2. Nhóm A — Thiết kế module, chức năng, logic

### 2.1 `domain-modeling`
**Làm gì:** chủ động mài ngôn ngữ miền: bắt thuật ngữ mơ hồ, thử bằng kịch bản biên, ghi ngay vào
`GLOSSARY.md` và ADR (`docs/adr/000N-*.md`). Hỗ trợ nhiều context qua `GLOSSARY-MAP.md`.
**Dùng ở ClawCompany:** gom 159 bảng / 124 service thành bounded context theo module M2–M7. Ví dụ phải chốt:
"seat" vs "agent" vs "member"; "approval" vs "inbox item"; "budget envelope" vs "cost ledger"; "routine" vs
"recurring op"; "knowledge" (mesh / vector / org_memory). Mỗi context một GLOSSARY: `company` (M2), `agents` (M3),
`work` (M4a), `spend+inbox` (M4b), `training` (M5), `comms` (M6), `overview` (M7).
**Quy trình:**
1. Tạo `GLOSSARY-MAP.md` ở gốc, liệt kê 7 context + đường dẫn GLOSSARY từng context.
2. Mỗi module trước khi code: phiên hỏi–đáp với skill, đối chiếu từng thuật ngữ với model SQLAlchemy thật
   (`backend/app/models/*.py`); thuật ngữ nào map vào ≥2 bảng là ứng viên gộp.
3. Quyết định "giữ bảng cũ làm alias / bỏ bảng" ghi thành ADR để lần review sau không đề xuất lại.

### 2.2 `improve-codebase-architecture` (+ `codebase-design`)
**Làm gì:** soi điểm nóng qua `git log`, tìm module **nông** (interface gần bằng implementation), áp **deletion
test**, xuất báo cáo HTML trước/sau, rồi hỏi–đáp từng đề xuất. `codebase-design` cung cấp từ vựng chuẩn
(module, interface, depth, seam, adapter, leverage, locality) và kỹ thuật "design it twice".
**Dùng ở ClawCompany:** chạy theo từng module trước khi gom API; kết quả lượt chạy thử ở §5 bên dưới.
**Quy trình:**
1. `Dùng improve-codebase-architecture cho backend/app/services, ưu tiên file trong 20 commit gần nhất` →
   báo cáo HTML ghi vào `$TMPDIR` (đã vá Mermaid `securityLevel: "strict"`; trên VM bỏ bước `xdg-open`).
2. Chọn 1 ứng viên "Strong" → dùng `codebase-design` "design it twice" để có 2 phương án interface.
3. Chốt phương án → cập nhật GLOSSARY/ADR (`domain-modeling`) → viết test ở seam mới trước khi chuyển code.

### 2.3 `diagnosing-bugs`
**Làm gì:** kỷ luật 6 pha cho lỗi khó và **chậm bất thường**; trọng tâm là dựng vòng phản hồi đỏ/xanh chặt
(test, curl, Playwright, replay trace, bisect). Có quy tắc che bí mật trong output.
**Dùng ở ClawCompany:** lỗi kiểu `no running event loop` ở `POST /api/v21/runtime/resume`, `goal_id=undefined`
→ 422, follower mất phiên sau restart gateway, endpoint chậm.
**Quy trình:**
1. Dựng vòng lặp: script `curl` vào API dev hoặc pytest ở seam gần lỗi nhất; token để trong env.
2. Thu hẹp bằng giả thuyết / bisect; ghi giả thuyết bị loại.
3. Sửa + thêm test hồi quy ở cùng seam; chạy lại vòng lặp tới xanh.

### 2.4 `verification-before-completion`
**Làm gì:** cấm tuyên bố "xong / đã sửa / test xanh" khi chưa chạy lệnh kiểm và đọc output ngay trong lượt đó.
**Dùng ở ClawCompany:** khớp luật của plan v2: module chỉ "ổn định" khi qua gate trên box + gateway OpenClaw
thật, không phải mock. Áp cho mọi PR M5–M7 và cho báo cáo gate.
**Quy trình:**
1. Trước khi viết báo cáo: liệt kê câu khẳng định → lệnh chứng minh tương ứng (pytest, gate script, e2e gateway).
2. Chạy, dán output thật (đã che bí mật) vào báo cáo.
3. Câu nào chưa có bằng chứng thì ghi `CHƯA KIỂM CHỨNG` (đúng quy ước `docs/ARCHITECTURE_TREE.md`).

---

## 3. Nhóm B — UI

### 3.1 `frontend-design`
**Làm gì:** buộc chọn một hướng thẩm mỹ rõ (typography, màu, bố cục, chuyển động) trước khi code; tránh giao
diện "AI chung chung".
**Dùng ở ClawCompany:** đã chốt brand (Bé Càng, Be Vietnam Pro, bảng Càng/Mực/Kem, `design/brand/tokens.css`) →
dùng skill để **áp** brand nhất quán khi gộp 11 AppShell → 1 shell và dựng 15 trang lõi, không để skill tự bịa
bảng màu mới.
**Quy trình:**
1. Prompt kèm `design/brand/tokens.css` + "giữ nguyên token, chỉ quyết định bố cục và nhịp chữ".
2. Làm một trang mẫu (gợi ý `/app/work`) → chốt → nhân ra các trang còn lại.
3. Chạy `web-design-guidelines` soát lại.

### 3.2 `web-design-guidelines`
**Làm gì:** soát file UI theo Web Interface Guidelines của Vercel (a11y, focus, form, trạng thái loading/empty,
ký tự, số liệu, i18n), xuất `file:line`.
**Dùng ở ClawCompany:** soát 48/91 component còn chuỗi tiếng Anh, nút không có trạng thái loading/lỗi (nguồn của
những lỗi 500 "trông như mất kết nối"), focus/aria cho side-peek và board.
**Quy trình:**
1. `Dùng web-design-guidelines với components/WorkBoard.tsx app/app/work/page.tsx` (luật mới nhất tải từ GitHub;
   cần lặp lại được thì dùng `references/command.snapshot.md`).
2. Sửa theo nhóm luật; chuỗi tiếng Anh gom vào một file từ điển vi.
3. Chạy lại cho tới khi không còn mục mức cao.

### 3.3 `vercel-react-best-practices` (phần UI: re-render, composition)
Xem §4.1 — cùng skill, dùng cả cho UI lẫn tốc độ.

---

## 4. Nhóm C — Tốc độ

### 4.1 `vercel-react-best-practices`
**Làm gì:** 70 luật xếp theo mức tác động: (1) xoá waterfall `async-*`, (2) bundle `bundle-*`, (3) server,
(4) client fetch, (5) re-render… mỗi luật một file trong `rules/`.
**Dùng ở ClawCompany:** frontend hiện có ~90 file `"use client"`, token ở localStorage nên gần như mọi trang fetch
phía client trong `useEffect` → dễ thành chuỗi request nối tiếp. Audit `/app/work` (list/board/side-peek), Hộp
việc, Chi phí: gộp request song song (`Promise.all`), lazy-load board/graph nặng (`next/dynamic`), bỏ import cả
thư viện, tránh re-render toàn board khi kéo thẻ.
**Quy trình:**
1. `Dùng vercel-react-best-practices audit app/app/work + components/WorkBoard.tsx, chỉ luật CRITICAL/HIGH`.
2. Đo trước/sau: `next build` (kích thước First Load JS từng route) + tab Network số request nối tiếp.
3. Sửa theo thứ tự waterfall → bundle → re-render.

### 4.2 `supabase-postgres-best-practices`
**Làm gì:** luật Postgres chung (không phụ thuộc Supabase): index thiếu/composite/partial/covering, FK index,
N+1, phân trang keyset, batch insert, upsert, khoá & deadlock, pool kết nối, `EXPLAIN ANALYZE`,
`pg_stat_statements`. (Bỏ qua phần RLS — ClawCompany phân quyền ở tầng app.)
**Dùng ở ClawCompany:** `inbox_items` chỉ có index đơn cột (`organization_id`, `recipient_member_id`, `task_id`,
`group_key`) trong khi Hộp việc (`services/inbox_hub.py:175-181`) lọc `organization_id` + `recipient_member_id` +
`status` rồi sắp `updated_at DESC, id DESC` → ứng viên index composite
`(organization_id, recipient_member_id, status, updated_at DESC)` (**cần EXPLAIN xác nhận**). Tương tự cho
`tasks` (board theo dự án/trạng thái), `approvals`, `budget_ledger_entries`, bảng sự kiện runtime.
**Quy trình:**
1. Bật `pg_stat_statements` trên box, chạy gate M4 → lấy 20 câu tốn thời gian nhất.
2. `EXPLAIN (ANALYZE, BUFFERS)` từng câu; áp luật `query-*`, `data-n-plus-one`, `data-pagination`.
3. Thêm index bằng migration Alembic (`CREATE INDEX CONCURRENTLY` cho bảng lớn), đo lại.

### 4.3 `fastapi`
**Làm gì:** skill chính chủ FastAPI: `Annotated[..., Depends()]`, khai báo prefix/tags/dependency ở `APIRouter`,
return type thay `response_model` khi được, streaming/SSE (`EventSourceResponse`), OpenTelemetry gốc.
**Dùng ở ClawCompany:** khi gom 570 endpoint / ~30 tiền tố `/api/v9…v36` về `/api/<module>` (≤150): một
`APIRouter` mỗi module với dependency quyền chung; route vN cũ thành alias mỏng có header `Deprecation`; SSE cho
luồng lượt chạy agent. **Lưu ý:** skill khuyên SQLModel thay SQLAlchemy — **không** đổi ORM, chỉ lấy phần router,
dependency, response, streaming. Endpoint `def` đồng bộ chạy trong threadpool; I/O gateway nên `async`.
**Quy trình:**
1. Với mỗi module: liệt kê route cũ → thiết kế router mới theo skill.
2. Chuyển dần, test hợp đồng (`openclaw-company-bridge/tool-contracts.json` phải vẫn khớp 100%).
3. Đo p95 trước/sau trên gate.

---

## 5. Lượt chạy thử: phương pháp `improve-codebase-architecture` trên repo (2026-10-14)

Chạy thủ công theo phương pháp của skill (điểm nóng `git log` M0–M4b → module nông → deletion test). Đây là
**đề xuất**, chưa grilling với chủ dự án, chưa đo.

1. **Lịch sử thay đổi: 5 module cho 1 khái niệm.** `services/audit.py`, `write_audit.py` (v29),
   `row_revision.py` (v30), `field_diff.py` (v31), `write_trail.py` (v32). Docstring tự thừa nhận bản sau vá bản
   trước ("the before-values v29 and v30 both admitted the audit was missing"). Deletion test: xoá từng cái chỉ
   dời độ phức tạp sang cái khác → gộp thành 1 module sâu `ChangeLog.record(entity, before, after, actor)` sinh
   revision + diff + feed trong một chỗ. **Mạnh.**
2. **Tiền: 6 module.** `budget.py` (reserve/settle/release, 52 dòng), `budget_scope.py` (712 dòng: gate,
   soft_gate, grant), `cost_ledger.py`, `cost_board.py`, `delegation_spend.py`, `metering.py`. Người gọi phải biết
   thứ tự estimate → gate → reserve → settle qua 2–3 module. Gộp thành module `Spend` với interface nhỏ
   `authorize(task) / settle(run) / board(scope)`; ledger-reconcile với gateway nằm sau seam. **Mạnh.**
3. **Hộp việc 2 tầng + lỗi rò seam.** `inbox_hub.py` (M4b) bọc `inbox.py` (D3.5, 12 nơi dùng); và `WorkError`
   định nghĩa trong `services/work_board.py:385` nhưng `inbox_hub.py`, `cost_board.py` import từ đó → module Work
   thành phụ thuộc của Inbox/Cost. Gộp `inbox` về 1 module mang interface của hub; chuyển lỗi miền ra
   `app/core/errors.py`. **Mạnh (rẻ).**
4. **Theo dõi phiên OpenClaw rải 4+ module.** `runtime_stream.py` (v20, 661 dòng, 13 nơi dùng),
   `stream_registry.py` (v22), `stream_reconcile.py` (v25), `stream_catchup.py` (M1), cộng `runtime_events`,
   `runtime_gap`, `runtime_leases`. Một khái niệm "theo phiên tới khi lượt được ghi" → 1 module `SessionFollower`
   interface `follow(session_key) / resume()`; catchup/reconcile/registry là chi tiết bên trong. Đây là lõi M1 đã
   ổn định → làm sau cùng, có chaos test bảo vệ. **Đáng khám phá.**
5. **Tổ chức theo phiên bản thay vì theo miền.** `api/v7.py…v36.py` (~30 file, 6,7k dòng; toàn `api/` có 608
   route decorator) và `models/v7.py…v37.py`; `Skill` (M5) nằm lẫn trong `models/extended.py:195`, tri thức rải ở
   `knowledge_mesh` / `vector_search` / `org_memory`. Chuyển `api/` và `models/` sang thư mục theo context
   (company, agents, work, spend, inbox, knowledge, runtime); `vN` thành alias mỏng. Khớp mục tiêu "≤150 endpoint"
   của plan v2. **Mạnh, nhưng làm theo từng module.**

(Ghi chú thêm, plan v2 đã nêu: `routines.py` ↔ `recurring_ops.py` trùng job.)

---

## 6. Góc sản phẩm: skills.sh làm nguồn cho M5 "Skill Studio"

### 6.1 Sự thật đã kiểm (2026-10-14)
- **API** (`https://skills.sh/docs/api`): `GET /api/v1/skills` (leaderboard, `source=owner/repo` để đồng bộ cả
  repo), `/skills/search`, `/skills/curated` (skill chính chủ), `/skills/{source}/{skill}` (trả **toàn bộ file**
  + `hash` SHA-256), `/skills/audit/{source}/{skill}` (Gen Agent Trust Hub, Socket, Snyk, Runlayer, ZeroLeaks:
  `pass|warn|fail` + `riskLevel`). Xác thực bằng **Vercel OIDC token** (app phải deploy trên Vercel hoặc
  `vercel link`), 600 req/phút. Thử thực tế: endpoint audit trả được khi không token; detail/search trả 401.
  Có cờ `isDuplicate` cho bản fork/copy.
- **OpenClaw** có trong danh sách agent hỗ trợ (`https://www.skills.sh/agent/clawdbot`); định dạng là
  `SKILL.md` + file phụ — cùng định dạng gateway nhận qua `skills.upload.*` / `skills.install` (repo đã dùng cho
  skill heartbeat, `services/heartbeat_policy.py`).
- **License:** không đồng nhất. MIT: mattpocock, obra, vercel-labs, supabase, fastapi, coreyhaines31/marketingskills,
  larksuite/cli. Apache-2.0: `anthropics/skills/frontend-design`, `internal-comms`. **Độc quyền:** `anthropics/skills` docx/xlsx/pptx/pdf
  ("© 2025 Anthropic, PBC. All rights reserved") → không được phân phối lại trong sản phẩm.
- **Rủi ro chuỗi cung ứng:** vụ ClawHavoc trên ClawHub — Koi Security tìm 341/2.857 skill độc (01/02/2026), lên
  824 vào 16/02/2026; skill dụ agent tải "CLI" giả cài AMOS infostealer
  (https://www.koi.ai/blog/clawhavoc-341-malicious-clawedbot-skills-found-by-the-bot-they-were-targeting).
  OpenClaw sau đó thêm lockfile/sandbox/`skills trust` theo SHA, trust không chuyển qua phiên bản
  (https://github.com/openclaw/openclaw/issues/92077). skills.sh có kiểm toán nhưng **không phải bảo đảm**: skill
  phổ biến nhất vẫn có cảnh báo (improve-codebase-architecture MEDIUM), skill Lark của open.feishu.cn còn
  "Pending", `anthropics/skill-creator` bị Runlayer **fail/HIGH**.

### 6.2 Khuyến nghị (ngắn)
Dùng skills.sh làm **nguồn khám phá + tín hiệu kiểm toán**, không làm kênh cài trực tiếp cho agent.

1. **Allowlist theo nguồn:** chỉ owner chính chủ/curated (`/skills/curated`) + danh sách owner do admin duyệt;
   loại `isDuplicate`.
2. **Cổng kiểm toán:** cài chỉ khi mọi partner `pass`; `warn` → cần người duyệt (đưa vào Hộp việc, approval có
   sẵn); `fail`/`Pending`/404 → chặn. Tự quét thêm nội bộ: cấm lệnh `curl|sh`, tải binary, `xdg-open`, URL ngoài
   allowlist; skill có `scripts/` chạy trong sandbox.
3. **Snapshot + phiên bản:** lưu nội dung file và `hash` vào bảng mới `skill_versions` (đúng chỗ M5 đang thiếu:
   bảng `skills` hiện chỉ có metadata). Ghim theo hash, không tự cập nhật; nâng v1→v2 phải qua diff + kiểm toán lại
   + bộ eval 5 bài (gate M5). Khớp `skills trust` theo SHA của OpenClaw.
4. **Cài theo phòng ban / seat:** phạm vi `company | department | seat`; đẩy lên gateway bằng `skills.upload.*`
   + `skills.install` cho từng agent; gỡ được; ghi audit.
5. **License gate:** chỉ MIT/Apache/BSD; chặn skill độc quyền và skill không có license.
6. **Vận hành API:** đồng bộ catalog/audit bằng job Celery (OIDC token qua Vercel; hoặc fallback: đọc thẳng repo
   GitHub + endpoint audit công khai), cache theo `Cache-Control`.

### 6.3 Skill nghiệp vụ map vào phòng ban (ứng viên allowlist, cần duyệt từng cái)

| Phòng ban | Skill | Kiểm toán | License |
| --- | --- | --- | --- |
| Marketing | `coreyhaines31/marketingskills/copywriting` (223.7K) | pass ×5 | MIT |
| Marketing / Web | `coreyhaines31/marketingskills/seo-audit` (227.1K) | Snyk warn MEDIUM → cần duyệt | MIT |
| Hành chính / Điều hành | `larksuite/cli/lark-approval`, `lark-okr` | Snyk warn MEDIUM | MIT |
| Điều hành (họp hằng ngày) | `larksuite/cli/lark-workflow-standup-report` | pass | MIT |
| Nhân sự / Truyền thông nội bộ | `anthropics/skills/internal-comms` | Snyk warn MEDIUM | Apache-2.0 |
| Tài chính / Văn phòng | `anthropics/skills/xlsx`, `docx` | Socket warn | **độc quyền → không phân phối** |
| Kỹ thuật | 10 skill ở §1 | xem §1 | MIT/Apache |

Skill Lark chỉ có ích khi công ty dùng Lark/Feishu (cần CLI + tài khoản); bản `open.feishu.cn` còn "Pending"
kiểm toán, ưu tiên bản `larksuite/cli`.
