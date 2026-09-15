# v11 API Map

Prefix: `/api/v11`

## Repository Registry

```text
POST /repositories
GET  /repositories
GET  /repositories/{repository_id}
POST /repositories/{repository_id}/sync
POST /repositories/{repository_id}/credentials
POST /repositories/{repository_id}/test-profiles
```

## Delivery Pipeline

```text
POST /pipelines
GET  /pipelines

POST /deliveries
GET  /deliveries
GET  /deliveries/{run_id}
POST /deliveries/{run_id}/prepare
POST /deliveries/{run_id}/enqueue?stage=prepare|tests
POST /deliveries/{run_id}/tests
POST /deliveries/{run_id}/reviews
POST /deliveries/{run_id}/merge-request
POST /deliveries/{run_id}/merge
POST /deliveries/{run_id}/resolve-conflicts
POST /deliveries/{run_id}/cleanup
```

## Review / Rollback

```text
POST /reviews/{review_id}/decision
POST /merge-requests/{merge_request_id}/rollback
GET  /rollbacks
GET  /delivery-dashboard
```

## Distributed Event Webhooks

```text
POST /webhook-endpoints
GET  /webhook-endpoints
GET  /webhook-deliveries
POST /webhook-deliveries/{delivery_id}/retry
```

## Representative scopes

```text
company.repositories:read
company.delivery:write
company.delivery:review
company.delivery:merge
company.delivery:rollback
```

RepositoryIdentityCredential then provides an additional repository-specific permission/branch gate. Passing a Company API scope does not automatically grant repository provider access.
