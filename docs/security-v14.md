# Security Model v14

1. **Tenant boundary** — all new resources carry `organization_id`; API endpoints call `enforce_org` before access.
2. **Runner identity** — runner nodes should use Company API keys with runner-only scopes. They do not inherit human roles.
3. **Lease revocation** — workload JWT verification checks active lease state in addition to cryptographic signature and expiry.
4. **Short lifetime** — workload tokens are capped at 15 minutes and leases at one hour by the API schema/service.
5. **Production JWT** — HS256 exists for local development. Production should set `WORKLOAD_IDENTITY_ALGORITHM=RS256` and provide protected private/public key paths.
6. **Secret references** — supply-chain signing stores only a key reference. Secret material is resolved from the external environment/provider at execution time.
7. **Cosign** — signing through `cosign_cli` is optional. Keyless verification is not marked successful without an explicit trust-policy/bundle implementation.
8. **Scanner execution** — external scanners execute in a temporary detached Git worktree. Their presence is detected explicitly; missing binaries fail closed.
9. **Kubernetes traffic** — disabled by default. Enabling it authorizes the service host's `kubectl` identity to patch a configured `HTTPRoute`; cluster RBAC must constrain that identity.
10. **Runner execution** — `app.runner_agent` defaults to `noop`. `local_process` is intentionally described as non-sandboxed and should run only inside already-isolated disposable infrastructure.
11. **Canary policy** — insufficient telemetry halts promotion. Breach shifts candidate traffic back to 0% rather than interpreting missing/failed telemetry as success.
12. **Incident audit** — incident state transitions create timeline entries and Company Events.

Known hardening work: asymmetric key rotation/JWKS overlap, workload-token revocation cache, remote runner mTLS, true microVM launcher, signed transparency-log verification, scanner network policy, Kubernetes service-account federation, Prometheus/OpenTelemetry ingestion adapters, incident paging connectors and HA traffic-router reconciliation.
