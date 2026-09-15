# ClawCompany v7 — Execution & SaaS Layer

## What v7 adds

### 1. Knowledge retrieval
- persisted `KnowledgeChunk`
- deterministic `hash384` embedding provider for local/dev
- `KnowledgeVector`
- PostgreSQL `pgvector` extension
- HNSW cosine index
- vector search with organization/company/department/project scope
- SQLite fallback using the same vectors and Python cosine similarity

The hash embedding is a deterministic development embedding, not a substitute for a production semantic embedding model. The vector provider boundary is ready to replace it later.

### 2. Policy enforcement
`PermissionPolicy` is now executable rather than only stored metadata.

Decision states:
- `allow`
- `deny`
- `approval_required`

Approval-required policies automatically create/reuse a pending `Approval`.

### 3. Workflow executor
Supported step types:
- `note`
- `tool`
- `agent`
- `approval`

A workflow run can enter:
- `running`
- `waiting_runtime`
- `waiting_approval`
- `completed`
- `failed`

Runtime and approval steps are resumable through the workflow-run API.

### 4. Realtime OpenClaw runs
- start runtime run through ClawCompany
- stream a run using Server-Sent Events
- mock runtime emits progress events locally
- Gateway runtime uses configurable RPC/event names

OpenClaw protocol settings are isolated in environment variables so a runtime upgrade does not change Company Core.

### 5. Customer Portal
New `/portal` frontend and portal-specific authentication.

Customer view includes:
- assigned AI employees
- customer-visible projects
- plan / subscription
- usage
- internal AI cost reference

### 6. Usage + billing
- `UsageEvent`
- customer usage aggregation
- agent/task/run attribution
- draft invoice generation
- `BillingInvoice`

Payment-provider capture is intentionally separate from the Company accounting model.

### 7. Nina executive API
- `/api/nina/brief`
- `/api/nina/command`
- command log persistence
- dashboard Nina chat wired to backend

The v7 Nina intent layer is deterministic operational routing. A model-backed planner can replace/augment it later without changing the executive API.

### 8. OpenClaw Company Bridge
Stable Company-side tools:
- `company.context`
- `company.tasks.list`
- `company.task.status`
- `company.knowledge.search`
- `company.approval.request`
- `company.message.owner`

Exact OpenClaw plugin registration remains version-specific and stays outside Company Core.