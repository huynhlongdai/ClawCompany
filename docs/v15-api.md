# v15 API map

Primary groups under `/api/v15`:

- `/runner-trust/authorities`, `/runner-trust/certificates` — CA/CSR/certificate lifecycle.
- `/runner/{node_id}/heartbeat`, `/jobs/next`, `/jobs/{id}/complete` — mTLS-edge-aware pull runner transport.
- `/workload-signing-keys`, `/workload-identity/{org}/jwks.json` — rotating workload identity keys.
- `/evidence-trust/policies`, `/evidence-trust/verify`, `/evidence-trust/verifications` — signed evidence trust.
- `/metrics`, `/telemetry/otlp-json`, `/telemetry/exporters` — Prometheus/OTLP federation.
- `/secret-providers`, `/secret-access-leases` — federated secret metadata and leases.
- `/paging/routes`, `/paging/notifications`, `/incidents/{id}/page` — incident paging.
- `/scheduler/nodes`, `/scheduler/leases` — HA scheduler leadership.
- `/sre/policies`, `/sre/plan`, `/sre/runs/{id}/execute`, `/sre/tick`, `/sre/decisions` — Nina SRE control loop.
- `/control-plane/summary` — UI/control-plane summary.

All tenant resources are checked against the authenticated organization. API keys require the explicit scope named by each endpoint; human JWTs still use the role/tenant model from v6+.
