# Architecture v14 — Distributed Secure Execution & Observability

## 1. Execution plane separation

ClawCompany remains the control plane. A runner node is a separate workload plane that is selected through `RunnerPool` and leased through `RunnerLease`. The lease contains organization/member/agent/workload/scope context but no cloud secret. `RunnerJob` is pull-based; a node can only claim jobs whose active lease points to that node.

```text
Company Core → Runner Broker → Lease → Workload JWT → Runner Node
```

The default pull runner executor is `noop`. A deployment can substitute Kubernetes, Firecracker or another execution provider behind the runner contract without changing Company Task / Artifact / CI/CD models.

## 2. Workload identity

A workload token is a short-lived JWT with `iss`, `aud`, `jti`, `org_id`, `lease_id`, optional `member_id`, optional `agent_id` and explicit scopes. Validation checks both the token record and the current lease state; a cryptographically valid token is rejected if its lease was released or expired.

Development can use HS256. Production should use RS256 and provide private/public PEM paths. The JWKS endpoint returns a public RSA key only in RS256 mode. This is an OIDC-style workload issuer for ClawCompany workloads, not a general user-login OAuth provider.

## 3. Supply-chain trust

`EvidenceSignature` binds an Artifact digest to a signer reference. The database stores key references, not signing secrets. The built-in development provider uses `env:KEY`. `cosign_cli` can sign a blob when cosign is installed. Verification of keyless cosign signatures is deliberately not faked; a trust policy/bundle adapter is required.

`ScannerProvider` and `ExternalScanRun` normalize results from built-in deterministic scanning, Semgrep, Trivy or OSV Scanner. External tool absence becomes an explicit unavailable/blocked run.

## 4. Progressive delivery

`TrafficRouter` stores the authoritative routing adapter configuration and current weights. `TrafficShift` is immutable history. Database and file providers are runnable without external infrastructure. Kubernetes Gateway API routing is opt-in and uses explicit `HTTPRoute` backend service mapping.

Canary execution:

```text
10% → evaluate SLOs
25% → evaluate SLOs
50% → evaluate SLOs
100% → promoted
```

If telemetry is insufficient, promotion stops in `waiting_metrics`. If an SLO breaches, candidate traffic is set to 0%, an Incident may be opened, and a deployment rollback is attempted when ClawCompany has previous-deployment lineage.

## 5. Observability and incidents

Telemetry samples are organization and optionally environment/deployment/release scoped. `SLODefinition` owns comparator, threshold, evaluation window, minimum sample count, incident policy and rollback policy. `SLOEvaluation` is persisted for audit.

Operational incidents are first-class Company OS objects with timeline events and Company Event emission, allowing humans, Nina and automation triggers to observe the same state.

## 6. Nina portfolio layer

`PortfolioObjective` defines an executive engineering outcome. `PortfolioReview` aggregates active initiatives, CI failure, rollout failure, SLO breach and open incident state. v14 uses deterministic aggregation; an LLM explanation can be added later without becoming the source of truth for health status.
