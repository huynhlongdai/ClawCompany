# Kiểm kê ClawCompany (sinh tự động bởi tools/inventory.py)

- Router file: **45** · endpoint: **490**
- Model file: **15** · bảng (`__tablename__`): **159**
- Service module: **93** · tổng dòng: **13826**
- Test file: **34** · hàm test: **616**
- Bridge tool contract: **192**

## Endpoint theo router

| File | Prefix | Endpoint | Dòng |
| --- | --- | --- | --- |
| `agents.py` | `/agents` | 1 | 35 |
| `approvals.py` | `/approvals` | 1 | 36 |
| `auth.py` | `/auth` | 5 | 88 |
| `companies.py` | `/companies` | 0 | 24 |
| `company_tools.py` | `/company-tools` | 6 | 93 |
| `crud.py` | `-` | 0 | 11 |
| `dashboard.py` | `/dashboard` | 1 | 23 |
| `departments.py` | `/departments` | 0 | 26 |
| `extended.py` | `-` | 43 | 236 |
| `health.py` | `/health` | 2 | 26 |
| `jobs.py` | `/jobs` | 2 | 32 |
| `knowledge.py` | `/knowledge` | 1 | 38 |
| `members.py` | `/members` | 0 | 30 |
| `organizations.py` | `/organizations` | 0 | 27 |
| `projects.py` | `/projects` | 0 | 26 |
| `realtime.py` | `-` | 0 | 49 |
| `tasks.py` | `/tasks` | 1 | 32 |
| `v10.py` | `/v10` | 31 | 323 |
| `v11.py` | `/v11` | 27 | 422 |
| `v12.py` | `/v12` | 26 | 331 |
| `v13.py` | `/v13` | 34 | 375 |
| `v14.py` | `/v14` | 42 | 364 |
| `v15.py` | `/v15` | 44 | 351 |
| `v16.py` | `/v16` | 28 | 269 |
| `v17.py` | `/v17` | 7 | 60 |
| `v18.py` | `/v18` | 12 | 271 |
| `v19.py` | `/v19` | 10 | 245 |
| `v20.py` | `/v20` | 6 | 152 |
| `v21.py` | `/v21` | 5 | 121 |
| `v22.py` | `/v22` | 4 | 89 |
| `v24.py` | `/v24` | 3 | 79 |
| `v25.py` | `/v25` | 2 | 74 |
| `v26.py` | `/v26` | 3 | 98 |
| `v27.py` | `/v27` | 7 | 122 |
| `v28.py` | `/v28` | 9 | 140 |
| `v29.py` | `/v29` | 15 | 216 |
| `v30.py` | `/v30` | 6 | 170 |
| `v31.py` | `/v31` | 5 | 168 |
| `v32.py` | `/v32` | 8 | 215 |
| `v33.py` | `/v33` | 10 | 174 |
| `v34.py` | `/v34` | 12 | 248 |
| `v35.py` | `/v35` | 11 | 172 |
| `v7.py` | `-` | 18 | 304 |
| `v8.py` | `-` | 18 | 234 |
| `v9.py` | `/v9` | 24 | 313 |

## Bảng dữ liệu theo model file

