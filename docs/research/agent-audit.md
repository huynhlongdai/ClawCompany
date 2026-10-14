# ClawCompany — AI agent ("digital human employee") capability audit

- Repo: `/workspace/projects/ad964bb9-1dd8-4a5d-af4e-aa97c66397f0/repo`, branch `ui-v2` (HEAD `b0de0fd`). Paths below are relative to the repo.
- Live gateway: VM container `clawcompany-openclaw-1`, image `ghcr.io/openclaw/openclaw:2026.9.8 (fc23bc8)`. I inspected it read-only with `openclaw agents list`, `skills list --agent nina`, `cron list`, `memory status`, `sandbox explain`, `mcp list`, `config schema`, and read `openclaw.json` with secrets redacted.
- Live DB: VM `clawcompany-db-1` (read-only `select`).
- Docs: https://docs.openclaw.ai/concepts/agent-workspace (fetched 2026-10-14).
- Read-only: I changed nothing in the code, config or VM.

Legend for **Wired?**:
- ✅ = real RPC to the gateway, verified on the VM or in `_reports`.
- 🟡 = code exists but is not active on the live gateway.
- ❌ = stored in the DB only.
- — = nothing exists.

---

## 0. How an agent seat is put together today

There are three sources of truth, merged by `services/seat_profile.py` and written by `services/agent_hr.py`:

1. **DB tables.**
   - `members` (member_type=agent, role, department, manager, status). Defined in `models/entities.py`.
   - `agents` (runtime_agent_id, model, lifecycle, success_rate, cost_30d, risk). Defined in `models/entities.py`.
   - `agent_file_snapshots` (`models/agent_hr.py`): ClawCompany's copy and hash of each bootstrap file.
   - `agent_provisioning_jobs` (`models/team.py`): its manifest holds the hire spec (personality, JD, notes, budget).
2. **Gateway config `agents.entries.<id>`.**
   - Changed through `agents.create/update/delete` and `config.patch`, via `services/openclaw_config.py` (ConfigRegistry: baseHash compare-and-set, replacePaths).
3. **Workspace files.**
   - Read and written with `agents.files.get/set` (expectedHash compare-and-set).
   - ClawCompany manages exactly 5 files: `ocp.AGENT_BOOTSTRAP_FILES` = IDENTITY, SOUL, AGENTS, USER, MEMORY (`runtime/openclaw_protocol.py:181`).

API surface (`api/agents.py`):

| Method | Path |
|---|---|
| GET | `/api/agents` |
| POST | `/api/agents` (legacy; creates the DB row, then `runtime.create_agent`) |
| GET | `/api/agents/roster` |
| GET | `/api/agents/hire/options` |
| POST | `/api/agents/hire` |
| PATCH | `/api/agents/{id}/hr` |
| GET | `/api/agents/{id}/drift` |
| POST | `/api/agents/{id}/resync` |
| POST | `/api/agents/{id}/lifecycle` |
| GET | `/api/agents/{id}/tools` |
| GET | `/api/agents/{id}/profile` |
| PUT | `/api/agents/{id}/files/{name}` |
| PATCH | `/api/agents/{id}/config` |

Related OpenClaw endpoints live in `api/v19.py` under `/api/v19/openclaw/*`: agents, seats, reconcile, bind, doctor, heartbeat-policy, heartbeat-skill.

UI:

| Route / component | What it shows |
|---|---|
| `app/app/team/page.tsx` → `components/TeamConsole.tsx` | Org chart; tabs AI / People / Departments / Training. The Training tab is a placeholder. |
| `app/app/agents/[id]/page.tsx` → `components/AgentProfile.tsx` | Three tabs (below). |
| ↳ `AgentDetail.tsx` | What the agent is doing now. |
| ↳ `AgentHR.tsx` | HR, lifecycle, drift, tool permissions. |
| ↳ `SeatProfile.tsx` | Six "OpenClaw config" sub-tabs. |
| `app/app/agents/page.tsx` → `WorkforceConsole` | Workforce list. |
| `app/app/agent-tools` | Tools page. |
| `app/app/memory` | Memory page. |
| `app/app/knowledge-mesh` | Knowledge mesh. |
| `app/app/autonomy` | Autonomy settings. |
| `app/app/routines` | Routines. |
| `app/app/collaboration` | Collaboration rooms. |
| `app/app/openclaw` | Gateway connection. |

