# v17 — UI Design Canvas & Workspace Cockpit

## 1. Why

The mockup (Trình bày "AI Organization OS") describes a business product: Trang chủ, Công ty,
Phòng ban, Nhân sự, AI Agents, Dự án, Nhiệm vụ, Kiến thức. Until v16 those screens existed
only as hardcoded demo arrays in `components/ClawCompanyApp.tsx`, while every shipped route was
an infrastructure console. v17 closes that gap from both sides:

- a **design canvas** that pins down the visual language extracted from the mockup, so future
  screens stop drifting;
- a **workspace cockpit** (API + UI) that serves the same screens from real tenant data.

## 2. Design canvas

`design/clawcompany-ui-canvas.html` — a single self-contained HTML file, no build step, no network.
Open it directly or render it headless with `chromium --headless --screenshot=...`.

Sections:

1. **Design tokens** — palette (cream paper `#faf7f2`, warm ink `#1b1a17`, terracotta accent
   `#c2703d`, semantic ok/warn/risk/info), type scale, radii, shadow.
2. **Screen 01 · Trang chủ** — full app shell: 248px dark sidebar with labelled nav groups and
   count badges, search bar, Nina hero, 5-metric strip, holding tree with four company cards,
   recent-projects table and agent activity feed.
3. **Screen 02 · AI Agents** — agent card grid (success rate, 30-day cost, risk) plus the detail
   table with runtime IDs.
4. **Screen 03 · Collaboration Room (v16)** — three-column layout: seats with the current turn
   highlighted, append-only transcript with turn types, delegation contracts and the state-machine
   strip.
5. **Screen 04 · Knowledge Mesh (v16)** — spaces with classification, the effective-permission
   ladder with its contributing sources, and the access log including denied attempts.
6. **Implementation notes** — canvas section → React component → endpoint mapping.

The canvas is a specification, not a shipped page: it is intentionally static HTML so it can be
reviewed, screenshotted and diffed without running the Next.js app.

## 3. Workspace cockpit API

`backend/app/api/v17.py` + `backend/app/services/workspace_cockpit.py`. Read-only aggregates,
**no new tables and no migration** — v17 reads the entities that have existed since v1.

| Endpoint | Screen | Returns |
| --- | --- | --- |
| `GET /api/v17/workspace/overview` | Trang chủ | org header, KPI block, company cards with member/agent/project counts |
| `GET /api/v17/workspace/org-chart` | Sơ đồ tổ chức | holding → company → department → member tree |
| `GET /api/v17/workspace/companies/{id}` | Công ty | departments with heads and headcount, human/agent split, projects |
| `GET /api/v17/workspace/people?member_type=&company_id=` | Nhân sự / AI Agents | directory with company and department names; agent rows carry model, success rate, 30-day cost, risk |
| `GET /api/v17/workspace/projects?company_id=` | Dự án | projects with task roll-up (total / open / done / by status) |
| `GET /api/v17/workspace/tasks?status=&assignee_member_id=` | Nhiệm vụ | tasks joined with project, company and assignee names |
| `GET /api/v17/workspace/knowledge?company_id=` | Kiến thức | classic knowledge documents (the v16 mesh keeps its own console) |

All endpoints require scope `company.context:read` and resolve the tenant from the principal via
`active_org`; the company detail endpoint additionally calls `enforce_org` on the loaded company,
so a valid token from another organization gets a 403 rather than a cross-tenant read.

The aggregates avoid N+1 queries: counts are grouped once per screen and joined in Python against
id→name maps.

## 4. Frontend

- `components/V17AppShell.tsx` — sidebar with the three nav groups from the canvas.
- `components/WorkspaceCockpit.tsx` — tabbed cockpit (Trang chủ / Công ty / Nhân sự / AI Agents /
  Dự án / Nhiệm vụ / Kiến thức) that loads all seven datasets in parallel and renders real rows.
  Empty states and API errors are shown as-is; there is no silent fallback to demo data.
- Routes: `/app/os`, and the v16 routes `/app/collaboration`, `/app/knowledge-mesh`.
- `lib/api.ts` — `apiV16` (28 methods) and `apiV17` (7 methods).

## 5. Validation

The sandbox has no network, so Python and Node dependencies cannot be installed.

- ✅ `python3 -m compileall backend/app backend/tests backend/alembic/versions` — OK.
- ✅ `chromium --headless --screenshot` renders the design canvas — the file is valid, standalone HTML.
- ⚠️ `backend/tests/test_v17_workspace_cockpit.py` (9 tests: tenant-scoped KPIs, company cards,
  company detail, agent enrichment, project roll-up, task joins and filters, knowledge scoping,
  org chart nesting, empty organization) is written but **not executed**.
- ❌ Not run: `alembic upgrade head`, `pytest`, `uvicorn`, `npm run build`.

Run on a networked machine:

```bash
cd backend && pip install -r requirements.txt && alembic upgrade head && pytest tests/test_v17_workspace_cockpit.py -q
npm install && npm run build
```

## 6. Known gaps

- The cockpit is read-only; creating companies, members and tasks still goes through the v1 CRUD
  endpoints and has no UI in this console yet.
- `ClawCompanyApp.tsx` still contains the original demo dashboard. It is left intact so the old
  landing page keeps working; `/app/os` is the real-data replacement.
- Revenue and customer-growth figures in the canvas hero are illustrative; there is no revenue
  model in the schema yet.