| File | Số bảng | Tên bảng |
| --- | --- | --- |
| `__init__.py` | 0 | - |
| `auth.py` | 3 | `users`, `user_organization_access`, `api_keys` |
| `entities.py` | 9 | `organizations`, `companies`, `departments`, `members`, `agents`, `projects`, `tasks`, `knowledge_documents`, `approvals` |
| `extended.py` | 22 | `inbox_items`, `missions`, `workflows`, `workflow_runs`, `automations`, `sops`, `decisions`, `conversations`, `conversation_messages`, `customers`, `customer_agent_assignments`, `reports`, `analytics_metrics`, `audit_events`, `integrations`, `skills`, `tools`, `marketplace_templates`, `subscriptions`, `organization_settings`, `role_bindings`, `permission_policies` |
| `knowledge_chunks.py` | 2 | `knowledge_chunks`, `background_jobs` |
| `v10.py` | 13 | `company_events`, `event_triggers`, `trigger_executions`, `agent_messages`, `artifacts`, `artifact_handoffs`, `artifact_evaluations`, `sla_profiles`, `sla_incidents`, `decision_loops`, `decision_loop_runs`, `simulation_scenarios`, `simulation_runs` |
| `v11.py` | 13 | `repositories`, `repository_identity_credentials`, `delivery_pipelines`, `repository_test_profiles`, `delivery_runs`, `delivery_artifacts`, `repository_test_runs`, `repository_reviews`, `repository_merge_requests`, `repository_conflicts`, `repository_rollbacks`, `event_webhook_endpoints`, `event_webhook_deliveries` |
| `v12.py` | 12 | `dev_workspaces`, `sandbox_profiles`, `sandbox_runs`, `secret_references`, `secret_grants`, `deployment_environments`, `releases`, `release_artifacts`, `preview_environments`, `deployments`, `deployment_rollbacks`, `delivery_automation_rules` |
| `v13.py` | 18 | `workspace_gateway_sessions`, `workspace_gateway_operations`, `cicd_pipeline_graphs`, `cicd_nodes`, `cicd_edges`, `cicd_runs`, `cicd_node_runs`, `build_records`, `sbom_documents`, `build_provenance`, `security_reviews`, `security_findings`, `preview_routes`, `deployment_health_policies`, `deployment_health_runs`, `deployment_strategy_runs`, `release_manager_runs`, `engineering_initiatives` |
| `v14.py` | 17 | `runner_pools`, `runner_nodes`, `runner_leases`, `runner_jobs`, `workload_identity_tokens`, `evidence_signatures`, `scanner_providers`, `external_scan_runs`, `traffic_routers`, `traffic_shifts`, `telemetry_metric_samples`, `slo_definitions`, `slo_evaluations`, `incidents`, `incident_events`, `portfolio_objectives`, `portfolio_reviews` |
| `v15.py` | 16 | `runner_trust_authorities`, `runner_certificates`, `workload_signing_keys`, `evidence_trust_policies`, `evidence_verifications`, `telemetry_exporters`, `telemetry_export_attempts`, `secret_provider_connections`, `secret_access_leases`, `incident_paging_routes`, `incident_notifications`, `scheduler_nodes`, `scheduler_leadership_leases`, `sre_recovery_policies`, `sre_recovery_runs`, `sre_decisions` |
| `v16.py` | 10 | `agent_teams`, `agent_team_members`, `collaboration_rooms`, `room_participants`, `room_turns`, `delegation_contracts`, `shared_knowledge_spaces`, `knowledge_grants`, `shared_knowledge_entries`, `knowledge_access_logs` |
| `v7.py` | 7 | `knowledge_vectors`, `workflow_step_runs`, `usage_events`, `billing_invoices`, `customer_portal_users`, `customer_project_assignments`, `nina_command_logs` |
| `v8.py` | 8 | `agent_provisioning_jobs`, `company_provisioning_jobs`, `nina_execution_plans`, `nina_plan_steps`, `runtime_events`, `customer_chat_bindings`, `workflow_graph_versions`, `usage_meter_rules` |
| `v9.py` | 9 | `autonomy_policies`, `executive_goals`, `budget_envelopes`, `budget_ledger_entries`, `operating_cycles`, `delegation_assignments`, `recovery_incidents`, `organization_memories`, `recurring_operations` |

## Test theo file

