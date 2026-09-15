# ClawCompany v12 — Secure AI Development Cloud

v12 closes the loop between multi-model agent work and governed software delivery. The core rule is that a coding agent does **not** need repository, CI or production credentials. It receives a company identity, a scoped workspace and only the execution grants required for the current job.

## End-to-end path

```text
Founder / Nina
      │
      ▼
Company Task
      │
      ▼
Coding Agent (OpenClaw / external model)
      │
      ├── company.workspace.create
      ├── company.sandbox.run
      │
      ▼
Artifact Registry
      │ accepted handoff: purpose=commit
      ▼
Delivery Automation Rule
      │
      ▼
Repository Delivery (v11)
 worktree → commit → test → review → merge
      │
      ▼
Release
 immutable Git commit SHA
      │
      ▼
Environment Gate
 preview / staging / production
      │
      ├── approval (when required)
      └── secret grants
      ▼
Deployment
      │
      └── rollback lineage
```

## Workspace service

`DevWorkspace` is provider-neutral. For a registered local repository the reference implementation creates a detached Git worktree. For non-repository jobs it creates an empty tenant-bounded directory. Every path is derived below `DEV_WORKSPACE_ROOT`; raw agent paths are never accepted.

Workspace lifetime is explicit (`expires_at`) and Celery cleanup runs periodically.

## Sandbox model

`SandboxProfile` controls image, provider, CPU, memory, PID limit, timeout, network mode, root filesystem mode and allowed executables. `SandboxRun` stores command argv, execution provenance and bounded output.

The Docker adapter constructs a process with:

- `--network none`
- `--cap-drop ALL`
- `no-new-privileges`
- read-only root filesystem
- explicit CPU / memory / PID limits
- tmpfs `/tmp` with `nosuid,nodev,noexec`
- non-root user
- only the controlled workspace mounted read/write
- optional secret directory mounted read-only

Docker execution is **disabled by default** in the supplied compose stack. The reference adapter is code-complete, but a production installation should run sandbox execution on a separate hardened worker pool or microVM/Kubernetes sandbox rather than giving the API container control of the host Docker daemon.

## Secret control plane

`SecretReference` stores metadata and an external provider reference only. `SecretGrant` binds a secret reference to a member/agent, optional sandbox profile or deployment environment, expiration and mount name.

The local adapter supports `env:` references for development. Values are resolved only at execution time, written to a temporary mode-0600 directory, mounted at `/run/secrets`, and deleted immediately afterward. The API returns `***redacted***`; it never returns a value field containing secret material.

Vault/AWS/GCP/Azure providers are extension points, not claimed as live integrations in this snapshot.

## Release and deployment model

A `Release` is pinned to an immutable Git commit SHA. It can be created from a merged v11 merge request or an explicit commit that exists in the controlled repository checkout.

`DeploymentEnvironment` declares preview/staging/production semantics, provider, approval requirement and risk level. Production can create/reuse a standard Company `Approval`; deployment is blocked until its status is `approved`.

The reference `filesystem` provider uses `git archive` to materialize the exact release commit to a versioned directory and atomically moves an environment `current` symlink. The previous successful deployment ID is recorded. Rollback atomically moves `current` back to the previous deployment.

This filesystem provider is for local/staging validation. Kubernetes/cloud deployment adapters still need environment-specific implementations.

## Artifact handoff → delivery automation

`DeliveryAutomationRule` maps an accepted `ArtifactHandoff` purpose, optional project and target member to a v11 repository pipeline. The default pattern is:

```text
agent artifact
  → handoff(purpose=commit, to=Commit Agent)
  → Commit Agent accepts
  → DeliveryRun automatically created
```

The handoff itself remains the source-of-truth transaction. Automation is fail-soft so a transient queue failure does not lose the handoff; `/api/v12/handoffs/{id}/trigger-delivery` allows deterministic replay.

## Multi-tenancy and identity

Every v12 persistent resource carries `organization_id`. API endpoints enforce the active organization. API keys use explicit scopes and may not impersonate a different member when creating workspaces, sandbox runs or deployments.

New scopes used by v12:

- `company.devcloud:read`
- `company.devcloud:write`
- `company.devcloud:execute`
- `company.releases:read`
- `company.releases:write`
- `company.deployments:read`
- `company.deployments:write`
- `company.deployments:rollback`

## Persistence added in v12

- `dev_workspaces`
- `sandbox_profiles`
- `sandbox_runs`
- `secret_references`
- `secret_grants`
- `deployment_environments`
- `releases`
- `release_artifacts`
- `preview_environments`
- `deployments`
- `deployment_rollbacks`
- `delivery_automation_rules`

Migration: `0008_v12_secure_dev_cloud.py`.
