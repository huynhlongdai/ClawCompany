# Nguồn gốc các skill trong `.agents/skills/`

Tải ngày 2026-10-14 bằng `git clone --depth 1` (không dùng `npx skills add`), chưa commit.
Số lượt cài lấy từ bảng xếp hạng https://www.skills.sh/ cùng ngày. Kiểm toán lấy từ
`GET https://skills.sh/api/v1/skills/audit/{source}/{skill}` (endpoint này trả về được khi không có token).

| Skill (thư mục) | Nguồn (repo @ commit) | Đường dẫn gốc | Lượt cài | Kiểm toán (Gen / Socket / Snyk / Runlayer / ZeroLeaks) | License |
| --- | --- | --- | --- | --- | --- |
| improve-codebase-architecture | mattpocock/skills @ 49dd158 | skills/engineering/improve-codebase-architecture | 1.1M | **warn MEDIUM** / pass / **warn MEDIUM** / pass / pass | MIT |
| codebase-design | mattpocock/skills @ 49dd158 | skills/engineering/codebase-design | 790.5K | pass / pass / pass LOW | MIT |
| domain-modeling | mattpocock/skills @ 49dd158 | skills/engineering/domain-modeling | 814.7K | pass / pass / pass LOW | MIT |
| diagnosing-bugs | mattpocock/skills @ 49dd158 | skills/engineering/diagnosing-bugs | 775.7K | pass / pass / pass LOW | MIT |
| verification-before-completion | obra/superpowers @ bb92a77 | skills/verification-before-completion | 237.9K | pass ×5 | MIT |
| frontend-design | anthropics/skills @ dbd4588 | skills/frontend-design | 984.0K | pass ×5 | Apache-2.0 (LICENSE.txt) |
| web-design-guidelines | vercel-labs/agent-skills @ 063bee9 | skills/web-design-guidelines | 733.3K | pass / **warn (gptAnomaly)** / pass / pass / pass | MIT (README repo) |
| vercel-react-best-practices | vercel-labs/agent-skills @ 063bee9 | skills/react-best-practices | 798.4K | pass ×5 | MIT (khai báo trong SKILL.md) |
| supabase-postgres-best-practices | supabase/agent-skills @ c9be0e9 | skills/supabase-postgres-best-practices | 443.5K | pass ×5 | MIT |
| fastapi | fastapi/fastapi @ f5c6e9b | fastapi/.agents/skills/fastapi | 12.2K | pass ×4+ | MIT |

## Sửa cục bộ (local patch)

1. `improve-codebase-architecture/HTML-REPORT.md`: đổi `mermaid.initialize({... securityLevel: "loose"})` thành
   `"strict"`. Đây đúng là điểm Gen Agent Trust Hub cảnh báo (nội dung lấy từ codebase có thể chạy script trong
   trình duyệt khi render sơ đồ). Ngoài ra skill này tự `xdg-open` file HTML: trên máy chủ/VM thì bỏ bước mở,
   chỉ ghi file.
2. `web-design-guidelines/references/command.snapshot.md`: bản chụp luật từ
   `https://raw.githubusercontent.com/vercel-labs/web-interface-guidelines/main/command.md` ngày 2026-10-14.
   SKILL.md gốc tải luật mới mỗi lần chạy (nguồn của cảnh báo Socket); dùng bản chụp khi muốn kết quả lặp lại được.
3. Đã bỏ thư mục `agents/` (file `openai.yaml` dành cho Codex) khỏi các skill của mattpocock.

## Phụ thuộc giữa các skill

- `improve-codebase-architecture` gọi `codebase-design` (có sẵn) và `grilling` (KHÔNG tải; nếu cần:
  `mattpocock/skills/skills/productivity/grilling`, kiểm toán Safe/Low). Không có `grilling` thì
  bước 3 (grilling loop) làm thủ công bằng hỏi–đáp.
- `tdd`, `diagnosing-bugs`, `domain-modeling` đọc `GLOSSARY.md` và `docs/adr/` nếu có.

## Cập nhật

So `hash` của skill qua `GET /api/v1/skills/{source}/{skill}` (cần Vercel OIDC token) hoặc `git log` của repo
nguồn; đọc diff trước khi chép đè.
