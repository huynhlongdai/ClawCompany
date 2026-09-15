# v29 — Cascade archive & write audit

Version `1.19.0`. No new tables, no migration. Head stays `0012_v16_agent_collaboration_mesh`.

v28 closed its own debts and wrote down three more (section 19.6 of the handover):

1. Restoring a project reopened every cancelled task at `todo`, because the archive event only carried an id list.
2. Archiving a company, department or member was still unimplemented — the cascade needed designing.
3. `board.write.guarded` and `board.write.conflict` were emitted on every protected write and **no screen read them**. An audit trail nobody reads is a log file with extra steps.

All three are closed here.

## 1. Per-task prior status on archive/restore

`board_truth.archive_project` now records `task_statuses: {task_id: status}` for each task it cancels, next to the existing `cancelled_task_ids`.

`board_restore` reads it back:

- `_task_statuses(payload)` keeps only digit keys whose value is a status in `OPEN_STATUSES`. Malformed or pre-v29 payloads yield `{}` rather than a guess.
- `restore_preview` returns `will_restore_tasks[*] = {task_id, title, restore_to, prior_status_known}` and `task_statuses_recorded`.
- `restore_project` restores each task to its own `restore_to` and returns `restored_tasks`.

A task archived while `blocked` comes back `blocked`, not `todo`. Where no record exists, the response says `prior_status_known: false` and falls back to `todo` instead of inventing history.

## 2. Cascade archive — `services/entity_archive.py`

Three kinds: `company`, `department`, `member`. Nothing is deleted, and no new status word is invented:

| Kind | Archived state | Source of the word |
| --- | --- | --- |
| Company | `status = archived` | `workspace_ops.COMPANY_STATUSES` |
| Member | `status = offboarded` | `workspace_ops.MEMBER_STATUSES` |
| Department | `access_level = confidential` | `workspace_ops.ACCESS_LEVELS` |

Departments have no status column. Adding one would mean the migration v27 and v28 both avoided, so a department archive locks its access level instead. That is a documented compromise, not an oversight — a v30 with a migration can do better.

**The cascade**

- Company → its departments (locked), its members (offboarded), its open projects (through `archive_project`, which cancels open tasks and records their statuses).
- Department → its members. Projects hang off the company, never a department, so a department archive never reaches the board.
- Member → the member row only. Agent rows are **never** touched: an agent's lifecycle belongs to the runtime, and flipping it from here would lie to OpenClaw about what we control. The preview lists them under `agents_left_registered`.

**The hazard, again.** A member can own a task attached to a live OpenClaw session. `cascade_preview` returns `live_runtime_sessions` and `blocked: true`; `archive_entity` refuses with 409 unless `force=true`, and a forced archive reports `left_running` rather than implying it stopped anything. Aborting is still `/api/v19/tasks/{id}/abort`.

**Reversibility.** Every archive records `previous.self`, `previous.members` and `previous.departments` in its event payload, so `restore_entity` returns each row to the state it actually had. Rows somebody already reinstated by hand are left alone — the same rule v28 applied to tasks. Projects cancelled by a company archive are reopened one at a time via `/api/v28/projects/{id}/restore`; reopening a whole board implicitly is a bigger decision than un-archiving a company.

## 3. Write audit — `services/write_audit.py`

Reads `CompanyEvent`, organization-scoped, newest first. Eleven write event types plus two runtime ones behind `include_runtime`:

- `write` — `board.write.guarded`
- `conflict` — `board.write.conflict`
- `archive` / `restore` — project, company, department, member
- `derived` — `project.progress.derived`
- `runtime` — `openclaw.stream.gap`, `openclaw.stream.reconciled` (they explain why a write looks strange; they are not writes)

Each row carries actor, entity, fields that moved, revision, and a one-line `summary` a human can read without opening the payload. Two honest limits: the feed does not reconstruct *previous field values*, because the guard event never recorded them, and it reports `truncated` instead of pretending to be a complete history.

## 4. Endpoints — `/api/v29`

- `GET /vocabulary` — kinds, status words, event types, categories, notes
- `GET|POST /companies/{id}/archive/preview|archive` — archive is **admin+**
- `GET|POST /companies/{id}/restore/preview|restore`
- `GET|POST /departments/{id}/...`, `GET|POST /members/{id}/...` — writes are manager+
- `GET /audit` — filters: `company_id`, `entity_type`, `entity_id`, `category` (repeatable), `include_runtime`, `since_hours`, `limit` (clamped to 200)
- `GET /audit/{entity_type}/{entity_id}` — the trail for one row

Scopes: `company.context:read` for reads, `company.workspace:write` for writes (same as v18/v27/v28).

## 5. Surfaces

- Bridge: 15 new tools, 141 total in `openclaw-company-bridge/tool-contracts.json`.
- Frontend: `apiV29` in `lib/api.ts`; `components/EntityArchivePanel.tsx` (preview → archive/force/restore, plus the audit table with a conflicts-only filter) wired into `WorkspaceOpsConsole`.
- Tests: `backend/tests/test_v29_cascade_archive.py`, 32 cases.

## 6. What is still not true

- **Nothing here has been executed.** The sandbox has no network, so FastAPI, SQLAlchemy and pytest cannot be installed. The tests are specifications; run `pytest -q` on a networked machine.
- Revisions are still derived from `updated_at`, so two writes inside the same clock tick can be indistinguishable. A monotonic revision column needs the migration this version again avoided.
- Un-archiving a member does not restore agent or session state; the agent row was never changed, but whatever it was running is gone.
- The audit feed is truncation-based, not paginated, and has no cursor.
- `Department` still has no unique-name constraint, and `update_project` still cannot clear `owner_member_id`.
