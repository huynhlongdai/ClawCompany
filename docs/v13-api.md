# ClawCompany v13 API

Base prefix: `/api/v13`.

All endpoints use the existing ClawCompany authentication/tenant context. API-key calls must also satisfy the required scope and, where relevant, the bound Member/Agent identity.

## Engineering dashboard

```http
GET /api/v13/engineering-dashboard
```

Returns organization-scoped counts/recent data for CI runs, builds, security reviews, release-manager runs, deployment strategies and initiatives.

## Execution fabric

```http
GET /api/v13/execution-fabric/providers
```

Returns control-plane capabilities for configured execution provider types. A listed provider type does not imply a live external runner is configured.

## Workspace Gateway

```http
POST /api/v13/workspace-gateway/sessions
GET  /api/v13/workspace-gateway/sessions
POST /api/v13/workspace-gateway/sessions/{session_id}/write
GET  /api/v13/workspace-gateway/sessions/{session_id}/read?logical_path=...
POST /api/v13/workspace-gateway/sessions/{session_id}/snapshot
POST /api/v13/workspace-gateway/sessions/{session_id}/close
GET  /api/v13/workspace-gateway/operations
```

Typical scopes:

```text
company.workspace:read
company.workspace:write
company.workspace:snapshot
```

## CI/CD graph and runs

```http
POST /api/v13/cicd/graphs
GET  /api/v13/cicd/graphs
GET  /api/v13/cicd/graphs/{graph_id}/validate
POST /api/v13/cicd/runs
GET  /api/v13/cicd/runs
GET  /api/v13/cicd/runs/{run_id}
```

Built-in node types: `noop`, `gate`, `sandbox`, `security`, `evidence`, `release`.

Creating a run resolves its ref to a Git commit SHA. Setting `execute=true` runs the DAG synchronously through the service in this API snapshot; Celery task `engineering.execute_cicd_run` is also available for asynchronous orchestration.

## Build evidence

```http
POST /api/v13/builds/evidence
GET  /api/v13/builds
GET  /api/v13/builds/{build_id}
```

Evidence output includes source manifest, SPDX-compatible SBOM metadata and SLSA-style provenance metadata registered in the Artifact Registry.

## Security review

```http
POST /api/v13/security-reviews
GET  /api/v13/security-reviews
GET  /api/v13/security-reviews/{review_id}
```

`block_on` defaults to `critical` and `high` severities.

## Preview routes

```http
POST /api/v13/preview-routes
GET  /api/v13/preview-routes
GET  /api/v13/preview-routes/resolve?hostname=...&path=/...
```

This is a route registry/resolver. It does not itself configure an ingress controller.

## Health policies and progressive delivery

```http
POST /api/v13/health-policies
GET  /api/v13/health-policies
POST /api/v13/deployment-strategies/run
GET  /api/v13/deployment-strategies
GET  /api/v13/health-runs
```

Strategies:

- `rolling`
- `blue_green`
- `canary`

`canary` requires an external weighted-router adapter and returns `waiting_router` when none is available.

## Release Manager

```http
POST /api/v13/release-manager/assess
GET  /api/v13/release-manager/runs
```

Decision values are `approve`, `hold` and `reject`.

## Nina engineering initiatives

```http
POST /api/v13/initiatives
GET  /api/v13/initiatives
POST /api/v13/initiatives/{initiative_id}/run
```

The run payload controls whether deployment should be attempted and can reference a health policy. Production approval rules are inherited from the v12 deployment gate.

## OpenClaw Company Bridge

v13 extends `openclaw-company-bridge/tool-contracts.json` with provider-neutral engineering tools:

```text
company.workspace.gateway.open
company.workspace.gateway.write
company.workspace.gateway.read
company.workspace.gateway.snapshot
company.cicd.run
company.security.review
company.release_manager.assess
company.engineering.initiative.run
```

The bridge remains a Company API contract. Exact OpenClaw Gateway RPC mapping is deployment/version-specific.