**Live state (VM, 2026-10-14):**
- **Roster.** The gateway has `main` plus 9 seats: nina, sophia-cmo, mia-content, and six `shop-a407-*`. All 9 also exist in the DB.
- **Model.** Every seat runs `custom/gpt-4.1-mini`. Nina, Sophia and Mia have it pinned per agent. The six shop seats set no model of their own, so they inherit `agents.defaults.model.primary`.
- **Files written by ClawCompany.**
  - The only snapshots in `agent_file_snapshots` are 9 rows, all IDENTITY.md.
  - `workspace-nina` holds the ClawCompany IDENTITY.md, but **SOUL/AGENTS/USER are still OpenClaw's default English templates**.
  - There is no MEMORY.md and no `memory/` folder.
  - Mia's workspace still has `BOOTSTRAP.md` (the first-run ritual was never completed or removed).
  - So for seeded and template seats, the personality and job description never reached the gateway. Only seats hired through the M3 wizard get the five rendered files.
- **Per-agent config.** `openclaw.json` has no `tools`, `sandbox`, `skills`, `heartbeat`, `subagents` or `memory` block on any agent. `mcp.servers` is empty (`openclaw mcp list` → none), and there is no top-level `tools` or `memory` config.
- **Native cron jobs on the gateway:**
  - `heartbeat:main` every 30 minutes; it skips.
  - `skill-collection-review` every 7 days, one per agent.
  - `memory-core: Memory Dreaming Promotion` daily at 03:00.

---

## 1. Capability matrix

### 1.1 Identity / role / job description

| | |
|---|---|
| DB | `members.name/role/department_id/manager_id`. The hire spec (JD, manager notes, personality, emoji, budget) sits in the provisioning-job manifest (`agent_hr.hire_spec/_save_spec`), not in columns. |
| API | `POST /api/agents/hire` (4-step wizard data); `PATCH /{id}/hr` (writes DB + `agents.update`, regenerates IDENTITY/SOUL/AGENTS/USER when the gateway copy is unchanged); `PUT /{id}/files/IDENTITY.md`; `PATCH /{id}/config tab=profile` (name, identity.name/theme/emoji/avatar). |
| Render | `agent_hr.render_files()`: Vietnamese IDENTITY (name, vibe, emoji, title, reports-to), AGENTS (role, duties from the JD, intake/return rules, budget line), USER ("what the manager wants", 4,000-char cap respected). |
| UI | Hire wizard in `AgentHR.tsx` (Team › AI tab); SeatProfile tabs "Profile" and "Job". |
| Wired? | ✅ for wizard-hired seats: `tools/gate_m3.py` 27/27 on 9.8 per `_reports/m3-agents.md`. 🟡 for seeded and template seats: only IDENTITY reached the gateway. `provision_company` (`services/provisioning.py`) creates gateway agents but does not render or write files. |
| OpenClaw native | `IDENTITY.md` (name/vibe/emoji), `AGENTS.md` (operating instructions, plus a `## Tools` section, since TOOLS.md is **retired** in 9.x), `USER.md` (directive-based user model, 4k cap), `agents.entries.*.identity` and `description`, `agents set-identity`, and the `BOOTSTRAP.md`/`BOOT.md` rituals. |
| Gaps | (a) No structured JD/role schema (responsibilities, KPIs, escalation matrix); free text only. (b) No endpoint to render and push the 5 files for existing seats (see bug B3). (c) `agents.entries.*.description` is unused. (d) BOOTSTRAP.md is left behind on new workspaces; nothing deletes it or runs the ritual. (e) USER.md is used as "manager wishes", which is fine, but the directive format OpenClaw expects (`<!-- observed … status: active -->`, "Always/Never/Prefer") is not followed. |

### 1.2 Personality / tone / values

| | |
|---|---|
| DB | `personality` key in the hire spec; 5 fixed presets in `agent_hr.PERSONALITIES` (tan-tuy, sang-tao, ngan-gon, than-thien, phan-bien). |
| API/UI | Wizard step 4; `PATCH /hr personality`; SeatProfile "Personality" tab edits SOUL.md raw, with expectedHash and a 409 on conflict. |
| Wired? | ✅ for wizard seats; SOUL edits change the voice (`_reports/seat-soul-e2e.md`, 4/4 markers). ❌ for seeded seats (SOUL is the OpenClaw default). |
| OpenClaw native | `SOUL.md` (persona, tone, boundaries, loaded every session), the SOUL personality guide, `agents.entries.*.tts` personas, `humanDelay`, `typingMode`. |
| Gaps | Presets are hard-coded in Python with no org-level custom values, company constitution or brand voice. No company-wide values file injected into every seat (it could be a shared skill or an `AGENTS.md` include). |

