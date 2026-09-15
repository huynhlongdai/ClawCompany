# v33 — Recovery & Retrieval

v33 closes four debts that earlier handovers reported honestly instead of fixing.
Every write in this release defaults to a dry run and is bounded per call, the
same contract v32 established for housekeeping.

Service version `1.23.0`. Router `/api/v33`. 10 new bridge tools (169 total).
No new migration: v33 adds no column.

## 1. A member restore no longer leaves the board lying

The v29 cascade archive sets `Member.status = offboarded`. Tasks that were
mid-flight keep their `runtime_session_key`, pointing at an OpenClaw session
that nobody will ever poll again. `entity_archive.restore_entity` restored the
row and deliberately stopped there — so after a restore the cockpit showed a
task `in_progress` with a dead session key, i.e. work in flight with no runner.

`app/services/member_reactivate.py`:

| Function | What it does |
| --- | --- |
| `orphans` | Tasks assigned to the member, in a running status, still naming a session key |
| `preview` | Orphan list split into parkable vs contested (lease still held) |
| `park` | **The only write.** Clears the dead session key, moves the task to `todo` |
| `resume_plan` | The `company.task.dispatch` calls that would restart the work — returned as data, never executed |
| `coverage` | What it fixes and what it refuses to do |

Deliberate choices:

- Parking lands in `todo`, not `backlog`. The work was already triaged once and
  demoting it would throw that decision away.
- A task whose runtime lease is still held is **never** touched. Some worker
  still believes it owns that session, and a repair routine must not fight a
  live process.
- `park` refuses with `ReactivateError` (HTTP 409) while the member is still
  archived. Repair the state first, then the runtime.
- Dispatch is not automated. Dispatch picks an agent and spends budget; that is
  not a decision a cleanup pass gets to make on the owner's behalf.

## 2. Project progress is measured, not typed

v27 derived a truthful progress number (`board_truth.derive`) and shipped a
one-project writer (`sync_progress`). It never shipped a way to run that across
a company, so in practice `Project.progress` stayed whatever a human typed
months ago.

`app/services/progress_autosync.py` is the batch pass. Three rules it will not
break:

1. A project with **no tasks** has no derived progress. It is reported as
   unknown and skipped — never silently written down to 0.
2. Drift below `MIN_DRIFT = 2` is noise, not news, and is not written.
3. `done` and `cancelled` projects are frozen: their progress is a historical
   record, not a live measurement.

`drift_report` sorts by absolute drift so the worst offenders come first.
`sync` delegates every actual write to `board_truth.sync_progress`, which stays
the single writer for that column and emits its own per-project event. One
failed project is recorded in `failed` instead of aborting the pass.

## 3. The knowledge mesh ranks instead of substring-matching

`knowledge_mesh.search` matched with `ILIKE %token%`. That is substring
matching, not retrieval — while v26 already shipped a real embedding path
(`vector_search.hash384_embedding` + `cosine`) used only by the document chunk
index.

`app/services/mesh_retrieval.py` joins the two, and the order matters:

1. Permission filtering and access logging stay inside
   `knowledge_mesh.search`. Nothing in this module queries entries directly, so
   there is no code path where a semantic search reads a space the member
   cannot read. The tests assert both facts.
2. Re-ranking happens afterwards, in memory, over that authorised candidate
   set (`limit x 5`, capped at 100).

Modes: `keyword` (v26 behaviour, unchanged), `semantic` (cosine only),
`hybrid` (default — `0.7` semantic + `0.3` keyword rank, because an exact
substring hit is rarely wrong, it just should not always win).

`explain()` is deliberately unflattering: `hash384` is a deterministic hashing
embedding, not a trained model. It is good at word overlap, word order and
typo-free paraphrase; it does **not** understand synonyms or cross-language
queries. Nobody should mistake this for a vector database.

## 4. The lease index set stops leaking

v26 replaced a `SCAN` over the keyspace with an index set, and pruned stale
members **only when `scan()` happened to run**. A deployment that never calls
scan therefore grew the set forever, one member per session that ever ran.

`runtime_leases` gains:

- `index_size()` — `SCARD` of the index, or `None` when there is no Redis. The
  leak is now visible in `status()`.
- `prune_index(dry_run=True, limit=1000)` — schedulable, bounded by
  `MAX_INDEX_PRUNE = 5000`, reads owners in batches of 200, and removes a
  member only when its lease key is actually gone. It can never unfollow a live
  session. On the memory backend it reports that there is no shared set to leak.

## 5. Endpoints and tools

| Method | Path | Role | Bridge tool |
| --- | --- | --- | --- |
| GET | `/api/v33/coverage` | read | `company.recovery.coverage` |
| GET | `/api/v33/members/{id}/runtime` | read | `company.member.runtime_orphans` |
| GET | `/api/v33/members/{id}/runtime/resume-plan` | read | `company.member.runtime_resume_plan` |
| POST | `/api/v33/members/{id}/runtime/park` | admin | `company.member.runtime_park` |
| GET | `/api/v33/progress/drift` | read | `company.progress.drift` |
| POST | `/api/v33/progress/sync` | manager | `company.progress.sync` |
| GET | `/api/v33/knowledge/search` | read | `company.knowledge.retrieve` |
| GET | `/api/v33/knowledge/retrieval-quality` | read | `company.knowledge.retrieval_quality` |
| GET | `/api/v33/runtime/lease-index` | read | `company.runtime.lease_index` |
| POST | `/api/v33/runtime/lease-index/prune` | admin | `company.runtime.lease_index_prune` |

API keys keep passing on scope alone (`company.workspace:write`), as in
v18–v32. `/knowledge/search` is the exception that refuses an identity-free
caller with HTTP 400: retrieval is filtered per member, so a key with no member
identity has no reading identity to filter by, and returning everything would be
a permission bypass dressed as a convenience.

## 6. Testing status — read this before trusting the numbers

`backend/tests/test_v33_recovery.py` adds **51 tests**. They have **never been
executed**: this sandbox has no network, so `fastapi`, `sqlalchemy` and `pytest`
cannot be installed. Everything shipped here is verified only by
`python3 -m compileall` and by reading the patched code in full context.

Running total across v19–v33: roughly 400 tests, none executed.

## 7. What v33 deliberately does not do

- **Does not re-dispatch work.** `resume_plan` hands you the calls; you make them.
- **Does not revive a runtime session.** A dead session key is dropped, not healed.
- **Does not replay lost runtime events.** Events that vanished with a dead
  session stay lost; only the board state is repaired.
- **Does not add synonym or multilingual retrieval.** That needs a real
  embedding provider, which needs network and a key.
- **Does not push progress in real time.** The sync is a pass you run or
  schedule, not a trigger on every task move.
