# v12 validation record

This file records what was actually executed while producing the v12 artifact.

## Passed

### Python compilation

```bash
cd backend
python -m compileall -q app tests
python -m py_compile seed.py alembic/versions/0008_v12_secure_dev_cloud.py
```

Result: **passed**.

### Focused regression suite: v7 → v12

```bash
python -m pytest -q \
  tests/test_v7_units.py \
  tests/test_v8_units.py \
  tests/test_v9_units.py \
  tests/test_v10_units.py \
  tests/test_v11_repository_delivery.py \
  tests/test_v12_secure_dev_cloud.py
```

Result: **29 passed**.

The v12 file itself contains **6 passing tests** covering:

- tenant-rooted workspace provisioning and path normalization;
- Docker sandbox command hardening flags;
- secret grant execution without value leakage;
- production deployment approval gate;
- commit-pinned local filesystem deploy + rollback;
- artifact handoff → automatic repository delivery creation.

### SQLAlchemy metadata smoke

An in-memory SQLite engine successfully executed `Base.metadata.create_all()` with all model modules imported.

Result: **98 tables**.

### TypeScript / TSX syntax

The globally available TypeScript compiler API parsed/transpiled all `.ts` / `.tsx` files under `app`, `components` and `lib`.

Result: **64 files, 0 syntax diagnostics**.

This is a syntax validation, not a dependency-resolved Next.js production build.

### Static data/config validation

- `openclaw-company-bridge/tool-contracts.json` passed `python -m json.tool`.
- `docker-compose.yml` parsed successfully with PyYAML.
- migration `0008_v12_secure_dev_cloud.py` compiled successfully.

### Real Git / release behavior

The v12 test suite creates real temporary local Git repositories, commits two release versions, materializes exact commit contents through the filesystem deployment provider, changes the atomic environment pointer and rolls it back to the previous deployment.

Result: **passed**.

## Not marked passed

### Full backend `pytest -q`

Full collection reaches older auth/API tests that import `python-jose`. The artifact host does not currently have that package installed. `python-jose[cryptography]==3.3.0` is pinned in `backend/requirements.txt`.

An installation attempt was made, but the environment could not resolve/reach the package index because outbound network access is disabled. Therefore the full test suite is **not** claimed as passed in this artifact host.

### Seed smoke

`seed.py` imports the same auth security module, so an end-to-end seed run in this host would hit the same missing `python-jose` dependency. The file itself compiles, and Docker installs the pinned backend requirements before running seed, but a host seed execution is **not** claimed as passed.

### `npm run build`

`node_modules` are not installed in the artifact host and network installation is unavailable. The Next.js production build is **not** claimed as passed. TypeScript/TSX syntax parsing did pass.

### Docker / production providers

The following were not live-tested here:

- Docker image build / `docker compose up`;
- Docker sandbox execution;
- live GitHub delivery;
- Kubernetes/microVM sandbox;
- Vault/AWS/GCP/Azure secret providers;
- cloud/Kubernetes production deploy adapters;
- exact deployed OpenClaw RPC contract.

These limitations are intentional and documented rather than represented as production-complete behavior.
