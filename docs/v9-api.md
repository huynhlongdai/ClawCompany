# v9 API

All internal endpoints below are under `/api/v9` and require the existing ClawCompany internal authentication/tenant model.

## Autonomy

```text
GET  /api/v9/autonomy-policy
PUT  /api/v9/autonomy-policy
```

`PUT` requires admin role. Policies can be organization-wide or company-specific.

## Executive goals

```text
POST /api/v9/goals
GET  /api/v9/goals
GET  /api/v9/goals/{goal_id}
POST /api/v9/goals/{goal_id}/plan
POST /api/v9/goals/{goal_id}/run
```

Typical flow:

```text
create goal → plan → run → cycle tick/reconcile
```

## Operating cycles / delegation

```text
GET  /api/v9/cycles
GET  /api/v9/cycles/{cycle_id}
POST /api/v9/cycles/{cycle_id}/tick?capture_runtime=true
GET  /api/v9/delegations
GET  /api/v9/org/delegation-tree
```

`tick` processes terminal runtime events, captures runtime stream events when requested, applies retries, settles budgets and dispatches newly dependency-ready assignments.

## Budgets

```text
POST /api/v9/budgets
GET  /api/v9/budgets
GET  /api/v9/budgets/{budget_id}
POST /api/v9/budgets/{budget_id}/entries
```

Ledger entry types: `reserve`, `spend`, `release`.

## Organizational memory

```text
POST /api/v9/memory
GET  /api/v9/memory/search?q=...
```

Memory supports organization/company/department/project/agent scope, importance, confidence and source lineage.

## Recurring operations

```text
POST /api/v9/recurring-operations
GET  /api/v9/recurring-operations
POST /api/v9/recurring-operations/{id}/run-now
```

Current operation type: `nina_goal`.

## Recovery incidents

```text
GET  /api/v9/incidents
POST /api/v9/incidents/{id}/retry
```

Autonomous mode can retry eligible incidents automatically. Supervised/manual flows expose retry as an explicit manager action.

## Executive control center

```text
GET /api/v9/control-center
```

Returns autonomy mode, active goals, operating cycles, open incidents, pending approvals, organizational memory count, 24h usage cost and budget summaries.
