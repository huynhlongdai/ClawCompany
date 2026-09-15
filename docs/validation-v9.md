# v9 Validation

Validation performed on the generated v9 snapshot:

## Passed

```text
python -m compileall -q backend/app
```

Result: backend Python syntax compilation passed.

Focused v9 tests:

```text
PYTHONPATH=. pytest -q tests/test_v9_units.py
```

Result: **4 passed**.

The focused tests cover:

- timezone-aware recurring cron calculation
- autonomy risk threshold evaluation
- budget reserve → settle ledger behavior
- end-to-end mock autonomous operating cycle with two dependency-ordered AI assignments, runtime streaming, budget settlement and goal completion


Frontend source syntax parser:

```text
TypeScript 5.8 parser over all .ts/.tsx sources
```

Result: **33 TS/TSX files parsed, 0 syntax errors**. This is syntax validation only, not a dependency-resolved Next.js build.

Model schema smoke test:

```text
Base.metadata.create_all(sqlite:///:memory:)
```

Result: metadata created successfully with **60 tables** in this snapshot.

## Frontend validation limitation

A normal TypeScript/Next.js build requires project dependencies. `npm install` was attempted in the execution environment but timed out, so a production Next.js build was not claimed.

The v9 source is still included with its pinned `package.json`; run `npm install && npm run build` in a network-enabled CI/dev environment.

## Not run

- full backend test suite (local execution image lacks several pinned auth/worker dependencies such as `python-jose`, `passlib`, `celery`)
- Postgres + pgvector integration suite
- Redis/Celery/Beat integration suite
- real OpenClaw Gateway contract test
- browser E2E suite

Warnings from focused tests: legacy models/services still use `datetime.utcnow()`, which Python 3.13 warns is deprecated. This is a known hardening task; v9 does not silently claim it is resolved across the inherited schema.
