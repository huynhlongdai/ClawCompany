# v16 API — Agent Collaboration Fabric & Shared Knowledge Mesh

All routes are prefixed `/api/v16`. Reconstructed from `backend/app/api/v16.py`
(the original file was lost from the working tree; this is generated from the
routes that actually exist in code, not from memory).

Humans are checked by role, agents by scope: structural creation uses
`require_role("manager")`, everything else uses a scope.

## Agent teams

| Method | Path | Guard |
| --- | --- | --- |
| POST | `/teams` | role `manager` |
| GET | `/teams` | `company.collaboration:read` |
| GET | `/teams/{team_id}` | `company.collaboration:read` |
| POST | `/teams/{team_id}/members` | `company.collaboration:write` |
| DELETE | `/teams/{team_id}/members/{member_id}` | `company.collaboration:write` |

A team scoped to one company rejects members from another. `team_key` is
unique per organization. Coordination modes: `lead_routed`, `round_robin`,
`parallel`. Seat roles: `lead`, `contributor`, `reviewer`, `observer`.

## Collaboration rooms

| Method | Path | Guard |
| --- | --- | --- |
| POST | `/rooms` | `company.collaboration:write` |
| GET | `/rooms` (`?status=`) | `company.collaboration:read` |
| GET | `/rooms/{room_id}` | `company.collaboration:read` |
| POST | `/rooms/{room_id}/participants` | `company.collaboration:write` |
| POST | `/rooms/{room_id}/turns` | `company.collaboration:write` |
| POST | `/rooms/{room_id}/close` | `company.collaboration:write` |

Turn order is enforced in the data layer, not in a prompt: `round_robin`
computes the next speaker deterministically and skips observers, speaking out
of turn is rejected, a `decision` turn requires `can_decide` on the seat, and
`max_turns` stops infinite agent loops. Closing a room can publish its summary
straight into the knowledge mesh.

## Delegation contracts

| Method | Path | Guard |
| --- | --- | --- |
| POST | `/delegations` | `company.delegation:write` |
| GET | `/delegations` (`?status=&member_id=`) | `company.delegation:read` |
| POST | `/delegations/{id}/accept` | `company.delegation:write` |
| POST | `/delegations/{id}/reject` | `company.delegation:write` |
| POST | `/delegations/{id}/deliver` | `company.delegation:write` |
| POST | `/delegations/{id}/close` | `company.delegation:write` |
| GET | `/delegations/overdue` | `company.delegation:read` |

```txt
proposed ──accept─▶ accepted ──deliver─▶ delivered ──close(ok)──▶ completed
    │                 │                    │
    ├─reject─▶ rejected └─cancel─▶ cancelled └─close(rework)─▶ accepted
```

Only the assignee may accept/reject/deliver; only the delegator may
close/cancel. Propose and deliver also write an `agent_message` with
`thread_key = delegation:{id}`.

## Shared knowledge mesh

| Method | Path | Guard |
| --- | --- | --- |
| POST | `/knowledge-spaces` | role `manager` |
| GET | `/knowledge-spaces` | `company.knowledge_mesh:read` |
| POST | `/knowledge-spaces/{id}/grants` | role `manager` |
| GET | `/knowledge-spaces/{id}/grants` | `company.knowledge_mesh:read` |
| DELETE | `/knowledge-grants/{grant_id}` | role `manager` |
| GET | `/knowledge-spaces/{id}/permission?member_id=` | `company.knowledge_mesh:read` |
| POST | `/knowledge-spaces/{id}/entries` | `company.knowledge_mesh:write` |
| POST | `/knowledge-mesh/search` | `company.knowledge_mesh:read` |
| GET | `/knowledge-mesh/access-logs` (`?space_id=`) | role `manager` |

Effective permission is deny-by-default:

```txt
effective = max(
  space default_permission (ignored when classification = confidential),
  "contribute" if the member belongs to the owning company,
  every unexpired grant matching member / department / company / team
)
```

Order: `none < read < contribute < admin`. Grants carry `expires_at` and lose
effect on their own — no cleanup job. Entries are versioned (`version`,
`supersedes_entry_id`). Every `search` / `contribute` / `denied` attempt is
written to `knowledge_access_logs`.

## Summary

| Method | Path | Guard |
| --- | --- | --- |
| GET | `/collaboration/summary` | `company.collaboration:read` |

## Tenancy

Every lookup helper (`_team`, `_room`, `_contract`, `_space`) resolves the
object inside the caller's organization before any write, so a cross-tenant id
fails with 403/404 before touching data.
