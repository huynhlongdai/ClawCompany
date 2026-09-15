# v22 — Cluster runtime: shared run reporting and session takeover

v21 made session *ownership* correct with a shared lease. It left two gaps,
both written down honestly in its own "Còn nợ" section. v22 closes them.

Service version `1.12.0`. No new tables, no migration.

## 1. The run view was one worker's memory

`GET /api/v20/streams` returned `supervisor.snapshot()`, which is a dict held
in the answering process. With two uvicorn workers, each response showed only
the sessions that worker happened to be following — and nothing in the payload
said so. An operator counting live runs got a number that changed depending on
which worker load balancing picked.

`services/stream_registry.py` publishes each follower's state to Redis under
`clawcompany:stream-state:<session key>`, refreshed as events arrive, with a
TTL longer than the lease TTL. A worker that dies leaves no stale row once the
TTL lapses, so there is no cleanup job.

Two deliberate constraints:

- **The registry never decides ownership.** The lease is the only authority on
  who may consume a session. If the two disagree, the lease wins and the
  registry row simply expires. A second source of truth for ownership would
  have re-introduced the double-write bug v21 fixed.
- **`withdraw` refuses to delete another worker's row**, the same ownership
  check the lease uses for `release`.

`cluster_snapshot()` merges the shared rows with this process's live state,
preferring local state because it is fresher than anything we last published.
When Redis is absent it returns `process_local: true` and
`registry.cluster_wide: false` rather than looking complete.

## 2. A lost lease left the session unattended

v21's follower stopped when it lost its lease — correct, it must not write the
same events twice. But nothing then picked the session up until a human
pressed "resume". The run kept going inside OpenClaw while the company
recorded none of it.

- `claimable_sessions(db)` is the list v21 could not express: mid-run tasks
  whose session has **no lease holder**. `resumable_sessions` includes
  sessions another worker is following happily; claiming those is refused
  anyway, so a sweep running every few seconds should not look at them.
- `claim_orphans(db, organization_id=None)` takes them over. Safe from every
  worker: the lease picks one winner, the rest come back as `declined`.
- `sweep_orphans_forever(interval)` is the background loop, started from the
  app startup hook and guarded by `OPENCLAW_CLAIM_SWEEP_SECONDS`.

`OPENCLAW_CLAIM_SWEEP_SECONDS` defaults to `0` (disabled), for the same reason
`OPENCLAW_RESUME_ON_BOOT` does: the sweep opens outbound gateway connections
on its own schedule, and that should be a deployment decision, not a default.
Every sweep failure is swallowed and printed; a sweeper must never be the
reason the API dies.

## 3. Surface

| Endpoint | Purpose |
| --- | --- |
| `GET /api/v22/runtime/streams` | Followers across every worker, tenant-scoped |
| `GET /api/v22/runtime/registry` | Is the view cluster-wide? Is the sweep on? |
| `GET /api/v22/runtime/orphans` | Mid-run sessions with no lease holder |
| `POST /api/v22/runtime/claim` | Take over unattended sessions now (manager+) |

Reads use `company.context:read`, writes `company.runtime:write`. Bridge tools:
4 new (total 104).

## 4. Validation

- Compiled: all new and edited backend modules and tests (`py_compile` → OK).
- Written but **not executed**: `backend/tests/test_v22_cluster_runtime.py`
  (16 tests). The sandbox has no network, so FastAPI/SQLAlchemy/pytest cannot
  be installed here.
- Not run: `alembic upgrade head`, `pytest`, `uvicorn`, `npm run build`.

The tests use a small `FakeRedis` to exercise the shared paths without a
server. That covers the logic, not the real Redis semantics of `SET NX EX`
and `SCAN` — those still need a run against an actual Redis instance.

On a networked machine:

```bash
cd backend && pip install -r requirements.txt && alembic upgrade head && pytest -q
npm install && npm run build
```

## 5. Still open

- `SCAN` is O(keys) per call. Fine for hundreds of sessions; a deployment with
  thousands should keep an index set instead of scanning.
- Takeover restarts a subscription; it does not replay events emitted during
  the unattended window. If the gateway does not retain them, that gap is
  permanent and is not currently reported to the operator.
- The registry and the lease each open their own Redis connection. They should
  share a pool.
- Still polling at 10s in the UI; WebSocket push remains unbuilt.
- `OPENCLAW_APPROVAL_REPLY_METHOD` (v21) still has no verified upstream value.
