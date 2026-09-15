# ClawCompany v13 Security Notes

v13 increases the amount of untrusted code and deployment control handled by ClawCompany. The secure design therefore separates **control plane**, **workspace**, **code execution**, **repository credentials** and **deployment credentials**.

## 1. Coding model has no repository credential by default

A model provider works through `WorkspaceGatewaySession`. Source is snapped into the Artifact Registry and the v11 Commit/Delivery Agent owns repository mutation. This reduces the blast radius of a compromised coding session.

## 2. Workspace Gateway is not an OS sandbox

The gateway protects logical-path access:

- normalized paths must remain under the workspace root;
- direct `.git` access is rejected;
- capabilities gate read/write/snapshot;
- every operation is persisted.

It does not make arbitrary code safe. Actual code execution must use a sandbox/remote runner boundary.

## 3. Do not mount the Docker socket into the API

`SANDBOX_DOCKER_ENABLED=false` remains the safe default. A Docker socket is effectively host control. For production, use dedicated runner nodes or microVM/container orchestration with a narrow authenticated execution API.

## 4. MicroVM status

`microvm` exists as an execution-fabric contract only. The included runner fails closed unless an external privileged adapter is configured. v13 does not bundle or claim Firecracker/Cloud Hypervisor isolation.

## 5. Secret handling

v12 `SecretReference`/`SecretGrant` continues to be the secret control plane. Do not put plaintext credentials in:

- prompts;
- Workspace Gateway files;
- Artifact metadata;
- repository credential rows;
- CI node JSON.

Use provider references and short-lived runner injection instead.

## 6. CI/CD graph policy

Graph validation prevents dependency cycles, but graph authorship itself is privileged. Treat `company.cicd:write` and `company.cicd:execute` as high-impact scopes. Sandbox-node command allowlists are policy controls, not a substitute for isolation.

## 7. Supply-chain evidence limits

The generated SBOM/provenance artifacts are useful audit evidence but are unsigned. For high-assurance deployments add:

- workload identity/OIDC;
- KMS-backed signing;
- Sigstore/cosign verification;
- immutable artifact storage;
- policy requiring signature verification before deploy.

## 8. Built-in security scanner limits

The deterministic scanner catches a small set of high-signal source patterns. It does not provide:

- dependency/CVE resolution;
- semantic interprocedural SAST;
- malware analysis;
- container/image scanning;
- external secret provider verification.

Production should aggregate specialized scanners into persisted `SecurityReview` evidence and keep deterministic blocking policy outside the LLM.

## 9. Progressive-delivery safety

Blue/green cutover is implemented only for the filesystem reference provider. Canary does not fake traffic shifting: it stays `waiting_router` until a real weighted ingress adapter exists.

HTTP health checks are constrained to the environment `base_url` hostname. Keep that base URL administrator-controlled to avoid SSRF-style misuse.

## 10. Release governance

Release Manager decisions are deterministic and persisted. AI explanations or recommendations must not bypass:

- CI success;
- security verdict;
- deployment approval requirements;
- health/strategy results.

## 11. Tenant isolation

All v13 APIs resolve resources through the authenticated organization. API-key operations also require explicit scopes and identity-binding checks where applicable. Continue treating cross-tenant queries as security defects, not UI bugs.
