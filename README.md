# ClawCompany v15 — Production Trust, Telemetry & Autonomous SRE

v15 extends v14's distributed execution plane with production-facing trust, observability federation, secrets federation, HA scheduler primitives, paging and a governed Nina SRE recovery loop.

## End-to-end control loop

```text
Founder / Nina
   ↓
Engineering Initiative / SLO
   ↓
Runner Broker
   ↓
mTLS Runner Identity + short Runner Certificate
   ↓
Lease-bound Workload JWT + rotating signing key
   ↓
Remote execution
   ↓
Signed SBOM / provenance
   ↓
Evidence Trust Policy + verification
   ↓
Release / Canary
   ↓
OTLP → ClawCompany SLO → Prometheus / OTLP exporters
   ↓
Incident
   ↓
Paging + Nina SRE Plan
   ↓
Deterministic Recovery Policy
   ├─ low/high governed action
   └─ critical → Founder/Admin approval
   ↓
Rollback / mitigate / re-evaluate / page
```

## New in v15

- Runner PKI control plane: CA metadata, CSR signing, short-lived client certificates, SHA-256 fingerprint identity, rotation and revocation. CA private keys are referenced via `env:`/`file:` and are not stored as plaintext DB values.
- Optional mTLS edge topology: `infra/envoy/runner-mtls.yaml.template` validates runner client certificates and injects an authenticated SHA-256 fingerprint into the private proxy→API hop.
- Workload signing-key rotation: per-organization `kid`, active/retiring/revoked states, old-token verification during overlap, JWKS publication and immediate fail-closed revocation.
- Evidence trust policies and persisted verification records. HMAC remains a development path; pinned-key `cosign verify-blob` is supported when the CLI/key are actually present. Keyless transparency verification is intentionally not claimed complete.
- OTLP JSON metric ingestion, Prometheus exposition at `/api/v15/metrics`, Pushgateway and OTLP HTTP JSON exporters with destination allowlists.
- Secrets federation control plane: env, Vault HTTP and AWS/GCP/Azure CLI adapters. `SecretAccessLease` is time- and runner-bound; plaintext secret values are resolved only at execution time and never persisted by the lease model.
- Incident paging: console/webhook routes, severity filters, HMAC webhook signatures, delivery records/retries and destination allowlists.
- HA scheduler primitives: scheduler nodes, leadership lease, expiration and fencing token. v15 SRE background work only runs for the elected leader per organization.
- Nina SRE recovery loop: deterministic policy selection, explainable `SREDecision`, optional approval gate, paging, mitigation, SLO re-evaluation and deployment rollback action.
- New UI routes: `/app/production-trust`, `/app/telemetry-federation`, `/app/secrets-federation`, `/app/sre-control`.
- OpenClaw Company Bridge: 57 tool contracts total; v15 adds trust visibility, evidence verification, OTLP metrics, secret leases, paging and SRE plan/execute.

## Runner mTLS topology

The application does not trust a client-supplied fingerprint by itself. Production topology is:

```text
Runner cert/key
    ↓ mTLS
Envoy / NGINX private edge
    ↓ verified fingerprint + private proxy proof
FastAPI /api/v15/runner/*
```

Set `RUNNER_MTLS_REQUIRED=true` and configure `RUNNER_MTLS_PROXY_SHARED_SECRET` only on the private API/proxy hop. The runner itself never receives that proxy secret.

The pull runner supports:

```bash
export CC_RUNNER_TRANSPORT_VERSION=v15
export CC_RUNNER_CLIENT_CERT=/secure/runner.crt
export CC_RUNNER_CLIENT_KEY=/secure/runner.key
export CC_RUNNER_CA_BUNDLE=/secure/control-plane-ca.pem
python -m app.runner_agent
```

## Development

```bash
docker compose up
# then
docker compose exec api python seed.py
```

Main UI: `http://localhost:3000`  
API docs: `http://localhost:8000/docs`

Demo admin: `admin@clawcompany.local / ChangeMe123!`

