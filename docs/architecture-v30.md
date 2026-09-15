# v30 — Revision counter, audit paging, batch board restore

v29 ended with three open items in section 20.6. v30 closes them, and the
first one finally spends the migration that v27, v28 and v29 all avoided.

## 1. An exact revision counter (migration 0013)

Since v27 a revision token has been `kind:id:updated_at`. That guard is
honest most of the time and wrong in one case: two writes inside the same
clock tick produce the same timestamp, so the second writer's compare-and-set
can succeed against a row it never read.

`0013_v30_row_revision_counter` adds a nullable `row_revision` integer to
`companies`, `departments`, `members`, `projects`, `tasks` and sets existing
rows to 1. `RevisionMixin` carries the column on the model side.

- Token becomes `project:12:r7` for counted rows.
- The old timestamp form is still accepted and still returned as
  `legacy_revision`, so a pre-v30 client keeps working.
- `GET /api/v30/revisions/{kind}/{id}` reports both tokens plus `exact`,
  which is the only field that matters when a caller wants a guarantee.

Why nullable rather than `NOT NULL DEFAULT 1`: a row whose counter is unknown
must not present itself as "version 1" — that would hand out a guarantee the
data cannot back. `counter()` returns `None`, never 0, and the row keeps the
timestamp guard until its first guarded write, which adopts it at 1.

`row_guard.compare_and_set` now picks the condition from the token shape:
`row_revision == n` for counter tokens, `updated_at == stamp` otherwise. It
refuses a counter token on a row that has no counter instead of silently
downgrading, and every response says which guard it actually got
(`guard_mode`, `exact`).

## 2. Cursor paging on the audit feed

v29's feed took a limit and said "truncated: true" with no way forward.
`GET /api/v30/audit` accepts `cursor` and returns `next_cursor` / `has_more`.
The cursor is a `CompanyEvent.id`, walked descending; event ids are monotonic
and events are never rewritten, so pages cannot shift under a reader the way
an offset would.

One subtlety worth stating: category filtering happens in Python, after the
SQL page is fetched. The cursor is therefore the last event **scanned**, not
the last row returned. Paging on the last returned row would re-serve every
event the filter dropped at the tail of the page.

A malformed cursor returns the first page instead of a 422. Paging is a
navigation aid, not a write, and a bad bookmark is not worth an error page.

## 3. Batch reopen of a company's board

v29 deliberately did not reopen projects when un-archiving a company:
reopening a board is a board decision. That was right, but it left an
operator clicking restore once per project.

`services/cascade_restore.py` reads the company's archive event, which
records `archived_projects[*].project_id`, and reopens exactly those.

- `GET /api/v30/companies/{id}/projects/restore/preview` lists what would
  reopen, to which status, and how many tasks come back; it also lists skips
  with reasons (already reopened by a human, project deleted).
- `POST .../restore` runs each project through the v28 restore path, so v29's
  task-status fidelity and the leave-what-humans-moved rule are inherited
  rather than re-implemented.
- One failing project rolls back that project only; it is reported in
  `failed` and the batch continues. `complete: false` says so plainly.
- No archive record means 409. Without the record there is no defensible
  list, and "reopen every cancelled project in the company" would resurrect
  boards that were cancelled for unrelated reasons.
- The response repeats `company_still_archived`. Reopening a board does not
  un-archive the company, and the UI should not imply otherwise.

## Surface added

| Method | Path |
| --- | --- |
| GET | `/api/v30/revisions` |
| GET | `/api/v30/revisions/{kind}/{entity_id}` |
| POST | `/api/v30/guarded/{kind}/{entity_id}` |
| GET | `/api/v30/audit` |
| GET | `/api/v30/companies/{company_id}/projects/restore/preview` |
| POST | `/api/v30/companies/{company_id}/projects/restore` |

Bridge tools go 141 → 147. Frontend: `apiV30` in `lib/api.ts` and
`components/RevisionAuditPanel.tsx`, mounted in the workspace ops console.

## What v30 does not do

- Rows never touched since migration 0013 keep the inexact timestamp guard
  until their first guarded write. There is no backfill pass, because a
  backfill would have to invent a version number for rows other writers may
  hold tokens for.
- The audit feed still reports which fields moved, not their previous
  values. Reconstructing old values needs the write path to record them.
- Un-archiving a member still does not restore agent or session state.
- `Department` still has no status column (access level is used instead) and
  no unique-name constraint; `update_project` still cannot clear
  `owner_member_id`.

## Verification status

Nothing in v30 has been executed. The sandbox has no network, so FastAPI,
SQLAlchemy, alembic and pytest are not installed; every file compiles
(`py_compile`) and nothing more than that has been proven. On a networked
machine: `alembic upgrade head` (head becomes `0013_v30_row_revision_counter`),
`pytest -q`, then the test that matters most — two concurrent writers against
one row, where exactly one should win.
