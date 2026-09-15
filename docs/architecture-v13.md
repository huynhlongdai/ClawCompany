# ClawCompany v13 Architecture — AI Engineering Organization

## Purpose

v13 turns the v12 development cloud into a governed engineering organization. The central design rule is that a coding model does not need Git, deployment or production credentials. ClawCompany owns identity, workspaces, artifacts, repository delivery, CI evidence, release policy and deployment state.

## End-to-end control flow

```text
Founder / Goal
   │
   ▼
Nina Engineering Initiative
   │
   ├── Workspace Gateway ── provider agent
   │       │
   │       └── snapshot → Artifact Registry → Repository Delivery
   │
   ▼
CICDPipelineGraph (DAG)
   │
   ├── sandbox
   ├── security review
   ├── build evidence / SBOM / provenance
   └── immutable release
   │
   ▼
Release Manager
   │
   ├── reject
   ├── hold / approval
   └── approve
          │
          ▼
Progressive Delivery
   ├── rolling
   ├── blue/green (filesystem reference provider)
   └── canary → router adapter required
          │
          ▼
Health Policy → deployment state → rollback when allowed
```

## 1. Workspace Gateway

`WorkspaceGatewaySession` is the provider-neutral API session. It references a v12 `DevWorkspace` rather than inventing a second filesystem abstraction. Every operation is recorded in `WorkspaceGatewayOperation`.

Security invariants:

- resolved paths must stay under the workspace root;
- `.git` cannot be accessed through the gateway;
- session status and expiry are checked;
- capabilities gate read, write and snapshot;
- API identity is tenant-bound and API-key member/agent binding is checked.

Snapshotting registers text files into the v10 Artifact Registry with the workspace logical path, allowing a downstream Commit Agent to materialize them into a repository worktree.

## 2. Execution fabric

`execution_fabric.py` describes provider capabilities for mock, Docker, Kubernetes and microVM. It is deliberately a control-plane abstraction. v13 does not ship a privileged microVM daemon.

The v12 sandbox runner continues to execute supported local/mock/Docker modes. `microvm` fails closed when no external adapter exists. This prevents a configuration label from being mistaken for real isolation.

## 3. CI/CD DAG

A `CICDPipelineGraph` contains `CICDNode` and `CICDEdge`. `validate_graph()` performs a topological sort and rejects cycles. A `CICDRun` resolves the repository ref to an immutable commit SHA before execution.

Node types:

- `noop`: bookkeeping/demo action;
- `gate`: deterministic allow/reject gate;
- `sandbox`: executes using v12 `SandboxRun`;
- `security`: deterministic source scan;
- `evidence`: creates build manifest/SBOM/provenance;
- `release`: creates a commit-pinned v12 `Release`.

Each node has a `CICDNodeRun`, so retry/audit can be extended without hiding step state inside one large job record.

## 4. Software supply-chain evidence

`generate_build_evidence()` reads the exact Git tree for a commit. It creates a source manifest with per-file SHA-256 and a whole-source digest. It then registers three evidence artifacts:

- `evidence/source-manifest.json`
- `evidence/sbom.spdx.json`
- `evidence/provenance.json`

The SBOM is SPDX-2.3-compatible JSON metadata. The provenance uses an in-toto Statement v1 envelope and the SLSA provenance v1 predicate URI. v13 does not sign these artifacts and makes no certification claim.

## 5. Security review

The deterministic scanner operates on the exact commit. `SecurityFinding` captures rule ID, severity, path, line and evidence. Required CI security nodes stop execution when a finding matches their configured block severities.

The built-in rule set is intentionally small. External SAST, dependency/CVE and secret-scanning adapters remain the correct production path.

## 6. Release governance

`ReleaseManagerRun` is a deterministic policy assessment over CI, security, approval and deployment strategy evidence. This service is the non-negotiable guardrail; an LLM may explain or recommend, but cannot override the persisted policy decision.

## 7. Progressive delivery

`DeploymentStrategyRun` records the strategy lifecycle.

- Rolling delegates to the v12 deployment provider, then evaluates health. When the policy enables rollback and a previous deployment exists, failure triggers `rollback_environment()`.
- Blue/green is implemented for the filesystem reference provider by extracting the candidate commit to an isolated version directory, checking health, then atomically changing the `current` symlink.
- Canary persists the requested traffic percentage and returns `waiting_router`. A real ingress/router adapter is required for weighted traffic; no traffic split is simulated.

HTTP health checks are constrained to the configured environment base hostname to reduce SSRF risk.

## 8. Nina Engineering Initiative

`EngineeringInitiative` binds business intent to repository, pipeline, optional executive goal and desired environment. The orchestrator composes existing services rather than bypassing them:

```text
CI run → release → security evidence → Release Manager → deployment gate → strategy → Release Manager
```

This makes Nina an engineering orchestrator while preserving Company governance.

## 9. Event model

v13 reuses the durable Company Event Bus from v10. CI, build evidence, health checks, deployment strategy, Release Manager and engineering initiative state transitions emit organization-scoped events. Those events can feed v10 triggers/webhook outbox and Founder Cockpit surfaces.

## 10. Multi-tenant boundary

Every v13 durable record contains `organization_id` directly or references a tenant-bound parent. API handlers verify the active principal organization before operating on repositories, workspaces, releases and environments. Agent/API-key actions require explicit scopes.

## 11. Important non-goals in v13

- no bundled Firecracker/Cloud Hypervisor privileged runner;
- no real weighted canary ingress adapter;
- no signed Sigstore/cosign attestations;
- no external CVE/SAST database;
- no claim that OpenClaw RPC names are universal across releases;
- no claim of production-complete CI/CD hosting.
