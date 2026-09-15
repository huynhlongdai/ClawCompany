# ClawCompany v8 — Completion Matrix

`✅` means the v8 snapshot contains a concrete implementation surface. It does not mean the feature has completed production hardening.

| Capability | UI | API | Persistence | Execution / enforcement |
|---|---:|---:|---:|---:|
| Dashboard / Company OS shell | ✅ | ✅ | aggregate | ✅ |
| Companies / departments / people | ✅ | ✅ | ✅ | tenant-scoped |
| AI Workforce registry | ✅ | ✅ | ✅ | ✅ |
| AI employee hire / provisioning | ✅ | ✅ | ✅ | OpenClaw runtime adapter |
| Company Factory | ✅ | ✅ | ✅ | departments + AI employees |
| Nina objective planner | ✅ | ✅ | ✅ | task creation + delegation |
| Missions / projects / tasks | ✅ | ✅ | ✅ | task runtime dispatch |
| Workflow registry | ✅ | ✅ | ✅ | ✅ |
| Visual workflow DAG versions | ✅ | ✅ | ✅ | graph compiler |
| Workflow execution | ✅ | ✅ | ✅ | agent/tool/approval/note steps |
| Automations | ✅ | ✅ | ✅ | baseline |
| Knowledge / RAG | ✅ | ✅ | ✅ | pgvector + dev fallback |
| SOP / decisions | ✅ | ✅ | ✅ | tenant-scoped |
| Conversations | ✅ | ✅ | ✅ | ✅ |
| Customer management | ✅ | ✅ | ✅ | AI/project assignments |
| Customer Portal | ✅ | ✅ | ✅ | restricted customer surface |
| Customer ↔ AI chat | ✅ | ✅ | ✅ | session-aware runtime stream |
| Approvals / policies | ✅ | ✅ | ✅ | allow/deny/approval gate |
| Reports / analytics | ✅ | ✅ | ✅ | baseline |
| Activity / audit | ✅ | ✅ | ✅ | event feed |
| Runtime event history | UI via runtime/chat | ✅ | ✅ | automatic persistence |
| Usage metering | ✅ | ✅ | ✅ | event-driven meter rules |
| Billing / invoices | ✅ | ✅ | ✅ | baseline invoice model |
| Integrations / skills / tools | ✅ | ✅ | ✅ | registry |
| OpenClaw Company Bridge | docs/contracts | ✅ | API keys | scope-enforced |
| Auth / org access | ✅ | ✅ | ✅ | JWT + role checks |
| Authenticated org WebSocket | client-ready | ✅ | transient broker | tenant-validated |
| Marketplace templates | ✅ | ✅ | ✅ | Company/Agent factory input |
| Settings / roles / policies | ✅ | ✅ | ✅ | enforced on protected paths |

## v8 security changes

- Public registration cannot self-assign an organization or privileged role.
- Organization access is granted by an admin/owner endpoint.
- Machine API keys cannot satisfy human role checks.
- OpenClaw bridge endpoints require explicit API-key scopes.
- Core and extended internal APIs use active-organization validation.
- The organization WebSocket validates JWT identity and organization claims.
- Customer chat checks customer identity, active assignment, and tenant ownership.

## Remaining production gates

- exact OpenClaw Gateway RPC/event mapping for the deployed release
- reviewed explicit Alembic migrations rather than metadata `create_all`
- durable distributed realtime/event transport instead of the in-process broker
- hardened browser session/cookie strategy and CSRF design if cookies are used
- production embedding provider and retrieval evaluation
- financial-grade billing ledger/payment reconciliation
- container images, CI/CD, secrets manager, observability, backup/restore and load testing
