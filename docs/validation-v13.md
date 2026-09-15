# ClawCompany v13 Validation

This document records checks actually executed for the v13 artifact. It deliberately separates syntax/unit/smoke validation from production deployment certification.

## Backend

Commands used include:

```bash
python -m compileall -q app tests
python -m pytest -q tests/test_v13_ai_engineering_org.py
python -m pytest -q \
  tests/test_v7_units.py \
  tests/test_v8_units.py \
  tests/test_v9_units.py \
  tests/test_v10_units.py \
  tests/test_v11_repository_delivery.py \
  tests/test_v12_secure_dev_cloud.py \
  tests/test_v13_ai_engineering_org.py
```

Results in the final source snapshot before packaging:

- backend compile: **PASS**
- v13 focused suite: **7 passed**
- v7 → v13 focused regression: **36 passed**
- warnings are primarily Python 3.13 `datetime.utcnow()` deprecations plus a future `tarfile.extractall` behavior warning; they did not fail the focused suites.

A full `pytest -q` collection was also attempted. It is **not marked passed** because four legacy API test modules import `python-jose`, which is not installed in the artifact host (`ModuleNotFoundError: jose`). `python-jose[cryptography]==3.3.0` is already pinned in `backend/requirements.txt`.

## Database metadata

The SQLAlchemy metadata smoke check created the complete schema in an in-memory SQLite database: **116 tables**. Key v13 tables were present. `python -m alembic heads` reported `0009_v13_ai_engineering_org (head)`.

## Frontend validation

A TypeScript 5.8.3 `transpileModule` pass was used as a **syntax-only parser** for all `.ts`/`.tsx` source files. Result: **75 files, 0 syntax errors**. It does not replace `tsc` type checking or `next build`.

A full typecheck/production build is **not marked passed**. The artifact host has no local `node_modules`; React/Next/type declarations are therefore unresolved for a real `tsc`/Next build. No dependency installation/build success is claimed.

## Bridge and package

`openclaw-company-bridge/tool-contracts.json` parsed successfully and contains **40 tool contracts**, including 8 v13 engineering tools. `docker-compose.yml` parsed successfully with services `db`, `redis`, `api`, `worker`, `beat`, `web`. The final ZIP is tested with `unzip -t` and a SHA-256 digest is recorded after packaging.

## Out-of-scope/live dependencies

The artifact validation does not claim:

- live Firecracker/microVM execution;
- live Kubernetes runner execution;
- live weighted canary routing;
- live GitHub/OpenClaw/cloud production integration;
- signed supply-chain attestations;
- external CVE/SAST provider coverage.


## Seed smoke

`backend/seed.py` compiles and includes an idempotent v13 baseline for the governed CI graph, staging health policy and engineering initiative. An end-to-end seed execution was attempted against a fresh temporary SQLite database, but it stops at import time because the artifact host does not have `python-jose` installed. For that reason seed runtime is **not marked passed** in this host environment.
