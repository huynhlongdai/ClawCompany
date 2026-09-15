# Repository Delivery Protocol v11

## 1. Agent produces source

Any AI capable of calling Company tools can register exact output in the Artifact Registry. It does not require Git or GitHub access.

Recommended artifact fields:

```text
bundle_key    = checkout-fix-219
logical_path  = src/checkout/service.ts
artifact_type = source_code
content_text  = <exact completed file>
```

If another agent modifies the file, it creates a new Artifact version rather than overwriting provenance.

## 2. Create Delivery Run

A Delivery Run references the artifact bundle and target repository/pipeline.

For API-key callers, the initiating Member must match the API key's bound `member_id`. This prevents an API key from impersonating another AI employee.

## 3. Prepare

Prepare performs:

1. validate refs and paths;
2. ensure repository checkout;
3. create an isolated Git worktree/source branch;
4. pick the latest Artifact version for each logical path in the bundle;
5. materialize exact file contents;
6. `git add` and commit as ClawCompany Commit Agent;
7. register the resulting Git patch as an Artifact;
8. record materialized Artifact links.

No `shell=True` execution is used for Git or tests.

## 4. Tests

A RepositoryTestProfile defines approved commands and timeout. The first executable must be on `REPOSITORY_TEST_ALLOWED_EXECUTABLES`.

Example:

```json
["python -m compileall src", "pytest -q"]
```

The allowlist is a control, not a sandbox. `pytest` or `node` can execute arbitrary repository code. Production runners should be isolated.

## 5. Review

A review can be assigned to a human Member or an Agent. Review decisions store:

- verdict;
- score;
- summary;
- structured findings;
- reviewer identity.

For API-key reviewers, the bound Member identity must match the assigned reviewer.

## 6. Merge Request

For `local`, a ClawCompany merge-request record represents the gate and audit object.

For `github`, the adapter can push the branch and create a real GitHub Pull Request when an identity credential with `create_pr` exists.

## 7. Merge Gate

The gate checks the pipeline requirements. A Delivery Run requiring tests/review cannot merge from stale or missing evidence.

Local strategies:

```text
merge
squash
rebase
```

GitHub strategies are mapped to the provider's merge API.

## 8. Conflict handling

If local merge produces conflicts:

```text
Delivery Run → conflict
RepositoryConflict rows → open
```

Resolution requires explicit content for every conflicted path. The service then commits the resolution and marks earlier tests/reviews stale. The delivery must be tested/reviewed again before merge.

This prevents a human or AI conflict-resolution edit from bypassing the quality gate.

## 9. Rollback

For a merged local delivery, rollback creates a new Git revert commit. Merge commits are reverted with mainline parent 1. The action is recorded in RepositoryRollback.

Rollback is permission-gated separately from merge.

## 10. Agent tool surface

The OpenClaw Company Bridge contract includes:

```text
company.repositories.list
company.delivery.create
company.delivery.prepare
company.delivery.tests
company.delivery.review
company.delivery.merge
company.delivery.rollback
```

Suggested separation of duties:

```text
Coding Agent    → artifacts + delivery create
Commit Agent    → prepare / branch publication
Test Agent      → tests
Reviewer Agent  → review decision
Release Agent   → merge
Founder/Admin   → emergency rollback
```

One agent may hold multiple roles, but production governance should use least privilege.
