# v24 — Gap awareness & approval backfill

Service version `1.14.0`. No new tables, no migration.

v22 shipped automatic takeover of unattended sessions and then admitted, in a
docs footnote, that re-subscribing does **not** replay what happened while
nobody was attached. v23 verified the approval contract against the upstream
docs and noted that ClawCompany never calls `exec.approval.list`, which the
same docs describe as the backfill a client performs on connect.

Both were real holes and both were invisible in the product. v24 makes them
visible, and recovers the part that is actually recoverable.

## 1. The transcript now admits its holes

`app/services/runtime_gap.py`

- `measure(db, session_key)` — how long since the last recorded event for the
  session. A session we have never recorded anything for returns
  `observed: false` with `gap_seconds: null`, because *unknown* and *zero* are
  different answers and only one of them is true.
- `record(...)` — writes an `openclaw.stream.gap` marker into the runtime
  event stream **and** the company event bus, with `replayed: false` stated in
  the payload. Gaps under `MIN_GAP_SECONDS = 5` are ignored: that is the round
  trip of a takeover, not lost work.
- `claim_orphans` calls it on every successful takeover and returns the gaps
  it recorded in a new `gaps` key.

The marker goes into the transcript itself rather than only a side table,
because a hole recorded somewhere nobody reads is the bug, not the fix. We do
not attempt to reconstruct the missing events: whether replay is possible is a
question about the gateway, and plausible filler would be worse than a gap.

## 2. Approval prompts raised while we were away

`app/services/approval_backfill.py`, plus `list_approvals` on the native
runtime (`exec.approval.list`, scope `operator.approvals`).

- `readiness()` reports whether the call is possible at all — the scope must be
  requested and the runtime must implement the method. A mock runtime returns
  `ready: false` rather than an empty list, because an empty list reads as
  "nothing pending", which would be a lie.
- `entries_from(result)` accepts a bare list or the common wrapper keys
  (`approvals`, `items`, `pending`, `result`, `data`). Non-mapping entries are
  dropped rather than coerced. The wrapper shape is the one part of this
  contract we have not read a schema for, so it is handled tolerantly and
  said so here.
- `apply_entries(...)` reuses `runtime_stream.record_approval` verbatim, so a
  backfilled prompt gets the same policy key, the same risk defaults, and the
  same idempotency as a live one. Re-running a backfill cannot duplicate the
  queue. An entry that is already resolved upstream and has no local row is
  ignored, not resurrected.

## 3. API and UI

`app/api/v24.py`, mounted at `/api/v24`:

| Method | Path | Scope | Purpose |
| --- | --- | --- | --- |
| GET | `/runtime/gaps` | `company.context:read` | Unattended sessions and how long they went unobserved. Always returns `replay_supported: false`. |
| GET | `/approvals/backfill/readiness` | `company.context:read` | Can we call `exec.approval.list`, and if not, what is missing? |
| POST | `/approvals/backfill` | `company.runtime:write` (manager) | Reconcile the gateway's pending prompts for one task's session. |

Three matching bridge tools were added (`company.runtime.gaps`,
`company.approvals.backfill_readiness`, `company.approvals.backfill`), taking
the bridge to **107** tools.

`components/LiveRunsConsole.tsx` gains a "Khoảng trống quan sát" panel that
states plainly that takeover does not replay anything, shows the unobserved
duration per session, and offers per-task backfill — disabled, with the reason
shown, when the gateway call is not available.

## 4. Tests

`backend/tests/test_v24_gap_awareness.py` — 15 tests covering: unknown vs zero
gap, measurement from the *last* event, the sub-threshold no-op, the marker
landing in the transcript, the three listing shapes, junk entries being
dropped, policy-key and risk parity with the live path, backfill idempotency,
resolved-entry handling, unsupported-vs-empty reporting, and the gateway call
itself.

## 5. Honest limits

- **The JSON key for listing by session is still inferred.** `exec.approval.list`
  and its scope are documented; that a `sessionKey` filter exists on it is not.
  If the gateway ignores the filter we will simply see more entries than we
  asked for, and idempotency keeps that harmless.
- **Enumeration is partial by design.** Operator-wide listing is documented as
  needing `operator.admin`, which ClawCompany never requests. What comes back
  is what this connection may see.
- **Nothing here was executed.** The sandbox has no network, so v19–v24 tests
  have still never been run. `python3 -m py_compile` is the only check that
  passed.
- **Missed events remain missed.** v24 reports the gap; it does not close it.
  Closing it would need either an upstream replay capability or a follower that
  never drops, and neither exists today.
