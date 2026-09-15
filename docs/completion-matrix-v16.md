# v16 completion matrix

Reconstructed from the code on disk. "Verified" here means verified by
reading or compiling the code — **the v16 test suite has never been
executed**, because the build sandbox has no network and cannot install
FastAPI/SQLAlchemy/pytest.

| Area | Built | Verified how | Gap |
| --- | --- | --- | --- |
| 10 tables (`agent_teams`, `agent_team_members`, `collaboration_rooms`, `room_participants`, `room_turns`, `delegation_contracts`, `shared_knowledge_spaces`, `knowledge_grants`, `shared_knowledge_entries`, `knowledge_access_logs`) | yes | compiled; no `__tablename__` collision with v1–v15 | not applied to a live DB |
| Migration `0012_v16_agent_collaboration_mesh` | yes | compiled | `alembic upgrade head` never run |
| 30 endpoints `/api/v16` | yes | route inventory in `docs/v16-api.md` | never called against a running server |
| 4 services (teams, rooms, delegation, knowledge mesh) | yes | compiled | logic unexercised |
| Round-robin turn order | yes | code read | test not run |
| `can_decide` on decision turns | yes | code read | test not run |
| `max_turns` loop cap | yes | code read | test not run |
| Delegation state machine + rework | yes | code read | test not run |
| Deny-by-default knowledge permission | yes | code read | test not run |
| Grant expiry at evaluation time | yes | code read | test not run |
| Entry versioning (`supersedes_entry_id`) | yes | code read | test not run |
| Access logs incl. denials | yes | code read | test not run |
| 13 openclaw bridge tools | yes | JSON validated, names unique | not invoked by a real agent |
| `/app/collaboration`, `/app/knowledge-mesh` | yes (rebuilt in v17) | file present, imports match `lib/api.ts` | `npm run build` never run |
| 16 tests in `test_v16_agent_collaboration_mesh.py` | written | — | **not executed** |

## Honest status

v16 is *code-complete and unproven*. Every rule described in
`docs/architecture-v16.md` exists in code, and nothing about it has been
observed running. Treat the first `pytest -q` on a networked machine as
discovery, not confirmation.

## Lost and rebuilt

During v16 packaging, four documents were lost from the working tree:
`docs/v16-api.md`, `docs/security-v16.md`, `docs/completion-matrix-v16.md`,
`docs/validation-v16.md`. They were regenerated in v22 from the code that
exists, so they describe the routes and rules actually on disk. Anything the
originals contained that is not derivable from code is gone.
