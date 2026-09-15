# v15 completion matrix

| Capability | Status | Notes |
|---|---|---|
| Runner CA / CSR / certificate rotation | Implemented | Private CA key external reference |
| mTLS runner client support | Implemented control-plane + Envoy template | Production certificate provisioning still infrastructure-owned |
| Workload key rotation / JWKS | Implemented | HS256 dev + RS256 managed key support |
| Pinned evidence verification | Implemented | HMAC and cosign pinned-key path |
| Keyless Sigstore transparency verification | Not complete | Fail closed |
| OTLP JSON ingest / Prometheus exposition | Implemented | Authenticated tenant endpoint |
| Pushgateway / OTLP HTTP exporter | Implemented adapter | Needs live endpoint to validate |
| Secret federation | Implemented adapters | env live-tested; Vault/cloud adapters require provider tooling |
| Incident paging | Implemented | Console live-tested; webhook needs live endpoint |
| HA scheduler leadership/fencing | Implemented DB primitive | Multi-region DB behavior needs production load testing |
| Nina SRE recovery | Implemented | Closed action set + approval gate |
| Firecracker/Kubernetes production runner | Adapter only | Not bundled or live-tested |
