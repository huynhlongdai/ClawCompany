# v32 - Housekeeping: before-values everywhere, retention, adoption

Version `1.22.0`. 159 bridge tools (+7). Migration head
`0015_v32_department_status_not_null`.

v31 added field-level audit values and v31.1 fixed the bugs that shipped with
it. This release closes the debts that were dangerous *over time* rather than
at once - the ones section 22.7 had been carrying for two versions.

## 1. Before-values on the paths people actually use

`app/services/write_trail.py`

v31 recorded `{from, to}` for **guarded** writes only. The cockpit forms -
`update_company`, `update_department`, `move_member`, `update_project`,
`move_task`, `assign_task` - kept emitting a `changed` map of *new* values.
So the field-history screen could reconstruct an edit made through
`/api/v28/guarded/...` and not the same edit made by clicking the form,
which is the path almost everybody uses.

`write_trail.start(kind, entity)` snapshots the tracked columns before the
mutation; `trail.finish(entity)` returns the payload fragment (`changes`,
`values_source`, and `values_error` if the snapshot failed). Same shape
`field_diff` defines and `write_audit.row_of` already reads - no second
format for a reader to learn.

Three decisions worth keeping:

- **Tracked columns are an explicit per-kind list**, not `__table__.columns`.
  A generic loop would start recording tenancy and runtime columns the first
  time somebody added one - the escalation surface `row_guard` avoided the
  same way.
- **The trail never raises.** A write must not fail because auditing failed;
  it degrades to an empty diff *and says so* via `values_error`. An empty
  `changes` already means "values did not move" (v31.1), so "unavailable"
  needed its own signal.
- **`changed` is kept alongside `changes`.** Clients from v18 read `changed`.

A structural test asserts every cockpit write path starts a trail and merges
it, and that no `create_*` path pretends to have before-values.

## 2. Retention for `company_events`

`app/services/event_retention.py` - `GET/POST /api/v32/retention/*`

An event store nothing prunes is a disk-full incident with a long fuse, and
v31 shortened the fuse by storing two copies of every changed column.

Three tiers, chosen to be explainable rather than clever:

| Tier | Days | What |
| --- | --- | --- |
| `evidence` | 400 | guarded writes, conflicts, archive/restore records |
| `default` | 90 | ordinary lifecycle events |
| `runtime` | 14 | stream gaps, reconciles, session churn - highest volume |

Two safety properties:

- **Reachability, not only age.** `board_restore` and `entity_archive` *read
  archive events back* to undo an operation. If a company, department,
  member or project is still in an archived state, its record is retained
  regardless of age. Age alone would quietly expire the undo.
- **Fail closed.** If the "which rows are still archived" query fails,
  `protected_aggregates` raises `RetentionError` and the endpoint returns
  503. An empty protected set would have authorised deleting undo records.

`prune` is `dry_run=True` by default, bounded to 5 000 rows per call
(`has_more` says to run again), and emits `company.events.pruned` with counts
only - listing deleted ids would recreate the volume just removed.

## 3. Adopting the rows migration 0013 left behind

`app/services/revision_backfill.py` - `GET/POST /api/v32/revisions/*`

v30 made `row_revision` nullable on purpose: a row whose count is unknown
must not claim to be version 1, because a client may hold a timestamp token
for it. What v30 got wrong was leaving **no path at all**.

`backfill` sets NULL counters to `1` only for rows whose `updated_at` is
older than a quiet period (default 60 s). That quiet period is what makes
adoption safe rather than merely bounded - a row written seconds ago may
have a writer mid-flight. Rows that already have a counter are **never**
renumbered; renumbering is indistinguishable from a lost update to anyone
holding the old token. `updated_at` is deliberately not bumped, for the same
reason.

Departments, projects and tasks have no `organization_id`, so `_org_filter`
reaches them through their parents. A backfill that skipped that would
renumber another tenant's rows, and unlike a read there is no way to notice
afterwards.

Not automatic, not run at boot - same policy as `OPENCLAW_RESUME_ON_BOOT`.

## 4. Departments archive on status, not on permission

`entity_archive` + migration `0015`

v29 locked departments with `access_level="confidential"` because no status
column existed. That conflated "put away" with "secret", and un-archiving
handed out a permission level the department may never have had.

v32 archives with `status="archived"` and **never touches `access_level`**.
Both eras restore: the two vocabularies (`active|paused|archived` vs
`org_public|restricted|confidential`) are disjoint, so the recorded word
itself says which era wrote it. `_dept_restore` returns
`{status, access_level, era, known}` - a v29 record puts back the level it
recorded, a v32 record touches only status, and an unrecognised value is
flagged `known: false` instead of being guessed silently.

