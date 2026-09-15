# ClawCompany v3 — Module Map

## Menu classification

### 1. Tổng quan
- **Trang chủ**: executive dashboard, Nina brief, company health, approvals, calendar.
- **Inbox**: unified notifications, mentions, requests, system events.

### 2. Tổ chức
- **Công ty**: multi-company management, health, financial, governance.
- **Phòng ban & Team**: teamspaces, goals, scoped knowledge, permissions.
- **Nhân sự**: human + AI memberships, roles, manager, access.
- **AI Workforce**: AI employee registry, lifecycle, performance, cost, runtime.
- **Org Map**: human + AI reporting hierarchy.

### 3. Công việc
- **Missions**: executive goals and outcomes.
- **Dự án**: project workspaces, team, files, reports, runtime mappings.
- **Nhiệm vụ**: board/list, review, dependencies, execution.
- **Workflows**: multi-step agent/human/tool processes.
- **Tự động hóa**: scheduled jobs and condition watches.

### 4. Tri thức
- **Knowledge Base**: scoped documents and semantic search.
- **SOP Library**: process versions, approvals, compliance.
- **Decisions**: decision records, alternatives, recommendations, impact.

### 5. Giao tiếp
- **Conversations**: internal/project/customer sessions.
- **Khách hàng**: customer portal, AI assignments, tenant boundaries.

### 6. Kiểm soát
- **Phê duyệt**: approval queue and policy engine.
- **Báo cáo**: executive/team/customer reports.
- **Analytics**: business/workforce/AI Ops metrics.
- **Activity & Audit**: immutable activity trail and security events.

### 7. Nền tảng
- **Integrations**: channels, SaaS, webhooks, data sources.
- **Skills & Tools**: skills, tools, MCP and policies.
- **OpenClaw Runtime**: gateway, agents, sessions, tasks, skills, plugins, logs.
- **Marketplace**: templates for employees, teams, companies, skills.
- **Billing**: plans, subscriptions, usage, AI costs, margin.
- **Settings**: organization, RBAC, security, tenant, notifications.

## Implemented frontend interactions
- Sidebar navigation grouped by product domain.
- Module tabs.
- Per-module KPI cards.
- Search/filter inside tables.
- Selectable rows with detail inspector.
- Command palette (Cmd/Ctrl + K).
- Global Create menu.
- Task Kanban.
- Org Map.
- Responsive layout.

## Backend boundaries prepared
Each module is structured so it can be connected to:
- Company API / Postgres
- OpenClaw Adapter / Gateway RPC
- Company plugin tools
- Knowledge/vector service
- Approval/policy engine
- Billing/metering service
- Audit/event bus
