# v26 — Shared Redis fabric (1.16.0)

No new capability. v26 fixes three defects that only become visible when you
read v21, v22 and v25 side by side, and that only hurt in the deployment we
keep telling people to use: more than one worker.

## Why

### 1. Two private clients, two opinions

`runtime_leases` and `stream_registry` each called `redis.from_url` at import
time. That is two connection pools per worker for one server, and — the part
that actually matters — two *independent* answers to "is Redis there?".

A worker could hold genuine shared leases while its registry reported
`cluster_wide: false`. Both statements were true about their own private
socket, and together they were a lie about the worker. v22 exists to remove
exactly that class of half-truth.

### 2. The first error was permanent

Both stores set `self._redis = None` on any exception and never tried again.
One network blip silently demoted a worker to in-process memory **until
somebody restarted it**. The status endpoint kept reporting `memory`, which
was technically correct and completely unhelpful.

### 3. `SCAN` where an index belongs

`scan()` and `snapshot()` walked the keyspace. `SCAN` is O(keys in the whole
database), not O(our keys) — fine with a few hundred sessions and a dedicated
Redis, wrong the moment ClawCompany shares a server with anything else.

## What changed

`services/redis_pool.py` owns one lazily-connected client for the process.
Stores call `pool.client()` and `pool.drop(err)` instead of holding handles,
so one store noticing an outage informs the others, and `RETRY_SECONDS = 10`
turns a blip back into a blip. `status()` redacts the password in the URL:
this is rendered in an API response.

Lease and registry reads now use index sets (`clawcompany:stream-lease-index`,
`clawcompany:stream-state-index`). The index is a **hint, not the truth** —
a key can expire while its member lingers — so readers verify against the
actual keys and prune what has gone. Pruning on read is why no cleanup job is
needed: the only code that reads the index is also the only code that can
tell a stale member from a live one.

If the index is empty, both stores fall back to the old walk and rebuild it.
A v25 worker's leases are therefore adopted with no migration step.

`stream_reconcile` writes each pass to a shared ledger. This matters more
than it looks: v25's cooldown was per-process, so a session bouncing between
three workers asked the gateway three times inside the window one worker
would have asked once. A rate limit that multiplies with your worker count is
not a rate limit. `history()` merges shared rows with local ones and lets the
shared row win — another worker's newer pass beats our older memory.

## API

| Endpoint | Purpose |
| --- | --- |
| `GET /api/v26/runtime/fabric` | Pool, lease, registry and ledger in one answer, plus `consistent` |
| `GET /api/v26/runtime/index` | Index-set health; reading it also prunes |
| `POST /api/v26/runtime/fabric/reconnect` | Skip the backoff after fixing Redis (manager+) |

Bridge: 3 new tools, 112 total.

## Honest limits

- Tests use a small `FakeRedis`. It covers the logic; it does **not** cover
  real `SET NX EX`, `SMEMBERS` or `MGET` semantics. Only a live Redis counts
  as verified, and none of v19–v26 has been run.
- The index prunes on read. A key that expires and is never read again leaves
  its member in the set indefinitely. The set is bounded by session count,
  so this is a leak in theory and not in practice — but it is a leak.
- `RETRY_SECONDS` is fixed, not exponential. During a long outage every
  worker dials every 10 seconds.
- Still no replay of missed events, and the `exec.approval.list` response
  shape remains inferred rather than documented.
