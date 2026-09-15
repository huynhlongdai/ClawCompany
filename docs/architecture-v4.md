# ClawCompany v4 — Full-stack Architecture

## Runtime boundary

Frontend (Next.js)
→ Company API (FastAPI)
→ Company Core / Postgres
→ OpenClaw Adapter
→ OpenClaw Gateway / Plugin

## Implemented backend domains

### Organization Core
- organizations
- companies
- departments
- members

### AI Workforce
- agent business metadata
- OpenClaw runtime binding
- lifecycle / model / performance / cost / risk
- runtime health

### Project Execution
- projects
- tasks
- AI task dispatch
- mapping:
  - company_task_id
  - runtime_task_id
  - runtime_run_id
  - runtime_session_key

### Knowledge
- organization/company/department/project scope
- access level
- basic text search
- indexed state

### Approvals
- requester
- approver
- policy key
- risk
- evidence
- approve/reject resolution

## OpenClaw Adapter

Two modes are included:

- `OPENCLAW_MODE=mock`
  - works immediately
  - generates mock task/run/session IDs
- `OPENCLAW_MODE=gateway`
  - WebSocket/RPC boundary
  - isolate exact RPC mapping in `backend/app/runtime/gateway.py`

The Gateway adapter intentionally does NOT leak OpenClaw-specific objects into Company Core.

## API surface

- GET/POST `/api/organizations`
- GET/POST `/api/companies`
- GET/POST `/api/departments`
- GET/POST `/api/members`
- GET/POST `/api/agents`
- GET `/api/agents/runtime/health`
- GET/POST `/api/projects`
- GET/POST `/api/tasks`
- POST `/api/tasks/{id}/dispatch`
- GET/POST `/api/knowledge`
- GET `/api/knowledge/search?q=...`
- GET/POST `/api/approvals`
- POST `/api/approvals/{id}/resolve`

## Next backend phases

1. Auth + RBAC + tenant isolation
2. Team memberships
3. Missions / workflows
4. Knowledge embeddings/vector search
5. Event bus + audit trail
6. Customer portal and tenant assignments
7. Billing/metering
8. Realtime run streaming from OpenClaw
