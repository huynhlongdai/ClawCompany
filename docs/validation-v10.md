# v10 Validation

Validation performed on the generated v10 snapshot.

## Passed

```text
python -m compileall -q app tests
PASS

PYTHONPATH=. pytest -q tests/test_v10_units.py
6 passed

PYTHONPATH=. pytest -q tests/test_v8_units.py tests/test_v9_units.py tests/test_v10_units.py
13 passed

SQLAlchemy metadata create_all on sqlite:///:memory:
73 tables created

TypeScript/TSX transpile syntax check:
45 files
0 syntax errors
```

The focused v10 tests cover:

- artifact version chain and checksum behavior,
- artifact handoff/acceptance,
- event trigger → persistent agent message,
- QA verdict/status update,
- Nina decision-loop snapshot,
- SLA breach/escalation,
- Digital Twin simulation.

## Not passed / not claimed

A direct `seed.py` smoke run in this execution environment stopped before seed execution because the environment does not have `python-jose` installed. `python-jose[cryptography]` is present in `backend/requirements.txt`; Docker installs requirements before starting the API. This is recorded as an environment dependency limitation, not a seed-pass claim.

A dependency-resolved `npm run build` was not executed in this snapshot. TypeScript/TSX syntax was checked using the available TypeScript compiler only.

No live OpenClaw Gateway contract test was run. `OPENCLAW_MODE=mock` remains the validated development path from earlier versions; Gateway method/event names must be mapped against the exact OpenClaw release deployed.

## Known warnings

Tests currently emit Python 3.13 deprecation warnings for `datetime.utcnow()`. They do not fail tests, but a hardening pass should convert persisted timestamps to timezone-aware UTC consistently.
