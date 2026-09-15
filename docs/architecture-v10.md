# ClawCompany v10 Architecture — Event-Driven Autonomous Company

## Purpose

v10 adds a durable coordination plane above OpenClaw so AI employees can exchange work, react to company events, pass source/files between providers, run quality gates and escalate operational breaches without relying on one chat thread.

## Core topology

```text
Founder / Customer / Runtime / Workflow / Agent
                    │
                    ▼
              CompanyEvent
                    │
          ┌─────────┴──────────┐
          ▼                    ▼
   realtime broker       durable database
          │                    │
          └─────────┬──────────┘
                    ▼
              Trigger Engine
                    │
       ┌────────────┼────────────┐
       ▼            ▼            ▼
   Message       Approval      Goal/Workflow
       │
       ▼
  AI Employee / Nina
       │
       ▼
  Artifact Registry
       │
       ├── immutable versions
       ├── SHA-256 checksum
       ├── logical path
       ├── task/run provenance
       └── bundle key
       │
       ▼
  Evaluator / QA Gate
       │
       ▼
  Artifact Handoff Queue
       │
       ▼
 Reviewer / Next Agent / Commit Agent
```

## Artifact Handoff as the universal agent output protocol

An agent does not need repository credentials. It can send exact completed source to ClawCompany as an Artifact. The Artifact preserves the source text, logical path, bundle key, version, checksum, producing member/agent, task and runtime run ID. A different agent can accept the handoff, create the next version and materialize the approved version into a controlled workspace.

This means the transport contract is ClawCompany rather than ChatGPT, Claude, Gemini, Perplexity or any single agent runtime.

## Durable Company Event Bus

`CompanyEvent` is a tenant-scoped business event journal. Important runtime events are mirrored into it by `runtime_events.persist_runtime_event()`.

Each event carries:

```text
organization_id
company_id
source
event_type
aggregate_type / aggregate_id
correlation_id / causation_id
actor_member_id
payload_json
status
occurred_at / processed_at
```

The in-memory websocket broker remains useful for live UI updates, while `CompanyEvent` is the durable source used by trigger processing. This snapshot does not claim distributed exactly-once delivery.

## Trigger Engine

`EventTrigger` supports:

```text
event_pattern   fnmatch-style wildcard
condition_json  equality / ne / in / gte / lte over payload paths
action_type     message | goal | approval | workflow
action_json     action-specific payload
cooldown        optional suppression window
```

Every execution is stored in `TriggerExecution`.

## Agent Message Bus

`AgentMessage` provides persistent internal communication independent of LLM session history. A message can link to a task or artifact and supports thread keys, subject, priority, context and read state.

## Quality Gate

`ArtifactEvaluation` stores the evaluator identity, rubric, score, verdict and findings. v10 ships a deterministic evaluator baseline so the pipeline works locally without an LLM. A production evaluator can replace this service with an OpenClaw/LLM evaluator while preserving the same contract.

## SLA and escalation

`SLAProfile` currently supports task completion deadlines. `monitor_sla()` creates `SLAIncident`, optionally messages the escalation target and emits `sla.breached`. More resource types can use the same schema later.

## Nina Continuous Decision Loop

`DecisionLoop` defines interval/mode/policy. Each tick stores `DecisionLoopRun` containing a snapshot of pending events, recovery incidents, SLA breaches and approvals plus the resulting decision list. The current decision function is deterministic; an LLM planner can be plugged in without changing persistence.

## Digital Twin

`SimulationScenario` stores what-if assumptions and `SimulationRun` stores the current company snapshot plus projected capacity, cost, backlog, utilization and a score. This is a baseline simulation model, not a financial forecasting claim.

## Background scheduling

Celery Beat now schedules:

```text
operations.scan_recurring       every 60s
operations.tick_cycles          every 30s
events.dispatch_pending         every 10s
events.monitor_sla              every 60s
events.tick_decision_loops      every 30s
```

## Data model additions

v10 adds 13 tables:

```text
company_events
event_triggers
trigger_executions
agent_messages
artifacts
artifact_handoffs
artifact_evaluations
sla_profiles
sla_incidents
decision_loops
decision_loop_runs
simulation_scenarios
simulation_runs
```

The full metadata snapshot contains 73 tables.

## Security boundaries

All v10 records are organization-scoped. Human administration endpoints use role checks. Agent-capable endpoints use scoped API keys such as `company.artifacts:write` and `company.messages:write`.

Important remaining gap: API keys are organization-scoped rather than cryptographically bound to a specific Member/Agent identity. Callers currently provide member IDs inside the tenant. Before production, bind machine credentials to a principal agent/member and derive actor identity server-side.

## Artifact storage security

v10 supports inline text artifacts and controlled materialization. Logical paths reject traversal and are resolved beneath `ARTIFACT_WORKSPACE_ROOT/<organization>/<bundle>/`.

Production hardening still needs object storage for large/binary files, malware scanning, MIME verification, encryption/key management, quotas, retention and immutable audit around deletes.

## OpenClaw boundary

OpenClaw remains behind `AgentRuntime`. v10 does not hard-code or claim the exact Gateway RPC contract for an unknown deployed OpenClaw release. Gateway RPC/event names stay configurable until the deployment contract is supplied.
