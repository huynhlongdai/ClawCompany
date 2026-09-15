# ClawCompany v9 — Autonomous Operations Architecture

v9 adds a governed autonomous operating loop on top of the v8 Company OS foundation. OpenClaw remains the agent runtime; ClawCompany owns organization context, goals, delegation, budgets, approvals, memory, recovery and customer/business state.

## Operating loop

```text
Founder / Executive Goal
        ↓
Nina planning
        ↓
Organizational memory grounding
        ↓
Operating Cycle
        ↓
Autonomy Policy
   ┌────┼──────────────┐
   │    │              │
manual supervised   autonomous
   │    │              │
   └─ approval/risk ───┘
        ↓
Delegation graph
manager → AI employee → Company Task
        ↓
Budget reservation
        ↓
OpenClaw Runtime Adapter
        ↓
Runtime events
        ↓
Result / failure
   ┌────┴─────────────┐
   │                  │
settle budget      incident
memory result      retry/recover
   │                  │
   └────────┬─────────┘
            ↓
next dependency-ready assignment
            ↓
Executive Goal complete / needs attention
```

## Core v9 objects

- `ExecutiveGoal`: founder-level outcome with risk, priority, deadline and autonomy mode.
- `OperatingCycle`: one governed execution loop for a goal.
- `DelegationAssignment`: maps a Nina plan step to manager/assignee/task/runtime run.
- `AutonomyPolicy`: mode, risk threshold, concurrency, retry and budget limits.
- `BudgetEnvelope` + `BudgetLedgerEntry`: reservation-first resource controls.
- `RecoveryIncident`: durable execution failure / retry state.
- `OrganizationMemory`: durable principles, facts, decisions, outcomes and lessons.
- `RecurringOperation`: cron-like company operations executed by Celery Beat.

## Governance semantics

### Manual
Every operating cycle starts behind an approval gate.

### Supervised
Low-risk work can execute automatically when it is at or under `max_auto_risk`. Higher-risk goals create an approval before dispatch.

### Autonomous
Eligible work is dispatched automatically. Retryable low/medium incidents can return assignments to the queue until `max_attempts` is reached. High/critical incidents can pause when `pause_on_high_incident` is enabled.

All modes still honor tenant boundaries, task ownership, runtime adapter isolation, per-action budget limits, goal budget envelopes and the organization daily budget guard.

## Budget lifecycle

```text
assignment ready
   ↓
check per-action limit
   ↓
check daily organization commitment
   ↓
check goal envelope remaining
   ↓
RESERVE
   ↓
runtime execution
   ├─ completed → SPEND
   └─ failed    → RELEASE
```

Reservations are source-linked to a delegation assignment. Retry creates a new reservation only after the previous reservation has been released or spent.

## Organizational memory

Goal planning queries organization memory before Nina creates the execution plan. Matching memories are attached to `NinaExecutionPlan.strategy_json` as `memory_context`. Goal creation, execution outputs and final outcomes can create new durable memories.

The current search implementation is intentionally simple keyword matching. v7 pgvector remains available for document knowledge/RAG; a later release can vectorize `OrganizationMemory` too.

## Recurring operations

Celery Beat runs two schedulers:

- `operations.scan_recurring` every 60 seconds
- `operations.tick_cycles` every 30 seconds

`RecurringOperation` currently supports `nina_goal`, which can create a goal, plan it and create an operating cycle. The cron parser supports five-field expressions with `*`, `*/n`, integer lists and ranges.

## Runtime behavior

`tick_cycle(..., capture_runtime=True)` consumes the configured `AgentRuntime.stream_run()` for running assignments, persists runtime events, records terminal status, settles budget, creates memory and advances dependency-ready work.

In mock mode this gives a complete local operating loop. In gateway mode behavior depends on the exact OpenClaw RPC/event contract mapped into `OpenClawGatewayRuntime`.

## New frontend routes

```text
/app/control-center
/app/goals
/app/memory
/app/budgets
/app/autonomy
```

Existing v8 routes continue to work. The light premium visual shell and original Dashboard are preserved.

## Production boundaries still open

v9 is not a production-complete autonomous company. Remaining work includes:

- exact OpenClaw Gateway RPC/event mapping for the deployed release
- hardened distributed run-event consumption rather than request/worker-held streams
- timezone-aware database timestamps across the whole legacy schema
- durable idempotency keys and distributed locks for schedulers/retries
- reviewed migrations for all pre-v9 prototype revisions
- secure secret management and HttpOnly/session authentication
- production embeddings and vectorized organizational memory
- accounting-grade cost ledger / invoice reconciliation
- full frontend dependency install + Next.js production build in CI
- end-to-end Postgres/Redis/OpenClaw integration tests
