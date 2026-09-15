# v11 Completion Matrix

| Area | Status | Notes |
|---|---|---|
| Repository Registry | Implemented | Multi-tenant model + API + frontend console |
| Identity-bound API key | Implemented | APIKey may carry Member identity |
| Repository credential binding | Implemented | Permission + branch pattern + external secret ref |
| Local Git checkout/worktree | Implemented/tested | Real Git exercised by unit tests |
| Artifact bundle materialization | Implemented/tested | Latest version per logical path |
| Commit + patch artifact | Implemented/tested | Real Git commit and patch artifact |
| Test profiles | Implemented/tested | Executable allowlist + timeout; not a sandbox |
| Human/AI review | Implemented/tested | Review gate and decision provenance |
| Local merge/squash/rebase | Implemented | Merge path exercised; strategy support in service |
| Conflict detection/resolution | Implemented/tested | Resolution invalidates prior quality evidence |
| Rollback | Implemented/tested | Local `git revert` path exercised |
| GitHub push | Implemented, not live-tested | Requires identity credential + network/token |
| GitHub PR create/merge | Implemented, not live-tested | Provider REST adapter present |
| Generic Git MR provider | Not implemented | Needs provider-specific adapter |
| Celery delivery jobs | Implemented | Prepare and test tasks |
| Event webhook outbox | Implemented/tested | Retry/backoff/dead-letter/signature |
| Webhook SSRF guard | Implemented | Host allowlist + HTTPS non-local |
| Frontend repository/delivery/reviews | Implemented | Route surfaces + API client |
| Alembic v11 | Implemented | 0006 + 0007 explicit migrations |
| Full app pytest | Blocked on host dependency | Host lacks python-jose; requirement exists |
| Next.js production build | Not validated | Syntax parse only |
| Docker image build | Not validated | Dockerfile/compose updated |
| Live OpenClaw contract | Not validated | Remains deployment-version dependent |

“Implemented” means code exists in this snapshot and the stated validation applies; it does not mean production certification.
