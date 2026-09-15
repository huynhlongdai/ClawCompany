# v19 — OpenClaw Core Alignment

v19 has one job: make ClawCompany talk to the **real** OpenClaw core
(<https://github.com/openclaw/openclaw>) instead of a contract we guessed.

## What was wrong before

`app/runtime/gateway.py` called `agents.create`, `agents.run`, `runs.cancel`,
`gateway.status` and `runs.subscribe`, opened a bare WebSocket with no
handshake, and let the runtime choose session keys. None of those RPC names
exist upstream, so that adapter could only ever have worked against a mock.

| Old assumption | Real OpenClaw |
| --- | --- |
| `agents.create` | No such call. Agents are config entries `agents.entries.<id>`, created by the operator with `openclaw agents add`. |
| `agents.run` | `sessions.create` then `chat.send` |
| `runs.cancel` | `chat.abort` / `sessions.abort` (by session key, optionally a `runId`) |
| `gateway.status` | `status` |
| `runs.subscribe` | `sessions.messages.subscribe` — subscriptions are per **session**, not per run |
| anonymous socket | connect frame declaring a **role** and **scopes**, answered by `hello-ok` |

## What v19 adds

### `app/runtime/openclaw_protocol.py`
Single source of truth for upstream facts: method names, event families,
operator scopes, the HTTP deny list, session-key helpers, and the
legacy→upstream map that the API and UI both render.

Session keys follow upstream shape:
- main session: `agent:<agentId>:main`
- company task: `agent:<agentId>:company-task-<taskId>`

Giving each task its own session keeps company work out of the operator's own
chat conversation with that agent.

### `app/runtime/openclaw_native.py`
`NativeOpenClawRuntime`, selected with `OPENCLAW_MODE=native`:

- performs the connect handshake as `role=operator` requesting only
  `operator.read` + `operator.write` (never `operator.admin`, `pairing` or
  `talk.secrets`);
- `run_agent` = `sessions.create` + `chat.send`;
- `cancel_run` = `sessions.abort` by session key or run id;
- `stream_run` subscribes to the session and normalises upstream frames
  (`chat`, `session.message`, `session.tool`, …) into ClawCompany's event shape,
  deriving terminality from the upstream `state` field rather than invented
  event names;
- `invoke_tool` posts to `POST /tools/invoke` on the same port as the gateway;
- `create_agent` **does not create anything** — it verifies the agentId exists
  and otherwise returns a `missing` result with the `openclaw agents add`
  hint. A company backend must not be able to mint personas on the operator's
  machine.

The legacy `gateway` mode still exists for deployments pinned to a custom RPC
surface, but it is deprecated.

### `app/services/openclaw_alignment.py`
Reconciles two rosters that drift the moment an operator adds or removes an
agent: company seats (`Agent.runtime_agent_id`) versus gateway agents. Output
is three buckets — matched / orphaned / unbound. Orphaned seats are marked
`lifecycle="detached"` and recover automatically when the agent returns.
Nothing is ever deleted.

Also holds `task_brief()`, the prompt a task session receives. The approval
boundary is part of that text, not a UI convention.

### `app/services/agent_dispatch.py`
Replaces `services/tasks.py::dispatch_task`, which set `task.status =
"running"` — a value outside the v18 board vocabulary, so dispatched tasks fell
out of the transition table. Dispatch now moves a task to `in_progress`, uses
the per-task session key, and records the runtime ids, a usage event, a company
event and a realtime broadcast.

### `app/api/v19.py` (`/api/v19`)

| Endpoint | Purpose |
| --- | --- |
| `GET /openclaw/protocol` | Contract this deployment speaks + legacy map |
| `GET /openclaw/health` | Gateway reachability |
| `GET /openclaw/agents` | Roster from the gateway |
| `GET /openclaw/seats` | Company seats and their bindings |
| `POST /openclaw/reconcile` | Drift report (manager) |
| `POST /openclaw/bind` | Bind a seat to an agentId (manager) |
| `POST /tasks/{id}/start` | Dispatch into an OpenClaw session |
| `POST /tasks/{id}/abort` | Abort and park the task |
| `GET /tasks/{id}/transcript` | `chat.history` for the task session |
| `POST /openclaw/tools/invoke` | Guarded single-tool passthrough (human admin only) |

Reads use `company.context:read`; writes use the new `company.runtime:write`
scope.

## Security boundaries

- The gateway bearer token stays in the backend. Clients authenticate to
  ClawCompany, never to the gateway.
- Upstream treats a shared-secret bearer on `/tools/invoke` as **full operator
  access**, ignoring narrower `x-openclaw-scopes`. The passthrough is therefore
  restricted to human admins and refuses API-key principals outright.
- The upstream hard deny list (`exec, spawn, shell, fs_write, fs_delete,
  fs_move, apply_patch, sessions_spawn, sessions_send, cron, gateway, nodes`)
  is mirrored locally so a blocked call fails with a readable reason.
- `agent_id` in a passthrough must belong to a seat in the caller's
  organization, otherwise 404.

## Configuration

```env
OPENCLAW_MODE=native            # mock | native | gateway (legacy)
OPENCLAW_GATEWAY_WS=ws://127.0.0.1:18789
OPENCLAW_GATEWAY_HTTP=          # defaults to the ws url with an http scheme
OPENCLAW_API_TOKEN=             # gateway.auth.token / OPENCLAW_GATEWAY_TOKEN
OPENCLAW_PROTOCOL_VERSION=4
OPENCLAW_CLIENT_NAME=clawcompany
OPENCLAW_AUTO_DISPATCH=false
```

Operator side:

```bash
openclaw onboard --install-daemon
openclaw agents team create --non-interactive   # coordinator + researcher + writer + reviewer
openclaw agents list --bindings
openclaw gateway status
```

The upstream `agents team create` preset (coordinator as chief of staff plus
specialists, wired with `subagents.allowAgents` and `delegationMode: "prefer"`)
maps one-to-one onto the v16 team/delegation model, so a ClawCompany department
can be mirrored by an OpenClaw agent team.

## Not done yet

- Long-lived subscription worker that keeps `sessions.messages.subscribe` open
  and feeds `persist_runtime_event` continuously (today streaming is per call).
- Auto-dispatch on `todo → in_progress` from the v18 board (flag exists,
  wiring pending).
- Mapping OpenClaw `session.approval` events onto the v13 approval queue.
