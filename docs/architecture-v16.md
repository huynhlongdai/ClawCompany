# v16 — Agent Collaboration Fabric & Shared Knowledge Mesh

## Why

v1–v15 built the operational plane (runners, delivery, incidents, SRE, production trust). The
product premise — many agent companies working together, interacting, sharing one knowledge base
— had only two loose pieces: `agent_messages` (1:1 mail) and `organization_memories`. v16 adds the
organizational rules that make multi-agent work auditable instead of emergent.

## Data model (10 tables, migration `0012_v16_agent_collaboration_mesh`)

| Table | Purpose |
| --- | --- |
| `agent_teams` | Named team per organization (`team_key` unique), `cross_company` flag, coordination mode |
| `agent_team_members` | Seat with role (`lead`/`contributor`/`reviewer`/`observer`) and deterministic `turn_order` |
| `collaboration_rooms` | Working session for a team: turn mode, `max_turns`, status, objective |
| `room_participants` | Per-room seat with `can_decide` |
| `room_turns` | Append-only transcript, unique `sequence` per room, typed turns |
| `delegation_contracts` | Agent-to-agent work contract with state machine, deadline, cost ceiling |
| `shared_knowledge_spaces` | Knowledge container with owner company, classification, default permission |
| `knowledge_grants` | Explicit grant to company/department/team/member, optional `expires_at` |
| `shared_knowledge_entries` | Versioned entries (`version`, `supersedes_entry_id`) |
| `knowledge_access_logs` | Every search/contribute attempt, including denials |

## Rules enforced in the data layer, not in prompts

**Turn taking.** `round_robin` computes the next speaker deterministically, skipping observers.
Speaking out of turn is rejected. `decision` turns require `can_decide`. `max_turns` caps
agent-to-agent loops.

**Delegation state machine.**

```text
proposed ──accept──▶ accepted ──deliver──▶ delivered ──close(ok)──▶ completed
    │                    │                     │
    ├─reject──▶ rejected └─cancel──▶ cancelled └─close(rework)──▶ accepted
```

Only the assignee may accept/reject/deliver; only the delegator may close/cancel. Proposing and
delivering also emit an `agent_message` on `thread_key = delegation:{id}`, so the agent mailbox
stays a valid source of truth.

**Knowledge permissions (deny-by-default).**

```text
effective = max(
  space.default_permission   (ignored when classification = confidential),
  "contribute" if member belongs to the owning company,
  every unexpired grant matching member / department / company / team
)
```

Order: `none < read < contribute < admin`. Expiry is evaluated at read time, so no cleanup job is
required. Denied attempts are logged, not silently dropped.

## Surfaces

- API: 30 endpoints under `/api/v16`, scopes `company.collaboration:read|write`,
  `company.delegation:read|write`, `company.knowledge_mesh:read|write`.
- Events on `company_event_bus` from sources `collaboration_fabric` and `knowledge_mesh`:
  `agent.team.created`, `agent.team.member_added`, `collaboration.room.opened|joined|closed`,
  `collaboration.turn.<type>`, `delegation.proposed|accepted|rejected|delivered|completed|rework_requested|cancelled`,
  `knowledge.space.created`, `knowledge.grant.created`, `knowledge.entry.contributed`.
- UI: `/app/collaboration`, `/app/knowledge-mesh`.
- OpenClaw bridge: 13 tool contracts (70 total) so the agent core can open rooms, speak in turn,
  delegate work and query shared knowledge strictly within its permissions.

## Validation status

The build sandbox has no network, so runtime dependencies cannot be installed.

- ✅ `python3 -m compileall backend/app backend/tests backend/alembic/versions` — OK.
- ✅ Tool contract JSON validates and has no duplicate tool names.
- ⚠️ `backend/tests/test_v16_agent_collaboration_mesh.py` (16 tests) is written but **not executed**.
- ❌ Not run: `alembic upgrade head`, `pytest`, `uvicorn`, `npm run build`.

On a networked machine:

```bash
cd backend && pip install -r requirements.txt && alembic upgrade head && pytest -q
npm install && npm run build
```

## Deliberate limits

- Rooms are polled, not realtime; WebSocket delivery is v17+ work.
- Mesh search is lexical (`ilike`); the existing `hash384` embedding backend is not wired in yet.
- `max_cost_usd` on a delegation is recorded and checked against the contract, but not yet joined
  to actual runner spend.
- Transcripts are append-only at the application layer; they are not cryptographically signed.
