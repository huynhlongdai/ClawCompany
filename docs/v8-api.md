# ClawCompany v8 API additions

All internal endpoints require a company JWT unless noted otherwise.

## AI Workforce

```text
POST /api/workforce/hire
GET  /api/workforce/provisioning-jobs
```

`POST /workforce/hire` creates the employment/runtime records and calls `AgentRuntime.create_agent()`.

## Company Factory

```text
POST /api/company-factory/install
GET  /api/company-factory/jobs
```

A company manifest can contain:

```json
{
  "industry": "AI Commerce",
  "departments": [
    {
      "name": "Growth",
      "agents": [
        {"name": "Maya", "role": "Growth Lead", "skills": ["research"]}
      ]
    }
  ]
}
```

## Nina planner

```text
POST /api/nina/plans
GET  /api/nina/plans
GET  /api/nina/plans/{plan_id}
POST /api/nina/plans/{plan_id}/delegate
```

## Workflow graph builder

```text
POST /api/workflows/{workflow_id}/graph
GET  /api/workflows/{workflow_id}/graph/versions
```

Publishing a version also updates `Workflow.definition_json`.

## Runtime history / metering

```text
GET  /api/runtime/runs/{run_id}/history
POST /api/usage/meter-rules
GET  /api/usage/meter-rules
```

The existing v7 stream endpoint now verifies the run belongs to the active tenant and persists streamed events:

```text
GET /api/runtime/runs/{run_id}/events
```

## Customer chat

Portal JWT only:

```text
POST /api/portal/chats
GET  /api/portal/chats
GET  /api/portal/chats/{binding_id}/messages
POST /api/portal/chats/{binding_id}/messages
GET  /api/portal/chats/{binding_id}/runs/{run_id}/events
```

A chat can only bind an AI employee present in an active `CustomerAgentAssignment` for that customer.

## Auth hardening

Public registration no longer accepts an organization or role:

```text
POST /api/auth/register
```

Organization role grants are separated:

```text
POST /api/auth/organization-access
```

Requires admin or owner role in the active organization.

## WebSocket

```text
WS /api/ws/events/{organization_id}?token=<company-jwt>
```

The token's `org_id` must equal `{organization_id}`.
