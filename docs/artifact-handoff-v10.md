# Universal Agent Source Handoff Protocol

## Problem

Not every AI agent/provider can write to GitHub. Requiring every agent to hold repository credentials increases coupling and risk.

## v10 solution

Treat source code as a governed business artifact.

```text
Agent completes code
      ↓
company.artifact.create
      ↓
Artifact(version + path + checksum + provenance)
      ↓
company.artifact.handoff
      ↓
Reviewer / QA / Commit Agent
      ↓
accept + inspect + optionally create next version
      ↓
materialize approved version to controlled workspace
      ↓
Git-capable tool/agent commits
```

## Why this is provider-neutral

The writer only needs HTTP/API-key access to ClawCompany. It does not need GitHub, filesystem, shell or the same chat runtime as the receiver.

## Version semantics

Version is incremented by `(organization_id, bundle_key, logical_path)`. Every new version links to `parent_artifact_id` and stores SHA-256 over inline text content.

## Commit Agent convention

Use handoff `purpose="commit"`. The target Commit Agent should:

1. inspect the exact artifact version/checksum,
2. require an approved QA verdict when policy says so,
3. materialize to the assigned workspace,
4. run repository-specific validation,
5. commit through a Git/GitHub-capable integration,
6. emit a result event and register any changed files as new Artifact versions.

The current v10 code implements steps 1–3 at the Company OS layer. Repository-specific Git operations are intentionally adapter/integration work, not embedded into generic Artifact storage.
