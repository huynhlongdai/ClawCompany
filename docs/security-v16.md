# v16 security model — collaboration and shared knowledge

Reconstructed from code (`api/v16.py`, `services/knowledge_mesh.py`,
`services/collaboration_rooms.py`, `services/delegation.py`). The original
file was lost from the working tree.

## 1. Two kinds of caller, two kinds of check

| Caller | Checked by |
| --- | --- |
| Human (JWT) | `require_role` — `guest < member < manager < admin < owner` |
| Agent / integration (API key) | `require_scope` — `company.collaboration:*`, `company.delegation:*`, `company.knowledge_mesh:*` |

`require_role` rejects API keys outright with `Human role required`. Creating
a team or a knowledge space, granting access, revoking a grant, and reading
access logs are therefore **human-only** — an agent cannot widen its own
reach by calling the API it was given.

## 2. Tenancy before data

Every v16 route resolves its object through a helper that filters by the
caller's organization first. A cross-tenant id fails before any read or write,
so object ids are not an enumeration oracle for other tenants' data.

## 3. Knowledge: deny by default

```txt
effective = max(
  space default_permission (ignored when classification = confidential),
  "contribute" if member belongs to the owning company,
  every unexpired grant matching member / department / company / team
)
```

- Absence of a grant means `none`. There is no implicit organization-wide read.
- `classification = confidential` suppresses the space default entirely: a
  confidential space is reachable **only** through an explicit grant.
- Grants expire by `expires_at` at evaluation time. An expired grant is
  ineffective immediately, with no cleanup job to fall behind.
- Every `search`, `contribute`, and **denied** attempt is appended to
  `knowledge_access_logs`. Denials are the interesting half: they are what
  shows an agent probing a space it cannot read.

## 4. Rooms: authority is data, not prose

An agent cannot talk its way past the rules, because the rules are checked
before the turn is stored:

- Speaking out of turn in `round_robin` is rejected.
- A `decision` turn requires `can_decide` on the speaker's seat.
- `max_turns` caps the transcript, which bounds cost and stops two agents
  looping at each other forever.
- The transcript is append-only with a per-room unique `sequence`; there is no
  edit or delete route.

## 5. Delegation: least authority between agents

Only the assignee may accept, reject, or deliver; only the delegator may close
or cancel. Each contract carries an objective, acceptance criteria,
`max_cost_usd`, and a deadline.

**Known gap:** `max_cost_usd` is recorded and returned but is not yet wired to
actual runner spend, so it documents intent rather than enforcing a budget.
This remains open (see the backlog in `docs/architecture-v22.md`).

## 6. What v16 does not do

- No delete/archive routes for teams, rooms, or spaces — cascade semantics
  were deferred rather than guessed.
- No optimistic concurrency: two managers editing one space, last write wins.
- Transcripts are not signed. v15 has workload signing keys; using them to
  make room history tamper-evident is still open.
