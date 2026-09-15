# ClawCompany v34 - Replay & Schedule

Service version `1.24.0`. No migration: v34 keeps its only new state on the
existing company event bus, so the migration head stays
`0015_v32_department_status_not_null`.

v34 closes three debts that earlier handovers named honestly and then left
alone. Each ships with a capability statement that says where it stops, because
two of the three cannot be made complete from inside this system.

## 1. Event replay (`app/services/event_replay.py`)

**The bug.** `company_event_bus.emit_event` writes the event row, then fans out:
realtime publish, webhook outbox, and - for callers that ask - the trigger pass.
The row is durable; the fan-out is not. A worker that died mid-turn, or a trigger
action that threw, left the event at `status='pending'` or `'error'` forever.
Nothing in v16-v33 came back for it.

**The fix.** `backlog()` lists stuck events oldest first. `replay()` re-runs
`trigger_engine.process_event` - the same code path the live emit uses, not a
parallel reimplementation.

Safety rules, each covered by a test:

- `REPLAYABLE = ("pending", "error")`. `processed` is excluded, so a completed
  trigger action is never run twice.
- `QUIET_SECONDS = 60`: an event only seconds old may still be in flight in
  another worker, so replay leaves it alone.
- `MAX_REPLAY = 200` per call. Replay executes trigger actions that create
  tasks, messages and workflow runs, so a sweep stays reviewable.
- One failing event does not stop the sweep: the session is rolled back, the
  failure is reported in `failed[]`, and the loop continues.
- `record_usage` and `persist_runtime_event` are never imported, so replay can
  never re-bill a customer.

**The honest ceiling.** `explain()` returns
`can_recover_lost_gateway_events: false`. We hold no upstream cursor and have
verified no gateway backfill RPC, so an event the gateway produced while we were
disconnected was never written down and is gone. What v34 adds is the narrow,
checkable case: `unmirrored_runtime_events()` finds runtime rows on disk whose
run never produced a company event, and `reemit_runtime_events()` puts specific
ids (explicit list, max 50, dry run by default) back on the bus with
`metered: false`.

## 2. Scheduled progress sync (`app/services/progress_schedule.py`)

v33 shipped `progress_autosync`, but the only way to run it was a human pressing
an endpoint - the handover called this "a pass, not a trigger". v34 registers
the sweep as a `RecurringOperation` of type `progress_sync` and adds that branch
to `recurring_ops.execute_operation`, so the scheduler loop already in the repo
(`due_operations` -> `execute_operation`) drives it.

- Default schedule `15 * * * *`, validated at registration time through
  `recurring_ops.compute_next`, so a cron typo fails loudly now instead of
  silently at 03:00.
- One schedule per scope: a second registration for the same company is
  refused rather than quietly doubling the write rate.
- Scheduled runs default to `dry_run=False` (a scheduled dry run would only
  produce log lines); `dry_run_runs` is an explicit opt-in.
- `run_scheduled()` delegates to `progress_autosync.sync` and contains no `try`
  block: `execute_operation` already records `last_status='failed'` plus the
  error, so swallowing it here would hide the failure.

**The honest ceiling.** `readiness()` returns `scheduler_observed: false`. From
inside the API process we cannot see whether a worker or beat process actually
polls `due_operations`. The check that matters is `last_run_at` on the
registered operation, which the schedule list exposes as `never_ran`.

## 3. Standing grant expiry ledger (`app/services/grant_ledger.py`)

When an approver answers `approved_always`, `approval_bridge.decide` relays
`allow-always` and the **gateway host** remembers the permission. Since v23 our
database only remembered that somebody chose it. v34 adds the ledger: what the
grant covers, when it was minted, and when it should stop being acceptable -
the equivalent of `--expires-in-days`.

- `DEFAULT_EXPIRES_IN_DAYS = 30`, range 1-365. Zero and negative are refused:
  an unexpiring standing grant is how blast radius grows.
- State lives in `company_events` as `openclaw.grant.minted` /
  `openclaw.grant.revoked`, folded by `_fold()`. That is why v34 needs no
  migration. A re-mint resets a revoked row.