## Security boundaries

v15 does not claim that a TLS template equals a managed PKI deployment, that a CLI adapter equals cloud IAM federation, or that `cosign` key verification equals full Sigstore/Fulcio/Rekor transparency verification. Firecracker/Kubernetes runtime providers remain deployment-specific adapters. Secrets are only as secure as the external provider/runtime into which they are injected. Critical SRE recovery is approval-gated by default in the seeded policy.

## Docs

- `docs/architecture-v15.md`
- `docs/v15-api.md`
- `docs/security-v15.md`
- `docs/completion-matrix-v15.md`
- `docs/validation-v15.md`

Migration head: `0011_v15_production_trust_sre`.

## v16 — Agent Collaboration Fabric & Shared Knowledge Mesh

The multi-agent layer the product was actually about: agent teams that span companies, collaboration rooms with enforced turn taking and immutable transcripts, auditable delegation contracts between agents, and a shared knowledge mesh that is deny-by-default with explicit, expiring grants and full access logging.

- API: `/api/v16` (teams, rooms, turns, delegations, knowledge spaces/grants/entries/search, access logs, summary)
- UI: `/app/collaboration`, `/app/knowledge-mesh`
- OpenClaw bridge: 13 new tool contracts (70 total)
- Docs: `docs/architecture-v16.md`, `docs/v16-api.md`, `docs/security-v16.md`, `docs/completion-matrix-v16.md`, `docs/validation-v16.md`

## v17 — UI Design Canvas & Workspace Cockpit

Closes the gap between the product mockup and the shipped app.

- `design/clawcompany-ui-canvas.html` — self-contained design canvas: tokens, app shell and four screens (Trang chủ, AI Agents, Collaboration Room, Knowledge Mesh) plus a canvas → component → endpoint mapping. No build step; open it directly or screenshot it headless.
- `/api/v17/workspace/*` — read-only aggregates (overview, org chart, company detail, people, projects, tasks, knowledge) serving the business screens from real tenant data. No new tables, no migration.
- `/app/os` — tabbed workspace cockpit wired to those endpoints, replacing the hardcoded demo dashboard.
- Docs: `docs/ui-canvas-v17.md`

Migration head: `0012_v16_agent_collaboration_mesh`. Service version: `1.7.0`.

## v18 — Workspace Operations (write half of the cockpit)

The cockpit becomes an operating console instead of a dashboard.

- `/api/v18/workspace/*` — 13 guarded write endpoints: create/update companies, departments, seats (human or agent), projects, tasks, task move/assign, knowledge documents, plus a `vocabulary` endpoint the UI uses to render only legal actions.
- Organizational rules live in `app/services/workspace_ops.py`, not in the UI: duplicate company names, agent seats without a runtime binding, reporting cycles, illegal task transitions, and assigning work to offboarded members are all rejected server-side.
- Every mutation emits a `company_event_bus` event from source `workspace_ops`.
- UI: `/app/workspace-ops`.
- OpenClaw bridge: 10 new tool contracts (80 total).
- Docs: `docs/architecture-v18.md`

Migration head unchanged: `0012_v16_agent_collaboration_mesh`. Service version: `1.8.0`.

## v19 — OpenClaw Core Alignment

