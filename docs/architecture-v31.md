# v31 - Field-level audit values, department status, clearable columns

v30 gave every guarded write an exact revision counter and an audit feed. The
feed recorded *which* fields changed but never *what they changed from*, so
"who broke this" was answerable and "what did it say before" was not. v31
closes that gap and three related ones from section 21.6.

## What changed

### 1. Before-values in the audit (`app/services/field_diff.py`)

`row_guard.compare_and_set` now snapshots the writable columns before it
assigns, and emits a `changes` map of `{field: {from, to}}` alongside the old
field-name list. `write_audit.row_of` carries that map through, and
`field_diff.reconstruct` folds a feed into a per-field timeline.

Deliberate choices:

- **Values are truncated at 500 characters** (`MAX_VALUE_CHARS`) with a
  visible `...[truncated]` marker. An audit table is not a document store,
  and a 200 KB description pasted twice would otherwise double the size of
  `company_events`.
- **Secret-looking fields are redacted**, not stored: `password`,
  `password_hash`, `token`, `secret`, `api_key`. None of them are writable
  through `row_guard` today; the filter exists so that adding one later does
  not quietly start logging credentials.
- **A rewrite of the same value is not a change.** `compare_and_set` reports
  it under `unchanged` and still consumes the revision, because the write
  did happen and the caller should learn its token is stale.
- **Pre-v31 writes are counted, not hidden.** `reconstruct` returns
  `writes_without_values` and a `note`. A history that silently omits older
  rows is worse than one that admits the gap.

### 2. Departments have a status (`migration 0014`)

Since v29, cascade-archiving a department set `access_level` to
`confidential`. That conflated "nobody should read this" with "this team no
longer exists". `departments.status` now holds `active | paused | archived`
and `access_level` goes back to meaning permission only.

The backfill sets every row to `active`, then `archived` where
`access_level = 'confidential'`. **That is a guess**, and a one-way one: a
genuinely confidential active department will be marked archived. It is
called out in the migration itself so an operator can review before running.

v29's cascade still writes `access_level`; migrating it to `status` is a v32
task, kept separate so this migration stays reviewable.

### 3. Department names are unique per company

Same migration adds `uq_departments_company_name` on `(company_id, name)`.
It **refuses to run** if duplicates exist, raising a `RuntimeError` that
lists them, rather than renaming rows nobody has looked at.
`GET /api/v31/companies/{id}/departments/name-conflicts` is the endpoint that
tells you what to fix first. `create_department` and the new
`update_department` both pre-check, so a collision is a 409 naming the other
department instead of a 500 from the index.

### 4. Columns can be cleared (`__clear__`)

JSON `null` already meant "leave this column alone" for every v28 client, so
it could not be reused to mean "unassign". v31 adds an explicit sentinel:

```json
{ "expected_revision": "project:12:r7",
  "values": { "owner_member_id": "__clear__" } }
```

Only fields on an allowlist accept it (`row_guard.CLEARABLE`): project
description and owner, task description and assignee, department head, member
manager, company industry. Anything else returns `Field cannot be cleared:
<name>`. Statuses are excluded on purpose - a row with no status is not a
state the rest of the system knows how to read.

The REST equivalents are `PATCH /api/v31/departments/{id}` with
`clear_head: true` and `POST /api/v31/projects/{id}/owner` with
`clear_owner: true`. The latter rejects a body with neither field set, so a
misspelled key cannot silently unassign an owner.

## Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/v31/vocabulary` | statuses, clearable fields, sentinel, limits |
| GET | `/api/v31/history/{entity_type}/{entity_id}` | per-field value timeline |
| PATCH | `/api/v31/departments/{department_id}` | edit name, head, access level, status |
| GET | `/api/v31/companies/{company_id}/departments/name-conflicts` | duplicates blocking 0014 |
| POST | `/api/v31/projects/{project_id}/owner` | assign or unassign an owner |

Reads need `company.context:read`; writes need `company.workspace:write`,
plus role `manager` for department edits and `member` for project owners.
Five bridge tools expose the same surface to agents (152 total).

## Not done

- **Un-archiving a member still does not restore agent or session runtime
  state.** It needs a live gateway to verify; shipping it untested would be
  worse than leaving it listed.
- Non-guarded writes (`update_project`, `move_task`, `update_department`)
  still emit `changed` maps without before-values. Only the guarded path
  produces a full diff.
- No retention policy for `company_events`. Storing before-values makes that
  table grow faster, which makes the missing policy more urgent, not less.
- `row_revision` rows left uncounted by v30 are still never backfilled.

## Verification status

Unrun, and stated plainly: this sandbox has no network, so there is no
FastAPI, SQLAlchemy, alembic or pytest. The 30 tests in
`backend/tests/test_v31_field_audit.py` compile and pin decision logic;
the ones that need the ORM skip themselves via `importorskip`. On a networked
machine:

```bash
cd backend && pip install -r requirements.txt
alembic upgrade head     # fails loudly if duplicate department names exist
pytest -q
```
