# v20 — Live runs: session followers, auto-dispatch, approval bridge

v19 made ClawCompany speak the real OpenClaw gateway protocol. v20 closes the
gap that made that alignment only half useful: a dispatched task stopped being
observed the moment the HTTP request returned.

## What was broken after v19

| Symptom | Cause |
| --- | --- |
| A task dispatched into OpenClaw stayed `in_progress` forever | Nothing consumed the session stream after the request ended, so the terminal event never arrived |
| Runtime events only existed for SSE-attached clients | `stream_run` was only called from the customer portal endpoint |
| Gateway permission prompts expired unseen | `session.approval` was persisted as a generic event and never surfaced to a human |
| `blocked` was unreachable | It was a target in `TASK_TRANSITIONS` but missing from `TASK_STATUSES`, so `_check` rejected it |

## What v20 adds

### 1. `services/runtime_stream.py` — long-lived session followers

One consumer per session key, running in the API process:

- owns its own `SessionLocal()` (a request-scoped session dies with the request);
- persists every normalized event through the existing `persist_runtime_event`,
  so metering rules and the company event bus keep working unchanged;
- applies the terminal state to the task;
- never lets a broken stream take down the app — a failed consumer records
  `openclaw.stream.failed` and stops.

Terminal mapping:

| Upstream state | Task status | Why |
| --- | --- | --- |
| `complete` | `review` | The agent finishing is not the company accepting the work |
| `error` | `blocked` | Needs a human, not a retry loop |
| `aborted` / `cancelled` | `todo` | Parked back on the board, still assigned |

**Known limit, stated plainly:** the supervisor is *process-local*. With more
than one uvicorn worker, each worker only knows its own followers and two
workers could follow the same session. Run it in a single worker (or a
dedicated sidecar) until it is backed by a shared lease in Redis.

### 2. Approval bridge

`session.approval` and `exec.approval.*` become rows in the existing
`approvals` table with `policy_key = openclaw:<session key>:<request id>`:

- re-announced prompts are idempotent (one row per request id);
- a resolution in the OpenClaw UI updates that row instead of adding a second;
- tools on the upstream HTTP deny list default to `risk = high`;
- the raw prompt is kept in `evidence` so the decision is auditable.

Note: this makes prompts *visible*, it does not yet answer them. Replying to
the gateway from the ClawCompany queue requires `operator.approvals` scope,
which v19 deliberately did not request. That is a conscious next step, not an
oversight.

### 3. Auto-dispatch from the board

`POST /api/v20/board/tasks/{id}/move` reuses the v18 transition rules, then —
when the task enters `in_progress`, is owned by a bound agent seat, and
`OPENCLAW_AUTO_DISPATCH` (or an explicit `dispatch: true`) is set — dispatches
and starts following it.

A dispatch failure does **not** roll back the move. The task stays where the
human put it and the response carries `dispatch_error`, because silently
reverting a board move is more confusing than an explicit error.

## Endpoints

| Method | Path | Scope |
| --- | --- | --- |
| GET | `/api/v20/streams` | `company.context:read` |
| POST | `/api/v20/tasks/{id}/follow` | `company.runtime:write` |
| POST | `/api/v20/tasks/{id}/unfollow` | `company.runtime:write` |
| GET | `/api/v20/tasks/{id}/events` | `company.context:read` |
| POST | `/api/v20/board/tasks/{id}/move` | `company.runtime:write` |
| GET | `/api/v20/approvals/openclaw` | `company.context:read` |

UI: `/app/live-runs`. Bridge tools: 6 new (95 total). No migration — v20 reuses
`runtime_events` and `approvals`; migration head stays
`0012_v16_agent_collaboration_mesh`.

## Not done yet

- Shared lease so followers survive a restart and work across workers.
- Answering approvals from ClawCompany (needs `operator.approvals`).
- Resuming followers on boot for tasks still `in_progress` with a session key.
- `services/tasks.py::dispatch_task` still sets the invalid status `running`;
  its callers should move to `services/agent_dispatch.py`.

## Verification status

16 tests in `backend/tests/test_v20_runtime_stream.py` cover the terminal map,
persistence, and every approval-bridge branch. They were **written but not
executed**: this sandbox has no network, so dependencies could not be
installed. Run `pytest -q` and `npm run build` on a networked machine before
trusting the build.
