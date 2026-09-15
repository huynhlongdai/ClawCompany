# Architecture v15

v15 adds five control-plane domains to v14: runner transport trust, rotating workload identity, observability federation, secrets federation, and autonomous SRE.

## Trust path

`Runner CSR → Runner CA reference → short client certificate → mTLS edge → fingerprint → RunnerNode → RunnerLease → Workload JWT`.

The runner owns its private key. ClawCompany stores the issued certificate and fingerprint, while CA private material is only referenced (`env:` or `file:`). Workload signing keys have overlapping `active`/`retiring` states so key rotation does not invalidate in-flight tokens until the old key is explicitly revoked.

## Observability path

`OTLP JSON → TelemetryMetricSample → SLOEvaluation → Incident → Paging → SRE Recovery`. Prometheus scrapes a tenant-authenticated text endpoint. Optional push exporters use a strict hostname allowlist.

## SRE path

`Incident → policy match → SREDecision → RecoveryRun → approval when required → action executor`. Supported deterministic actions are `page`, `mark_mitigating`, `re_evaluate_slo`, and `rollback`. Unknown actions are recorded as skipped rather than executed dynamically.

## HA

`SchedulerNode` competes for a named `SchedulerLeadershipLease`. A monotonically increasing fencing token changes on leader takeover. The v15 control-loop task performs recovery/paging only when it owns the current organization lease.

## Secrets

`SecretReference` remains metadata. v15 adds provider connection metadata and a `SecretAccessLease` bound to organization/member/agent/runner lease. Resolution happens only at execution time through explicit adapters.
