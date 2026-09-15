# v12 security notes

v12 materially improves the development execution boundary, but the name "Secure AI Development Cloud" describes the product layer, not a claim that this local reference stack is a certified sandbox.

## Implemented controls

1. Workspace paths are derived under a configured tenant workspace root.
2. Sandbox commands are argv arrays; no `shell=True` execution is used by the v12 runner.
3. Docker sandbox policy drops capabilities, disables network by default, uses a non-root user and enforces CPU/RAM/PID/timeout constraints.
4. Docker root filesystem defaults to read-only.
5. Secret values are not stored in `SecretReference` or returned by API serialization.
6. Secret grants are identity/profile/environment scoped and can expire.
7. Releases are pinned to Git commit SHA and verified against the repository checkout.
8. Production environments may require a normal Company approval before deploy.
9. Filesystem deploy archives reject path traversal and symbolic/hard links.
10. Deployments retain previous-deployment lineage for rollback.

## Deliberately disabled / not claimed

- The compose stack leaves `SANDBOX_DOCKER_ENABLED=false`.
- No Docker socket is mounted into the API/worker containers.
- Vault, AWS Secrets Manager, GCP Secret Manager and Azure Key Vault are schema/provider extension points only.
- Kubernetes/microVM sandbox and deployment providers are not live adapters yet.
- Filesystem deployment is a local reference provider, not a production cloud deployer.
- The current app still uses bearer JWT in browser localStorage from earlier versions; HttpOnly session/cookie hardening remains future work.

## Production recommendation

Run sandbox execution as a separate service on dedicated nodes with no control-plane credentials. Prefer microVM/gVisor/Kata or a locked Kubernetes runtime class, default-deny egress, per-job service accounts, image allowlists/signatures, ephemeral disks and provider-native secret injection. Treat repository source as hostile code during build/test.
