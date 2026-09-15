# v12 API

All routes are mounted below `/api/v12`.

## Dev Cloud

- `GET /dev-cloud-dashboard`
- `POST /workspaces`
- `GET /workspaces`
- `POST /workspaces/{id}/destroy`
- `POST /sandbox-profiles`
- `GET /sandbox-profiles`
- `POST /sandbox-runs?enqueue=false`
- `GET /sandbox-runs`

## Secrets

- `POST /secrets`
- `GET /secrets`
- `POST /secret-grants`
- `GET /secret-grants`

Secret APIs return metadata only. There is intentionally no endpoint that reads a secret value.

## Release / environments

- `POST /environments`
- `GET /environments`
- `POST /releases`
- `GET /releases`
- `GET /releases/{id}`
- `GET /releases/{id}/gate?environment_id=...`
- `POST /releases/{id}/deploy?enqueue=false`
- `POST /releases/{id}/preview?environment_id=...`
- `GET /deployments`
- `GET /previews`
- `POST /deployments/{id}/rollback`

## Artifact handoff automation

- `POST /delivery-automation-rules`
- `GET /delivery-automation-rules`
- `POST /handoffs/{handoff_id}/trigger-delivery`

## Example sandbox run

```json
{
  "workspace_id": 3,
  "profile_id": 1,
  "purpose": "test",
  "command": ["python", "-m", "pytest", "-q"],
  "secret_grant_ids": []
}
```

Commands are argv arrays, not shell strings.

## Example production deploy

```http
POST /api/v12/releases/12/deploy
Content-Type: application/json

{"environment_id": 3}
```

If the environment requires approval and the release approval is pending, the API returns a conflict instead of deploying.