### 1.3 Memory

| Layer | ClawCompany | OpenClaw native (9.8) | Wired? | Gap |
|---|---|---|---|---|
| Personal long-term | MEMORY.md is in `SEAT_FILES`; the hire renders a stub; `AGENT_OWNED_FILES=("MEMORY.md",)`, so edits by the agent don't count as drift. No UI editor (FILE_TABS maps it to a "memory" tab the UI never renders). | `MEMORY.md` (curated, main session only), automatic memory flush on compaction, **Dreaming** (light/REM/deep promotion, cron 03:00), `openclaw memory promote`, DREAMS.md, standing intents, Honcho/LanceDB/wiki plugins | 🟡 the file is written only at hire; the live seats have none | No review or approval of agent memory, no UI view, and no use of dreaming or promote outputs. |
| Short-term / daily (episodic) | — | `memory/YYYY-MM-DD.md` daily notes, session transcripts, `sessions_search` / `sessions_history` tools, `memory search` over memory and sessions | ❌ (unused) | No daily-note view; the gateway side is unconfigured. |
| Working / scratch | Per-task session key `agent:<id>:company-task-<taskId>` (agent_dispatch); the 7-block **context pack** in `services/work_context.py` (6,000-char budget, pins task and rules) | Session context, compaction, `contextPruning`, `updatePlan` tool, workspace files as scratch | ✅ (context pack sent with `chat.send`; `_reports/work-memory-gap.md`: 358 → 1,310 chars) | — |
| Work memory (per task, across runs) | `task_journal_entries` (`models/v37.py`), `services/task_journal.py`; API `GET/POST /api/tasks/{id}/journal`; fed into block 4 of the context pack | No equivalent (memory is per agent or per session) | ✅ in the prompt; ❌ as a gateway memory object | A deliberate boundary and a good design. |
| Episodic, past runs | `task_runs`, `runtime_events`, `room_conductor_runs`, `company_events` | transcripts, `openclaw audit`, `transcripts` CLI | 🟡 (runs are recorded; agents can't query their own history through MCP) | No "what did I do last week" tool. |
| Shared org / team knowledge | **Three overlapping stores:** `knowledge_documents` + `knowledge_chunks` / `knowledge_vectors` (pgvector or hash384; `api/knowledge.py`, `/api/v7/knowledge/vector-search`, `/api/v33/knowledge/search`); `shared_knowledge_spaces/entries/grants` (`/api/v16/knowledge-*`, department ACL); `organization_memory` (`/api/v9/memory`). Agent access goes through the MCP tools `company_knowledge_search/get`, `company_sop_get`, `company_decision_log`. | `memory.search` is per agent; cross-agent memory search was **removed upstream in 2026.8.1** (noted in `work_context.py`); `skills.library` (team libraries); `memory-wiki` plugin | ❌ the MCP server isn't registered on the gateway, so agents can't call these tools (see 1.5) | Merge into one store (planned for M5); register MCP; decide whether shared knowledge becomes a team skill library or MCP. |

Live memory index: nina has 2/2 files and 12 chunks, but the store is *dirty*, the provider is `openai text-embedding-3-small` while chat runs on a `custom` provider, and vector search on `main` is "paused / metadata_missing". Memory search is effectively unconfigured.

### 1.4 Skills

| | |
|---|---|
| DB | `skills` table (`models/extended.py:195`): name, version (string), scope, description, status. **Metadata only: no content, no history, no link to an agent.** API `GET/POST /api/v?/skills` (`api/extended.py:170`). Seed gives Maya/Leo `skills: [...]` labels only. |
| Gateway push | Only the hard-coded `backend/app/skills/clawcompany-heartbeat/SKILL.md`, via `skills.upload.begin/chunk/commit` + `skills.install` (`services/heartbeat_policy.py`, `POST /api/v19/openclaw/heartbeat-skill`). Requires `skills.install.allowUploadedArchives`. |
| Seat config | `PATCH /{id}/config tab=permission` can write `skills` (the array allowlist at `agents.entries.<id>.skills`). |
| Wired? | 🟡 **On the live VM, `clawcompany-heartbeat` is NOT installed for nina** (`skills list --agent nina` → absent; 15/51 ready, all bundled or extra). No per-seat skill allowlist is set. |
| OpenClaw native | Very rich: bundled/managed/workspace `skills/` precedence; ClawHub search/install/verify/update; `skills library` (personal and team libraries, attach/detach per turn); **Skill Workshop** (`propose-create/update → evaluate → apply/reject/quarantine`), self-learning; **curator / collection review** (weekly cron per agent, already scheduled); `skills.limits.maxSkillsPromptChars`, `agents.entries.*.skillsLimits`. |
| Gaps | No Skill Studio (content, versions, diff, rollback), no per-agent install/uninstall UI, no eval harness. The `skills` table version is a free string. Nothing surfaces Workshop proposals or collection-review results to managers. Best path: make ClawCompany the approval UI over Workshop and library instead of re-implementing skills. |

### 1.5 Tools / hands (MCP, browser, code, integrations, permissions, budgets)

| | |
|---|---|
| Company tools | MCP server `POST /api/mcp` (`api/mcp.py`, `services/company_mcp.py`) with **25 `company_*` tools**: context, org, calendar, tasks list/get/status/comment/assign/checkout, plan_submit, project, knowledge, sop, decision_log, message_send, handoff_create, artifact create/get, approval_request, policy_check, budget_check, metric_read, report_submit, event_emit. Auth is a per-seat API key; the scopes filter `tools/list`. |
| Permissions | `tool_permissions` table (`models/tool_access.py`), three levels `allowed / ask / off`, resolved member > tier (lead/executor) > default (`services/tool_permissions.py`). `ask` creates an Approval with a 24h grant. API: `/api/mcp/permissions` GET/PUT, `GET /api/agents/{id}/tools`. UI: the tool-permission block in AgentHR and `/app/agent-tools`. |
| Gateway tool policy | SeatProfile "Permission" tab can write `tools.profile`, `tools.allow/deny`, `tools.elevated.enabled`, `sandbox.mode/scope/workspaceAccess/docker.network`, `skills` via `config.patch`. |
| Wired? | ❌/🟡. **`mcp.servers` is empty on the live gateway**, so no agent can call the `company_*` tools today. The handoff note claims Nina reads company data; on the VM she cannot. Layer 2 (API-side `decide`) is enforced when the MCP endpoint is called (`_reports/d15-d16-mcp-tool-permissions.md`), but was only tested with a direct MCP client. No per-agent tools or sandbox blocks are set. `sandbox explain --agent nina` shows mode off, runtime direct, default allow `exec, process, read, write, edit, apply_patch, sessions_*, subagents`, default deny browser and channels; elevated enabled but not allowed by config. So seats run host `exec` unsandboxed inside the container. |
| Budgets | `budget_envelopes` (member/department/company scope, monthly, warn 80%) are created at hire; `services/budget_scope.py` settles runs against `sessions.usage`; `wakeup.budget_block` refuses runs over budget. ✅ verified in the M4b report. |
| OpenClaw native | Tool profiles, allow/alsoAllow/deny, per-provider and per-sender rules, `exec` approvals and allowlist (`approvals allowlist`, grants), elevated mode, sandbox (docker/podman/ssh/openshell, per-agent scope), browser (managed Chrome and profiles), Code Mode, MCP servers with include/exclude per server (`mcp tools`), Tool Search (hides MCP tools behind `tool_search`), loop detection, `tools.effective` / `tools.catalog`, GitHub identity. |
| Gaps | (1) **Register the ClawCompany MCP server on the gateway** (`mcp.servers.clawcompany` with a per-seat key and `toolFilter include company_*`); without it most of the design is inert. (2) Sync ClawCompany `off` tools to gateway `tools.deny` so layer 1 matches layer 2. (3) Sandbox defaults are off; nothing sets `sandbox.mode=all` for executor seats. (4) No browser or integration provisioning per seat. (5) `tools.effective` needs a sessionKey, so effective tools aren't displayed. |

### 1.6 Reasoning / thinking (model, thinking level, planning)

| | |
|---|---|
| DB | `agents.model` (string). |
| API/UI | Wizard model picker (from `models.list`); `PATCH /hr model` → `agents.update`; SeatProfile "Capability" tab keys `model, utilityModel, thinkingDefault, fastModeDefault, timeoutSeconds, compaction.enabled, compaction.notifyUser, modelPolicy.allow` (`seat_profile.CONFIG_TABS`). UI fields: model, thinkingDefault (off…max), timeoutSeconds, compaction.notifyUser. |
| Wired? | ✅ model and thinkingDefault (valid per-agent keys). ❌ **`timeoutSeconds`, `compaction.*` (Capability tab), and `maxConcurrent`, `subagents.maxConcurrent`, `subagents.maxChildrenPerAgent` (Budget tab) are NOT valid keys under `agents.entries.<id>` in 9.8.** The entry schema has `additionalProperties:false`; those keys exist only under `agents.defaults` / `agents.defaults.subagents`. The UI exposes three of them (timeoutSeconds, compaction.notifyUser, maxConcurrent), so saving those fields should fail validation. (Inferred from the live `config schema`; I did not attempt a write.) |
| Planning | Nina planner (`services/nina_planner.py`, `strategy.py`, `/api/v8/nina/plans`, approval-gated strategy plans D3.3); `company_plan_submit` tool. |
| OpenClaw native | Per agent: `model {primary, fallbacks}`, `utilityModel`, `decisionModel`, `thinkingDefault`, `reasoningDefault`, `fastModeDefault`, `modelPolicy`, `params`, `contextLimits`, `subagents.model/thinking`, `heartbeat.model`; per session: `/think`, Goal and Steer tools, `updatePlan`. |
| Gaps | Fix the invalid tab keys and add `reasoningDefault`, fallbacks, `decisionModel`, `subagents.model`. No model-tier policy by role or cost. |

### 1.7 Learning

| Channel | ClawCompany | OpenClaw native | Status |
|---|---|---|---|
| From docs, courses, books | Upload to `knowledge_documents` (+ indexing job `/api/jobs/knowledge/{id}/index`) | Workspace files and memory indexing, `skills library import`, memory-wiki plugin | ❌ not reachable by agents (no MCP registration); no curriculum concept |
| From experience / reflection | Task journal entries with outcome; `agent_daily_stats` | Memory flush and Dreaming promotion to MEMORY.md, `memory promote`, `session-backfill`, Skill Workshop proposals, self-learning, weekly skill collection review (already scheduled per agent) | 🟡 native machinery runs, but the memory index is dirty or paused and nothing is surfaced |
| From human feedback | Review stages in `execution_policy` (review/approval participants), inbox approvals, `company_task_comment` | USER.md directives, standing intents | 🟡 feedback is stored but never distilled into agent memory or skills |
| Lessons → approval → MEMORY.md | **Not implemented.** `grep lesson` finds only inbox/handoff stubs ("room for M5 lessons", `_reports/m4b-inbox.md`). Planned in `docs/plan-v2-modules.md` M5. | Workshop has propose → evaluate → apply → reject; memory promote has a candidate scoring explainer | ❌ |
| Gap | Build the lesson pipeline on top of native primitives: lesson candidate (from the journal, review rejections, or `memory promote` candidates) → inbox approval → `agents.files.set MEMORY.md` with expectedHash, or Workshop apply for procedural lessons. | | |

### 1.8 Autonomy levels, approvals, guardrails

| | |
|---|---|
| DB/services | `autonomy_policies` (`models/v36.py`, `services/autonomy.py`: mode supervised, `max_auto_risk`); `approvals` with expiry and escalation (D3.5); `execution_policy` stages; `policy` / `permission_policies`; `company_policy_check` and `company_approval_request` tools; the tool `ask` level; BLOCKED_LIFECYCLES gate dispatch. |
| Gateway | Exec approvals bridged: `exec.approval.list/resolve` and events `exec.approval.requested/resolved` (`services/approval_bridge.py`, `runtime/openclaw_native.respond_approval`); `/api/v20/approvals/openclaw`; inbox one-tap approve (`components/QuickApprove.tsx`, `/app/inbox`). ✅ `_reports/approval-e2e.md`. |
| Rules in prompt | SOUL "general principles" (ask before spending or sending outside), work_context block 6 (rules, never cut). |
| OpenClaw native | Permission modes per session, exec approvals and allowlists, standing grants, policy-as-code (`openclaw policy`), tool-call policy hooks, sandbox vs tool policy vs elevated, prompt-injection guidance, `security audit`. |
| Gaps | Autonomy is org/company-wide, not per seat or level (e.g. L0 suggest … L3 act). It isn't mapped to gateway permission modes or exec policy, so it is enforced only in ClawCompany dispatch and the MCP layer. Gateway exec on seats is unsandboxed. |

### 1.9 Independent work (routines / heartbeat / cron)

| | |
|---|---|
| ClawCompany | `routines` + `routine_triggers` + `routine_runs` (`models/routines.py`, `services/routines.py`, `/api/routines`, UI `/app/routines`); **wakeup queue** (`services/wakeup.py`: reasons assigned, mention, handoff, approved, routed; active hours read from the gateway `heartbeat.activeHours`; budget block; coalescing) → `agent_dispatch.run_agent` via `chat.send`. Celery beat ticks. Recurring-ops duplicates exist (plan-v2 §2). |
| Heartbeat policy | `POST /api/v19/openclaw/heartbeat-policy`: keeps heartbeat on one "keeper" seat and sets `every:"0m"` on the others (dry run by default). The heartbeat skill teaches the wake routine. |
| Wired? | ✅ wakeup → `chat.send` (`_reports/wakeups-e2e.md`, operating-loop-e2e). 🟡 heartbeat: live `agents.defaults.heartbeat.agentId=main`; the policy has not been applied; the skill is not installed. |
| OpenClaw native | Heartbeat per agent (every, activeHours, isolatedSession, lightContext, model, target), automations/cron (`cron` CLI, payloads, delivery, webhooks, Gmail/IMAP triggers), standing orders, hooks (boot-md etc.). |
| Gaps | Routines duplicate OpenClaw cron. That is acceptable (ClawCompany owns the business schedule), but there is no mapping or visibility of native cron jobs (Dreaming, skill review) per seat. |

### 1.10 Teamwork (delegation, cross-review, handoff, chat between agents)

| Mechanism | Where | Wired? |
|---|---|---|
| Handoff → dispatch | `POST /api/tasks/{id}/handoff`, `services/handoff_dispatch.py` (journal entry + reassign + wake recipient) | ✅ `_reports/handoff-dispatch-e2e.md` |
| Conducted meeting rooms | `/api/v16/rooms*`, `services/room_conductor.py` (chair, turn caps, cost cap, stop reason), `room_conductor_runs` | ✅ `_reports/room-conductor-e2e.md` (2 real agents, 3 turns) |
| Cross-review | `execution_policy` review stage → `run_agent_review` (agent reviewer) | ✅ per `_reports/execution-policy-e2e.md` |
| Department routing | `services/routing.py` wakes the department head with reason `routed` | ✅ D3.1 |
| Delegation contracts | `/api/v16/delegations*`, `services/delegation.py`, `/api/v9/delegations`, `delegation_spend` | ❌ DB-only state machine |
| Agent messages | `agent_messages`, `services/agent_messaging.py`, `company_message_send` | ❌ DB-only (and the MCP tool isn't reachable) |
| Agent teams | `agent_teams` / `agent_team_members` (v16), `team_templates.py` | ❌ DB-only |
| OpenClaw native | `sessions_spawn` / sub-agents (allowAgents, delegationMode, maxSpawnDepth, announce), `sessions_send` / agent-send, `tools.agentToAgent`, swarm, parallel specialist lanes, `agents team create` (coordinator + specialists), A2A channel | — not configured. No `subagents.allowAgents` or `tools.agentToAgent` set for any seat. |

Gap: decide which collaboration is orchestrated by ClawCompany (auditable, budgeted: rooms, handoffs, review) and which is delegated natively (`sessions_spawn` for sub-tasks). If native delegation is enabled, child-run cost and audit must flow back (`sessions.usage` per child).

### 1.11 Performance / scorecard / cost

| | |
|---|---|
| DB | `agents.success_rate`, `agents.cost_30d` (**static seed values**, never recomputed); `agent_daily_stats` (derived from usage_events and company_events: runs, completed, failed, cost, success rate; `/api/v36/agent-stats`, `/derive`); `task_runs.cost_usd`; `budget_ledger_entries`; `usage_events`; task journal success rate (`task_journal.py:189`). |
| Cost source | `budget_scope.settle_run` reconciles against gateway `sessions.usage` ✅ (`_reports/cost-reconciliation.md`); `/app/costs`. |
| Scorecard | **None.** No first-pass review rate, revision count, cost per task, or quality score per seat (planned for M5). `artifact_evaluations` (v10) exist but aren't tied to agents. |
| OpenClaw native | `usage.cost`, `sessions.usage`, OpenTelemetry/Prometheus metrics, trajectory bundles, a personal-agent benchmark pack. |
| Gap | Replace the static columns with derived values; add a scorecard and an eval-suite runner that uses fixed inputs plus a rubric on a dedicated session. |

### 1.12 Lifecycle (hire, onboard, train, evaluate, promote, retire)

| Stage | Implementation | Wired? |
|---|---|---|
| Hire | `POST /api/agents/hire` (seat + `agents.create` + `agents.update` name/emoji + 5 files + member budget + tool overrides); `provision_company` for templates; legacy `POST /api/agents`, `/api/v8/workforce/hire` | ✅ wizard; 🟡 templates (no files) |
| Onboard | `members.status='onboarding'` is accepted by MCP auth; the 4-step org onboarding is for the company, not the agent | — no agent onboarding (BOOTSTRAP ritual, first task, knowledge grants) |
| Train | Training tab placeholder in `TeamConsole.tsx:101` | — |
| Evaluate | daily stats only | — |
| Promote | Can change role, department or manager via `PATCH /hr`; tier (lead/executor) derives from org position and changes tool defaults | partial; no level/promotion concept, no autonomy change on promotion |
| Pause / resume | `POST /{id}/lifecycle` (abort active sessions, tasks → todo; resume re-checks the roster) | ✅ |
| Retire | Snapshot the 5 files → abort and `sessions.delete` side sessions → `agents.delete{deleteFiles}`; reassign tasks, drop department head, re-parent reports, revoke API keys, close the budget | ✅ gate_m3. Daily `memory/` notes and transcripts are not archived (only the 5 files). |
| Drift / resync | `GET /drift`, `POST /resync` push/pull | ✅ with bug B1 |

---

## 2. Known bugs and defects found

| # | Bug | Evidence | Fix |
|---|---|---|---|
| B1 | **Resync push sends display model names to the gateway.** `agent_hr.resync` push → `upd["model"] = agent.model` with no validation. Seed writes `"GPT-4.1"` / `"Gemini 1.5"` (`backend/seed.py:63-65`), so drift shows a mismatch, and "Push" sends `agents.update {model:"GPT-4.1"}`. `_agents_update` and `update_hr` have the same gap. Only `NativeOpenClawRuntime.create_agent` filters with `"/" in model`. | `services/agent_hr.py` resync (~L720-735), seed. The live DB now shows `custom/gpt-4.1-mini` (fixed by hand). | Validate against `models.list` (or require `provider/model`) in `_agents_update`. Make the seed write `""` or real ids. Default resync for the model field to pull. |
| B2 | **`/api/v36/nina/ask` returns `answered:true` on errors.** `ask_nina` takes the first new assistant message with any text. A provider or run error that OpenClaw writes as an assistant message (stopReason error, an "Agent failed…" notice) counts as an answer; only `NO_REPLY` is excluded. Also: (a) `before = len(history)` with `limit=50`, so once a session has ≥50 messages, `fresh` is always empty and the call times out; (b) it picks *any* usable seat (`usable[0]`, active first), not specifically Nina. | `services/v36_insights.py:415-535` | Check `stopReason` / `errorMessage` / `isError` on the message (or use `agent.wait` with the run id); compare by message id or timestamp, not count; select by role or runtime id `nina`. |
| B3 | **No endpoint to create gateway agents or push files for seeded seats.** Seats from `seed.py` or `provision_company` either have no gateway agent (`resync` → 409 "Gateway không có agent này", `lifecycle resume` → `runtime_missing`) or have one with OpenClaw default files. `create_agent` runs only inside `POST /api/agents` (which inserts a new row) and `hire`. `/openclaw/bind` only links an existing id. On the VM the 9 agents exist, but only IDENTITY was ever written. | `api/agents.py`, `api/v19.py`, `services/agent_hr.py` (`resync` requires `roster_match`) | Add `POST /api/agents/{id}/provision`: `runtime.create_agent` if missing → `render_files` from the spec, or defaults from member/role → write the 5 files → snapshot. Expose it as "Create on gateway" in drift. |
| B4 | **Invalid per-agent config keys in SeatProfile.** `CONFIG_TABS` capability: `timeoutSeconds`, `compaction.enabled`, `compaction.notifyUser`; budget: `maxConcurrent`, `subagents.maxConcurrent`, `subagents.maxChildrenPerAgent`. None exist under `agents.entries.<id>` in the 9.8 schema (additionalProperties:false; they are `agents.defaults.*` only), so a `config.patch` would fail validation. The UI exposes three of them. | `services/seat_profile.py:59-75`, `components/SeatProfile.tsx:49-76`, live `openclaw config schema` | Remove them, or route them to defaults. Add valid per-agent keys: `reasoningDefault`, `subagents.allowAgents/model/thinking`, `heartbeat.model/lightContext/isolatedSession`, `memory.search`, `skillsLimits`, `tools.alsoAllow`. Verify with `config.schema.lookup` on startup. |
| B5 | **ClawCompany MCP is not registered on the gateway.** `mcp.servers` is empty, so the 25 `company_*` tools, the knowledge tools and the heartbeat skill's workflow are unusable by real agents. No code or setup script writes `mcp.servers`. | live `openclaw mcp list`; `grep mcp.servers` finds only a comment in `api/mcp.py` | Provisioning step: per seat, `mcp.servers.clawcompany-<seat>` (HTTP transport + seat API key as a SecretRef + `tools include company_*`), or one server plus a per-agent header. |
| B6 | **Heartbeat skill not installed / policy not applied on the live VM.** `skills list --agent nina` has no `clawcompany-heartbeat`; heartbeat is still `main` every 30 minutes (skipped). | live CLI | Run the doctor and install it as part of provisioning; check `allowUploadedArchives`. |
| B7 | **Seat files are left in an inconsistent state.** OpenClaw default English SOUL/AGENTS/USER sit beside a Vietnamese IDENTITY; `BOOTSTRAP.md` is still present (Mia); no MEMORY.md. Drift reports these as `untracked`, not drift, so the UI looks "in sync". | live workspaces, `agent_file_snapshots` = IDENTITY only | Count `untracked` on managed files as drift, and offer "render from profile". |
| B8 | **Static performance columns.** `agents.success_rate` / `cost_30d` come from seed and are shown in the profile (`seat_profile.py:267`) but never derived. | | Derive from `agent_daily_stats`. |
| B9 | **Memory search is effectively unconfigured.** The embedding provider is `openai` while chat goes through `custom`; the main index has metadata missing and vector search paused; nina's index is dirty. | live `memory status` | Configure `memory.search` provider/model to match the available credentials, then reindex. |

---

## 3. Native OpenClaw 2026.9.8 capabilities relevant to a "digital employee" (verified on the VM)

- **Per-agent entry keys:** `agentDir, bootstrapMaxChars, bootstrapTotalMaxChars, contextInjection, contextLimits, cwd, decisionModel, default, description, embeddedAgent, experimental, fastModeDefault, groupChat, heartbeat{every, activeHours, isolatedSession, lightContext, model, prompt, session, target, timeoutSeconds…}, humanDelay, identity{name, theme, emoji, avatar}, memory{search}, model (string or {primary, fallbacks}), modelPolicy, models, name, params, reasoningDefault, runtime, sandbox{backend, browser, docker, mode, prune, scope, workspaceAccess…}, skills[], skillsLimits, subagents{allowAgents, delegationMode, model, requireAgentId, thinking}, thinkingDefault, toolProgressDetail, tools{allow, alsoAllow, deny, profile, elevated, exec, fs, github, loopDetection, sandbox, swarm, toolsBySender, …}, tts, typingMode, utilityModel, verboseDefault, workspace`.
- **Workspace files** (docs): AGENTS.md (with a Tools section), SOUL.md, USER.md (directive model, 4k), IDENTITY.md, BOOT.md, BOOTSTRAP.md, `memory/YYYY-MM-DD.md`, MEMORY.md, `skills/`. **TOOLS.md and HEARTBEAT.md are retired**; ClawCompany correctly does not manage them.
- **Skills:** `install / search / verify / update` (ClawHub), `library` (personal/team), `workshop` (proposal lifecycle with evaluate), `curator` + weekly collection review (already scheduled per agent on the VM).
- **Memory:** search, index, promote, promote-explain, session-backfill, REM/dreaming, forget, reset; Dreaming cron daily.
- **CLI groups:** `agents add / bind / delete / set-identity / team create`; `sandbox explain / list / recreate`; `approvals allowlist / grants / pending / resolve`; `mcp add / set / tools / probe`; `hooks`; `cron`; `users`; `policy`; `audit`; `transcripts`.

## 4. Recommended order of work (smallest steps that unlock the most)

1. Fix B3 + B7: add a provision/render endpoint for existing seats.
2. Fix B5: register MCP per seat.
3. Fix B6: install the heartbeat skill and apply the keeper policy.
4. Fix B1, B2 and B4 (correctness).
5. Seat security defaults: sandbox `all` for executors, gateway `tools.deny` synced from `off`.
6. M5 on native primitives: lessons → inbox → MEMORY.md; Workshop proposals → inbox; a skill library as Skill Studio storage with versions in the DB; eval runs on isolated sessions; a scorecard from `agent_daily_stats` and review outcomes.
7. Merge the three knowledge stores into one, exposed through MCP.
