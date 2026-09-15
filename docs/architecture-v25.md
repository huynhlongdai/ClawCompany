# v25 — Automatic reconciliation on attach

Service version `1.15.0`. No new tables, no migration.

## Why

v24 shipped both halves of honest recovery and then attached them to a button:

- `runtime_gap` could report how long a session went unobserved.
- `approval_backfill` could pull back approval prompts raised while nobody was listening.

Both only ran when a human called `POST /api/v24/approvals/backfill`. That is the
wrong trigger. The moment reconciliation matters is the moment a follower attaches
to a session it was not watching a second earlier — on boot resume, on an orphan
claim, on a lease handover. No human is present at any of those moments, and an
approval prompt expires whether or not anyone was.

## What changed

`app/services/stream_reconcile.py` is the trigger v24 was missing. It runs inside
`_consume`, before the first live event is read:

1. **Measure and record the gap first.** A backfilled approval carries the current
   timestamp, so writing it before measuring would make the hole look closed.
2. **Then backfill.** Via `approval_backfill.backfill_session`, which reuses the
   live `record_approval` path — same policy key, same idempotency.
3. **Then emit one `openclaw.stream.reconciled` event** so a queue that suddenly
   grows four prompts has an explanation in the company event bus.

### It cannot break the stream

Every step is wrapped. A gateway that is down, unauthorized, or answering in an
unexpected shape produces an `error` string in the outcome and nothing more. The
live events are worth more than the recovered ones, so reconciliation is never
allowed to be the reason a follower dies.

### It does not double-report

`claim_orphans` already records a gap when it takes a session over. The follower
it starts then reconciles too — but the gap the claim just wrote is itself the
newest event for that session, so the second measurement correctly finds nothing
significant. This is a property of measuring against the transcript rather than
keeping a separate flag, and it is pinned by a test.

### Cooldown

A flapping lease can re-attach the same session every few seconds.
`COOLDOWN_SECONDS = 30` stops that from becoming a polling loop against the
gateway; the second answer would have been identical anyway. `force=true` on the
manual endpoint bypasses both the cooldown and the feature flag.

## Configuration

| Setting | Default | Effect |
| --- | --- | --- |
| `OPENCLAW_AUTO_RECONCILE` | `true` | Reconcile on every attach. Safe as a default: it is a no-op unless the approvals scope is granted and the runtime implements listing. |
| `OPENCLAW_REQUEST_APPROVALS_SCOPE` | `false` | Still required for the backfill half to do anything. |

## API

| Method | Path | Role | Returns |
| --- | --- | --- | --- |
| `GET` | `/api/v25/runtime/reconcile` | read scope | `history`, `enabled`, `cooldown_seconds`, `readiness`, `process_local: true` |
| `POST` | `/api/v25/runtime/reconcile` | manager | one forced pass: `ran`, `gap`, `backfill`, `error` |

Bridge tools: `company.runtime.reconcile_status`, `company.runtime.reconcile`
(109 total).

## Honest limits

- **The history is in memory.** `GET` returns only this worker's passes;
  `process_local: true` says so. The durable trace is the emitted event.
- **Still no replay.** v25 reports gaps sooner and automatically. It does not
  make missed events recoverable — that would require gateway support that does
  not exist.
- **The listing contract remains inferred.** The `sessionKey` filter on
  `exec.approval.list` and its response shape are still not documented
  upstream; `entries_from` tolerates several wrappers for that reason.
- **Untested against a live gateway.** As with v19–v24, the sandbox has no
  network: `py_compile` passes, the 12 tests in `test_v25_auto_reconcile.py`
  have never been executed.
