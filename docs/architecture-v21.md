# v21 — Durable runtime control

v20 shipped session followers and said out loud what it had not solved. v21
closes those three holes and removes one piece of legacy that kept producing
invalid task states.

## 1. A shared lease decides who follows a session

`services/runtime_leases.py` holds the claim in Redis (`SET key value NX EX
ttl`). A follower renews on every event; if the renewal fails it stops instead
of writing a second copy of the same events. Release only succeeds for the
owner, so a paused process cannot delete the new owner's claim.

When Redis is unreachable the store degrades to a process-local dict and
reports `backend: memory`, `single_process_only: true`. That is a real
single-worker deployment, not a pretend distributed lock, and both the API and
the UI say so.

## 2. Followers survive a restart

- `resumable_sessions()` finds tasks that are `in_progress` with a session key.
- `resume_followers()` re-attaches them; the lease decides which worker wins,
  the rest come back as `declined`.
- `OPENCLAW_RESUME_ON_BOOT` runs it on startup. Off by default, because boot
  should not silently open outbound gateway connections. Failures are logged,
  never fatal.
- `POST /api/v21/runtime/resume` does the same on demand.

## 3. Gateway approvals can be answered from the company queue

`services/approval_bridge.py` turns a decision in ClawCompany into a reply to
OpenClaw, with two refusals that matter:

- **We do not guess the RPC name.** v19 exists because an earlier version
  invented `agents.run`. The reply method comes from
  `OPENCLAW_APPROVAL_REPLY_METHOD`; unset means "unsupported", not "try
  something plausible".
- **Scope is opt-in.** Answering needs `operator.approvals`, which the
  handshake requests only when `OPENCLAW_REQUEST_APPROVALS_SCOPE` is on. The
  default scope set stays `operator.read` + `operator.write`; admin, pairing
  and secrets are never requested.

The response separates `recorded` from `delivered`, and the resolution note
keeps the same distinction (`relayed to OpenClaw` vs `recorded locally only
(reason)`), so a decision the agent never received cannot look like one it did.
`GET /api/v21/approvals/readiness` reports this before anyone clicks.

Policy keys are parsed from the right (`openclaw:agent:nina:main:req-7`)
because session keys contain colons.

## 4. One dispatch implementation

`services/tasks.py` was still setting `task.status = "running"`, a value absent
from the board vocabulary, for four call sites (`api/tasks.py`,
`services/orchestration.py`, `services/nina_planner.py`, `tasks/runtime.py`).
It is now a deprecation shim delegating to `services/agent_dispatch.py`, so
every caller gets per-task sessions, `in_progress`, metering and company
events. `DispatchError` subclasses `ValueError`, so old error handling still
works.

## Surface

| Endpoint | Purpose |
| --- | --- |
| `GET /api/v21/runtime/leases` | Lease backend, owner, sessions held here |
| `GET /api/v21/runtime/resumable` | Mid-run tasks nobody is following |
| `POST /api/v21/runtime/resume` | Re-attach followers (manager+) |
| `GET /api/v21/approvals/readiness` | Can a decision reach the gateway? |
| `POST /api/v21/approvals/{id}/decide` | Approve/deny a gateway prompt (manager+) |

UI: the `/app/live-runs` console gains a lease panel, a resume button, and
approve/deny buttons that surface undelivered decisions as a warning.
Bridge tools: 100. Version `1.11.0`. No migration; head stays
`0012_v16_agent_collaboration_mesh`.

## Still open

- Redis lease loss mid-stream stops the follower but does not hand the session
  to the new owner until someone calls resume.
- `OPENCLAW_APPROVAL_REPLY_METHOD` must be filled in per gateway version; we
  deliberately ship no default.
- The 21 v21 tests and the v19/v20 suites have not been executed in this
  environment (no network to install dependencies). Run
  `pip install -r backend/requirements.txt && pytest -q` before trusting them.
