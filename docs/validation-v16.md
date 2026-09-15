# v16 validation — what was checked, and what to run

Rebuilt in v22 after the original file was lost from the working tree. Section 5
of the handover page pointed here, so it now exists again.

## 1. What was actually checked in the build sandbox

| Check | Result |
| --- | --- |
| `python3 -m compileall` over backend, tests, migrations | OK |
| `__tablename__` collision scan against v1–v15 | no collisions |
| `openclaw-company-bridge/tool-contracts.json` parses, names unique | OK |
| Route inventory matches `docs/v16-api.md` | OK (30 routes) |

## 2. What was NOT checked

The sandbox has no network access, so these could not be installed:
`fastapi`, `sqlalchemy`, `pydantic`, `alembic`, `pytest`, `next`. Consequently:

- `alembic upgrade head` — never run. Migration `0012` is unproven.
- `pytest` — the 16 v16 tests are **written but never executed**.
- `uvicorn` — the app has never started; no endpoint has served a request.
- `npm run build` — the two v16 pages have never been type-checked or built.

Every later version (v17–v22) inherits the same limitation.

## 3. Commands to run on a networked machine

```bash
# Backend
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
pytest -q                      # all versions
pytest -q tests/test_v16_agent_collaboration_mesh.py
uvicorn app.main:app --reload  # then GET /health

# Frontend (repo root)
npm install
npm run build
```

## 4. Manual smoke path for v16

After `uvicorn` is up and you have a manager JWT:

1. `POST /api/v16/teams` — create a cross-company team.
2. `POST /api/v16/teams/{id}/members` — add a lead and two contributors;
   confirm an out-of-company member is rejected when the team is company-scoped.
3. `POST /api/v16/rooms` then `/participants`, `/turns` — post turns in order,
   then deliberately out of order and confirm the rejection.
4. `POST /api/v16/delegations` → `/accept` → `/deliver` → `/close` with
   `rework`, and confirm the contract returns to `accepted`.
5. `POST /api/v16/knowledge-spaces` with `classification=confidential`, then
   `GET /knowledge-spaces/{id}/permission?member_id=` for an outsider and
   confirm `none`; add a grant, re-check, then set `expires_at` in the past and
   confirm the permission drops without any cleanup step.
6. `GET /api/v16/knowledge-mesh/access-logs` — confirm the denied attempt from
   step 5 is recorded, not just the successful reads.

## 5. Expected failures worth knowing

- `Department` has no unique-name constraint, so duplicate department names
  are accepted by design decisions made before v16.
- There are no delete/archive routes for v16 objects; cleanup is manual.
- Two managers editing the same space will overwrite each other (no optimistic
  concurrency).
