# v18 — Workspace Operations (the write half of the cockpit)

## Why

v17 made the business screens read real tenant data, but every screen was still
read-only: you could look at the organization and not change it. Anything real —
standing up a company, hiring, registering an agent seat, filing work — still
required the older per-entity CRUD endpoints, which apply no organizational
rules. v18 adds a guarded write surface so the cockpit is usable as an operating
console, and so an openclaw agent can restructure work without being able to
corrupt it.

**No new tables. No migration.** Head remains `0012_v16_agent_collaboration_mesh`.
Service version is now `1.8.0`.

## Rules the UI cannot bypass

All of these live in `app/services/workspace_ops.py`, not in the frontend, so the
same rules apply to a human clicking a button and an agent calling the bridge.

| Rule | Behavior |
| --- | --- |
| Duplicate company names | Case-insensitive check per organization → `409` |
| Agent seats | An `agent` member without `runtime_agent_id` is rejected; a valid one creates the `Agent` runtime row in the same transaction |
| Runtime id collisions | A `runtime_agent_id` already bound in the organization → `409`, and the just-created orphan seat is rolled back |
| Department/company mismatch | A seat cannot join a department belonging to another company → `400` |
| Company moves | Moving a seat to another company clears its now-invalid department |
| Reporting cycles | Manager changes walk the chain upward; a cycle → `400` |
| Task transitions | Explicit state machine; skipping review → `409` |
| Starting work | A task cannot enter `in_progress`/`review` unassigned → `400` |
| Assignment | Suspended/offboarded members cannot receive work → `400`; work in progress cannot be unassigned |
| Vocabulary | Statuses, priorities and access levels are validated server-side, not merely constrained by dropdowns |

### Task state machine

```text
backlog ─▶ todo ─▶ in_progress ─▶ review ─▶ done
   │        │          │              │         │
   │        ▼          ▼              ▼         └─▶ review (reopen)
   └─▶ cancelled ◀────┴──────────────┘
```

`cancelled` can return to `backlog`; `done` can only reopen to `review`.

## Authorization

Writes use a combined gate. `require_role` rejects API keys outright, while
`require_scope` waves JWTs through, so together they mean: **humans are checked
by role, agents by scope.**

- Structural changes (company, department, seats): human `manager` role, or API key with `company.workspace:write`.
- Work changes (projects, tasks, knowledge): human `member` role, or the same scope.
- Every target is resolved through `ensure_company` / `ensure_project` / `ensure_task` /
  `ensure_member` first, so a cross-tenant id returns 403/404 before any write.

## Surfaces

- API: 13 endpoints under `/api/v18/workspace/*` — `companies` (POST/PATCH),
  `departments`, `members` (POST/PATCH), `projects` (POST/PATCH), `tasks`,
  `tasks/{id}/move`, `tasks/{id}/assign`, `knowledge`, and `vocabulary`.
- `GET /api/v18/workspace/vocabulary` exists so the UI can build dropdowns and
  render only legal transitions instead of hardcoding them and drifting.
- Events: every mutation emits a `company_event_bus` event from source
  `workspace_ops` — `company.created|updated`, `department.created`,
  `member.created|updated`, `project.created|updated`, `task.created`,
  `task.assigned`, `task.<new-status>`, `knowledge.document.created`.
- UI: `/app/workspace-ops` — forms for company, department, seat (human or
  agent), project and task, plus a task queue whose action buttons are generated
  from the server's transition map.
- OpenClaw bridge: 10 new tool contracts (80 total).

## Validation status

No network in the build sandbox, so runtime dependencies still cannot be installed.

- ✅ `python3 -m compileall backend/app backend/tests backend/alembic/versions` — OK.
- ✅ Tool contract JSON validates, 80 tools, no duplicate names.
- ⚠️ `backend/tests/test_v18_workspace_ops.py` (16 tests) written but **not executed**.
- ❌ Not run: `alembic upgrade head`, `pytest`, `uvicorn`, `npm run build`.

```bash
cd backend && pip install -r requirements.txt && alembic upgrade head && pytest -q
npm install && npm run build
```

## Deliberate limits

- No delete/archive endpoints yet. Removing organizational structure has
  cascade implications (tasks, grants, rooms) that deserve their own design.
- Task moves do not yet trigger `dispatch_task`, so moving an agent's task to
  `in_progress` does not start a runtime run. Wiring the two is the natural v19 step.
- Project `progress` is manual; it is not derived from task completion.
- No optimistic concurrency: two operators editing the same project last-write-wins.
