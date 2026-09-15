# v12 completion matrix

| Capability | v12 status | Notes |
|---|---|---|
| Provider-neutral dev workspace | Implemented | Empty workspace or detached local Git worktree |
| Workspace TTL cleanup | Implemented | Celery periodic cleanup |
| Sandbox policy model | Implemented | CPU/RAM/PID/network/rootfs/command allowlist |
| Mock sandbox runner | Implemented + tested | Deterministic local development path |
| Docker sandbox adapter | Implemented, disabled by default | Requires external hardened execution setup to enable safely |
| Kubernetes/microVM sandbox | Adapter point | Not implemented |
| Secret reference registry | Implemented | Metadata only |
| Env secret provider | Implemented + tested | Development/local provider |
| Vault/cloud secret providers | Adapter point | Not live |
| Identity-bound secret grants | Implemented + tested | Member/agent/profile/environment + expiry |
| Handoff → Delivery automation | Implemented + tested | Accepted artifact handoff can create v11 DeliveryRun |
| Release registry | Implemented + tested | Immutable Git commit SHA |
| Preview environment registry | Implemented | Filesystem reference provider |
| Deployment environment policy | Implemented | preview/staging/production + approval requirement |
| Production approval gate | Implemented + tested | Uses existing Approval model |
| Filesystem deployment | Implemented + tested | Git archive → versioned directory → atomic current symlink |
| Deployment rollback | Implemented + tested | Previous deployment lineage |
| Cloud/Kubernetes deploy providers | Adapter point | Not live |
| Celery sandbox/deploy jobs | Implemented | Async endpoints supported |
| Next.js Dev Cloud UI | Implemented | Dev Cloud, Workspaces, Sandboxes, Releases, Deployments, Secrets |
| OpenClaw bridge v12 contracts | Implemented | Workspace/sandbox/release/deploy tools |
| Explicit Alembic migration | Implemented | `0008_v12_secure_dev_cloud.py` |
