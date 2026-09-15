# ClawCompany v11 Architecture — Repository Delivery

## Purpose

v11 turns the v10 Artifact/Handoff layer into a governed repository delivery system. AI workers produce artifacts; repository-capable identities publish them. Repository credentials remain separate from model/provider credentials.

## Control plane

```text
Founder / Nina
     │
     ├── Repository Registry
     ├── Delivery Pipelines
     ├── Test Profiles
     ├── Review Policy
     └── Repository Identity Credentials
             │
             ▼
       Company API / Policy
```

## Data plane

```text
AI Worker
   │ exact source
   ▼
Artifact Registry
   │ bundle_key
   ▼
Delivery Run
   │
   ├── isolated Git worktree
   ├── materialize latest artifact versions
   ├── commit + patch artifact
   ├── tests
   ├── review
   └── merge gate
          │
          ├── local Git merge
          └── GitHub push → PR → merge
```

## Delivery state

A Delivery Run links Organization, Repository, Project/Task, initiating Member/Agent, artifact bundle, source branch, target branch, worktree path, base/head commit and optional merge request.

The important rule is that the Artifact Registry is the cross-agent interchange format. Git is a controlled publication target, not the collaboration protocol between agents.

## Repository providers

### Local

The local provider is fully handled by the ClawCompany Git service:

1. initialize/sync checkout;
2. create an isolated worktree and source branch;
3. materialize artifact bundle;
4. commit;
5. test/review gate;
6. merge using merge/squash/rebase;
7. record conflicts;
8. explicit conflict resolution;
9. rollback with `git revert`.

### GitHub

The GitHub adapter provides:

- authenticated branch push using transient Git HTTP header configuration;
- Pull Request creation using GitHub REST;
- PR merge using GitHub REST;
- identity-bound credential lookup.

Provider secrets are resolved through an external reference (`env:NAME` in v11). Live GitHub network behavior has not been validated in this snapshot.

### Generic Git

A repository may be represented as `generic_git`, but v11 does not claim a generic merge-request provider implementation. Provider-specific PR/merge semantics require an adapter.

## Merge gate

A Delivery Pipeline can require:

- tests;
- review;
- N approvals;
- merge strategy.

A merge cannot pass the gate unless the latest required evidence is valid. Conflict resolution deliberately marks prior test/review evidence stale, because the source content changed.

## Async execution

Celery tasks currently support the heavy stages:

```text
delivery.prepare
delivery.tests
```

This keeps worktree/materialization/test execution outside request latency when the async endpoint is used.

## Event integration

Repository delivery emits Company Events. v11 adds a durable webhook outbox:

```text
CompanyEvent
   ↓
EventWebhookDelivery row
   ↓
Celery Beat/worker
   ↓
HTTP endpoint
   ├── delivered
   ├── retry_at + exponential backoff
   └── dead_letter
```

Webhook payloads preserve event, correlation, causation, source and aggregate metadata.

## Frontend

New route surfaces:

```text
/app/repositories
/app/delivery
/app/reviews
```

They reuse the light premium ClawCompany shell instead of creating a separate admin aesthetic.

## Database additions

v11 adds Repository, RepositoryIdentityCredential, DeliveryPipeline, RepositoryTestProfile, DeliveryRun, DeliveryArtifact, RepositoryTestRun, RepositoryReview, RepositoryMergeRequest, RepositoryConflict, RepositoryRollback, EventWebhookEndpoint and EventWebhookDelivery.

The aggregate model metadata in this snapshot contains 86 tables.
