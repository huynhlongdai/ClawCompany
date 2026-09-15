# v27 — Board truth: derived progress, revision guards, archive cascade

Service version `1.17.0`. **No new tables, no migration.**

v27 adds no new capability. It closes the three debts v18 wrote down about its own write half (handover section 8.5) and never came back for:

| v18 debt | v27 |
| --- | --- |
| `Project.progress` typed by a human | Derived from the task board; drift is visible, applying it is an explicit action |
| No optimistic concurrency — the later save silently wins | Opt-in `expected_revision`; a mismatch returns 409 **with the current revision** |
| No archive/delete because the cascade needed designing | Archive = cancel what is still owed; nothing is deleted; live OpenClaw sessions block it |

## Revisions without a migration

`board_truth.revision(entity)` builds an opaque token from `updated_at`, which `TimestampMixin` already maintains via `onupdate` on every entity in `models/entities.py`. That is why there is no schema change — and it also means the token only moves when a write actually touched the row.

`expected_revision` is **optional**. Omitting it opts out, which keeps every pre-v27 client (including v18's own endpoints) working unchanged. Passing it is what buys the guarantee. The 409 body carries `current_revision` and `last_edited_at` so a client can re-read, show the difference and retry; a conflict that only says "no" forces a blind overwrite on the next attempt, which is the problem we started with.

## Progress derivation rules

```txt
progress = round(100 * done / (all tasks - cancelled))
```

- **Cancelled tasks leave the denominator.** Dropping scope must not pin a project at 50% forever.
- **`review` is not half a point.** Partial credit is how a number starts drifting away from anything you can point at — v18's hand-typed value already showed where that ends.
- **No countable tasks returns `derivable: false`, not 0%.** "Nothing to measure" and "measured zero" are different statements, and only one of them justifies overwriting a number a human typed on purpose.

Syncing is an explicit endpoint rather than a trigger on every task move: the stored column is what dashboards and exports read, and quietly rewriting a human's number during an unrelated write is how you lose their trust in the field entirely.

## Archive cascade

Archiving sets the project to `cancelled` — a status from v18's own `PROJECT_STATUSES` — and cancels every task still in an open status. Done tasks stay done. **Nothing is deleted**, so an archived project remains readable, auditable and reversible instead of becoming a hole in every historical report.

The hazard v18 could not have designed for arrived with v20–v26: a task can be attached to a **live OpenClaw session**. Cancelling it out from under a follower leaves an agent running inside the gateway with nothing on our side recording it — exactly the orphaned-stream state v22 through v26 exist to prevent. So:

- `archive_preview` reports each live session and who holds its lease.
- Archive refuses with 409 while any exist.
- `force: true` archives anyway and reports `left_running`. It does **not** claim to have stopped anything: aborting a run is `POST /api/v19/tasks/{id}/abort`, and implying otherwise would be worse than refusing.

## Surface

| Endpoint | Role | Purpose |
| --- | --- | --- |
| `GET /api/v27/projects/{id}/truth` | read | Derived progress, stored value, signed drift, revision |
| `POST /api/v27/projects/{id}/progress/sync` | member+ | Apply the derived number |
| `GET /api/v27/projects/{id}/archive/preview` | read | What archiving cancels, and what blocks it |
| `POST /api/v27/projects/{id}/archive` | manager+ | Archive with cascade |
| `GET /api/v27/revisions/project/{id}` | read | Revision token before a guarded write |
| `GET /api/v27/revisions/task/{id}` | read | Same, for a task |
| `POST /api/v27/tasks/{id}/move` | member+ | v18's move, refusing a stale read |

Scopes match v18 (`company.context:read` / `company.workspace:write`) because this is cockpit writing, not runtime control. Bridge tools: 5 new (total **117**).

UI: `/app/workspace-ops` gains the "Sự thật bảng dự án (v27)" panel — board progress vs stored column, the archive preview, and a force button that only appears when something is actually blocking.

## Events

- `project.progress.derived` — from/to, complete/countable
- `project.archived` — cancelled task ids, whether it was forced, what was left running
- `board.write.conflict` — a stale write was rejected; failing to emit this never turns the 409 into a 500

## Testing

`backend/tests/test_v27_board_truth.py` — 21 tests, **not run** (the sandbox has no network, so FastAPI/SQLAlchemy cannot be installed). They use light stand-ins for the ORM rows, so they pin the decision logic, not the SQL.

## Known debt

- Revision guards are **opt-in**. A client that never sends `expected_revision` is exactly as unprotected as it was in v18.
- The window between reading a revision and writing is not transactional: two writers who read the same revision and race at the millisecond level can both pass the check. Closing that needs a conditional `UPDATE ... WHERE updated_at = ?`, i.e. real row-level compare-and-set.
- Progress sync is manual. Deriving it on every task move would need a decision about whether a derived column may overwrite a human's value silently — v27 deliberately does not make that decision.
- Archive covers projects only. Companies, departments and members still have no archive path, and their cascades are wider.
- Unarchive exists only as "set the status back" via v18; cancelled tasks are not restored, because we do not record which ones we cancelled beyond the event payload.
