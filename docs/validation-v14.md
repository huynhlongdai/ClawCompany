# ClawCompany v14 Validation Record

This file records checks that were actually executed against the v14 snapshot. It deliberately distinguishes syntax/unit/schema validation from infrastructure that was not available in the build host.

## Passed

| Check | Result |
|---|---|
| Backend Python bytecode compile | PASS — `python -m compileall -q backend` |
| v14 focused unit/integration tests | PASS — 8 passed |
| Focused regression v7 → v14 | PASS — 44 passed |
| SQLAlchemy current metadata | PASS — 133 model tables |
| Alembic head | PASS — `0010_v14_distributed_secure_execution` |
| Fresh Alembic migration chain on SQLite | PASS — 133 model tables, head `0010_v14_distributed_secure_execution` |
| v14 tables in migrated schema | PASS |
| TypeScript/TSX parser check | PASS — 89 files, 0 syntax parse errors |
| OpenClaw tool-contract JSON | PASS — valid JSON, 49 tool contracts |
| Docker Compose YAML | PASS — services: db, redis, api, worker, beat, web |

The fresh migration smoke uncovered and fixed an inherited historical migration issue: the v6-v8 metadata-backed migrations previously imported current metadata without limiting the historical table set. They are now scoped to their respective version table sets, and the v11 `api_keys.member_id` evolution is idempotent/SQLite-batch compatible. A clean SQLite database can now migrate from baseline through v14 without table/column collisions.

## Test command used for focused regression

```bash
cd backend
PYTHONPATH=. pytest -q \
  tests/test_v7_units.py \
  tests/test_v8_units.py \
  tests/test_v9_units.py \
  tests/test_v10_units.py \
  tests/test_v11_repository_delivery.py \
  tests/test_v12_secure_dev_cloud.py \
  tests/test_v13_ai_engineering_org.py \
  tests/test_v14_distributed_execution.py
```

Observed result: **44 passed**.

The v14-only file produced **8 passed**.

## Warnings / technical debt observed

The regression run emitted 1,048 warnings. Most are Python 3.13 deprecation warnings for `datetime.utcnow()`. The v14-only run emitted 235 warnings. These are not test failures, but the codebase should migrate to timezone-aware UTC timestamps before treating the runtime as production-hardened.

## Not claimed as passed

- **Full `pytest -q` suite:** not completed on this host because `python-jose` is not installed in the host interpreter. `python-jose[cryptography]==3.3.0` remains pinned in `backend/requirements.txt` and is installed by the container build path.
- **Seed end-to-end on this host:** not marked passed for the same missing `python-jose` host dependency. The v14 seed additions are idempotent by construction/query guards but were not given an end-to-end success claim here.
- **`next build` / full TypeScript dependency-resolved typecheck:** not run because this snapshot host has no local `node_modules`. The global TypeScript parser was used only for syntax parsing.
- **Live Firecracker/microVM runner:** not installed or tested. v14 provides the control-plane/runner contract only.
- **Live Kubernetes runner/traffic routing:** not tested against a cluster. Kubernetes traffic mutation is opt-in and disabled by default.
- **Live Sigstore/cosign trust verification:** cosign signing adapter exists, but no live transparency-log/keyless trust-policy verification was exercised.
- **Live Semgrep/Trivy/OSV scanners:** adapters exist; external binaries were not bundled or live-tested.
- **Production Prometheus/OpenTelemetry ingestion:** REST metric ingestion/SLO evaluation is implemented; dedicated telemetry adapters are future work.

## Migration note

The v6-v8 migrations remain metadata-assisted historical migrations rather than fully hand-reviewed explicit DDL for every baseline table. They are now version-scoped and a clean migration chain is validated, but a production release should still freeze/review the baseline schema and exercise the same chain against the target PostgreSQL + pgvector version in CI.
