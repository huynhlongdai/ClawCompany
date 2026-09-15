# ClawCompany v6 — Production Foundation

## Added

### Authentication
- User table
- JWT login/register
- Password hashing
- User ↔ Organization access
- `/api/auth/me`
- Hashed API keys + scopes
- Optional frontend AuthGate

### Tenant / RBAC baseline
- JWT active organization + role
- Principal dependency
- `require_role(...)`
- `enforce_org(...)`
- role order: guest < member < manager < admin < owner

### Background jobs
- Redis
- Celery
- async knowledge indexing
- async OpenClaw task dispatch
- background job persistence

### Knowledge pipeline
- persisted document chunks
- chunking worker
- provider-neutral embedding fields
- ready for pgvector/external embedding service

### Realtime
- organization WebSocket event broker skeleton
- `/api/ws/events/{organization_id}`

### Reliability / security
- liveness and readiness probes
- DB, Redis and runtime health
- request IDs
- security headers

### Database migrations
- Alembic configured
- baseline migration included

### Docker stack
- PostgreSQL
- Redis
- FastAPI API
- Celery worker

## Before production
Replace the baseline metadata migration with a reviewed explicit Alembic migration:

```bash
alembic revision --autogenerate -m "initial production schema"
```