- `ledger()` classifies each grant `active` / `expired` / `revoked` /
  `unknown_expiry` and sorts soonest-to-expire first. `due_for_review()` adds
  `session_keys_to_clear`.
- The module never imports `get_runtime` and has no `await`: it cannot talk to
  the gateway at all.

**The honest ceiling.** `enforcement()` returns
`enforces_expiry_upstream: false`. The verified gateway methods are
`exec.approval.resolve` and `exec.approval.list`; neither revokes a standing
grant. So `expires_at` is a review deadline and an audit record, not
enforcement, and `revoke()` records `confirmed_cleared_upstream` as a human
claim (`verified_upstream: false`). Calling this enforcement would be a
security lie.

## 4. API surface (`app/api/v34.py`, prefix `/api/v34`)

| Method | Path | Floor | Bridge tool |
| --- | --- | --- | --- |
| GET | `/api/v34/coverage` | read | `company.replay.coverage` |
| GET | `/api/v34/events/backlog` | read | `company.events.backlog` |
| GET | `/api/v34/events/{event_id}` | read | `company.events.detail` |
| POST | `/api/v34/events/replay` | admin | `company.events.replay` |
| GET | `/api/v34/events/runtime/unmirrored` | read | `company.events.runtime_unmirrored` |
| POST | `/api/v34/events/runtime/reemit` | admin | `company.events.runtime_reemit` |
| GET | `/api/v34/progress/schedules` | read | `company.progress.schedules` |
| POST | `/api/v34/progress/schedules` | manager | `company.progress.schedule_create` |
| POST | `/api/v34/progress/schedules/{operation_id}/enabled` | manager | `company.progress.schedule_toggle` |
| GET | `/api/v34/grants` | read | `company.grants.ledger` |
| GET | `/api/v34/grants/due` | read | `company.grants.due` |
| POST | `/api/v34/grants/revoke` | admin | `company.grants.revoke` |

Reads use scope `company.context:read`, writes `company.workspace:write`, and
API keys pass on scope alone exactly as in v18-v33. Bridge contracts total
**181**.

## 5. Frontend

`apiV34` in `lib/api.ts` and `components/ReplayPanel.tsx` (Vietnamese labels,
mounted in `WorkspaceOpsConsole`). The three write buttons are confirm-gated and
send `dry_run: true` first; the panel prints the ceiling sentences from
`/coverage` next to each section so an operator reading the screen sees the same
caveats this document states.

## 6. Testing status - read this before trusting v34

`backend/tests/test_v34_replay.py` adds **63 tests**: pure functions
(`_statuses`, `_cutoff`, `_age_seconds`, `_event_json`, `_days`, `_grant_key`,
`_parse`, `_status`, `_fold`, `_payload`, `_row`), guard clauses, AST assertions
(replay rolls back and continues, `run_scheduled` has no `try`, the cron branch
precedes the unsupported-type raise), and contract/wiring checks.

**No test in this repository has ever been executed.** The sandbox that produced
v19-v34 has no network, so `fastapi`, `sqlalchemy`, `pytest` and `alembic` were
never installed. Roughly 400 tests are unrun. Everything asserted here is
static: `python -m compileall` passes, nothing else was verified. Migrations
`0013`, `0014` and `0015` have never been applied to a database.

What specifically needs a real environment:

1. `replay()` against a session with real stuck events and a trigger that throws.
2. A worker polling `due_operations` to prove the `progress_sync` branch fires.
3. `mint()` -> `ledger()` -> `revoke()` round trip through `company_events`.
4. `ensure_company` tenancy rejection on every v34 endpoint that takes
   `company_id`.

## 7. Deliberate non-goals

- No replay of events the gateway produced while we were offline (section 1).
- No upstream grant revocation (section 3).
- No new scheduler process; v34 reuses `recurring_operations`.
- No trigger-on-task-change progress sync; it remains a poll.
- No re-delivery of webhooks - that outbox has its own retry.
- No compensation for a trigger action that half-completed on the first attempt;
  replay re-runs the action, it does not undo the earlier partial write.