ClawCompany now speaks the real [OpenClaw](https://github.com/openclaw/openclaw) gateway contract instead of a guessed one.

- `app/runtime/openclaw_protocol.py` — upstream facts in one place: method names, event families, operator scopes, HTTP deny list, session-key helpers (`agent:<id>:main`, `agent:<id>:company-task-<taskId>`), and the legacy→upstream map.
- `app/runtime/openclaw_native.py` — `OPENCLAW_MODE=native`. Operator handshake with narrow scopes (`operator.read`, `operator.write`), `sessions.create` + `chat.send` for work, `sessions.abort` for cancel, `sessions.messages.subscribe` for streaming, `POST /tools/invoke` for single tools. It never pretends to create an OpenClaw agent — those are operator-owned config entries (`openclaw agents add`).
- `app/services/openclaw_alignment.py` — reconciles company agent seats with the gateway roster (matched / orphaned / unbound); orphaned seats become `detached`, nothing is deleted.
- `app/services/agent_dispatch.py` — replaces the old dispatcher that set the out-of-vocabulary status `"running"`. Tasks now move to `in_progress` and run in their own session.
- `/api/v19/*` — protocol, health, gateway agents, seats, reconcile, bind, task start/abort/transcript, and an admin-only guarded tools passthrough. New write scope: `company.runtime:write`.
- UI: `/app/openclaw`.
- OpenClaw bridge: 9 new tool contracts (89 total).
- Docs: `docs/architecture-v19.md`

The gateway token stays server-side: upstream treats a bearer on `/tools/invoke` as full operator access, so that endpoint is human-admin only and mirrors the upstream deny list locally.

Migration head unchanged: `0012_v16_agent_collaboration_mesh`. Service version: `1.9.0`.

## v20 — Live runs (session followers, auto-dispatch, approval bridge)

Version `1.10.0`. Builds on the v19 OpenClaw alignment so a dispatched task keeps
behaving like real work after the HTTP request ends.

- `backend/app/services/runtime_stream.py` — one long-lived consumer per OpenClaw
  session key: persists every event, moves the task on terminal states
  (`complete → review`, `error → blocked`, `aborted → todo`), and turns gateway
  permission prompts into rows in the company approval queue.
- `backend/app/api/v20.py` — 6 endpoints under `/api/v20` (streams, follow,
  unfollow, task events, board move with auto-dispatch, OpenClaw approvals).
- `OPENCLAW_AUTO_DISPATCH=true` starts agent-owned tasks when they enter
  `in_progress` from the board.
- Fix: `blocked` was a transition target but not a valid task status, so it was
  unreachable. It is now in `TASK_STATUSES` with exits to `in_progress`, `todo`,
  `cancelled`.
- UI `/app/live-runs`; bridge tools now 95; no migration (head stays
  `0012_v16_agent_collaboration_mesh`).

Limits: the follower registry is process-local (run one worker or a sidecar until
it is backed by a shared lease), and approvals are surfaced but not answerable
from ClawCompany yet — replying upstream needs the `operator.approvals` scope.

Docs: `docs/architecture-v20.md`. Tests: `backend/tests/test_v20_runtime_stream.py`
(16 tests, written but not executed — this sandbox has no network).

## v21 — Durable runtime control

Session followers now claim their session through a Redis lease, so running
more than one API worker no longer means two processes recording the same run
twice. When Redis is missing the lease degrades to process memory and reports
`single_process_only`, instead of pretending to be distributed.

Followers can be re-attached after a restart, on boot with
`OPENCLAW_RESUME_ON_BOOT` or on demand via `POST /api/v21/runtime/resume`.

Gateway permission prompts can be decided from the company approval queue.
That reply needs `operator.approvals` (`OPENCLAW_REQUEST_APPROVALS_SCOPE`) and
an RPC name from `OPENCLAW_APPROVAL_REPLY_METHOD` — we do not guess the method.
Every response separates `recorded` from `delivered`, so a decision kept only
in ClawCompany is never shown as one the agent received.

`services/tasks.py` is now a deprecation shim over `services/agent_dispatch.py`,
which removes the last code path that set the out-of-vocabulary task status
`running`.

See `docs/architecture-v21.md`.

## v22 — Cluster runtime: shared run reporting and session takeover

v21 fixed session *ownership* with a shared lease but left two gaps it wrote
down honestly. v22 closes them. Service version `1.12.0`, no migration.

- **Shared run reporting.** `GET /api/v20/streams` described one worker's
  memory. `services/stream_registry.py` publishes each follower's state to
  Redis, so `GET /api/v22/runtime/streams` covers every worker — and reports
  `process_local: true` when Redis is missing instead of looking complete.
  The registry never decides ownership; the lease remains the only authority.
- **Automatic takeover.** A follower that lost its lease stopped, correctly,
  but the session then sat unattended until a human pressed resume.
  `claim_orphans()` takes over sessions with no lease holder, and
  `OPENCLAW_CLAIM_SWEEP_SECONDS` (default `0`, disabled) runs it on a loop.
- **Rebuilt v16 docs.** `docs/v16-api.md`, `docs/security-v16.md`,
  `docs/completion-matrix-v16.md`, and `docs/validation-v16.md` were lost from
  the working tree during v16 packaging and are regenerated from the code that
  exists on disk.

Endpoints: `/api/v22/runtime/streams|registry|orphans|claim`. Bridge tools: 104.
Tests: `backend/tests/test_v22_cluster_runtime.py` (16) — written, **not run**
(no network in the build sandbox).

## v23 — Approval contract alignment (1.13.0)

v21 answered gateway approval prompts with a **guessed** payload. v23 replaces it
with the contract the upstream OpenClaw docs actually describe:

- method `exec.approval.resolve`, scope `operator.approvals` (still opt-in);
- resolved **by approval id**, not by session key;
- three-valued decision `allow-once` / `allow-always` / `deny`, not a boolean;
- the reviewer's note is **not** sent — the gateway record has no reason field,
  so the note stays in ClawCompany and the audit trail says so.

`approved` maps to `allow-once`. Standing grants (`allow-always`) need
`OPENCLAW_APPROVAL_ALLOW_ALWAYS_ENABLED=true` and get their own button.

Still unverified: the JSON parameter names (`id`, `decision`) are inferred from
the documented CLI signature and have never been sent to a live gateway.

See `docs/architecture-v23.md`.

## v24 — Gap awareness & approval backfill (1.14.0)

Two things v22 and v23 admitted in footnotes are now visible in the product.

- **Takeover does not replay anything.** When a worker claims an unattended
  session, `runtime_gap` measures how long nobody was listening and writes an
  `openclaw.stream.gap` marker into the transcript with `replayed: false`.
  A session we never recorded reports `observed: false`, not a gap of zero.
- **Approval prompts raised while we were away are now recoverable.**
  `exec.approval.list` (scope `operator.approvals`) backfills them through the
  same recording path as live prompts, so policy keys, risk defaults, and
  idempotency are identical and re-running a backfill cannot duplicate rows.

New endpoints `GET /api/v24/runtime/gaps`,
`GET /api/v24/approvals/backfill/readiness`, `POST /api/v24/approvals/backfill`
(manager). Bridge is now 107 tools.

Still unverified: the `sessionKey` filter on the listing call is inferred, and
no test in v19–v24 has ever been executed (no network in the build sandbox).

See `docs/architecture-v24.md`.

## v25 — Automatic reconciliation on attach (1.15.0)

v24 could report an observation gap and pull back approval prompts raised while
nobody was listening — but only when a human called the endpoint. v25 moves the
trigger to where it belongs: every time a follower attaches to a session (boot
resume, orphan claim, lease handover), it records the gap and backfills the
pending prompts before reading the first live event.

- `app/services/stream_reconcile.py` — runs inside `_consume`, measures the gap
  *before* backfilling (a backfilled row carries today's timestamp and would
  otherwise hide the hole), then emits one `openclaw.stream.reconciled` event.
- Cannot break the stream: every step is caught and reported as `error`.
- Cannot double-report: a gap recorded by `claim_orphans` is itself the newest
  event for the session, so the follower's measurement finds nothing left.
- `COOLDOWN_SECONDS = 30` stops a flapping lease from polling the gateway;
  the manual endpoint's `force` bypasses both the cooldown and the flag.
- `OPENCLAW_AUTO_RECONCILE` (default `true`) — a no-op unless
  `OPENCLAW_REQUEST_APPROVALS_SCOPE` is granted and the runtime can list.

New endpoints `GET /api/v25/runtime/reconcile` (history, process-local) and
`POST /api/v25/runtime/reconcile` (force one pass). Bridge tools:
`company.runtime.reconcile_status`, `company.runtime.reconcile_session` — 109
total. The v19 name `company.runtime.reconcile` reconciles agent seats and is
unrelated.

Still true: OpenClaw does not replay missed events, so v25 reports holes sooner
rather than filling them; the `exec.approval.list` response shape remains
inferred; and no test in v19–v25 has ever been executed (no network in the
build sandbox).

See `docs/architecture-v25.md`.

## v26 — Shared Redis fabric (1.16.0)

No new capability; three defects fixed that only appear with more than one worker.

- **One connection per process.** `services/redis_pool.py` replaces the private clients in `runtime_leases` and `stream_registry`. Those two could previously disagree about whether Redis existed — one holding real shared leases while the other reported `cluster_wide: false`.
- **A blip is no longer permanent.** The old stores nulled their handle on the first error and never retried, silently demoting the worker to in-process memory until a restart. The pool retries every `RETRY_SECONDS` (10s), and `POST /api/v26/runtime/fabric/reconnect` skips the wait.
- **Index sets instead of `SCAN`.** Lease and registry reads use `clawcompany:stream-lease-index` / `clawcompany:stream-state-index`. The index is a hint; readers verify against the real keys and prune stale members, so no cleanup job is needed and pre-v26 keys are adopted without a migration.
- **Shared reconcile ledger.** v25's cooldown was per-worker, so three workers meant three gateway calls per window. The ledger and the cooldown are now cluster-wide, falling back to memory (and saying so) without Redis.

Endpoints: `GET /api/v26/runtime/fabric`, `GET /api/v26/runtime/index`, `POST /api/v26/runtime/fabric/reconnect`. Bridge: 112 tools. 16 tests in `backend/tests/test_v26_shared_fabric.py` (not executed — no network in the build sandbox).

## v27 — Board truth (1.17.0)

Closes the three debts v18 declared about its own write half. No new tables, no migration.

- **Project progress is derived from the task board** (`done / (all − cancelled)`). No countable tasks returns `derivable: false`, not 0% — "nothing to measure" and "measured zero" are different answers. Applying the derived value stays an explicit action.
- **Optimistic concurrency**: pass `expected_revision` (built from `updated_at`, hence no schema change) and a stale write gets 409 *with the current revision*, so the retry is informed instead of blind. Omitting it keeps every pre-v27 client working.
- **Archive with cascade**: the project goes to `cancelled` and open tasks are cancelled; done work stays done and nothing is deleted. Tasks attached to a **live OpenClaw session** block the archive — `force: true` proceeds and reports what it left running rather than pretending it stopped anything.

Endpoints under `/api/v27`; UI panel "Sự thật bảng dự án (v27)" on `/app/workspace-ops`; 5 new bridge tools (total 117). Tests: `backend/tests/test_v27_board_truth.py` (21, not run — no network in the sandbox).

## v28 — Binding write guards & reversible archive (1.18.0)

v27's revision check was advisory: it compared a token against the row it had
just loaded, so two writers racing on the same revision both passed. v28 does
the write as a conditional `UPDATE ... WHERE updated_at = ?` and reports a 409
only when the database matched zero rows — the guard is now binding.

It also makes archiving reversible. `POST /api/v28/projects/{id}/restore`
reads the `project.archived` event back and reopens exactly the tasks that
archive cancelled, skipping any a human has moved since.

- `GET /api/v28/guards` — which entities and fields accept a guarded write
- `POST /api/v28/guarded/{projects|tasks|companies|departments|members}/{id}`
- `GET /api/v28/projects/{id}/restore/preview` · `POST .../restore`
- `GET /api/v28/projects/{id}/history` — truth + archive + restore in one call

126 bridge tools. No new tables, no migration. See `docs/architecture-v28.md`,
including what the 26 new tests do *not* prove.

## v29 — Cascade archive & write audit (1.19.0)

v28 left three debts written down. v29 closes all three, still with no new
table and no migration.

- **Per-task prior status**: an archive now records each task's status before
  cancelling it, so a restore returns a `blocked` task to `blocked` instead of
  reopening everything at `todo`. Where no record exists the response says
  `prior_status_known: false` rather than guessing.
- **Cascade archive for the org tree**: company → departments, members and
  open projects; department → its members; member → itself. Companies use
  `archived`, members use `offboarded`, departments (which have no status
  column) lock `access_level` to `confidential`. Agent rows are never touched —
  their lifecycle belongs to the runtime. Live OpenClaw sessions block the
  archive unless `force: true`, which then reports what it left running.
- **Write audit**: `board.write.guarded` and `board.write.conflict` had no
  consumer. `GET /api/v29/audit` turns them, plus every archive and restore,
  into rows with actor, entity, fields and a readable summary.

- `GET /api/v29/vocabulary`
- `GET|POST /api/v29/{companies|departments|members}/{id}/archive/preview|archive`
- `GET|POST /api/v29/{companies|departments|members}/{id}/restore/preview|restore`
- `GET /api/v29/audit` · `GET /api/v29/audit/{entity_type}/{entity_id}`

UI panel "Lưu trữ dây chuyền & sổ kiểm toán (v29)" on `/app/workspace-ops`;
15 new bridge tools (total 141). Tests: `backend/tests/test_v29_cascade_archive.py`
(32, not run — no network in the sandbox). See `docs/architecture-v29.md`.

## v31 - Field-level audit values, department status, clearable columns

The v30 audit said which fields changed but not what they changed from. v31
records before-values, gives departments a real `status` column, makes
department names unique per company, and adds a `__clear__` sentinel so a
column can be unassigned without redefining what JSON null means.

- `app/services/field_diff.py` - snapshot/diff/describe/reconstruct, with
  values truncated at 500 chars and secret-looking fields redacted.
- `alembic/versions/0014_...` - `departments.status` plus
  `uq_departments_company_name`; refuses to run while duplicates exist.
- `app/api/v31.py` - `/vocabulary`, `/history/{type}/{id}`,
  `PATCH /departments/{id}`, `/departments/name-conflicts`,
  `POST /projects/{id}/owner`.
- 5 new bridge tools (152 total), 30 new tests, `docs/architecture-v31.md`.

Still open: un-archiving a member does not restore runtime state, and
`company_events` has no retention policy. Nothing here has been executed -
this sandbox has no network.

## v30 — Revision counter, audit paging & batch board restore (1.20.0)

v29's three open items, closed — and the first one finally spends a migration.

- **Exact revisions.** Migration `0013_v30_row_revision_counter` adds a
  nullable `row_revision` counter to companies, departments, members,
  projects and tasks. Tokens become `project:12:r7`; the v27 timestamp form
  is still accepted and returned as `legacy_revision`. A row with no counter
  reports `exact: false` rather than pretending to be version 1, and its
  first guarded write adopts it at 1.
- **Paged audit.** `GET /api/v30/audit` takes `cursor` and returns
  `next_cursor` / `has_more`. The cursor is the last event *scanned*, not the
  last row returned, because category filtering happens after the SQL page.
- **Batch board restore.** `POST /api/v30/companies/{id}/projects/restore`
  reopens exactly the projects the company archive cancelled, each through
  the v28 restore path. One failure is reported, not fatal; the company
  stays archived.

Endpoints: `GET /api/v30/revisions`, `GET /api/v30/revisions/{kind}/{id}`,
`POST /api/v30/guarded/{kind}/{id}`, `GET /api/v30/audit`,
`GET|POST /api/v30/companies/{id}/projects/restore/preview` and `.../restore`.

UI panel "Revision chính xác và sổ kiểm toán phân trang (v30)" on
`/app/workspace-ops`; 6 new bridge tools (total 147). Tests:
`backend/tests/test_v30_exact_revisions.py` (36, not run — no network in the
sandbox). See `docs/architecture-v30.md`.
