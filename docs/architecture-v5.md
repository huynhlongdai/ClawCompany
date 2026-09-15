# ClawCompany v5 — Complete Module Architecture

## Layering

Next.js UI
→ ClawCompany API (FastAPI)
→ Company Core (SQLAlchemy/Postgres)
→ Services
   - Audit/Event
   - Workflow
   - Knowledge
   - Billing
   - Policy
→ OpenClaw Adapter
→ OpenClaw Gateway / Plugin

## Tenancy
All business resources are scoped by `organization_id`, `company_id`, or `customer_id`.
Customer isolation uses `tenant_key` and assignment records.

## RBAC baseline
- `RoleBinding`
- `PermissionPolicy`
- approval-required actions
- organization settings

## Execution
Company Task → Agent business record → OpenClaw runtime agent → task/run/session IDs.

## Customer SaaS
Customer → Subscription → Assigned Agent(s) → customer knowledge scope → portal.

## Audit
Create actions in extended modules automatically write an `AuditEvent`.
High-risk runtime actions should also call the same service.

## Remaining production hardening
- JWT/OAuth/SAML authentication
- Alembic migrations
- background worker/queue
- object storage
- pgvector / vector DB
- Redis
- realtime streaming
- payment provider
- actual OpenClaw RPC contracts