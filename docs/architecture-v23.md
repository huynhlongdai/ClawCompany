# v23 — Approval contract alignment

v21 closed the approval loop but did it with a **guessed payload**. v23 replaces
that guess with the contract the upstream OpenClaw gateway documents.

## What was wrong in v21

```python
# v21 (guessed)
params = {"sessionKey": ..., "requestId": ..., "approved": True, "decision": "approve", "note": ...}
```

The upstream docs say:

- *"Operator clients resolve by calling `exec.approval.resolve` (requires `operator.approvals`)."*
- Approvals are resolved **by id**: `openclaw approvals resolve <id> <allow-once|allow-always|deny>`.
- *"The current Gateway approval record has no free-text resolution-reason field, so this note is not persisted or sent to other approval surfaces."*
- Clients backfill pre-connection prompts with `exec.approval.list`.

So v21 was wrong in four ways: the method name was unset (nothing could be sent
at all), the decision was a boolean, the key was the session rather than the
approval id, and the note pretended to travel upstream.

## What v23 sends

```python
# app/runtime/openclaw_native.py
params = {"id": request_id, "decision": "allow-once" | "allow-always" | "deny"}
# sessionKey added only as a disambiguator when we happen to have one
```

| ClawCompany decision | Upstream decision | Local `Approval.status` |
| --- | --- | --- |
| `approved` | `allow-once` | `approved` |
| `approved_always` | `allow-always` | `approved` |
| `denied` | `deny` | `denied` |

`approved` maps to **allow-once** on purpose. `allow-always` mints a standing
grant on the gateway host tied to the command's exact argv and cwd — a wider
act than approving one run — so it needs its own word in the API and is refused
unless `OPENCLAW_APPROVAL_ALLOW_ALWAYS_ENABLED` is on. The button only appears
in the UI when the backend reports it enabled.

## Settings

| Setting | Default | Meaning |
| --- | --- | --- |
| `OPENCLAW_APPROVAL_REPLY_METHOD` | `exec.approval.resolve` | Now has a default, because it is documented rather than invented. Override it if your gateway version differs. |
| `OPENCLAW_REQUEST_APPROVALS_SCOPE` | `false` | Still opt-in: it widens the handshake to `operator.approvals`. |
| `OPENCLAW_APPROVAL_ALLOW_ALWAYS_ENABLED` | `false` | Allows standing grants to be created from ClawCompany. |

`GET /api/v21/approvals/readiness` now reports `method_source`
(`documented default` / `operator override` / `unset`), `decisions`,
`allow_always_enabled`, and `note_delivered_upstream: false`.

## The note stays home

A reviewer's note is still stored on the approval row and still emitted on
`openclaw.approval.decided`, but it is **not** sent to the gateway and the
resolution note now says so verbatim: `decision relayed to OpenClaw; this note
stayed in ClawCompany`. The UI repeats this above the note field.

## Why the v19 "never guess" rule is not being broken

v19 exists because an earlier version invented `agents.run`, `runs.cancel` and
friends. The rule was never "leave everything unset" — it was "do not ship a
plausible-looking name you have not read anywhere". `exec.approval.resolve`,
the `operator.approvals` scope and the three decision words are quoted from the
upstream docs, so they ship as defaults.

## Still unverified

- The **JSON parameter names** (`id`, `decision`) are inferred from the
  documented CLI signature, not from a schema dump. If your gateway rejects the
  call, this is the first thing to check.
- `--expires-in-days` for standing grants is not exposed; ClawCompany always
  uses the gateway's configured default lifetime.
- Nothing here has been run against a live gateway. The 14 tests in
  `tests/test_v23_approval_contract.py` pin our side of the contract only.
- Complete enumeration and operator-wide resolve are documented as needing
  `operator.admin`; ClawCompany never requests admin, so it can only resolve
  prompts it can already see.

## Files

| File | Change |
| --- | --- |
| `app/runtime/openclaw_protocol.py` | `M_EXEC_APPROVAL_RESOLVE`, `M_EXEC_APPROVAL_LIST`, `APPROVAL_DECISIONS` |
| `app/runtime/openclaw_native.py` | `respond_approval(request_id, decision, session_key="")` |
| `app/services/approval_bridge.py` | decision mapping, `LOCAL_STATUS`, allow-always gate, honest note |
| `app/api/v21.py` | `DecideIn` accepts `approved_always` |
| `app/core/config.py` | version `1.13.0`, method default, allow-always flag |
| `lib/api.ts`, `components/LiveRunsConsole.tsx` | three-way decision UI |
| `tests/test_v23_approval_contract.py` | 14 tests |
