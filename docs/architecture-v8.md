# ClawCompany v8 — Operating System Layer

v8 turns the v7 execution/SaaS foundation into a more complete operating system for running an AI-first company.

## Core flows

### AI Employee hiring

```text
Founder / Manager
      ↓
Hire AI Employee
      ↓
AgentProvisioningJob
      ↓
Member (employment identity)
      ↓
Agent (runtime identity)
      ↓
AgentRuntime.create_agent()
      ↓
OpenClaw / mock runtime
      ↓
ready | failed
```

The business identity (`Member`) remains separate from the runtime binding (`Agent`). Runtime-specific fields stay behind `AgentRuntime`.

### Company Factory

```text
Company Template Manifest
      ↓
CompanyProvisioningJob
      ↓
Company
      ↓
Departments
      ↓
AI Members + Agents
      ↓
OpenClaw provisioning
```

A template can define departments and agents. The factory records partial success rather than pretending an install is atomic across a remote runtime.

### Nina planner / delegation

```text
Founder objective
      ↓
NinaExecutionPlan
      ↓
NinaPlanStep[]
      ↓
Role-to-owner matching
      ↓
Company Task[]
      ↓
AgentRuntime dispatch
```

The v8 planner is deterministic on purpose. It provides stable orchestration semantics now and leaves room for a model-backed planning engine later.

### Customer chat

```text
CustomerPortalUser
      ↓
CustomerChatBinding
      ↓
Conversation + Messages
      ↓
Assigned CustomerAgentAssignment
      ↓
AgentRuntime.run_agent(session_key=...)
      ↓
OpenClaw runtime session
      ↓
SSE runtime events
      ↓
RuntimeEvent persistence + usage metering
```

Only agents explicitly assigned to the customer can be selected by that customer.

### Workflow visual builder

`WorkflowGraphVersion` stores immutable graph snapshots. Publishing a graph updates the executable `Workflow.definition_json`.

The graph validator enforces:
- unique node IDs
- valid edge endpoints
- directed acyclic graph (DAG)

The visual editor is intentionally implemented without a third-party canvas dependency in v8.

## Tenant security hardening

v8 adds tenant checks to the core and extended API surfaces. Lists are scoped to the credential's active organization and create/update operations validate related resources before mutation.

Public registration now creates only a user identity. Organization membership and role elevation require `/api/auth/organization-access` from an admin/owner credential.

API keys no longer bypass human roles. Machine integrations use explicit scopes through `require_scope()`.

OpenClaw Company Bridge scopes:
- `company.context:read`
- `company.tasks:read`
- `company.tasks:write`
- `company.knowledge:read`
- `company.approvals:write`
- `company.messages:write`

WebSocket organization events require a valid JWT whose `org_id` matches the requested organization.

## Runtime event persistence and metering

Every streamed runtime event can be persisted to `runtime_events` and matched against `usage_meter_rules`.

A rule can record:
- internal unit cost
- whether the event is customer billable
- customer unit price

This is a metering foundation, not a final accounting system. Invoices still need production-grade period filtering, taxes, credits, provider reconciliation, and immutable ledger rules before real money should depend on them.

## OpenClaw compatibility boundary

The gateway RPC names remain environment configurable:

```env
OPENCLAW_RPC_CREATE_AGENT=
OPENCLAW_RPC_RUN_AGENT=
OPENCLAW_RPC_CANCEL_RUN=
OPENCLAW_RPC_GATEWAY_STATUS=
OPENCLAW_RPC_SUBSCRIBE_RUN=
```

v8 also adds session continuity to `AgentRuntime.run_agent(..., session_key=...)`.

These names are placeholders until mapped to the exact OpenClaw build deployed by the operator.

## Frontend routes

- `/` — existing approved Company dashboard shell
- `/app/agents` — AI Workforce registry + hiring
- `/app/company-factory` — company template provisioning
- `/app/nina` — objective planning + delegation
- `/app/workflows` — versioned workflow graph builder
- `/portal` — customer portal
- `/portal/chat` — customer ↔ assigned AI employee chat

## Remaining production gaps

v8 is not production-complete. Important remaining work includes:
- reviewed explicit Alembic migrations instead of metadata-driven additive migrations
- HttpOnly session/cookie strategy (current internal frontend still stores JWT in localStorage)
- CSRF strategy if cookie auth is adopted
- durable distributed event bus instead of in-process event broker
- idempotency keys and retry/resume semantics for remote provisioning
- real embedding provider and retrieval quality evaluation
- exact OpenClaw Gateway contract mapping for the deployed version
- persistent runtime stream cursor/reconnect behavior
- secrets manager and key rotation
- production deployment images (no `--reload`, no runtime package installation)
- customer billing ledger / payment provider webhook verification
