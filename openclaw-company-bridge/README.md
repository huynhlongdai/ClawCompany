# OpenClaw ↔ ClawCompany Bridge

This directory defines the stable Company-side tool contract that an OpenClaw plugin/skill can expose to agents.

The Company API is intentionally independent from OpenClaw's plugin SDK. The bridge authenticates using a tenant-bound ClawCompany API key and passes the current `runtime_agent_id` on each call.

## Stable Company tools

| Tool | Required API-key scope |
|---|---|
| `company.context` | `company.context:read` |
| `company.tasks.list` | `company.tasks:read` |
| `company.task.status` | `company.tasks:write` |
| `company.knowledge.search` | `company.knowledge:read` |
| `company.approval.request` | `company.approvals:write` |
| `company.message.owner` | `company.messages:write` |

See `tool-contracts.json` for paths and methods.

## Authentication

Create an API key for the organization with only the required scopes and configure the OpenClaw-side bridge to send:

```http
X-API-Key: cc_...
```

Machine API keys do **not** bypass human role checks. Company-tool endpoints opt into machine access using explicit `require_scope(...)` dependencies. In v11 an API key may also be bound to a specific `Member`, allowing repository permissions and assigned reviews to be checked against the AI employee identity.

## Runtime compatibility

The exact OpenClaw Plugin SDK registration and Gateway RPC names depend on the OpenClaw build/version deployed by the operator. Keep that version-specific code on the OpenClaw side; do not move Company business logic into the runtime plugin.


## v10 artifact handoff

OpenClaw agents do not need direct GitHub access to contribute code. An agent can write exact source into `company.artifact.create`, then call `company.artifact.handoff` to pass that immutable version to a reviewer or dedicated Commit Agent. The receiver can inspect the checksum/logical path, create a new version, run QA, materialize it into a controlled workspace, and only then invoke a Git/GitHub-capable tool. This keeps source transfer independent of the originating chat/provider.

## v11 repository delivery

v11 extends the Artifact Handoff contract into a governed repository pipeline. The bridge contract now includes:

| Tool | Required scope |
|---|---|
| `company.repositories.list` | `company.repositories:read` |
| `company.delivery.create` | `company.delivery:write` |
| `company.delivery.prepare` | `company.delivery:write` |
| `company.delivery.tests` | `company.delivery:write` |
| `company.delivery.review` | `company.delivery:review` |
| `company.delivery.merge` | `company.delivery:merge` |
| `company.delivery.rollback` | `company.delivery:rollback` |

An API key used by an AI employee can be bound to that employee's `Member` identity. Repository operations then pass through a second repository-specific gate (`RepositoryIdentityCredential`) which controls permissions and branch patterns. This makes a useful separation of duties possible:

```text
Coding Agent  → artifact + delivery
Commit Agent  → prepare/write branch/create PR
Review Agent  → review
Release Agent → merge
Owner         → rollback / credential administration
```

Provider secrets are not part of the tool contract. The ClawCompany backend resolves external secret references such as `env:GITHUB_TOKEN` only when a provider operation actually requires them.

## v12 Secure Development Cloud tools

v12 extends the bridge so an OpenClaw coding employee can work without owning repository or deployment credentials directly:

- `company.workspaces.list`
- `company.workspace.create`
- `company.sandbox.run`
- `company.releases.list`
- `company.release.create`
- `company.release.deploy`
- `company.deployment.rollback`
- `company.handoff.trigger_delivery`

The intended identity path is **Agent API key → explicit company scope → workspace/sandbox policy → artifact/release/deployment audit trail**. Secret values are not exposed by these tool contracts.


## v13 AI Engineering Organization tools

v13 adds a provider-neutral engineering contract. A coding employee can be Claude, Gemini, OpenClaw or another provider and still use the same Company-side workspace and SDLC controls:

- `company.workspace.gateway.open`
- `company.workspace.gateway.read`
- `company.workspace.gateway.write`
- `company.workspace.gateway.snapshot`
- `company.cicd.run`
- `company.security.review`
- `company.release_manager.assess`
- `company.engineering.initiative.run`

The Workspace Gateway deliberately does not expose Git credentials. Source is snapshotted into Artifact Registry and then moves through the existing Commit/Delivery Agent separation of duties. The `microvm` execution fabric entry is a contract only; a privileged runner must be deployed separately rather than mounting a host hypervisor or Docker socket into the API service.

## v14 distributed execution tools

v14 adds lease-bound compute and operational-control tools. Coding agents still do **not** receive infrastructure credentials: they acquire a Company runner lease, may request a short-lived workload token, emit telemetry, and interact with governed delivery/incident APIs. The workload token is scoped to the lease and becomes invalid when the lease is released or expires.

External scanner, Kubernetes traffic routing and Sigstore/cosign support are adapter contracts. A missing executable/cluster trust policy fails closed; the bridge does not fake a successful external integration.

## v15 production trust / SRE tools
v15 adds runner trust visibility, tenant JWKS, evidence verification, OTLP metric ingestion,
short-lived secret access leases, incident paging and Nina SRE plan/execute contracts. These
contracts never return private signing keys or secret plaintext.
