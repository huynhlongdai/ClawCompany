# v31.1 — review pass, three real defects

Version `1.21.1`. No new surface: no endpoints, no tools, no migrations added.
This release exists because the v31 review found bugs, and a fix release with
an honest changelog is cheaper than a feature release that carries them.

## 1. The guarded write compared the row against the value it was writing

`row_guard.compare_and_set` unpacked the parsed revision into `value`:

```python
name, row_id, mode, value = rev.parse(expected_revision)
...
for field, value in values.items():   # <-- rebinds the same name
...
condition = model.row_revision == value   # <-- now the written value
```

The v31 patch added that loop (for the `__clear__` sentinel) and reused the
name. From then on the conditional `UPDATE` compared `row_revision` — or
`updated_at` — against the last field value in the request body instead of
the expected revision. In practice every guarded write raised 409 on a row
nobody else had touched, and in the rare case the value happened to match,
the guard passed without checking anything.

This is the single guarantee v28 was built to provide, and the v31 tests did
not catch it because they asserted on the returned payload and never on the
SQL predicate. The fix renames the parsed value to `expected_value`; the
tests now assert on the predicate itself.

## 2. `create_project` referenced a parameter it does not have

The same patch landed `and not clear_owner` in `create_project`, where
`clear_owner` is not defined — it belongs to `update_project`. Creating a
project with an owner raised `NameError`, i.e. a 500, on one of the oldest
calls in the module. Nothing in the suite creates a project with an owner,
which is how a ten-version-old code path broke silently.

Related, fixed in the same pass: `update_project` applied `clear_owner`
first and then a non-null `owner_member_id`, so a body sending both ended up
assigning. Clearing is the destructive, explicit intent and now wins.

## 3. `has_values` was true for an empty diff

`write_audit.row_of` reported `has_values: isinstance(changes, dict)`. An
empty `changes` dict — a guarded write that set columns to the values they
already held — satisfied that, so the reader showed an empty history and
claimed it was complete. Now `has_values` requires a non-empty diff, which
makes the three states distinct and readable:

| `changes` | `has_values` | meaning |
| --- | --- | --- |
| absent (`None`) | `false` | written before v31, before-values unknowable |
| `{}` | `false` | written after v31, no value actually moved |
| populated | `true` | reconstructable |

## 4. Migration `0014` could leave a half-migrated schema

`upgrade()` added the `status` column, backfilled it, and *then* raised on
duplicate department names. On PostgreSQL the DDL rolls back with the
transaction; on SQLite and MySQL it does not, so a refused upgrade left the
column behind and the second attempt died on `duplicate column`. The
duplicate check now runs before the first DDL statement, so a refusal is a
no-op and the upgrade is safe to re-run after renaming.

## Tests

`backend/tests/test_v31_bugfixes.py`, 17 tests. Bugs 1 and 2 are asserted
statically — against the source and the AST — because reproducing them needs
a live session and two concurrent writers, and the defects are structural.
That is a weaker test than a behavioural one, and it is written down here as
such: it prevents the exact regression, not the whole class.

Still unrun in this sandbox (no network, no `pytest`, no database). On a
networked machine:

```bash
cd backend && pip install -r requirements.txt && pytest -q
```

## What the review did not fix

* The fifth debt from 21.6 — restoring agent and session runtime state when
  a member is un-archived — still needs a live gateway.
* Non-guarded writes (`update_project`, `move_task`, `update_department`)
  still emit a `changed` map with no before-values. Only guarded writes have
  a real audit trail.
* v29's cascade archive still flips `access_level`; it has not been moved to
  the new `departments.status`.
* `departments.status` is nullable in the database and non-null in the
  model. SQLite cannot add a NOT NULL column with a default in one step, so
  tightening it needs a table rebuild in a later migration.
