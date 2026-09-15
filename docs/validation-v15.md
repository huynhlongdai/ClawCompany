# Validation v15

Validation performed on the final source snapshot in this archive:

- `python -m compileall -q backend` — **PASS**.
- v15 focused unit suite — **7 passed**.
- v7→v15 focused regression suite — **51 passed**.
- Fresh Alembic migration on a new SQLite database from baseline through `0011_v15_production_trust_sre` — **PASS**, 150 physical tables including `alembic_version`.
- SQLAlchemy metadata — **149 application tables**.
- TypeScript/TSX parser — **97 files, 0 syntax errors**.
- OpenClaw tool-contract JSON — **valid, 57 tools**.
- `docker-compose.yml` YAML parse — **PASS**. The Envoy mTLS edge is shipped as an explicit template, not an auto-enabled Compose service.

Not claimed as passed:

- Full `pytest -q` / API auth suite on this host: the host environment does not have `python-jose` installed. It remains pinned in `backend/requirements.txt` and is installed by the backend container build.
- `npm run build` / Next.js dependency-resolved build: no project `node_modules` snapshot is bundled/installed in this execution environment. TS/TSX syntax was parsed using the available TypeScript parser only.
- Live Envoy mTLS, Vault/AWS/GCP/Azure secret providers, Pushgateway/OTLP collector, cosign binary, Kubernetes, Firecracker or external paging webhook: adapters/configuration are present but no corresponding external infrastructure is available in this environment.
- Keyless Sigstore/Fulcio/Rekor transparency verification: intentionally fail-closed and documented as incomplete.

The historical Python 3.13 `datetime.utcnow()` deprecation warnings remain in older v7–v14 services; v15-new services use a UTC helper where practical, but the whole repository has not yet been migrated to timezone-aware persistence.