| File | Hàm test | Dòng |
| --- | --- | --- |
| `test_auth.py` | 1 | 11 |
| `test_extended.py` | 1 | 16 |
| `test_health.py` | 1 | 9 |
| `test_health_ready.py` | 1 | 9 |
| `test_v10_units.py` | 6 | 122 |
| `test_v11_repository_delivery.py` | 8 | 218 |
| `test_v12_secure_dev_cloud.py` | 6 | 159 |
| `test_v13_ai_engineering_org.py` | 7 | 159 |
| `test_v14_distributed_execution.py` | 8 | 165 |
| `test_v15_production_trust_sre.py` | 7 | 151 |
| `test_v16_agent_collaboration_mesh.py` | 16 | 238 |
| `test_v17_workspace_cockpit.py` | 9 | 152 |
| `test_v18_workspace_ops.py` | 16 | 191 |
| `test_v19_openclaw_alignment.py` | 15 | 192 |
| `test_v20_runtime_stream.py` | 15 | 188 |
| `test_v21_durable_runtime.py` | 21 | 289 |
| `test_v22_cluster_runtime.py` | 16 | 264 |
| `test_v23_approval_contract.py` | 14 | 240 |
| `test_v24_gap_awareness.py` | 15 | 200 |
| `test_v25_auto_reconcile.py` | 12 | 217 |
| `test_v26_shared_fabric.py` | 16 | 267 |
| `test_v27_board_truth.py` | 21 | 245 |
| `test_v28_write_guards.py` | 26 | 288 |
| `test_v29_cascade_archive.py` | 32 | 422 |
| `test_v30_exact_revisions.py` | 36 | 463 |
| `test_v31_bugfixes.py` | 17 | 225 |
| `test_v31_field_audit.py` | 30 | 220 |
| `test_v32_housekeeping.py` | 38 | 358 |
| `test_v33_recovery.py` | 51 | 418 |
| `test_v34_replay.py` | 63 | 491 |
| `test_v35_spend_push.py` | 82 | 554 |
| `test_v7_units.py` | 2 | 14 |
| `test_v8_units.py` | 3 | 32 |
| `test_v9_units.py` | 4 | 93 |

## Bridge tool: nhóm theo namespace

| Nhóm | Số tool |
| --- | --- |
| `runtime` | 31 |
| `events` | 9 |
| `project` | 9 |
| `member` | 8 |
| `company` | 7 |
| `department` | 7 |
| `delivery` | 6 |
| `work` | 6 |
| `spend` | 6 |
| `artifact` | 5 |
| `workspace` | 5 |
| `progress` | 5 |
| `live` | 5 |
| `room` | 4 |
| `org` | 4 |
| `approvals` | 4 |
| `audit` | 4 |
| `revision` | 4 |
| `task` | 3 |
| `knowledge` | 3 |
| `runner` | 3 |
| `delegation` | 3 |
| `knowledge_mesh` | 3 |
| `grants` | 3 |
| `agent` | 2 |
| `handoff` | 2 |
| `release` | 2 |
| `security` | 2 |
| `workload_identity` | 2 |
| `supply_chain` | 2 |
| `telemetry` | 2 |
| `incident` | 2 |
| `sre` | 2 |
| `team` | 2 |
| `board` | 2 |
| `fields` | 2 |
| `context` | 1 |
| `tasks` | 1 |
| `approval` | 1 |
| `message` | 1 |
| `handoffs` | 1 |
| `repositories` | 1 |
| `workspaces` | 1 |
| `sandbox` | 1 |
| `releases` | 1 |
| `deployment` | 1 |
| `cicd` | 1 |
| `release_manager` | 1 |
| `engineering` | 1 |
| `canary` | 1 |
| `portfolio` | 1 |
| `secret` | 1 |
| `collaboration` | 1 |
| `archive` | 1 |
| `row` | 1 |
| `recovery` | 1 |
| `replay` | 1 |

## Đối chiếu bridge tool với endpoint thật

- Tool có khai báo endpoint: **192/192**
- Tool trỏ tới endpoint **không tìm thấy trong code**: **0**


## 15 service module lớn nhất

| File | Dòng | def | class |
| --- | --- | --- | --- |
| `repository_delivery.py` | 567 | 26 | 1 |
| `workspace_ops.py` | 486 | 17 | 0 |
| `orchestration.py` | 471 | 18 | 0 |
| `entity_archive.py` | 461 | 16 | 1 |
| `runtime_stream.py` | 435 | 8 | 0 |
| `event_replay.py` | 342 | 13 | 1 |
| `board_truth.py` | 288 | 8 | 0 |
| `runtime_leases.py` | 268 | 0 | 0 |
| `grant_ledger.py` | 255 | 11 | 1 |
| `event_retention.py` | 253 | 8 | 1 |
| `workspace_cockpit.py` | 242 | 9 | 0 |
| `stream_reconcile.py` | 241 | 6 | 0 |
| `write_audit.py` | 239 | 6 | 0 |
| `cicd.py` | 228 | 8 | 1 |
| `workload_identity.py` | 227 | 13 | 1 |
