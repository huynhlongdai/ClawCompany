# Security Model v11

## Identity-bound repository access

Repository permissions are attached to `RepositoryIdentityCredential` and can reference a Member and/or Agent. API keys may now be bound to a Member identity. An API-key principal carries that identity through authorization.

Repository permissions are deliberately separate:

```text
read
write_branch
create_pr
merge
rollback
```

Branch restrictions use a pattern such as `cc/*`.

Human JWT users with Admin/Owner role can operate local repositories administratively. Remote provider operations still require an explicit identity-bound provider credential; elevated ClawCompany role does not synthesize a GitHub credential.

## Secret handling

`RepositoryIdentityCredential.secret_ref` stores a reference, not a raw token. v11 supports:

```text
env:GITHUB_TOKEN
```

The GitHub token is resolved at execution time. Git authentication is passed through transient process environment configuration and is not written into the repository remote URL.

Production should replace environment-only resolution with a dedicated secrets manager adapter and short-lived provider credentials where available.

## Path and Git ref controls

The repository service:

- validates Git refs;
- constrains all repository/worktree paths beneath the configured workspace root;
- rejects `..`, absolute logical paths and `.git` materialization;
- invokes subprocesses as argv arrays without `shell=True`.

## Test runner warning

The executable allowlist controls which program starts. It does **not** make repository code safe. Commands such as `pytest`, `npm`, `node` and Python compilation/import flows can execute untrusted repository code.

Production requirement: run delivery tests in a disposable sandbox/container/VM with:

- no host Docker socket;
- restricted network egress;
- read-only secrets by default;
- no production credentials;
- CPU/memory/time limits;
- bounded workspace mount;
- filesystem cleanup;
- audit logs.

## Webhook SSRF controls

Webhook URLs are validated against `EVENT_WEBHOOK_ALLOWED_HOSTS`. Non-local targets require HTTPS. Production deployments should keep the allowlist narrow and should not permit arbitrary tenant-controlled destinations without stronger egress policy.

Optional signatures use HMAC-SHA256 through `X-ClawCompany-Signature`. Webhook shared secrets are also referenced externally.

## Multi-tenancy

v11 API lookups enforce active Organization ownership before repository/delivery/review/webhook operations. Provider credentials are queried within repository and organization identity scope.

Production hardening should additionally use database-level tenant policies or isolated schemas/databases where the deployment risk warrants it.

## Separation of duties

Recommended production policy:

```text
Worker AI:       Artifact create only
Commit Agent:    write_branch + create_pr
Reviewer:        delivery review
Release Agent:   merge
Owner/Admin:     rollback / credential binding
```

Avoid giving a single autonomous worker unrestricted `write_branch + review + merge + rollback` unless the risk policy explicitly permits it.
