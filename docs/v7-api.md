# v7 API additions

## Knowledge
- `POST /api/knowledge/vector-search`

## Policy
- `POST /api/policies/check`

## Workflow execution
- `POST /api/workflow-runs/{workflow_id}/start`
- `POST /api/workflow-runs/{run_id}/advance`
- `GET /api/workflow-runs/{run_id}`

## Runtime
- `POST /api/runtime/run`
- `GET /api/runtime/runs/{run_id}/events` (SSE)
- `GET /api/runtime/protocol`

## Usage / billing
- `POST /api/usage/events`
- `GET /api/usage/customers/{customer_id}/summary`
- `POST /api/billing/invoices`
- `GET /api/billing/invoices`

## Customer portal
- `POST /api/portal/users`
- `POST /api/portal/auth/login`
- `GET /api/portal/me`
- `POST /api/customers/{customer_id}/projects`

## Nina
- `GET /api/nina/brief`
- `POST /api/nina/command`

## OpenClaw Company Bridge
- `GET /api/company-tools/context`
- `GET /api/company-tools/tasks`
- `POST /api/company-tools/tasks/{task_id}/status`
- `POST /api/company-tools/knowledge/search`
- `POST /api/company-tools/approval/request`
- `POST /api/company-tools/message/owner`