Migration `0015` makes `departments.status` `NOT NULL DEFAULT 'active'`,
fixing the mismatch where the model treated the column as required and the
database did not. It **backfills NULLs first, then alters** - SQLite cannot
alter in place, so the constraint goes on through Alembic batch mode, which
rebuilds the table and would abort on NULLs. If any NULL survives the
backfill it raises `RuntimeError` before the rebuild, so a refusal is a
no-op and re-runnable (the v31.1 lesson from `0014`).

## 5. Redis backoff and runtime metrics

`redis_pool.backoff_delay` - `GET /api/v32/runtime/{pool,metrics}`

The fixed `RETRY_SECONDS = 10` meant a hard-down Redis was dialled six times
a minute per worker, forever, and every worker retried in lockstep - a
thundering herd the moment Redis came back. Now exponential (x2) to a 300 s
cap with +/-20 % jitter, reset to base on the first success.
`backoff_delay(1)` still equals 10 s, so nothing regresses from v26.

`/v32/runtime/metrics` returns Prometheus text for the pool and the lease
store: availability, attempts, failures, reconnects, current backoff, leases
held, lease backend shared or not. Hand-rolled exposition rather than a new
dependency this build cannot verify. It is **scope-protected**, not open - an
unauthenticated `/metrics` is how a private deployment leaks its topology. A
partial deploy degrades to a `*_scrape_ok 0` gauge instead of a 500 on a
monitoring endpoint.

## 6. Endpoints and tools

| Endpoint | Tool | Role |
| --- | --- | --- |
| `GET /api/v32/coverage` | `company.audit.coverage` | read |
| `GET /api/v32/retention/policy` | - | read |
| `GET /api/v32/retention/preview` | `company.events.retention_preview` | read |
| `POST /api/v32/retention/prune` | `company.events.prune` | admin |
| `GET /api/v32/revisions/preview` | `company.revision.adoption_preview` | read |
| `POST /api/v32/revisions/backfill` | `company.revision.backfill` | admin |
| `GET /api/v32/runtime/pool` | `company.runtime.pool` | read |
| `GET /api/v32/runtime/metrics` | `company.runtime.metrics` | read |

Housekeeping writes default to **admin**, not `member` as in v31: pruning an
audit table and adopting revision counters are operator actions. API keys
still pass on scope alone, exactly as in v18-v31 - a key has no human role.

## 7. Testing status - read this before believing anything above

`backend/tests/test_v32_housekeeping.py` - 38 tests, dependency-free where
possible, so they run in a sandbox with no network. They pin the *decisions*:
tracked-field sets, tier membership, backoff schedule and jitter bounds, era
detection, dry-run defaults, migration ordering.

**Still never executed in this sandbox**: `pytest` itself. No FastAPI,
SQLAlchemy, Alembic or Redis is installed here, so the ~350 tests from
v19-v32 have been compiled, never run. The SQL-touching parts of this
release - the `UPDATE` in `revision_backfill`, the `DELETE` in
`event_retention`, migration `0015`'s batch rebuild - are pinned
*structurally* only. Run before release:

```bash
cd backend && pip install -r requirements.txt
alembic upgrade head        # 0013, 0014, 0015 have never been applied
pytest -q
```

Migration `0014` still refuses if two departments in one company share a
name; fix the duplicates first
(`GET /api/v31/companies/{id}/departments/name-conflicts`).

## 8. What v32 deliberately does not do

These need something this sandbox does not have, and shipping them untested
would be worse than leaving them written down:

- **Un-archiving a member does not restore agent/session runtime state.**
  Needs a live OpenClaw gateway to verify.
- **No replay of runtime events lost during a gap.** `runtime_gap` measures
  and records; replay needs the gateway's history semantics confirmed.
- **The approval contract is still inferred.** `exec.approval.resolve`
  `{id, decision}` and the `exec.approval.list` response shape come from CLI
  signatures, not from a live handshake.
- **WebSocket push.** `/app/live-runs` still polls every 10 s; collaboration
  rooms still poll. The transport swap is mechanical but untestable here.
- **Semantic knowledge search.** `knowledge_mesh.search` still uses `ilike`;
  `vector_search.hash384_embedding` is wired for documents, not for shared
  entries.
- **Delegation `max_cost_usd` is not compared against real runner spend.**
- **Transcripts are not yet signed with the v15 workload keys.**
- **Project progress stays manual** (`POST /api/v27/projects/{id}/progress`).
