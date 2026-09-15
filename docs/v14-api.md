# v14 API surface

All paths are under `/api/v14` unless noted.

## Runners

`POST /runner-pools`, `GET /runner-pools`, `POST /runner-nodes/register`, `GET /runner-nodes`, `POST /runner-nodes/{id}/heartbeat`, `POST /runner-leases`, `GET /runner-leases`, `POST /runner-leases/{id}/release`, `POST /runner-jobs`, `GET /runner-jobs/next?node_id=...`, `POST /runner-jobs/{id}/complete`.

## Workload identity

`GET /workload-identity/.well-known/openid-configuration`, `GET /workload-identity/jwks.json`, `POST /workload-identity/token`, `POST /workload-identity/verify`.

## Supply chain / security

`POST /evidence-signatures`, `POST /evidence-signatures/verify`, `GET /evidence-signatures`, `POST /scanner-providers`, `GET /scanner-providers`, `POST /scanner-runs`, `GET /scanner-runs`.

## Progressive delivery

`POST /traffic-routers`, `GET /traffic-routers`, `POST /traffic-shifts`, `GET /traffic-shifts`, `POST /canary-runs`.

## Telemetry and SLO

`POST /telemetry/metrics`, `GET /telemetry/metrics`, `POST /slos`, `GET /slos`, `POST /slos/{id}/evaluate`, `GET /slo-evaluations`.

## Incident response

`POST /incidents`, `GET /incidents`, `GET /incidents/{id}`, `POST /incidents/{id}/events`, `POST /incidents/{id}/status`.

## Nina portfolio

`POST /portfolio/objectives`, `GET /portfolio/objectives`, `POST /portfolio/reviews`, `GET /portfolio/reviews`.
