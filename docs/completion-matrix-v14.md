# v14 Completion Matrix

| Capability | Model/API | Service behavior | UI | Status |
|---|---|---|---|---|
| Runner pool/node/lease/job | yes | capability + capacity + expiry | `/app/runners` | implemented |
| Pull runner agent | yes | register/heartbeat/pull/complete | n/a | implemented; noop default |
| Workload JWT | yes | lease-bound, HS256 dev / RS256 prod | runners | implemented |
| Firecracker execution | contract | external privileged runner required | runners | adapter boundary only |
| Kubernetes execution | contract | external cluster runner required | runners | adapter boundary only |
| Evidence signatures | yes | HMAC dev + cosign sign adapter | `/app/trust` | implemented |
| Keyless cosign verification | record boundary | trust bundle/policy missing | trust | intentionally incomplete |
| Scanner adapters | yes | builtin/Semgrep/Trivy/OSV | trust | implemented; external CLIs not bundled |
| Traffic router | yes | database/file/Kubernetes HTTPRoute | `/app/progressive-delivery` | implemented |
| Canary | yes | weighted steps + SLO gate + rollback | progressive delivery | implemented |
| Telemetry | yes | metric ingestion | `/app/observability` | implemented |
| SLO evaluator | yes | window/min sample/comparator | observability | implemented |
| Incident response | yes | state + timeline + event | `/app/incidents` | implemented |
| Nina engineering portfolio | yes | deterministic aggregate/recommendation | `/app/portfolio` | implemented |
| Prometheus/OTel ingestion | no dedicated adapter | REST metric ingest only | observability | future hardening |
| PagerDuty/Opsgenie paging | no | Company Event available | incidents | future connector |
