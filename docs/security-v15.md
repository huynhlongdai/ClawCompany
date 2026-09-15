# Security model v15

1. **mTLS**: FastAPI trusts a runner fingerprint only when `RUNNER_MTLS_REQUIRED=true` and the private TLS terminator also supplies the configured proxy verification proof. Never expose the proxy→API hop publicly.
2. **Runner keys**: runner private keys never enter the database. CSR signing returns a certificate, not a private key.
3. **CA/signing keys**: private material uses `env:`/`file:` references. For production, prefer an HSM/KMS-backed signer adapter instead of filesystem keys.
4. **Workload identity**: tokens are bounded to an active `RunnerLease`; a revoked signing key or released lease invalidates verification.
5. **Secrets**: `SecretAccessLease` contains no plaintext value. Vault/cloud values are resolved at execution time. External provider hosts are allowlisted.
6. **Telemetry/paging egress**: outbound endpoints must match explicit hostname allowlists. Paging webhook bodies can be HMAC-signed.
7. **Evidence verification**: keyless Sigstore verification fails closed until an explicit certificate/transparency trust policy is implemented. A stored signature alone is never treated as verification.
8. **Autonomous recovery**: SRE actions come from a closed deterministic action set. Seeded `critical` incidents require approval. `force=true` is restricted to admin/owner.
9. **HA fencing**: leader takeover increments a fencing token. External side-effect adapters should carry/check the token when upgraded to multi-region execution.
