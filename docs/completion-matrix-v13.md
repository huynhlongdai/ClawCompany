# ClawCompany v13 Completion Matrix

`Complete` below means a concrete source implementation suitable for further hardening. It does not mean the feature is production-certified.

| Capability | Status | Notes |
|---|---|---|
| Provider-neutral Workspace Gateway | Complete | Read/write/snapshot, TTL, path isolation, `.git` block, operation audit |
| Provider identity binding | Complete | Member/Agent IDs on gateway sessions; tenant/scope checks in API |
| Execution-fabric abstraction | Complete | mock/docker/kubernetes/microvm capability contracts |
| Bundled production microVM runner | Not bundled | External privileged adapter required; runner fails closed |
| CI/CD DAG model | Complete | Nodes/edges/runs, cycle rejection, commit pinning |
| Sandbox CI node | Complete | Reuses v12 SandboxRun boundary |
| Security CI node | Complete baseline | Deterministic rules only; not full SAST/CVE scanning |
| Build evidence | Complete | Source manifest + SHA-256 + Artifact Registry |
| SBOM | Complete baseline | SPDX-2.3-compatible generated metadata |
| Build provenance | Complete baseline | in-toto Statement v1 / SLSA-style predicate metadata; unsigned |
| Immutable release node | Complete | Release pinned to exact Git commit |
| Preview route registry | Complete | Registry/resolution only; does not configure ingress |
| Filesystem rolling deploy | Complete | Reuses v12 deploy provider |
| Filesystem blue/green | Complete reference implementation | Preflight health then atomic symlink cutover |
| Canary traffic state | Complete control-plane | Real weighted router adapter not bundled; returns `waiting_router` |
| Health checks | Complete baseline | filesystem marker and same-host HTTP |
| Automatic rollback | Complete reference implementation | Rolling path can rollback after failed health when lineage exists |
| Release Manager | Complete deterministic baseline | approve/hold/reject based on persisted evidence |
| Nina engineering initiative | Complete | Composes CI, security, release, gate, strategy and decision services |
| Celery engineering tasks | Complete | CI run and initiative tasks |
| Event integration | Complete | v13 emits Company Events for major state transitions |
| v13 frontend surfaces | Complete baseline | Engineering, Workspace Gateway, CI/CD, Supply Chain, Release Manager |
| OpenClaw Company Bridge contracts | Complete | v13 engineering tool contracts/scopes added |
| Exact live OpenClaw RPC mapping | Deployment-specific | Must map to deployed OpenClaw version |
| Signed provenance / Sigstore | Not implemented | Recommended v14+ hardening |
| Real external SAST/CVE adapters | Not implemented | Adapter layer recommended |
| Full frontend production build validation | Not verified | Dependencies unavailable in artifact host |
