# v28 — Binding write guards & reversible archive (1.18.0)

v27 closed the three debts v18 declared, and then wrote down two of its own
in section 18.7. v28 closes those two. No new tables, no migration.

## 1. The race v27 could not close

v27's `check_revision` loads a row, compares its `updated_at` token against
what the client read, and raises 409 on a mismatch. That catches a human
editing a stale form. It does not catch two writers who read the *same*
revision microseconds apart: both pass the check, both write, the later one
silently wins — which is the original v18 defect, just narrower.

`services/row_guard.py` does the write as a conditional UPDATE:

```py
UPDATE projects SET name = ?, updated_at = ? WHERE id = ? AND updated_at = ?
```

If `rowcount` is 0, nothing was written and the 409 is a report of what the
database did, not a prediction. `updated_at` is set explicitly because this
is a Core UPDATE and the ORM's `onupdate` does not fire for it; without that
the revision would not move and the next writer would pass a guard it should
have failed.

Both mechanisms are kept, with one honest difference:

| | v27 `check_revision` | v28 `compare_and_set` |
| --- | --- | --- |
| Enforced by | application, before the write | the database, during the write |
| `expected_revision` | optional (pre-v27 clients keep working) | required |
| Safe under concurrent writers | no | yes |
| Usable in a preview endpoint | yes | no, it writes |

## 2. Field allowlist

A generic guarded-update endpoint is a privilege-escalation surface if it
takes its field list from the request body: `company.workspace:write` would
become permission to set `organization_id` or `runtime_session_key`.
`row_guard.WRITABLE` fixes the writable columns per entity, `GET /api/v28/guards`
publishes them so clients stop hardcoding, and a test asserts tenancy and
runtime columns appear in no list.

Guarded task writes set columns directly, so they deliberately bypass v18's
status transition rules. Status moves belong to `POST /api/v27/tasks/{id}/move`,
and the docstring says so rather than leaving a trap.

## 3. Restoring an archive

v27 archived by cancelling every open task and recording their ids in the
`project.archived` event. Reversing it meant fixing the project status by hand
and the tasks stayed cancelled, because nobody read that payload back.

`services/board_restore.py` reads it back. The event bus is already durable
and organization-scoped, so restore needs no new column — the organization
filter is part of the query, since `aggregate_id` is a bare integer and
without it one tenant could read another's payload.

Two deliberate limits:

- A task somebody moved *after* the archive is left alone and listed under
  `will_skip_tasks`. The event records what we cancelled, not what we own.
- Archives written before v28 carry no `previous_status`, so the project
  returns to `planning` and the response sets `previous_status_known: false`.
  v28's archive path now records the previous status so future restores are
  exact.

## 4. Endpoints (126 bridge tools)

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/v28/guards` | entities and fields open to a guarded write |
| POST | `/api/v28/guarded/projects/{id}` | compare-and-set on a project |
| POST | `/api/v28/guarded/tasks/{id}` | compare-and-set on task fields |
| POST | `/api/v28/guarded/companies/{id}` | compare-and-set on a company (manager+) |
| POST | `/api/v28/guarded/departments/{id}` | compare-and-set on a department (manager+) |
| POST | `/api/v28/guarded/members/{id}` | compare-and-set on a member (manager+) |
| GET | `/api/v28/projects/{id}/restore/preview` | what un-archiving would do |
| POST | `/api/v28/projects/{id}/restore` | reverse an archive (manager+) |
| GET | `/api/v28/projects/{id}/history` | truth + archive + restore in one call |

## 5. Testing, honestly

`tests/test_v28_write_guards.py` has 26 tests over token parsing, the field
allowlist, conflict shape, rollback-on-conflict and restore selection. They
have never been executed: this sandbox has no network, so SQLAlchemy and
pytest cannot be installed. They also use fake rows, which means the one
thing v28 is actually about — that the conditional UPDATE matches zero rows
when the timestamp moved — is asserted at the decision level only. It needs
a real database, and preferably two concurrent writers, to be called
verified.

## 6. Remaining debt

- `updated_at` has second-or-better resolution depending on backend; two
  writes inside the same tick could produce the same token. A monotonic
  revision counter column would remove the ambiguity, at the cost of the
  migration v27 and v28 both avoided.
- Archive/restore still exists only for projects. Companies, departments and
  members have wider cascades (members hold agents, agents hold sessions) and
  were not attempted here.
- Restore reopens tasks to `todo`, not to whatever they held before the
  archive; the archive event records ids, not per-task prior statuses.
- Guarded writes emit `board.write.guarded`, but nothing consumes it yet as
  an audit view.
