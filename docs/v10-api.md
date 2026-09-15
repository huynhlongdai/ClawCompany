# ClawCompany v10 API

Base prefix: `/api/v10`.

## Event bus

```text
POST /events
GET  /events
POST /events/{event_id}/dispatch
POST /triggers
GET  /triggers
GET  /trigger-executions
```

Agent/API-key scopes:

```text
company.events:read
company.events:write
```

## Agent message bus

```text
POST /messages
GET  /messages
POST /messages/{message_id}/read
```

Scopes:

```text
company.messages:read
company.messages:write
```

## Artifact Registry and Handoff

```text
POST /artifacts
GET  /artifacts
GET  /artifacts/{artifact_id}
POST /artifacts/{artifact_id}/handoff
GET  /handoffs
POST /handoffs/{handoff_id}/accept?member_id=...
POST /artifacts/{artifact_id}/materialize
POST /artifacts/{artifact_id}/evaluate
GET  /evaluations
```

Scopes for agent-facing read/write endpoints:

```text
company.artifacts:read
company.artifacts:write
```

Example source artifact:

```json
{
  "organization_id": 1,
  "company_id": 1,
  "created_by_member_id": 4,
  "bundle_key": "checkout-fix-42",
  "logical_path": "src/payments/service.ts",
  "name": "service.ts",
  "artifact_type": "source_code",
  "mime_type": "text/typescript",
  "content_text": "export function ..."
}
```

Example handoff to a Commit Agent:

```json
{
  "to_member_id": 9,
  "from_member_id": 4,
  "purpose": "commit",
  "instructions": "Validate tests, materialize this exact version, then commit to the assigned branch."
}
```

## QA and SLA

```text
POST /sla-profiles
GET  /sla-profiles
POST /sla/check
GET  /sla-incidents
POST /artifacts/{artifact_id}/evaluate
GET  /evaluations
```

## Nina continuous loop

```text
POST /decision-loops
GET  /decision-loops
POST /decision-loops/{loop_id}/tick
GET  /decision-loop-runs
```

## Digital Twin

```text
POST /simulations
GET  /simulations
POST /simulations/{scenario_id}/run
GET  /simulation-runs
```

## Founder Cockpit

```text
GET /founder-cockpit
```

Returns a compact operating snapshot of pending events, agent messages, artifacts, QA state, SLA breaches, recovery incidents, approvals, goals and the latest Nina decision-loop runs.
